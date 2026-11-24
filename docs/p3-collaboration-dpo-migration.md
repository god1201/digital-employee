# P3：多员工协作、DPO 数据资产、跨员工能力迁移（已实现）

对应 `docs/requirements-agentic-workforce.md` 的 P3 路线图。
P0–P2 与生产化见 `docs/p0-contract-learning.md`、`docs/p1-evaluation-loop.md`、
`docs/p1-skill-marketplace.md`、`docs/p2-learning-loop.md`、`docs/production.md`。

## 1. 多员工协作

### 执行模型

- 任务步骤新增 `type=employee`：把子任务委派给另一个数字员工。
- 引擎为每个委派创建一个子 `task_instance`（`status=running`，绕过队列领取），
  递归执行 LangGraph，父步骤记录 `child_instance_id` / 员工 / 子任务输出。
- 协作层级通过 `input.collaboration_depth` 限制，最多 3 层。
- 子任务默认 `task_type=free`，由目标员工自由规划（需要 `LLM_API_KEY`）；
  也可在参与者中传 `steps` 固定子任务步骤，用于无 LLM 的确定性流程。
- 父任务支持两种模式：
  - `sequential`（默认）：按参与者顺序串行执行，后者可读取前者结果；
  - `parallel`：一个 `type=parallel` 步骤并发执行所有子任务，再统一汇总结果。
- 并行子任务通过 `asyncio.gather` 同时运行，每个子任务独立事件循环上下文与数据库会话；
  任一失败则父步骤失败，并保留各子任务输出用于排查。
- 可选最后一步由负责人 LLM 汇总。

### 会话与接口

表：`collaboration_runs`（`CollaborationRun`），含 `mode` 字段。

- `POST /api/v1/collaborations`
  ```json
  {
    "owner_employee_id": 1,
    "goal": "核对两家客户回款",
    "mode": "parallel",
    "participants": [
      {"employee_id": 2, "instruction": "查 A 客户", "steps": [
        {"name": "查询", "type": "tool", "tool_code": "crm_query", "arguments": {"customer": "A"}}
      ]},
      {"employee_code": "billing_bot", "instruction": "查 B 客户"}
    ],
    "summarize": false
  }
  ```
- `GET /api/v1/collaborations`、`GET /api/v1/collaborations/{id}`
  （读取时同步父任务状态与结果）。
- 父任务沿用任务中心：详情、回放、人工确认、审计。

### 前端

- 任务中心新增「多员工协作」页签与「发起协作」按钮。
- 参与者用 JSON 数组填写，支持固定 `steps`。

## 2. DPO / RLHF 数据资产

平台负责**数据资产与训练台账**，不在平台内执行训练；训练由外部 trainer 完成后回调。

### 偏好对

表：`preference_pairs`（`PreferencePair`），`(tenant_id, source_ref)` 唯一。

来源：

- `intervention`：人工接管增量，`chosen=final_output`、`rejected=original_output`；
- `evaluation`：评估用例实际输出 vs 期望文本/关键词；
- `feedback`：人工修正输出 vs 原任务输出。

接口：

- `GET /api/v1/preference-pairs`
- `POST /api/v1/preference-pairs/collect`（支持 source 过滤与上限）
- `POST /api/v1/preference-pairs/export`（导出 `data/training/dpo_*.jsonl`，标记已导出）
- `PATCH /api/v1/preference-pairs/{id}/archive`

JSONL 每行：`{"prompt", "chosen", "rejected", "metadata"}`。

### 训练任务

表：`training_jobs`（`TrainingJob`）

- `POST /api/v1/training-jobs`：登记 `method=dpo|sft`、数据集路径（必须位于
  `data/training` 下）与配置；统计数据集行数。
- `POST /api/v1/training-jobs/{id}/dispatch`：读取数据集并派发到配置的外部 trainer：
  - 目标地址 `TRAINING_PROVIDER_URL`，可选 `TRAINING_PROVIDER_API_KEY`（Bearer）；
  - 请求体包含 `job_id/method/config/dataset_size/dataset`（逐行 JSON）；
  - 成功返回外部 `job_id` 时状态置为 `dispatched`，记录在 `metrics.dispatch`；
  - 不可达或 4xx/5xx 会记录错误并返回 400。
- `POST /api/v1/training-jobs/{id}/status`：外部 trainer 回调
  `dispatched/running → running → succeeded/failed/cancelled`，记录指标与错误。
  - 派发时为任务生成一次性回调令牌，原始令牌放入派发请求体 `callback_token`，
    数据库只存 SHA-256 哈希（`config.callback_token_hash`）；
  - 回调可使用 `X-Training-Token: <callback_token>`，也可使用租户内用户 JWT；
  - 令牌只对单个训练任务有效，避免跨租户/跨任务伪造。
- `GET /api/v1/training-jobs`、`GET /api/v1/training-jobs/{id}`。

状态机：`pending → dispatched → running → succeeded/failed/cancelled`；
也支持 `pending → running`（手工执行）与任意非终态 `→ cancelled`。

### 前端

- 新增「训练数据」页：偏好对、训练任务两个页签；
  支持采集、导出 JSONL、登记任务、状态回调。

## 3. 跨员工能力迁移

表：`capability_migrations`（`CapabilityMigration`）

`POST /api/v1/capability-migrations`：

```json
{
  "source_employee_id": 1,
  "target_employee_id": 2,
  "components": ["skills", "artifacts", "preferences", "contract"],
  "dry_run": false
}
```

迁移语义：

| 组件 | 处理 |
| --- | --- |
| `skills` | 逐个复制已启用技能及依赖；目标已装同版本跳过；不同版本记为冲突；权限并集告警写入报告 |
| `artifacts` | 复制 `active/approved` 且非越权类的学习工件，目标侧为 `pending_approval` 副本；按 proposal 哈希去重 |
| `preferences` | 复制启用偏好，目标已有同名 key 则跳过 |
| `contract` | 仅当目标无契约时复制为 `draft`，不直接生效 |

- `dry_run=true` 只返回计划与冲突，不写业务数据（仍记录迁移报告）。
- 报告包含 planned / installed / created / skipped / conflicts / warnings。
- `GET /api/v1/capability-migrations`、`GET /{id}`。

前端：数字员工「能力迁移」抽屉，选择源员工、组件，先预览再执行。

## 4. Alembic

新增迁移 `0002`（`f436d9df5275`）创建：

- `collaboration_runs`
- `preference_pairs`
- `training_jobs`
- `capability_migrations`

并同步 `knowledge_chunks` 注释与 `learning_artifacts.status` 注释。
后续 `0003`（`82ae780f2bdb`）同步 `training_jobs.status` 的 `dispatched` 注释；
`0004`（`ad29d72d4a31`）为 `collaboration_runs` 增加 `mode` 字段。
已执行 `alembic upgrade head`，当前 head 为 `ad29d72d4a31`。

## 5. 验证

- `ruff check app tests scripts` 通过。
- `pytest`：56 passed（新增偏好哈希、评估期望文本、训练状态机、派发载荷、
  回调令牌与协作模式测试）。
- `npm run build` 通过。
- PostgreSQL 冒烟：
  - 协作会话创建，父任务计划包含两个 `employee` 步骤；
  - 受控执行父任务：两个子任务均 `succeeded`，父任务 `succeeded`；
  - 并行模式：一个 `parallel` 步骤并发创建两个子任务，父任务 `succeeded`；
  - 接管增量采集为偏好对并导出 JSONL，训练任务 pending→running→succeeded；
  - 能力迁移预览不写入；执行后目标获得技能、偏好、契约草稿与待审批工件；
  - 外部 trainer 派发：本地 mock HTTP 服务收到数据集，任务转为 `dispatched`，
    `metrics.dispatch.external_job_id` 正确；
  - 回调令牌：`X-Training-Token` 正确时 200，错误时 401；JWT 回调仍可用；
  - Celery 无 Redis 时用 eager 模式验证：`enqueue_task` 成功执行并落库，
    任务 `succeeded`。
- 前端 E2E 冒烟（Playwright/Edge）：
  - 数字员工「岗位契约 / 技能装配 / 能力迁移 / 数字履历」抽屉均可打开；
  - 任务中心「多员工协作」页签；
  - 学习中心 10 个页签、训练数据 2 个页签、技能市场与详情抽屉；
  - 无 page error / console error。
- 敏感操作（契约保存、工件审批/发布/共享、技能包发布、训练派发、能力迁移）
  已加管理员校验。

## 6. 边界

1. 协作是顺序委派，不是并发多 Agent 谈判；子任务自由规划依赖 LLM。
2. DPO/RLHF 目前是数据资产、派发与台账，不包含训练执行；需外部 trainer 回调。
   派发请求会把数据集逐行 JSON 发送到配置的 HTTP 服务，不支持大文件分片或对象存储 URL。
3. 能力迁移不会自动审批工件或激活契约；技能冲突需要人工处理。
4. 迁移只在同租户内进行；跨租户复制不在范围内。
