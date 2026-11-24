# 数字员工平台（Digital Employee Platform）

用 FastAPI + SQLAlchemy + LangGraph 搭建的数字员工底座：让 AI 以“岗位”的身份，在受控权限下承接任务、执行并留下可审计的轨迹。

当前版本为 **MVP 框架骨架**，已实现：

- 认证与初始化管理员、JWT 登录
- 多租户基础隔离（租户 / 用户）
- 数字员工档案管理
- 授权登记（凭证加密存储）
- 路径级访问准入规则（`/admin/**` 拒绝、`/user/**` 允许，默认拒绝）
- 接口登记（手动 + OpenAPI 导入 + 一键转工具）
- 工具管理（HTTP / Python / MCP 三类）
- MCP Server 管理（stdio / SSE / Streamable HTTP + 工具自动同步）
- Agent 管理（内置 Agent / 第三方 Agent）
- 内置 Agent ReAct 执行（绑定工具、多轮推理）
- 多 Agent 编排（任务步骤 `type=agent`，可串联并传递结果）
- 工具执行器（HTTP 调用、Python 子进程沙箱、MCP 调用、准入拦截、凭证注入）
- 任务定义与任务实例，LangGraph 真实执行（感知 → 规划 → 执行 → 校验）
- 数据库持久化任务队列 + Worker（原子领取、失败重试、僵死任务回收）
- 人工确认步骤与恢复执行（`resume`），支持“纠正后批准”
- 岗位契约（can_do / cannot_do / must_ask / KPI / 汇报关系 / 自主权 L0–L3）
- 权限红线与任务引擎联动（禁用工具、只读、金额/条数阈值，越线转人工或拦截）
- 人工接管增量采集（Agent 原输出 vs 人工终稿结构化 diff）
- 偏好记忆（称呼、格式、结论先行等，实时注入提示词）
- 学习工件审批队列（归因 / 作用域 / 证据 / 审批 / 生效 / 回滚）
- 失败归因分类器（知识缺失 / 检索未召回 / 工具用错 / 规划错误 / 风格不符 / 越权）
- 综合评估套件（断言 / LLM 用例、基线回归、学习工件生效门禁）
- 影子试运行、上岗资格认证与员工数字履历
- 技能市场（技能包版本、依赖解析、冲突检测、权限并集、装配/升级/复制/推荐）
- 调教台（学习事件时间线、学习工件版本谱系、Diff 与回滚、轨迹逐帧回放）
- 学习工件影子/金丝雀/全量发布，按 trace 稳定分流
- 团队级/组织级经验共享（共享副本需再次审批）
- 主动学习每日提问预算、结构化提问与回答入库
- 成长周报、专家轨迹蒸馏
- Alembic 基线迁移（57 张业务表）与后续 autogenerate 流程
- 可选 Celery + Redis 任务队列；默认数据库持久化队列
- 可选 pgvector 向量检索；扩展不可用时自动回退 JSON 内积
- 请求 ID、结构化日志、Prometheus `/metrics` 与 `/health/ready`
- 生产配置校验（严格模式可启动失败）与数据库连接池参数
- 任务级 Token/成本预算
- 数据维护脚本（过期提问、Worker 心跳、可选审计与训练文件清理）
- 登录/注册限流、安全响应头与 8 位密码策略
- 队列与学习闭环关键查询索引（Alembic `0005`）
- 人格表现层（风格卡、禁忌词、统一润色）
- 分层记忆（冲突 supersede、情景压缩、过期遗忘）
- 业务结果回执（Outcome Telemetry）
- 入职引导（JD/SOP → 契约草稿、知识导入、示范案例）
- 提示词预算装配与“该问谁”协作路由
- 任务触发器（间隔/每日/事件）与主动汇报
- 岗位模板五件套（9 个内置岗位，一键装配）
- 幻觉检测（逐句来源支撑度）
- 多模态解析（文本/表格本地，图片/音频/PDF 走 Provider）
- 隐式学习信号（重复追问/换说法/放弃/复制片段）
- 多员工协作（`employee` 委派步骤 + 顺序/并行协作会话）
- DPO 偏好对采集、JSONL 导出、训练任务台账、外部 trainer 派发与任务级回调令牌
- 跨员工能力迁移（技能/工件/偏好/契约草稿，支持预览与冲突报告）
- 任务步骤轨迹、审计日志、人工反馈样本
- 监控指标（成功率、耗时、人工介入率、重试率、Token/成本）
- Worker 心跳与队列积压监控
- 告警规则、告警事件与 Webhook 通知
- 知识库（文档分块、向量 + 关键词混合检索、GraphRAG、知识图谱三元组）
- 内容风控（关键词规则 + 分级处置）
- 质检（规则扣分、A/B/C/D 评级、人工复核）
- AI 剧本 → 分镜（DeepSeek 场景/镜头拆解、JSON/CSV 导出）
- 团队模板（AI / 客服 / 研发 / 知识运营 / 企业级；角色预设、成员自定义、待确认启用）
- 前端控制台（运行概览、任务、知识、风控、质检、接入、治理）
- Alembic 迁移配置

## 技术栈

| 层    | 选型                                                   |
|------|------------------------------------------------------|
| Web  | FastAPI + Uvicorn                                    |
| ORM  | SQLAlchemy 2.0 async + Alembic                       |
| 校验   | Pydantic v2 + pydantic-settings                      |
| 认证   | PyJWT + PBKDF2                                       |
| 凭证   | Fernet（cryptography）                                 |
| 执行引擎 | LangGraph                                            |
| MCP  | 官方 mcp SDK（stdio / SSE / Streamable HTTP）            |
| 前端   | Vue 3 + Vite + TypeScript + Pinia + Vue Router（独立工程） |
| 数据库  | PostgreSQL 16                                        |

## 目录结构

```
app/
├── main.py                 # 应用入口、种子、Worker 生命周期
├── core/                   # 配置、数据库、安全、异常、响应、依赖
├── api/router.py           # 路由组合根
└── domains/                # 按业务域划分
    ├── identity/           # 租户、用户、登录
    ├── workforce/
    │   ├── employees/      # 数字员工
    │   ├── contracts/      # 岗位契约、自主权、权限红线
    │   └── teams/          # 角色、模板、团队
    ├── skills/
    │   ├── tools/          # 工具
    │   ├── mcp/            # MCP
    │   ├── agents/         # Agent
    │   ├── marketplace/    # 技能市场、依赖/冲突/权限并集
    │   └── registry/       # 接口登记
    ├── knowledge/          # 知识库、检索、GraphRAG
    ├── learning/           # 反馈、接管增量、偏好记忆、学习工件
    ├── workflows/
    │   ├── tasks/          # 任务队列与执行引擎
    │   ├── approvals/      # 审批流
    │   ├── aigc/           # AIGC 生成
    │   └── storyboards/    # 剧本分镜
    ├── governance/
    │   ├── access/         # 授权与准入
    │   ├── risk/           # 内容风控
    │   ├── quality/        # 质检
    │   └── audit/          # 审计
    └── operations/         # 监控、告警、Worker 心跳
frontend/                   # 独立前端工程（Vue 3 + Vite + TypeScript）
docs/requirements-agentic-workforce.md  # 平台目标需求说明
data/aigc/                  # AIGC 素材本地存储目录
scripts/                    # 冒烟测试、启动/停止脚本
alembic/                    # 数据库迁移
```

> 已实现 P0 的岗位契约、权限红线、接管增量、偏好记忆与学习工件基础
> （`docs/p0-contract-learning.md`），P1 的失败归因、综合评估套件、
> 影子试运行/上岗认证与数字履历（`docs/p1-evaluation-loop.md`），以及
> 技能市场与调教台版本谱系（`docs/p1-skill-marketplace.md`），以及 P2 的
> 影子/金丝雀发布、经验共享、主动学习、周复盘、专家轨迹与逐帧回放
> （`docs/p2-learning-loop.md`）。生产化基础已完成：Alembic 基线、可选
> Celery/Redis 队列、可选 pgvector、`/metrics` 与 `/health/ready`
> （`docs/production.md`）。P3 的多员工协作、DPO 数据资产/训练台账与跨员工
> 能力迁移也已实现（`docs/p3-collaboration-dpo-migration.md`），训练任务可派发到
> 外部 trainer（`TRAINING_PROVIDER_URL`）。部署与运维见 `docs/deployment.md`。
> 需求文档逐条对照见 `docs/requirements-checklist.md`。剩余：日结/周报定时化、
> 主动学习自动触发、Token 真实计量、LLM 归因/推荐、履历雷达图；
> 真实 Redis/pgvector 环境与外部训练服务仍需联调。

## 快速开始

```bash
# 1. 创建并激活虚拟环境（已有 .venv 可跳过）
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# 2. 安装依赖
pip install -e ".[dev]"

# 3. 准备环境变量
copy .env.example .env         # Windows
# cp .env.example .env         # macOS / Linux

# 4. 启动后端（Windows 控制台中文乱码时先执行 set PYTHONUTF8=1）
.venv\Scripts\python.exe -m app.main

# 5. 另开一个终端启动前端
cd frontend
npm install
npm run dev
```

数据库 schema：

- 开发期默认 `AUTO_CREATE_TABLES=true`，启动时自动建表。
- 生产/受控环境设 `AUTO_CREATE_TABLES=false`，执行 `alembic upgrade head`；
  已有开发库（表已存在）执行 `alembic stamp head` 标记基线。
- 后续模型变更：`alembic revision --autogenerate -m "..."` 后 `alembic upgrade head`。

打开：

- **前端控制台：http://localhost:5173**
- Swagger：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health
- 服务信息：http://localhost:8000/info

前后端分离：FastAPI 只提供 `/api/v1` 与 `/media`，前端由 Vite（开发）或 Nginx（生产）独立托管。后端根路径 `/` 会重定向到
`FRONTEND_URL`。

## 首次使用流程

```bash
# 1. 初始化管理员（仅首次可调用）
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"tenant_name":"演示租户","tenant_code":"demo","username":"admin","password":"admin123","full_name":"管理员"}'

# 2. 登录拿 token
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123","tenant_code":"demo"}'
```

后续请求带上 `Authorization: Bearer <access_token>`。

### 冒烟测试

另开一个终端，在服务运行状态下执行：

```bash
.venv\Scripts\python.exe scripts\smoke_test.py
```

覆盖：初始化管理员、数字员工、Python 工具、HTTP 工具、默认拒绝、固定任务、人工确认恢复、自动重试、MCP 工具同步与执行、Agent
注册与调用、多 Agent 编排、知识检索、风控、质检、分镜 CRUD、监控指标、告警评估与确认、OpenAPI 导入、一键转工具、审计日志。

P0 新增能力（岗位契约、权限红线、偏好记忆、接管增量、学习工件）的验证记录见
`docs/p0-contract-learning.md`；P1 的失败归因、综合评估与上岗认证见
`docs/p1-evaluation-loop.md`（`scripts/p1_smoke.py`）；技能市场与调教台见
`docs/p1-skill-marketplace.md`（`scripts/skill_market_smoke.py`）；P2 的发布、共享、
主动学习、周复盘、专家轨迹与回放见 `docs/p2-learning-loop.md`（`scripts/p2_smoke.py`）；
P3 的协作、DPO 数据与能力迁移见 `docs/p3-collaboration-dpo-migration.md`；
人格层、分层记忆、业务回执、入职引导、提示词预算与协作路由见
`docs/agent-studio.md`；逐条对照见 `docs/requirements-checklist.md`；
生产部署、备份、Nginx/systemd 示例见 `docs/deployment.md`；
配置校验、预算与维护见 `docs/production.md`。
前端页面冒烟：`scripts/p3_ui_smoke.py`（Playwright，截图写入系统临时目录）；
数据维护：`scripts/maintenance.py`（默认 dry-run）。

配置 DeepSeek 后，还可以跑 LLM 专项冒烟：

```bash
.venv\Scripts\python.exe scripts\llm_smoke.py
```

团队模板专项冒烟：

```bash
.venv\Scripts\python.exe scripts\team_smoke.py
```

AIGC 专项冒烟（内置 Mock 服务，无需外部 Key）：

```bash
.venv\Scripts\python.exe scripts\aigc_smoke.py
```

审批流专项冒烟（自动创建审批专员账号）：

```bash
.venv\Scripts\python.exe scripts\approval_smoke.py
```

Vue 前端冒烟（需先启动后端与 `frontend/npm run dev`）：

```bash
.venv\Scripts\python.exe scripts\vue_ui_smoke.py
```

### 质量检查

```bash
ruff check app tests scripts
pytest -q
```

## 核心接口

| 模块    | 路径                                                     | 说明                            |
|-------|--------------------------------------------------------|-------------------------------|
| 认证    | `POST /api/v1/auth/register`                           | 首次初始化管理员                      |
|       | `POST /api/v1/auth/login`                              | 登录                            |
|       | `GET /api/v1/auth/me`                                  | 当前用户                          |
| 数字员工  | `GET/POST /api/v1/digital-employees`                   | 列表 / 创建                       |
|       | `GET/PATCH/DELETE /api/v1/digital-employees/{id}`      | 详情 / 更新 / 停用                  |
| 岗位契约  | `GET/PUT /api/v1/digital-employees/{id}/contract`      | 读取 / 保存契约（仅人工，版本 +1）          |
|       | `POST /api/v1/digital-employees/{id}/contract/check`   | 预检工具调用是否触碰红线                  |
| 人格风格  | `GET/PUT /api/v1/digital-employees/{id}/persona`       | 风格卡 / 禁忌词 / 统一润色               |
| 分层记忆  | `GET /api/v1/digital-employees/{id}/memories`          | 工作/情景/语义/程序/偏好记忆总览            |
|       | `POST /api/v1/digital-employees/{id}/memories/compress` | 压缩情景记忆为学习工件                   |
| 入职引导  | `POST /api/v1/digital-employees/{id}/onboarding/import` | JD/SOP → 契约草稿 / 知识导入            |
|       | `GET/POST /api/v1/digital-employees/{id}/few-shot-examples` | 示范案例                         |
|       | `POST /api/v1/digital-employees/{id}/onboarding/examples` | 批量导入入职案例                    |
| 业务回执  | `GET/POST /api/v1/outcome-events`                      | 结果回执列表 / 记录                   |
|       | `GET /api/v1/outcome-events/stats`                     | 各类型成功率                        |
| 协作路由  | `GET /api/v1/digital-employees/{id}/routing`           | 推荐“该问谁”                       |
| 任务触发器 | `GET/POST /api/v1/task-triggers`                       | 触发器列表 / 创建（间隔/每日/事件）         |
|       | `POST /api/v1/task-triggers/{id}/fire`                 | 立即触发                          |
|       | `POST /api/v1/task-triggers/events/{event_name}`       | 事件驱动触发                        |
| 岗位模板  | `GET /api/v1/job-templates`                            | 岗位模板列表                        |
|       | `POST /api/v1/digital-employees/{id}/apply-job-template` | 一键装配技能/人设/契约草稿              |
| 幻觉检测  | `POST /api/v1/hallucination/check`                     | 答案逐句来源支撑度                     |
|       | `GET /api/v1/hallucination/checks`                     | 检测记录                          |
| 多模态   | `POST /api/v1/multimodal/extract`                      | 文本/表格/图片/音频/PDF 解析             |
|       | `GET /api/v1/multimodal/extractions`                   | 解析记录                          |
| 隐式信号  | `GET/POST /api/v1/implicit-signals`                    | 列表 / 记录                       |
|       | `GET /api/v1/implicit-signals/stats`                   | 分类统计                          |
| 授权    | `GET/POST /api/v1/authorizations`                      | 授权登记（凭证加密）                    |
|       | `PATCH/DELETE /api/v1/authorizations/{id}`             | 更新 / 删除                       |
| 准入规则  | `GET/POST /api/v1/access-rules`                        | 规则列表 / 创建                     |
|       | `PATCH/DELETE /api/v1/access-rules/{id}`               | 更新 / 删除                       |
|       | `POST /api/v1/access-rules/check`                      | 模拟访问检查                        |
| 接口登记  | `GET/POST /api/v1/api-registries`                      | 列表 / 登记                       |
|       | `POST /api/v1/api-registries/import-openapi`           | 导入 OpenAPI                    |
|       | `POST /api/v1/api-registries/{id}/to-tool`             | 一键转工具                         |
| 技能市场  | `GET/POST /api/v1/skill-packages`                      | 市场列表 / 创建技能包                  |
|       | `GET /api/v1/skill-packages/{code}`                    | 详情与版本历史                       |
|       | `POST /api/v1/skill-packages/{code}/versions`          | 创建新版本                         |
|       | `POST /api/v1/skill-packages/{id}/publish`             | 发布版本                          |
|       | `GET/POST /api/v1/digital-employees/{id}/skills`       | 已装技能 / 安装（自动解析依赖）             |
|       | `POST /api/v1/digital-employees/{id}/skills/copy`      | 跨员工复制技能                       |
|       | `POST /api/v1/digital-employees/{id}/skills/{code}/upgrade` | 升级并跑评估回归                 |
|       | `GET /api/v1/digital-employees/{id}/skills/recommend`  | 规则版组合推荐                       |
| 工具    | `GET/POST /api/v1/tools`                               | 列表 / 创建                       |
|       | `GET/PATCH/DELETE /api/v1/tools/{id}`                  | 详情 / 更新 / 删除                  |
| MCP   | `GET/POST /api/v1/mcp-servers`                         | 列表 / 注册                       |
|       | `GET/PATCH/DELETE /api/v1/mcp-servers/{id}`            | 详情 / 更新 / 停用                  |
|       | `POST /api/v1/mcp-servers/{id}/sync`                   | 连接并同步远端工具                     |
|       | `GET /api/v1/mcp-servers/{id}/tools`                   | 已同步工具列表                       |
| Agent | `GET/POST /api/v1/agents`                              | 列表 / 注册                       |
|       | `GET/PATCH/DELETE /api/v1/agents/{id}`                 | 详情 / 更新 / 停用                  |
|       | `POST /api/v1/agents/{id}/invoke`                      | 调用 Agent（调试）                  |
| 任务    | `GET/POST /api/v1/tasks/definitions`                   | 任务定义                          |
|       | `GET/POST /api/v1/tasks/instances`                     | 任务实例 / 发起任务                   |
|       | `GET /api/v1/tasks/instances/{id}`                     | 详情 + 步骤轨迹                     |
|       | `POST /api/v1/tasks/instances/{id}/resume`             | 人工确认后恢复                       |
|       | `POST /api/v1/tasks/instances/{id}/retry`              | 手动重试失败任务                      |
|       | `POST /api/v1/tasks/instances/{id}/cancel`             | 取消                            |
| 知识库   | `GET/POST /api/v1/knowledge-bases`                     | 知识库列表 / 创建                    |
|       | `GET/POST /api/v1/knowledge-bases/{id}/documents`      | 文档列表 / 新增并分块                  |
|       | `POST /api/v1/knowledge-bases/{id}/search`             | 知识检索（auto / vector / keyword） |
|       | `POST /api/v1/knowledge-bases/{id}/reindex`            | 重建分块向量                        |
|       | `POST /api/v1/knowledge-bases/{id}/graph-search`       | GraphRAG 图谱问答                 |
|       | `GET /api/v1/knowledge-bases/{id}/graph`               | 图谱节点与边                        |
|       | `POST /api/v1/knowledge-bases/{id}/import-triples`     | 批量导入三元组                       |
|       | `GET /api/v1/knowledge-bases/{id}/vector-status`       | 向量后端状态（pgvector/json）          |
| 风控    | `GET/POST /api/v1/risk/rules`                          | 规则列表 / 创建                     |
|       | `POST /api/v1/risk/check`                              | 内容风控检查                        |
|       | `GET /api/v1/risk/checks`                              | 检查记录                          |
| 质检    | `GET/POST /api/v1/qa/rules`                            | 质检规则列表 / 创建                   |
|       | `POST /api/v1/qa/checks`                               | 执行质检                          |
|       | `GET /api/v1/qa/checks`                                | 质检记录                          |
|       | `POST /api/v1/qa/checks/{id}/review`                   | 人工复核                          |
| 分镜    | `GET/POST /api/v1/storyboards`                         | 分镜项目列表 / 创建                   |
|       | `GET/PATCH/DELETE /api/v1/storyboards/{id}`            | 详情 / 更新 / 删除                  |
|       | `POST /api/v1/storyboards/{id}/generate`               | DeepSeek 生成分镜                 |
|       | `GET /api/v1/storyboards/{id}/export?format=json\|csv` | 导出分镜                          |
| AIGC  | `GET/POST /api/v1/aigc/providers`                      | 生成服务配置                        |
|       | `PATCH/DELETE /api/v1/aigc/providers/{id}`             | 更新 / 删除                       |
|       | `POST /api/v1/aigc/providers/{id}/test`                | 连通性测试                         |
|       | `GET/POST /api/v1/aigc/templates`                      | 提示词模板                         |
|       | `PATCH/DELETE /api/v1/aigc/templates/{id}`             | 更新 / 删除                       |
|       | `POST /api/v1/aigc/templates/{id}/render`              | 渲染模板变量                        |
|       | `GET/POST /api/v1/aigc/generations`                    | 生成任务列表 / 创建                   |
|       | `GET/DELETE /api/v1/aigc/generations/{id}`             | 详情 / 删除                       |
|       | `POST /api/v1/aigc/generations/{id}/cancel`            | 取消任务                          |
|       | `POST /api/v1/aigc/generations/{id}/retry`             | 重试任务                          |
|       | `GET /api/v1/aigc/assets`                              | 素材库                           |
|       | `POST /api/v1/aigc/assets/upload`                      | 上传源图（图生视频）                    |
|       | `GET/DELETE /api/v1/aigc/assets/{id}`                  | 素材详情 / 删除                     |
|       | `POST /api/v1/aigc/assets/{id}/review`                 | 审核素材                          |
|       | `GET /api/v1/aigc/stats`                               | 成本与产出统计                       |
| 审批流   | `GET/POST /api/v1/approvals/forms`                     | 审批表单                          |
|       | `PATCH/DELETE /api/v1/approvals/forms/{id}`            | 更新 / 删除                       |
|       | `GET/POST /api/v1/approvals/flows`                     | 审批流程                          |
|       | `PATCH/DELETE /api/v1/approvals/flows/{id}`            | 更新 / 删除                       |
|       | `GET/POST /api/v1/approvals/instances`                 | 审批实例列表 / 发起                   |
|       | `GET /api/v1/approvals/instances/{id}`                 | 详情（节点、任务、时间线）                 |
|       | `POST /api/v1/approvals/instances/{id}/cancel`         | 取消                            |
|       | `POST /api/v1/approvals/instances/{id}/remind`         | 催办                            |
|       | `POST /api/v1/approvals/instances/{id}/launch-task`    | 审批通过后创建员工任务                   |
|       | `GET /api/v1/approvals/tasks`                          | 我的待审批任务                       |
|       | `POST /api/v1/approvals/tasks/{id}/approve`            | 通过                            |
|       | `POST /api/v1/approvals/tasks/{id}/reject`             | 驳回                            |
|       | `POST /api/v1/approvals/tasks/{id}/transfer`           | 转办                            |
|       | `POST /api/v1/approvals/tasks/{id}/add-sign`           | 加签                            |
|       | `GET /api/v1/approvals/notifications`                  | 站内通知                          |
|       | `POST /api/v1/approvals/notifications/{id}/read`       | 标记已读                          |
|       | `POST /api/v1/approvals/notifications/read-all`        | 全部已读                          |
|       | `GET /api/v1/approvals/stats`                          | 工作台统计                         |
|       | `GET/POST /api/v1/auth/users`                          | 租户用户列表 / 创建（管理员）              |
| 团队    | `GET /api/v1/role-presets`                             | 角色预设库                         |
|       | `GET /api/v1/team-templates`                           | 团队模板列表                        |
|       | `GET/POST /api/v1/teams`                               | 团队列表 / 从模板创建                  |
|       | `GET /api/v1/teams/{id}`                               | 团队详情                          |
|       | `POST /api/v1/teams/{id}/activate`                     | 确认启用（管理员）                     |
|       | `POST /api/v1/teams/{id}/pause`                        | 暂停（管理员）                       |
|       | `DELETE /api/v1/teams/{id}`                            | 停用（管理员）                       |
| 监控    | `GET /api/v1/monitoring/overview`                      | 任务总览与指标                       |
|       | `GET /api/v1/monitoring/workers`                       | Worker 心跳与存活状态                |
|       | `GET /api/v1/monitoring/queue`                         | 队列积压                          |
| 告警    | `GET/POST /api/v1/alert-rules`                         | 规则列表 / 创建（管理员）                |
|       | `PATCH/DELETE /api/v1/alert-rules/{id}`                | 更新 / 删除（管理员）                  |
|       | `POST /api/v1/alert-rules/{id}/evaluate`               | 立即评估（管理员）                     |
|       | `GET /api/v1/alert-events`                             | 告警事件（管理员）                     |
|       | `POST /api/v1/alert-events/{id}/ack`                   | 确认告警（管理员）                     |
| 反馈    | `GET/POST /api/v1/feedback`                            | 人工反馈样本                        |
| 偏好记忆  | `GET/POST /api/v1/preferences`                         | 列表 / 写入（实时生效）                 |
|       | `PATCH/DELETE /api/v1/preferences/{id}`                | 更新 / 遗忘                       |
|       | `GET /api/v1/preferences/context/{employee_id}`        | 查看注入提示词的偏好上下文                 |
| 接管增量  | `GET/POST /api/v1/interventions`                       | 列表 / 单次示范教学                   |
|       | `GET/PATCH /api/v1/interventions/{id}`                 | 详情（含 diff）/ 状态               |
|       | `POST /api/v1/interventions/{id}/artifact`             | 提炼为学习工件                       |
| 学习工件  | `GET/POST /api/v1/learning-artifacts`                  | 列表（含审批队列）/ 创建                |
|       | `GET /api/v1/learning-artifacts/{id}`                  | 详情                            |
|       | `POST /api/v1/learning-artifacts/{id}/approve\|reject` | 审批                            |
|       | `POST /api/v1/learning-artifacts/{id}/activate`        | 生效                            |
|       | `POST /api/v1/learning-artifacts/{id}/rollback`        | 回滚                            |
|       | `POST /api/v1/learning-artifacts/{id}/archive`         | 归档                            |
|       | `GET /api/v1/learning-artifacts/{id}/lineage`          | 版本谱系                          |
|       | `POST /api/v1/learning-artifacts/{id}/new-version`     | 创建新版本                         |
|       | `POST /api/v1/learning-artifacts/{id}/rollout`         | 影子 / 金丝雀 / 全量发布               |
|       | `POST /api/v1/learning-artifacts/{id}/promote`         | 推进发布阶段                        |
|       | `POST /api/v1/learning-artifacts/{id}/share`           | 共享到团队 / 组织                    |
|       | `GET /api/v1/timeline`                                 | 调教台事件时间线                      |
| 主动学习  | `GET/POST /api/v1/learning-questions`                  | 提问列表 / 发起提问                   |
|       | `POST /api/v1/learning-questions/{id}/answer`          | 回答并生成学习工件                    |
|       | `GET /api/v1/digital-employees/{id}/learning-budget`   | 每日提问预算                        |
| 周复盘   | `GET/POST /api/v1/weekly-reviews`                      | 周报列表 / 生成                     |
|       | `GET /api/v1/weekly-reviews/{id}`                      | 周报详情                          |
| 专家轨迹  | `GET /api/v1/expert-trajectories/candidates`           | 候选成功轨迹                        |
|       | `POST /api/v1/expert-trajectories/distill`             | 蒸馏为学习工件                       |
| 任务回放  | `GET /api/v1/tasks/instances/{id}/replay`              | 逐帧轨迹与关联事件                     |
|       | `GET /api/v1/digital-employees/{id}/artifacts/context` | 生效工件上下文                       |
| 多员工协作 | `GET/POST /api/v1/collaborations`                      | 协作会话列表 / 发起                  |
|       | `GET /api/v1/collaborations/{id}`                      | 协作详情（同步父任务状态）                |
| 训练数据  | `GET /api/v1/preference-pairs`                         | 偏好对列表                         |
|       | `POST /api/v1/preference-pairs/collect`                | 采集偏好对                         |
|       | `POST /api/v1/preference-pairs/export`                 | 导出 DPO JSONL                    |
|       | `GET/POST /api/v1/training-jobs`                       | 训练任务列表 / 登记                  |
|       | `POST /api/v1/training-jobs/{id}/dispatch`             | 派发数据集到外部 trainer              |
|       | `POST /api/v1/training-jobs/{id}/status`               | 外部 trainer 回调状态               |
| 能力迁移  | `GET/POST /api/v1/capability-migrations`               | 迁移记录 / 执行（支持 dry_run）         |
|       | `GET /api/v1/capability-migrations/{id}`               | 迁移报告                          |
| 失败归因  | `GET /api/v1/attributions`                             | 归因列表                          |
|       | `POST /api/v1/attributions/analyze`                    | 归因任务失败或接管增量                   |
|       | `GET/PATCH /api/v1/attributions/{id}`                  | 详情 / 状态                       |
|       | `POST /api/v1/attributions/{id}/artifact`              | 归因转学习工件                       |
| 综合评估  | `GET/POST /api/v1/evaluation-suites`                   | 套件列表 / 创建                     |
|       | `GET/PATCH/DELETE /api/v1/evaluation-suites/{id}`      | 详情 / 更新 / 停用                  |
|       | `GET/POST /api/v1/evaluation-suites/{id}/cases`        | 用例列表 / 新增                     |
|       | `PATCH/DELETE /api/v1/evaluation-cases/{id}`           | 更新 / 停用用例                     |
|       | `POST /api/v1/evaluation-suites/{id}/run`              | 执行评估                          |
|       | `GET /api/v1/evaluation-runs`                          | 评估记录                          |
| 试运行   | `POST/GET /api/v1/digital-employees/{id}/trials`       | 发起 / 查询试运行与认证                 |
|       | `GET /api/v1/trials`                                   | 全部试运行记录                       |
|       | `GET /api/v1/digital-employees/{id}/profile`           | 员工数字履历                        |
| 审计    | `GET /api/v1/audit-logs`                               | 审计日志（管理员）                     |
| 系统    | `GET /health`                                          | 存活检查                          |
|       | `GET /health/ready`                                    | 就绪检查（数据库/队列）                  |
|       | `GET /metrics`                                         | Prometheus 指标（无 API 前缀）        |

## 前端控制台（Vue 3 + Vite + TypeScript）

前端已拆分为独立工程 `frontend/`，后端只保留 API。开发模式：

```bash
cd frontend
npm install
npm run dev
```

访问 **http://localhost:5173**。Vite 会把 `/api` 与 `/media` 代理到 `http://127.0.0.1:8000`。

生产构建：

```bash
cd frontend
npm run build
```

产物在 `frontend/dist/`，由 Nginx / CDN 托管，`/api` 与 `/media` 反向代理到 FastAPI。详细说明见 `frontend/README.md`。

已包含页面：

- 运行概览：任务趋势、成功率、人工介入、队列、Worker、异常任务
- 任务中心：实例 / 定义、发起任务、步骤轨迹、人工确认、重试、取消
- 数字员工：岗位、编码、模型与状态
- 知识库：文档分块、检索测试、GraphRAG 图谱问答、知识图谱
- 内容风控：规则管理、即时检查、检查记录
- 质检：规则扣分、即时评分、等级与人工复核
- 剧本分镜：创建项目、DeepSeek 生成场景/镜头、详情与 JSON/CSV 导出
- AIGC 生成：文生图/文生视频/图生视频、生成队列、素材库、人工审核、提示词模板、服务配置与成本统计
- 审批流：待我审批、我发起的、流程模板、表单模板、统计；通过/驳回/转办/加签/催办/取消、通知、超时处理、审批后创建员工任务
- 团队模板：模板卡、角色预设库、员工工牌、从模板创建团队
- 我的团队：待确认团队、成员/技能/工具/审批/沙箱、确认启用与暂停
- 能力接入：工具、MCP、Agent、接口登记
- 治理：授权与准入、告警、审计日志

首次部署点击登录页的“初始化管理员”，之后使用管理员账号登录。前端通过 JWT 调用 `/api/v1`，与后端同域（Nginx 反代）或跨域（配置
`CORS_ORIGINS`）均可。

前端冒烟测试（需安装 Playwright 与 Edge/Chrome，并先启动前后端）：

```bash
.venv\Scripts\python.exe -m pip install playwright
.venv\Scripts\python.exe scripts\vue_ui_smoke.py
```

截图输出到 `screenshots/`。

## 本地启动脚本

```powershell
# 同时打开后端与前端窗口
powershell -ExecutionPolicy Bypass -File scripts\start_dev.ps1

# 停止 8000 / 5173 进程
powershell -ExecutionPolicy Bypass -File scripts\stop_dev.ps1
```

单独启动：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_backend.ps1
powershell -ExecutionPolicy Bypass -File scripts\start_frontend.ps1
```

## 团队模板与团队创建

平台内置 5 个团队模板和 12 个角色预设：

| 模板     | 岗位                         |
|--------|----------------------------|
| AI 团队  | 内容策划、文案生成、审核员、数据分析         |
| 客服团队   | 客服值守、知识运营员、审核员             |
| 研发团队   | 产品经理、开发工程师、测试工程师           |
| 知识运营团队 | 知识运营员、审核员、数据分析             |
| 企业级团队  | IT值守员、HR助理、财务审计员、知识运营员、审核员 |

创建流程：

```
选择模板 → 自定义团队名/说明
        → 自定义成员：员工姓名、Skills、工具组、审批阈值、沙盒
        → 创建团队（pending_confirmation）
        → 管理员确认启用（active）
        → 自动生成 DigitalEmployee 并绑定团队角色
```

- 创建时即为每个成员生成数字员工（待确认状态下为 draft）。
- 确认启用后团队与员工变为 active；暂停/停用会同步停用员工。
- AI 团队只是内置模板之一，后续可新增更多行业模板。
- 启动时幂等写入内置角色和模板，不会覆盖自定义数据。
- 团队、成员、角色、模板相关操作全部写入审计日志。

## AI 剧本 → 分镜

1. `POST /api/v1/storyboards` 创建项目（标题、类型、风格、剧本）
2. `POST /api/v1/storyboards/{id}/generate` 调用 DeepSeek 拆解场景和镜头
3. 结果写入 `storyboard_scenes` / `storyboard_shots`，包含：
    - 场景：地点、时间、角色、概述、氛围
    - 镜头：景别、运镜、时长、台词、画面描述、AIGC 提示词、音效备注
4. `GET /api/v1/storyboards/{id}/export?format=json|csv` 导出

前端「业务模块 → 剧本分镜」可创建、生成、查看分镜表并下载 JSON/CSV。

## AIGC 内容生成

支持文生图、文生视频、图生视频。内置 Mock 服务开箱即用；真实服务通过生成服务适配层接入，无需改动任务队列、素材库与审核逻辑。

### 生成服务类型

| 类型             | 说明                                                     | 关键配置                                                                                          |
|----------------|--------------------------------------------------------|-----------------------------------------------------------------------------------------------|
| `mock`         | 无需外部 Key，输出带提示词的 SVG 占位素材，用于流程演示与联调                    | 无                                                                                             |
| `openai_image` | OpenAI 兼容 `/images/generations`，支持 URL 或 `b64_json` 返回 | `base_url`、`api_key`、`model`                                                                  |
| `comfyui`      | 提交 workflow → 轮询 `/history/{prompt_id}` → 下载 `/view`   | `config.workflow`、`prompt_node_id`、`prompt_input`；可选 `negative_node_id`、`input_image_node_id` |
| `http_generic` | 配置驱动的异步任务适配器，可对接即梦、可灵、Runway 等                         | `config.create`、`config.poll`、`result_url_path` / `task_id_path`                              |

`http_generic` 配置示例：

```json
{
  "create": {
    "method": "POST",
    "path": "/v1/generations",
    "body": {
      "prompt": "{{prompt}}",
      "negative_prompt": "{{negative_prompt}}",
      "duration": "{{duration}}"
    }
  },
  "task_id_path": "data.task_id",
  "poll": {
    "method": "GET",
    "path": "/v1/generations/{{task_id}}",
    "status_path": "data.status",
    "result_url_path": "data.video_url"
  }
}
```

ComfyUI 配置示例：

```json
{
  "workflow": {
    "6": {
      "class_type": "CLIPTextEncode",
      "inputs": {
        "text": ""
      }
    }
  },
  "prompt_node_id": "6",
  "prompt_input": "text",
  "input_image_node_id": "10",
  "input_image_input": "image"
}
```

图生视频时，平台会把素材库中的源图通过 ComfyUI `/upload/image` 上传后再注入 workflow。

### 任务与队列

- 创建任务只做校验、内容风控与成本预估，随后写入 `aigc_jobs` 持久化队列。
- 独立 AIGC Worker 使用条件 UPDATE 原子领取，失败按指数退避重试；进程重启回收僵死任务。
- 支持取消、手动重试，以及按状态 / 类型 / 生成服务筛选。
- 生成结果落盘到 `AIGC_STORAGE_DIR`（默认 `./data/aigc`），通过 `/media` 静态目录访问。

### 素材与审核

- 素材库同时保存生成结果与上传源图（图生视频输入）。
- 生成素材默认 `pending`，可人工通过 / 驳回，审核历史写入 `aigc_reviews`。
- 上传仅支持图片，出于安全考虑拒绝 SVG；默认上限 20MB。
- 提示词命中内容风控 `block` 规则时直接拒绝创建任务；`review` 只记录风险信息，素材仍进入人工审核。

### 提示词模板与成本

- 模板支持 `{{变量}}` 占位、默认变量、负向提示词与默认参数。
- 生成服务可配置单价与计价单位（每张图 / 每个视频 / 每秒 / 每次请求）。
- `GET /api/v1/aigc/stats` 返回任务量、成功率、平均耗时、成本、素材审核状态，以及按类型 / 服务 / 天聚合。

### 配置项

```env
AIGC_STORAGE_DIR=./data/aigc
AIGC_PUBLIC_PREFIX=/media
AIGC_WORKER_ENABLED=true
AIGC_WORKER_CONCURRENCY=2
AIGC_JOB_MAX_ATTEMPTS=2
# 应大于单次视频生成的最长耗时，避免运行中的任务被误回收
AIGC_STALE_SECONDS=1800
AIGC_UPLOAD_MAX_BYTES=20971520
```

前端「业务模块 → AIGC 生成」提供生成任务、素材库、提示词模板、生成服务与成本统计五个页签。

## 审批流引擎

通用审批工作台：表单模板、流程编排、条件分支、会签 / 或签 / 依次审批、转办、加签、催办、超时处理、站内通知、审计，以及审批通过后创建数字员工任务。

### 核心对象

| 对象                       | 说明                                                         |
|--------------------------|------------------------------------------------------------|
| `approval_forms`         | 表单模板，字段定义存 JSON，发起时按 schema 校验类型与必填                        |
| `approval_flows`         | 流程定义，节点按顺序执行，条件节点可跳转到任意节点 key                              |
| `approval_instances`     | 一次审批，发起时快照表单与流程，后续修改模板不影响在途审批                              |
| `approval_tasks`         | 节点上的审批人任务，支持 `waiting/pending/approved/rejected/cancelled` |
| `approval_actions`       | 审批时间线：提交、进入节点、通过、驳回、转办、加签、催办、超时、结束                         |
| `approval_notifications` | 站内通知：待审批、结果、转办、加签、催办、超时                                    |

### 节点类型

- `approval` 审批节点：`approvers` 支持用户 ID、`admin`（全部管理员）、`initiator`（发起人）。
- `condition` 条件节点：按表单字段判断，`on_true` / `on_false` 跳转到目标节点 key。
- `cc` 抄送节点：自动通知抄送人后继续。
- `end` 结束节点：实例状态变为已通过。

会签模式：

- `any` 或签：任一审批人通过即可，其余任务自动取消。
- `all` 会签：所有审批人都通过才进入下一节点。
- `sequence` 依次审批：按审批人顺序逐个激活。

条件节点示例：

```json
{
  "key": "c1",
  "name": "金额判断",
  "type": "condition",
  "field": "amount",
  "operator": "gt",
  "value": 5000,
  "on_true": "boss",
  "on_false": "finance"
}
```

支持的判断符：`eq/ne/gt/gte/lt/lte/in/not_in/contains/exists`。

### 审批动作

- **转办**：当前审批人把任务转给同租户其他用户，记录 `delegated_from` 与时间线。
- **加签**：当前节点审批人或管理员追加审批人；或签立即生效，会签需要新增审批人通过，依次审批排到队尾。
- **催办**：发起人或管理员通知当前所有待处理审批人。
- **取消**：发起人或管理员取消流程，未处理任务全部取消。
- **超时**：节点可配置 `timeout_hours` 与 `timeout_action`：
    - `remind`：提醒一次并顺延；
    - `auto_approve`：自动通过；
    - `auto_reject`：自动驳回；
    - `escalate`：转办给 `escalate_to` 中的审批人。

### 业务模板

启动时按租户幂等初始化三个模板：

1. **费用报销**：金额 > 5000 直达总经理，否则财务审核 → 总经理审批。
2. **合同审批**：法务审核 → 财务审核 → 总经理审批。
3. **文书用印**：部门负责人审批 → 用印管理员。

模板使用 `admin` 作为默认审批人（解析为租户内全部管理员），可在流程编辑器中改成具体用户；管理员可通过
`POST /api/v1/auth/users` 创建审批专员账号。

### 与数字员工任务联动

- 发起审批时可选择关联数字员工；审批通过后自动创建自由任务，任务 `input` 中包含 `approval_instance_id`、`form_data` 与
  `request`。
- 流程 `config` 也支持默认联动：

```json
{
  "auto_launch_task": true,
  "employee_id": 12,
  "title_template": "审批通过：{title}",
  "task_type": "free"
}
```

- 已通过的实例也可调用 `POST /api/v1/approvals/instances/{id}/launch-task` 手动创建任务；创建后实例记录
  `task_instance_id`。

### 配置项

```env
APPROVAL_WORKER_ENABLED=true
APPROVAL_TIMEOUT_CHECK_INTERVAL=60
```

审批超时由独立 Worker 扫描；内联模式下随 API 进程启动，独立部署时 `scripts/worker.py` 会同时启动任务 Worker、AIGC Worker
与审批 Worker。

前端「业务模块 → 审批流」提供待我审批、我发起的、流程模板、表单模板与统计五个页签，并在页面右上角提供通知入口。

## 任务执行与工具调用

### 执行流程

```
POST /tasks/instances
  → 后台 LangGraph：perceive → plan → execute → verify
  → 每步写 task_steps 并提交，监控端可实时看到进度
  → 遇到 human 步骤：实例进入 waiting_human
  → POST /tasks/instances/{id}/resume 确认后从下一步继续
```

执行计划会固化到 `task_instances.plan`，恢复时不会重新规划，避免步骤错位。

### 持久化队列与 Worker

任务不再依赖进程内的 `BackgroundTasks`，而是写入数据库队列：

```
POST /tasks/instances → status=pending
Worker 原子领取（条件 UPDATE）→ status=running, attempt+1
执行成功 → succeeded
执行失败 → 可重试则 pending + 指数退避；否则 failed
遇到 human 步骤 → waiting_human（不占重试次数）
```

- **内联 Worker**：`INLINE_WORKER=true`（默认），随 API 进程启动，适合开发和单机部署；AIGC Worker 与审批 Worker 分别由
  `AIGC_WORKER_ENABLED`、`APPROVAL_WORKER_ENABLED` 控制。
- **独立 Worker**：`INLINE_WORKER=false`，另开进程（同时启动任务队列 Worker、AIGC Worker 与审批 Worker）：

```bash
.venv\Scripts\python.exe -m scripts.worker
```

- 多实例部署时，数据库原子领取保证同一任务不会被重复执行；生产环境建议换 PostgreSQL。
- 进程异常退出后，`WORKER_STALE_SECONDS` 之外仍处于 running 的任务会在下次启动时被回收。

### 重试策略

- 每个任务有 `attempt` / `max_attempts`（默认 3）。
- 只重试基础设施类错误：超时、连接失败、HTTP 5xx/429、数据库锁、MCP 连接失败等。
- 业务错误不重试：访问被拒绝、工具/Agent 不存在、未配置 LLM、参数无效等。
- 退避时间：`TASK_RETRY_BASE_SECONDS * 2^(attempt-1)`，上限 `TASK_RETRY_MAX_SECONDS`。
- 失败任务可手动重试：`POST /api/v1/tasks/instances/{id}/retry`，从失败步骤继续，`attempt` 归零。

相关环境变量：

| 变量                        | 默认     | 说明                  |
|---------------------------|--------|---------------------|
| `QUEUE_BACKEND`           | `db`   | `db` 或 `celery`     |
| `REDIS_URL`               | `redis://127.0.0.1:6379/0` | Celery broker / backend 默认 |
| `CELERY_TASK_QUEUE`       | `tasks` | Celery 队列名         |
| `INLINE_WORKER`           | `true` | 是否随 API 进程启动 Worker（Celery 模式下自动关闭） |
| `WORKER_POLL_INTERVAL`    | `0.5`  | 轮询间隔（秒）             |
| `WORKER_CONCURRENCY`      | `2`    | 单 Worker 并发任务数      |
| `WORKER_STALE_SECONDS`    | `600`  | running 任务多久视为僵死    |
| `TASK_MAX_ATTEMPTS`       | `3`    | 默认最大尝试次数            |
| `TASK_RETRY_BASE_SECONDS` | `10`   | 退避基数                |
| `TASK_RETRY_MAX_SECONDS`  | `300`  | 退避上限                |
| `VECTOR_BACKEND`          | `auto` | `auto` / `json` / `pgvector` |
| `METRICS_ENABLED`         | `true` | 是否暴露 `/metrics`      |

### 固定任务 steps 示例

```json
{
  "name": "查询用户并生成摘要",
  "code": "user_report",
  "task_type": "fixed",
  "steps": [
    {
      "name": "查询用户",
      "type": "tool",
      "tool_code": "api_1",
      "arguments": {
        "user_id": "{{input.user_id}}"
      }
    },
    {
      "name": "生成摘要",
      "type": "llm",
      "prompt": "根据以下结果生成摘要：{{last.result.body}}"
    },
    {
      "name": "人工确认",
      "type": "human",
      "description": "确认摘要后再发送"
    }
  ]
}
```

### HTTP 工具配置示例

```json
{
  "name": "查询用户",
  "code": "crm_get_user",
  "tool_type": "http",
  "parameters_schema": {
    "type": "object",
    "properties": {
      "user_id": {
        "type": "integer"
      }
    }
  },
  "config": {
    "system_code": "crm",
    "method": "GET",
    "path": "/user/{{args.user_id}}",
    "timeout": 10
  }
}
```

- `path` 使用相对路径时，需要一条同 `system_code` 且带 `base_url` 的授权记录。
- 凭证按授权类型自动注入：`api_key` → 请求头，`token/oauth2` → Bearer，`cookie` → Cookie。
- **默认拒绝**：HTTP 工具调用前会走准入规则，必须存在匹配的 allow 规则，否则步骤失败。例如先创建：
    - allow `GET /user/**`（priority 10）
    - deny `/admin/**`（priority 100，优先级更高）

### Python 工具配置示例

```json
{
  "name": "计算金额",
  "code": "calc_amount",
  "tool_type": "python",
  "config": {
    "code": "def run(args):\n    return {'total': args.get('a', 0) + args.get('b', 0)}",
    "timeout": 10
  }
}
```

工具代码必须定义 `run(args: dict) -> dict`，执行时使用独立子进程，带超时和输出大小限制。

### MCP Server 配置示例

stdio（本地进程）：

```json
{
  "name": "Demo MCP",
  "code": "demo",
  "transport": "stdio",
  "command": "python",
  "args": [
    "scripts/demo_mcp_server.py"
  ],
  "cwd": "D:\\System\\code\\digital-employee-python",
  "env": {}
}
```

sse / streamable_http（远程服务）：

```json
{
  "name": "Remote MCP",
  "code": "remote",
  "transport": "streamable_http",
  "url": "https://mcp.example.com/mcp",
  "headers": {
    "Authorization": "Bearer <token>"
  }
}
```

使用流程：

1. `POST /api/v1/mcp-servers` 注册
2. `POST /api/v1/mcp-servers/{id}/sync` 连接、拉取工具并自动写入 `tools` 表
3. 在任务 steps 中用同步生成的 `tool_code` 调用，`tool_type` 为 `mcp`

安全约束：

- stdio 只能执行 `MCP_ALLOWED_COMMANDS` 白名单内的命令（默认 `python,python3,node,npx,uvx,uv`），生产环境务必显式配置。
- 每次调用新建 MCP 连接，不保留长连接；高频场景需要后续加连接池。
- MCP Server 停用后，其同步工具会一并停用。

### 本地演示 MCP Server

`scripts/demo_mcp_server.py` 提供 `add` 和 `echo` 两个工具，冒烟测试会自动拉起它。

### Agent 配置示例

内置 Agent（ReAct + 绑定工具，需要 `LLM_API_KEY`）：

```json
{
  "name": "审核 Agent",
  "code": "reviewer_agent",
  "agent_type": "internal",
  "protocol": "builtin",
  "system_prompt": "你是内容审核助手，必要时调用工具核实信息。",
  "tools": [
    "calc_amount",
    "mcp_1_add"
  ],
  "capabilities": [
    "审核",
    "计算"
  ],
  "config": {
    "max_steps": 6
  }
}
```

第三方 HTTP Agent：

```json
{
  "name": "外部写作 Agent",
  "code": "writer_agent",
  "agent_type": "third_party",
  "protocol": "http",
  "endpoint_url": "https://agent.example.com/invoke",
  "headers": {
    "Authorization": "Bearer <token>"
  },
  "config": {
    "timeout": 30
  }
}
```

第三方 OpenAI 兼容 Agent：

```json
{
  "name": "外部模型 Agent",
  "code": "openai_agent",
  "agent_type": "third_party",
  "protocol": "openai",
  "endpoint_url": "https://api.example.com/v1/chat/completions",
  "headers": {
    "Authorization": "Bearer <token>"
  },
  "model_name": "your-model"
}
```

任务中调用 Agent：

```json
{
  "name": "调用审核 Agent",
  "type": "agent",
  "agent_code": "reviewer_agent",
  "arguments": {
    "text": "{{input.content}}"
  },
  "prompt": "请审核以下内容：{{input.content}}"
}
```

多 Agent 编排：在固定任务里按顺序配置多个 `type=agent` 步骤即可，后续步骤可以通过 `{{last...}}` 引用上一个 Agent 的输出。

## 知识检索与向量

- `POST /knowledge-bases/{id}/search` 支持 `mode`：
    - `auto`：默认，0.7 × 向量相似度 + 0.3 × 关键词得分
    - `vector`：纯向量检索
    - `keyword`：纯关键词检索
- 文档创建时自动生成分块向量；历史数据可调用 `POST /knowledge-bases/{id}/reindex` 重建。
- 默认使用**本地哈希向量**，不需要 API Key；配置 `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` 后自动切换为
  OpenAI 兼容 Embedding。
- 本地哈希向量是词法哈希，不等同于语义模型；生产环境建议配置外部 Embedding。
- 当前向量在应用层计算余弦相似度；数据量增大后可迁移到 pgvector。

### GraphRAG 图谱问答

`POST /knowledge-bases/{id}/graph-search`：

1. 按查询词匹配图谱实体（种子实体）
2. 沿关系扩展 1~3 跳，得到实体与关系上下文
3. 同时做向量 + 关键词分块检索
4. 可选调用 DeepSeek，只基于上下文生成答案

```json
{
  "query": "退款政策属于哪个业务？",
  "top_k": 5,
  "max_hops": 1,
  "answer": true
}
```

返回 `seed_entities`、`entities`、`relations`、`chunks`、`context`、`answer`、`tokens`。任务步骤可使用 `type: "graph_rag"`
调用同样的能力。

## 监控与告警

### 总览接口

`GET /api/v1/monitoring/overview?days=7` 返回：

```json
{
  "totals": {
    "pending": 0,
    "running": 0,
    "waiting_human": 0,
    "succeeded": 5,
    "failed": 1,
    "cancelled": 0
  },
  "rates": {
    "success_rate": 0.8333,
    "failure_rate": 0.1667,
    "human_intervention_rate": 0.1667,
    "retry_rate": 0.1667
  },
  "performance": {
    "avg_duration_ms": 812.5,
    "p95_duration_ms": 2350.0,
    "total_tokens": 22,
    "total_cost": 0.0
  },
  "queue": {
    "pending": 0,
    "running": 0,
    "waiting_human": 0,
    "oldest_pending_age_seconds": 0.0
  },
  "workers": {
    "total": 1,
    "active": 1,
    "stale": 0
  },
  "by_employee": [
    {
      "employee_id": 1,
      "employee_name": "审核员",
      "total": 6,
      "succeeded": 5,
      "failed": 1,
      "success_rate": 0.8333,
      "avg_attempt": 1.17
    }
  ],
  "by_task_type": [
    {
      "task_type": "fixed",
      "total": 6,
      "succeeded": 5,
      "failed": 1
    }
  ],
  "time_series": [
    {
      "date": "2026-11-15",
      "total": 6,
      "succeeded": 5,
      "failed": 1
    }
  ],
  "recent_failures": [
    {
      "id": 4,
      "title": "默认拒绝验证",
      "error": "访问被拒绝..."
    }
  ]
}
```

指标口径：

- `success_rate = succeeded / (succeeded + failed)`，取消任务不计入。
- `human_intervention_rate = 有 human 步骤的任务数 / 窗口内任务数`。
- `retry_rate = attempt > 1 的任务数 / 窗口内任务数`。
- `avg_duration_ms` / `p95_duration_ms` 基于任务 `started_at` / `finished_at`。
- `total_cost` 按 `LLM_COST_PER_1K_TOKENS` 估算，未配置时为 0。

### Worker 心跳

- Worker 每 `WORKER_HEARTBEAT_INTERVAL` 秒写一次心跳。
- 超过 `WORKER_HEARTBEAT_TIMEOUT` 秒未更新视为 stale。
- `GET /api/v1/monitoring/workers` 可看到 worker_id、主机、PID、当前任务数。

### 告警规则

支持的指标：

| 指标                        | 含义              |
|---------------------------|-----------------|
| `failure_rate`            | 失败率（0-1）        |
| `queue_backlog`           | 待执行任务数          |
| `avg_duration_ms`         | 平均耗时            |
| `token_usage`             | Token 总量        |
| `token_cost`              | 估算成本            |
| `human_intervention_rate` | 人工介入率           |
| `sensitive_actions`       | 删除/停用/拒绝等敏感操作次数 |

比较符：`gt` / `gte` / `lt` / `lte`。

```json
POST /api/v1/alert-rules
{
  "name": "失败率告警",
  "metric": "failure_rate",
  "operator": "gt",
  "threshold": 0.2,
  "window_minutes": 60,
  "cooldown_minutes": 30,
  "webhook_url": "https://example.com/hooks/alert"
}
```

- Worker 每 `ALERT_CHECK_INTERVAL` 秒评估一次启用的规则。
- 触发后写入 `alert_events`，冷却期内不会重复生成事件。
- 配置 `webhook_url` 时会 POST 告警 JSON，结果记录在 `webhook_status`。
- 可手动触发评估：`POST /api/v1/alert-rules/{id}/evaluate`。

## 设计约定

- **默认拒绝**：准入规则未匹配到 allow 时一律拒绝；同优先级 deny 胜出。
- **凭证不落明文**：授权凭证使用 Fernet 加密，接口响应不回传凭证。
- **审计留痕**：所有写操作写入 `audit_logs`，任务执行带 `trace_id`。
- **多租户隔离**：所有业务查询强制带 `tenant_id`。
- **凭证密钥**：生产环境务必替换 `SECRET_KEY`，并妥善保管（更换会导致已存凭证无法解密）。

## 数据库配置

当前 `.env` 指向虚拟机 Docker 中的 PostgreSQL：

```ini
DATABASE_URL = postgresql+asyncpg://de:***@192.168.100.168:5432/digital_employee_platform
```

- 使用独立数据库 `digital_employee_platform`，避免与虚拟机上已有项目的 `digital_employee` 库冲突。
- 首次启动 `AUTO_CREATE_TABLES=true` 会自动建表；生产环境请关闭并执行 Alembic 迁移。
- 本项目只使用 PostgreSQL，不再保留 SQLite 开发库文件与兼容分支。
- 切换 MySQL：安装 `aiomysql` / `pymysql`，使用 `mysql+aiomysql://用户:密码@主机:3306/库名`。

如果从 `.env.example` 重新生成 `.env`，需要自行填入数据库连接串。

## 大模型配置

当前使用 DeepSeek：

```ini
LLM_PROVIDER = deepseek
LLM_MODEL = deepseek-chat
LLM_BASE_URL = https://api.deepseek.com/v1
# Key 从系统环境变量 DEEPSEEK_API_KEY 读取，也可填 LLM_API_KEY
LLM_API_KEY =
```

- 内部 Agent、自由任务规划、任务校验都使用该配置。
- DeepSeek 不提供 Embeddings；知识检索默认使用本地哈希向量。如需外部 Embedding，单独配置 `EMBEDDING_API_KEY` /
  `EMBEDDING_BASE_URL`。
- 验证 DeepSeek 集成：

```bash
.venv\Scripts\python.exe scripts\llm_smoke.py
```

该脚本会创建内部 Agent、调用模型，发起自由任务，生成一个分镜项目，并执行 GraphRAG 问答。

## 数据库迁移

开发期默认 `AUTO_CREATE_TABLES=true` 自动建表。生产环境请关闭并执行：

```bash
alembic revision --autogenerate -m "init schema"
alembic upgrade head
```

## 已知限制

- 当前使用数据库队列 + 数据库轮询，适合单机与中小规模；更高吞吐可平滑替换为 Celery / ARQ。
- 监控指标按请求实时聚合，数据量很大时建议增加日/小时汇总表。
- 告警 Webhook 失败只记录状态，不自动重发。
- MCP 每次调用新建连接，高频场景需要连接池或会话复用。
- 本地向量是词法哈希，不具备真正的语义理解；配置外部 Embedding 后效果更好。
- 向量相似度目前在应用层计算，数据量大时需要迁移到 pgvector 或专用向量库。
- GraphRAG 的图谱扩展基于实体名匹配，尚未把实体与分块做显式关联。
- 业务模块已实现内容风控、质检、剧本分镜、AIGC 生成与审批流；更复杂的组织权限与并行流程仍是后续增强项。
- 审批流的审批人目前支持具体用户、全部管理员与发起人，尚未接入部门 / 岗位 / 角色体系；条件节点是 if/else 链式跳转，暂不支持并行网关。
- 审批表单中的文件字段保存的是链接，未内置附件上传与电子签；通知目前只有站内消息，未接邮件 / IM / Webhook。
- 审批超时由 Worker 定时扫描（默认 60 秒），实际触发时间存在一个扫描周期的误差。
- 分镜生成会对 LLM 输出做数量、时长与字段归一化，但不会校验剧情合理性；分镜的 `image_prompt` 可直接作为 AIGC
  文生图提示词，尚未做一键批量联动。
- AIGC 默认使用内置 Mock 服务，生成的是 SVG 占位素材；真实出图 / 出视频需要配置外部生成服务或 ComfyUI。
- AIGC 素材默认存本地文件系统，生产环境建议替换为对象存储；目前只做提示词文本风控，未接入输出图片 / 视频的多模态审核。
- `http_generic` 只覆盖常见的“创建任务 + 轮询 + 下载 URL”模式，带签名或私有协议的厂商需要扩展 Provider。
- 团队模板中的角色是创建时的快照，后续修改角色预设不会自动更新已创建模板或团队。
- 暂停/停用团队会同步停用其员工；如果员工未来需要跨团队复用，需要调整归属模型。
- 前端以管理员视角为主，尚未做细粒度角色权限 UI。
- 内置 Agent 需要 `LLM_API_KEY`，未配置时只能使用第三方 Agent。
- Agent 间目前是顺序编排，尚未接入 A2A 协议与并行调度。
- 高风险工具不会自动插入人工确认，需在任务 steps 中显式配置 human 步骤。
- 新增了 `task_instances.plan` / `current_step_index` 字段；生产环境请使用 Alembic 迁移管理表结构。

## 下一步

1. 生产化：pgvector、Celery / ARQ、正式 Alembic 迁移、密钥管理
2. 审批流增强：部门 / 岗位 / 角色审批人、并行分支、附件上传与电子签、邮件 / IM 通知
3. AIGC 真实服务接入与分镜联动：即梦 / 可灵 / Runway / ComfyUI、批量出图、输出内容审核
4. 前端：细粒度权限、移动端适配、更多可视化
5. GraphRAG 增强：实体-分块关联、社区摘要、多跳查询规划
6. 团队模板：更多行业模板、自定义模板编辑器、员工绩效画像
