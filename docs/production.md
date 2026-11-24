# 生产化：Alembic、Celery、pgvector、可观测性

本文件对应需求文档的生产化项，P0–P2 业务闭环见
`docs/p0-contract-learning.md`、`docs/p1-evaluation-loop.md`、
`docs/p1-skill-marketplace.md`、`docs/p2-learning-loop.md`。

## 1. Alembic 迁移

已添加基线迁移 `alembic/versions/0001_baseline.py`（57 张业务表），
`alembic/env.py` 使用 `settings.database_url` 与 `Base.metadata`。

```bash
# 新库
alembic upgrade head

# 已有开发库（表已存在）：只标记基线，不重复建表
alembic stamp head

# 当前版本
alembic current

# 后续模型变更
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

生产环境建议：

```env
AUTO_CREATE_TABLES=false
STRICT_CONFIG_CHECK=true
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800
AUTH_RATE_LIMIT_ENABLED=true
AUTH_RATE_LIMIT_PER_MINUTE=10
```

并只通过 Alembic 管理 schema。当前开发库已执行 `alembic stamp head`。

## 2. 队列：数据库默认，Celery 可选

默认 `QUEUE_BACKEND=db`：沿用数据库持久化队列 + 内联/独立 Worker，无需 Redis。

启用 Celery：

```bash
pip install ".[workers]"          # celery[redis] + redis
# 启动 Redis 后
export QUEUE_BACKEND=celery
export REDIS_URL=redis://:<password>@<redis-host>:6379/0
python scripts/celery_worker.py
```

行为：

- `QUEUE_BACKEND=celery` 时 API **不再启动内联 DB Worker**，避免重复执行；
  `scripts/worker.py` 也不再启动任务 Worker（仍可启动 AIGC/审批 Worker）。
- 任务创建接口提交后投递 `digital_employee.run_task`；每个 Celery 任务
  `asyncio.run(run_task_graph(...))` 并在结束时 `engine.dispose()`，避免跨事件循环
  复用 asyncpg 连接。
- `app/worker/celery_app.py` 通过 `include=["app.worker.tasks"]` 注册任务；
  `app/worker/tasks.py` 导入 `app.domains.models`，保证 Worker 进程的
  `Base.metadata` 完整（否则外键解析会失败）。
- 触发器在 Celery 模式下仍由 API/独立 Worker 的 `run_trigger_scheduler` 扫描；
  创建实例并提交后再 `enqueue_task`，避免 Worker 读不到未提交的任务行。
  手动触发接口返回 `queued` 字段。
- Celery 未安装或 Redis 不可用时，入队失败会记录日志并保留在数据库队列，
  不会丢掉任务；但此时必须确保有 DB Worker 在跑，否则任务会停在 `pending`。
- **当前环境**：Redis 7.2.4 运行在数据库 VM（`192.168.100.168:6379`），
  `.env` 已设置 `QUEUE_BACKEND=celery` 与带密码的 `REDIS_URL`；
  Celery Worker 以 `--pool=solo` 在宿主机运行，任务创建/手动触发/定时触发
  三条路径均已实测由 Celery 执行。

配置：

```env
QUEUE_BACKEND=celery
REDIS_URL=redis://:<password>@<redis-host>:6379/0
CELERY_BROKER_URL=
CELERY_RESULT_BACKEND=
CELERY_TASK_QUEUE=tasks
```

外部训练服务（可选）：

```env
TRAINING_PROVIDER_URL=https://trainer.example.com/jobs
TRAINING_PROVIDER_API_KEY=
TRAINING_PROVIDER_TIMEOUT=60
TRAINING_DATASET_MAX_BYTES=52428800
```

派发时会为每个任务生成一次性 `callback_token` 并放入请求体；数据库只保存
SHA-256 哈希。外部 trainer 回调状态时使用 `X-Training-Token: <callback_token>`，
也可使用租户内用户 JWT。令牌仅对单个任务有效。

参考 trainer（用于联调，不执行真实训练）：

```bash
# 默认监听 127.0.0.1:9100，回调平台 http://127.0.0.1:8000
.venv\Scripts\python.exe scripts/trainer_reference.py

# .env
TRAINING_PROVIDER_URL=http://127.0.0.1:9100/jobs
```

它接收数据集后返回 `job_id`，随后回调 `running` 与 `succeeded` 指标。
端到端验证：

```bash
.venv\Scripts\python.exe scripts/trainer_smoke.py
```

当前环境已用参考 trainer 验证：偏好对采集 → JSONL 导出 → 创建训练任务 →
派发 → 回调 `running/succeeded`，任务最终 `succeeded`，派发元信息与回调指标
合并保留。

真实 DPO/SFT trainer（小模型参考实现）：

```bash
# 独立训练环境（不影响平台 venv）
uv venv .venv-trainer --python 3.14
uv pip install --python .venv-trainer\Scripts\python.exe torch transformers httpx

# 默认 127.0.0.1:9101，CPU 训练，中文小模型
.venv-trainer\Scripts\python.exe scripts/trainer_dpo.py
```

- 实现：`scripts/trainer_dpo.py`
- 默认模型：`uer/gpt2-chinese-cluecorpussmall`（102M 参数）
- `method=dpo`：对 chosen/rejected 做真实 DPO 偏好损失；
  `method=sft`：对 chosen 文本做交叉熵
- 训练产物保存到 `data/training/models/<job_id>/`，包含
  `model.safetensors`、`config.json` 与 tokenizer 文件
- 回调契约与参考 trainer 完全一致

可调环境变量：

```env
TRAINER_PORT=9101
PLATFORM_BASE_URL=http://127.0.0.1:8000
TRAINER_MODEL=uer/gpt2-chinese-cluecorpussmall
TRAINER_DEVICE=auto
TRAINER_MAX_STEPS=2
TRAINER_MAX_LENGTH=128
TRAINER_LR=5e-5
TRAINER_BETA=0.1
TRAINER_OUTPUT_DIR=data/training/models
HF_ENDPOINT=https://hf-mirror.com
```

实测（job #7）：2 步 DPO，CPU，耗时 14.3s，loss 0.445，
产物 `data/training/models/7` 可正常加载并推理。当前 `.env` 指向
`TRAINING_PROVIDER_URL=http://127.0.0.1:9101/jobs`。

> 当前 `torch` 为 CPU 版，RTX 3050 Ti 4GB 未启用。要大模型/GPU 训练，需在
> `.venv-trainer` 安装匹配驱动的 CUDA 版 torch，并设置
> `TRAINER_MODEL` / `TRAINER_DEVICE=cuda`；4GB 显存建议使用 LoRA/4bit。
> 大规模 DPO/SFT 仍建议外接专业训练服务。

学习节奏自动化（可选，时间均按 UTC）：

```env
LEARNING_SCHEDULER_ENABLED=true
LEARNING_SCHEDULER_POLL_INTERVAL=60
LEARNING_DAILY_AT=02:00
LEARNING_DAILY_LOOKBACK_HOURS=24
LEARNING_WEEKLY_WEEKDAY=0          # 0=周一
LEARNING_WEEKLY_AT=09:00
LEARNING_AUTO_QUESTION_ENABLED=true
LEARNING_AUTO_QUESTION_CONFIDENCE=0.6
LEARNING_AUTO_QUESTION_RECURRENCE=2
LEARNING_AUTO_QUESTION_MAX_PER_RUN=2
WEEKLY_REVIEW_DELIVERY_URL=        # 留空则只生成不投递
WEEKLY_REVIEW_DELIVERY_TIMEOUT=10
LLM_ATTRIBUTION_ENABLED=false      # 开启后日结自动复核低置信度规则归因
LLM_ATTRIBUTION_MIN_CONFIDENCE=0.75
LLM_ATTRIBUTION_MAX_PER_RUN=5
LLM_RECOMMEND_TIMEOUT=60
REFLECTION_ENABLED=true            # 失败后进入反思节点
REFLECTION_AUTO_RETRY=true         # 仅自由任务；固定任务永不自动重试
REFLECTION_LLM_ENABLED=false       # 可选 LLM 反思
REFLECTION_MAX_RETRIES=1
```

定时器随 API 进程启动；多实例重复执行由归因与周报的幂等查询兜底。
需要独立部署时可设置 `LEARNING_SCHEDULER_ENABLED=false`，改由外部定时任务调用
`POST /learning/jobs/daily-batch` 与 `POST /weekly-reviews/generate-batch`。

## 3. pgvector 可选向量检索

`app/domains/knowledge/vector_store.py` 提供可选 pgvector 后端：

- `VECTOR_BACKEND=auto`（默认）：检测到 `vector` 扩展就用 pgvector，否则回退 JSON 内积。
- `VECTOR_BACKEND=json`：强制 JSON。
- `VECTOR_BACKEND=pgvector`：优先 pgvector；扩展不可用时仍会安全回退并记录告警。

实现要点：

- 惰性创建 `knowledge_chunk_vectors(chunk_id, tenant_id, base_id, embedding vector, model)`；
  DDL 与写入/检索/清理都包在 SAVEPOINT 中，失败不会污染业务事务。
- 新增文档、`reindex` 时同步向量；删除文档/知识库时清理。
- `POST /knowledge-bases/{id}/search` 的 `mode=vector` 在 pgvector 可用时走
  `embedding <=> query` 精确检索；`mode=auto` 仍保持现有 Python 混合检索。
- `GET /knowledge-bases/{id}/vector-status` 查看当前后端。
- `knowledge_chunk_vectors` 由 `vector_store` 惰性创建，不属于 ORM 模型；
  `alembic/env.py` 的 `include_object` 已排除该表及其索引，避免 `alembic check`
  误报“删除表”。

**当前环境已安装并验证**：

- PostgreSQL 为 `de-pg` 容器（`postgres:16-alpine`，PG 16.15，musl）
- pgvector **0.8.1** 已编译并装入容器，`CREATE EXTENSION vector` 成功
- `.env` 已设置 `VECTOR_BACKEND=pgvector`
- 实测 `reindex` 返回 `vector_backend=pgvector, synced=1`，
  `knowledge_chunk_vectors.embedding` 为 `vector` 类型，
  `mode=vector` 检索返回 `vector_score`

> Alpine 仓库里的 `postgresql-pgvector` 0.8.1 依赖 PostgreSQL 18
> （v3.24），v3.21 的包依赖 PostgreSQL 17，均不能直接用于官方
> `postgres:16-alpine` 镜像。本次是按源码针对 PG16 编译。

复现步骤（在同一 VM 上）：

```bash
# 1. 用同版本镜像准备构建环境（Alpine 镜像源慢时可换阿里云/清华）
docker run -d --name pgvector-build --network host postgres:16-alpine \
  sh -c "sed -i 's#dl-cdn.alpinelinux.org#mirrors.tuna.tsinghua.edu.cn#g' /etc/apk/repositories \
  && apk add --no-cache build-base && sleep 7200"

# 2. 下载 pgvector 源码（github.com 慢时用 codeload.github.com）
curl -sSL https://codeload.github.com/pgvector/pgvector/tar.gz/refs/tags/v0.8.1 \
  -o /tmp/pgvector.tar.gz
mkdir -p /tmp/pgvector-src
tar -xzf /tmp/pgvector.tar.gz -C /tmp/pgvector-src --strip-components=1
docker exec pgvector-build mkdir -p /src
docker cp /tmp/pgvector-src/. pgvector-build:/src

# 3. 编译（官方 PG 镜像带 LLVM，但容器内没有 clang-21，必须关闭 bitcode）
docker exec pgvector-build sh -c \
  "cd /src && make with_llvm=no && make install with_llvm=no"

# 4. 把 vector.so 与扩展 SQL/control 复制进数据库容器
docker cp pgvector-build:/usr/local/lib/postgresql/vector.so /tmp/vector.so
docker cp /tmp/vector.so de-pg:/usr/local/lib/postgresql/vector.so
docker exec pgvector-build sh -c \
  "cd /usr/local/share/postgresql/extension && tar cf - vector*" \
  | docker exec -i de-pg sh -c \
  "cd /usr/local/share/postgresql/extension && tar xf -"

# 5. 创建扩展（de-pg 的数据库超级用户是 de，不是 postgres）
docker exec -e PGPASSWORD=de de-pg psql -h 127.0.0.1 -U de \
  -d digital_employee_platform -c 'CREATE EXTENSION IF NOT EXISTS vector;'
```

注意：扩展文件在 `de-pg` 容器的可写层中，**重建容器会丢失**。长期方案是把
上述步骤固化到自定义镜像，或在容器重建后重新执行。验证：

```sql
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
SELECT count(*) FROM knowledge_chunk_vectors WHERE base_id = <id>;
```

安装后重启后端，并对知识库执行 `POST /knowledge-bases/{id}/reindex`。
`VECTOR_BACKEND=auto` 仍可在缺少扩展时安全回退 JSON。

## 4. 可观测性

- **请求 ID**：`ObservabilityMiddleware` 为每个请求生成或透传 `X-Request-ID`，
  响应带 `X-Request-ID` 与 `X-Process-Time-Ms`。
- **结构化日志**：格式包含 `rid`（请求 ID）与 `tid`（任务 trace_id）；
  任务引擎执行时把 `TaskInstance.trace_id` 写入 ContextVar。
- **Prometheus 指标**：`GET /metrics`（无 `/api/v1` 前缀）输出
  `http_requests_total`、`http_request_duration_seconds_sum/count`、`app_uptime_seconds`，
  以及数据库侧 `de_tasks_total{status}`、`de_worker_heartbeats`；
  路径中的数字会归一化为 `{id}`，避免标签爆炸。可用 `METRICS_ENABLED=false` 关闭。
- **敏感操作管理员校验**：契约保存、学习工件审批/发布/回滚/共享、技能包创建/发布/下架、
  训练任务创建/派发、能力迁移等接口要求 `is_superuser`；普通用户仍可查看与执行
  任务相关操作。训练状态回调额外支持任务级 `X-Training-Token`。
- **就绪检查**：`GET /health/ready` 检查数据库；`QUEUE_BACKEND=celery` 时额外检查
  Redis 连通性，失败返回 503。存活检查仍用 `GET /health`。
- `/metrics` 默认无鉴权，建议由反向代理限制内网访问。
- **安全响应头**：所有响应附加 `X-Content-Type-Options: nosniff`、
  `X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`、
  `Permissions-Policy`。
- **登录限流**：`/api/v1/auth/login` 与 `/register` 按 IP 使用进程内滑动窗口，
  默认 10 次/分钟，超限返回 429 + `Retry-After`。
  - `AUTH_RATE_LIMIT_ENABLED`、`AUTH_RATE_LIMIT_PER_MINUTE` 可调；
  - 多进程/多实例时每进程独立计数，生产建议同时在 Nginx 配 `limit_req`；
  - 仅在可信反向代理后使用 `X-Forwarded-For`/`X-Real-IP`，否则客户端可伪造。
- **密码策略**：新建/修改密码至少 8 位；登录不限制历史密码长度，避免锁死老账号。

## 5. 任务预算与数据维护

### 启动配置校验

`app/core/startup.py` 在 `APP_ENV=production/prod` 时检查：

- `SECRET_KEY` 是否仍为默认值或长度不足 32；
- `DEBUG`、`AUTO_CREATE_TABLES` 是否为危险值；
- CORS 是否仍包含 localhost；
- Celery 模式是否缺少 Redis；
- `TRAINING_PROVIDER_URL` 是否为 http(s)；
- `WEEKLY_REVIEW_DELIVERY_URL` 是否为 http(s)；
- `LEARNING_WEEKLY_WEEKDAY` 是否在 0-6；
- `LLM_ATTRIBUTION_ENABLED` / `REFLECTION_LLM_ENABLED=true` 时是否配置了 LLM Key；
- `FRONTEND_URL` 是否使用 https。

默认只记录告警；`STRICT_CONFIG_CHECK=true` 时启动失败，适合生产 fail-fast。

### 任务级预算

员工 `config` 支持：

```json
{
  "max_tokens_per_task": 20000,
  "max_cost_per_task": 1.5
}
```

任务执行中累计 `task_steps` 的 tokens/cost；超过上限时当前步骤保留成功记录，
任务转为 `failed` 并写入预算超限原因。`0` 或未配置表示不限制。

### 提示词 Token 计量

`app/core/tokenizer.py` 优先使用 `tiktoken` 按模型编码器计量提示词预算：

```bash
pip install ".[tokenizer]"
```

- 已安装时按 `model_name` 匹配编码器，未知模型回退 `o200k_base` / `cl100k_base`；
- 未安装、离线且无缓存或编码失败时，回退为 CJK 1.5 字符/token、其他 4 字符/token
  的保守估算，不影响启动；
- `fit_sections` 采用二分查找按真实 token 截断，不再按字符数截断；
- 任务步骤 Token 仍以 LLM 返回的 `usage.total_tokens` 为准，二者互补；
- 离线部署可预先设置 `TIKTOKEN_CACHE_DIR` 并预热编码文件。

### 数据维护

```bash
# 预览
python scripts/maintenance.py

# 执行默认清理（过期提问 + 7 天前 Worker 心跳）
python scripts/maintenance.py --apply

# 额外清理 180 天前审计日志（确认合规保留期！）
python scripts/maintenance.py --apply --audit-days 180

# 清理 30 天前且未被训练任务引用的 data/training 文件
python scripts/maintenance.py --apply --training-days 30
```

审计日志删除属于破坏性操作，默认关闭，必须显式传天数并 `--apply`。

### 迁移漂移检查

```bash
alembic check
```

输出 `No new upgrade operations detected.` 表示模型与数据库一致，可加入发布前检查。

### 查询索引

迁移 `0005`（`1d85d3fd3413`）补充了队列与学习闭环常用索引：

- `task_instances(status, next_run_at)`：Worker 领取与队列积压；
- `audit_logs(created_at)`：审计检索与保留期清理；
- `worker_heartbeats(last_seen_at)`：心跳巡检；
- `learning_questions(status, expires_at)`：过期提问处理；
- `learning_artifacts(status, scope)`：审批队列与共享读取；
- `preference_pairs(status)`、`training_jobs(status)`、`collaboration_runs(status)`、
  `failure_attributions(status)`、`evaluation_runs(status)`、`intervention_deltas(status)`。

## 6. 验证结果

- `alembic upgrade head --sql` 在 PostgreSQL 方言下成功渲染 57 张表。
- 已有开发库先执行 `alembic stamp 0001_baseline` 标记基线，再依次执行后续迁移；
  当前 head 为 `1d85d3fd3413`（P3 表、协作模式与性能索引）。
- `alembic check`：`No new upgrade operations detected.`
- `scripts/maintenance.py` dry-run 正常。
- `ruff check app tests scripts alembic/versions` 通过。
- `pytest`：61 passed（新增路径归一化、指标渲染、向量字面量、Celery 配置/eager、
  回调令牌、并行协作、配置校验、预算、限流与密码策略测试）。
- 前端 E2E 冒烟（Playwright/Edge）：登录、数字员工四个抽屉、任务协作页签、
  学习中心 10 个页签、训练数据、技能市场与详情抽屉，无 page/console error。
- 真实服务冒烟：
  - `/health/ready` 返回 database ok；
  - 响应包含 `X-Request-ID` / `X-Process-Time-Ms`；
  - `/metrics` 可抓取请求计数与运行时长；
  - `VECTOR_BACKEND=auto` 在缺少扩展时回退 json，文档写入/reindex/vector 检索均正常；
  - 安全响应头存在；登录连续 10 次失败后第 11 次返回 429（`Retry-After`）；
  - `QUEUE_BACKEND=celery` 且无 Redis 时就绪检查 503，任务创建不报错；
  - 安装 `workers` extra 后用 Celery eager 模式（无需 Redis）验证
    `enqueue_task` 与 `run_task` 全链路，任务成功落库；
  - 外部训练派发用本地 mock HTTP 服务验证，任务转为 `dispatched`。

## 7. 仍需注意

1. 当前环境已安装 Celery/Redis Python 包，并用 eager 模式验证了任务链路；
   但真实 Redis broker 与多进程 Worker 仍需在目标环境联调。pgvector 扩展仍未安装。
2. AIGC/审批 Worker 仍使用数据库队列；Celery 目前只接管任务执行队列。
3. `/metrics` 未鉴权；生产应放在内网或加反向代理白名单。
4. 生产密钥、TLS、备份、连接池参数仍由部署环境负责。
