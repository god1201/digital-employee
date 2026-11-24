# 部署与运维手册（宿主机本地运行）

> 本平台不使用 Docker（用户明确要求），生产部署按“宿主机进程 + 外部 PostgreSQL”
> 组织。仓库内不包含容器、CI 或 GitHub 相关文件。

## 1. 目标拓扑

```
                 TLS / 反向代理（Nginx 或企业网关）
                /            |                 \
       /api, /media       /health, /metrics    静态前端
              |                  |                 |
        FastAPI 进程        FastAPI 进程      frontend/dist
              |
      ┌───────┴────────┐
   PostgreSQL          Redis（可选）
   （VM de-pg）        Celery（可选）
```

- **API**：`uvicorn app.main:app`，可多实例。
- **Worker**：
  - 默认：`python -m scripts.worker`（数据库队列，原子领取）；
  - 可选：`python scripts/celery_worker.py`（Redis/Celery）。
- **前端**：`npm run build` 产物 `frontend/dist/` 由 Nginx 托管。
- **数据库**：VM 上的 PostgreSQL；所有业务表由 Alembic 管理。
- **Redis**：仅 `QUEUE_BACKEND=celery` 时需要。

### Windows 本地进程（当前开发环境）

```powershell
# 1. 后端 API（读取 .env）
Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "app/main.py" -WorkingDirectory $PWD
# 2. Celery Worker（QUEUE_BACKEND=celery 时必须常驻）
Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "scripts/celery_worker.py" -WorkingDirectory $PWD
# 3. 前端
Start-Process -FilePath "npm.cmd" -ArgumentList "run","dev" -WorkingDirectory "frontend"
# 4. 真实 DPO/SFT trainer（监听 9101，使用独立训练 venv）
Start-Process -FilePath ".venv-trainer\Scripts\python.exe" -ArgumentList "scripts/trainer_dpo.py" -WorkingDirectory $PWD
# 或参考 trainer（仅联调，监听 9100）
# Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "scripts/trainer_reference.py" -WorkingDirectory $PWD
```

当前 `.env` 指向 VM 上的 Redis（`192.168.100.168:6379`，带密码）与 PostgreSQL；
Celery Worker 使用 `--pool=solo`，日志在 `logs/celery.log`，API 日志在
`logs/server.log`。重启机器后需要重新拉起 API、Celery Worker 和前端。

## 2. 环境变量清单

生产至少确认：

```env
APP_ENV=production
DEBUG=false
SECRET_KEY=<32+ 字节随机值>
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/<db>
AUTO_CREATE_TABLES=false
STRICT_CONFIG_CHECK=true
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800
AUTH_RATE_LIMIT_ENABLED=true
AUTH_RATE_LIMIT_PER_MINUTE=10
CORS_ORIGINS=https://console.example.com
FRONTEND_URL=https://console.example.com

INLINE_WORKER=false
QUEUE_BACKEND=db
# 或
# QUEUE_BACKEND=celery
# REDIS_URL=redis://:<password>@<redis-host>:6379/0
# 另起一个常驻进程：python scripts/celery_worker.py

MCP_ALLOWED_COMMANDS=python,python3,node
LOG_LEVEL=INFO
METRICS_ENABLED=true

VECTOR_BACKEND=auto
TRAINING_PROVIDER_URL=
TRAINING_PROVIDER_API_KEY=
```

敏感项（`SECRET_KEY`、数据库密码、LLM/Embedding Key、训练服务 Key）只放环境变量，
不要写入仓库；`.env` 已被 `.gitignore` 忽略。

## 3. 数据库迁移与备份

```bash
# 首次部署 / 升级
alembic upgrade head

# 查看当前版本
alembic current

# 回滚一个版本（确认无数据破坏后）
alembic downgrade -1

# 备份（在 PostgreSQL 主机执行）
pg_dump -Fc -h <host> -U <user> <db> > /backup/de_$(date +%F).dump

# 恢复
pg_restore -h <host> -U <user> -d <db> --clean /backup/de_YYYY-MM-DD.dump
```

建议：

- 每日全量 + 归档 WAL（按企业现有备份体系）。
- 升级前先备份，并在预发环境跑 `alembic upgrade head --sql` 审阅 SQL。
- 备份文件与应用分离存放，定期演练恢复。

## 4. Linux systemd 示例

`/etc/systemd/system/de-api.service`：

```ini
[Unit]
Description=Digital Employee API
After=network.target

[Service]
User=de
WorkingDirectory=/opt/digital-employee
EnvironmentFile=/opt/digital-employee/.env
ExecStart=/opt/digital-employee/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/de-worker.service`：

```ini
[Unit]
Description=Digital Employee DB Worker
After=network.target de-api.service

[Service]
User=de
WorkingDirectory=/opt/digital-employee
EnvironmentFile=/opt/digital-employee/.env
Environment=INLINE_WORKER=false
ExecStart=/opt/digital-employee/.venv/bin/python -m scripts.worker
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Celery 模式额外加 `de-celery.service`，ExecStart 指向
`scripts/celery_worker.py`，并确保 `QUEUE_BACKEND=celery`、Redis 可用。
API 与 `scripts/worker.py` 在 Celery 模式下不会启动 DB 任务 Worker。

Windows 开发机可用 NSSM 注册相同命令；生产建议 Linux。

## 5. Nginx 示例

```nginx
server {
    listen 443 ssl http2;
    server_name console.example.com;

    ssl_certificate     /etc/letsencrypt/live/console.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/console.example.com/privkey.pem;

    root /opt/digital-employee/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # 登录接口网关级限流（与后端进程内限流叠加）
    limit_req_zone $binary_remote_addr zone=login:10m rate=10r/m;

    location /api/v1/auth/login {
        limit_req zone=login burst=5 nodelay;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Request-ID $request_id;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Request-ID $request_id;
    }

    location /media/ {
        proxy_pass http://127.0.0.1:8000;
    }

    location = /health { proxy_pass http://127.0.0.1:8000; }
    location = /health/ready { proxy_pass http://127.0.0.1:8000; }

    # 指标只允许内网抓取
    location = /metrics {
        allow 10.0.0.0/8;
        deny all;
        proxy_pass http://127.0.0.1:8000;
    }
}
```

- 前端是 hash 路由，`try_files` 回退到 `index.html` 即可。
- `/media` 对应 AIGC 素材目录，注意磁盘配额与清理策略。
- `X-Request-ID` 可透传网关的请求 ID，便于日志串联。

## 6. 健康检查与监控

- 存活：`GET /health` → 200。
- 就绪：`GET /health/ready` → 数据库 / Redis 检查；非 200 时从负载均衡摘除。
- 指标：`GET /metrics`（Prometheus 文本）。
  - `http_requests_total`、`http_request_duration_seconds_*`、`app_uptime_seconds`。
- 建议告警：
  - 5xx 比例、P95 延迟；
  - 队列积压（`/api/v1/monitoring/queue`）；
  - Worker 心跳超时（`/api/v1/monitoring/workers`）；
  - `/health/ready` 连续失败；
  - 训练任务/评估回归失败。

## 7. 日志

- API/Worker 输出到 stdout，由 systemd journald 或日志采集器收集。
- 格式包含 `rid`（请求 ID）与 `tid`（任务 trace_id）。
- 日志轮转交给 journald / logrotate，应用不自行写文件。
- 审计日志在数据库 `audit_logs`，按合规要求保留与导出。

## 8. 安全清单

- 使用最小权限数据库账号（仅业务库 DML/DDL 所需权限）。
- 反向代理启用 TLS，关闭不必要端口；API 响应已带常用安全响应头。
- 登录/注册已启用进程内限流（默认 10 次/分钟/IP），建议同时在 Nginx 配
  `limit_req`，多实例部署时尤其必要。
- 新建/修改密码至少 8 位。
- `MCP_ALLOWED_COMMANDS` 只放行必要命令；Python 工具在子进程沙箱运行。
- 岗位契约与准入规则先配置再让员工上岗；越权类失败不进入学习。
- `/metrics`、`/docs`、`/redoc` 在公网应关闭或限制访问（可按环境用网关控制）。
- 定期轮换 `SECRET_KEY`（会使既有 JWT 失效）、数据库密码、外部服务 Key。
- AIGC 素材目录定期清理并做容量告警。

## 9. 发布与回滚流程

1. 备份数据库。
2. 部署代码，安装依赖（`pip install -e .` 或 `uv sync`）。
3. `alembic upgrade head`，并执行 `alembic check` 确认无漂移。
4. `npm ci && npm run build`，发布 `frontend/dist`。
5. 重启 API 与 Worker。
6. 检查 `/health/ready`、`/metrics`、任务队列。
7. 定期执行 `python scripts/maintenance.py` 预览，再按需 `--apply` 清理过期数据。
8. 出问题：回滚代码 + `alembic downgrade -1` + 恢复备份（如涉及数据变更）。

## 10. 与业务回滚的关系

- **学习工件回滚**：调教台/工件接口按版本回滚，不需要回滚数据库。
- **技能升级回滚**：评估回归失败会自动回滚技能版本。
- **发布阶段回滚**：影子/金丝雀可随时回到上一阶段。
- **数据库回滚**：仅用于 schema 变更事故，需与应用版本一起回退。
