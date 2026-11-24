# P0：岗位契约与学习闭环（已实现）

本文件记录本轮 P0 的落地范围、数据模型、接口与运行语义，对应
`docs/requirements-agentic-workforce.md` 中 M2 / M7 / 7.2 / 7.8。

## 1. 数据模型

| 表 | 模型 | 作用 |
| --- | --- | --- |
| `job_contracts` | `JobContract` | 岗位职责契约：can_do / cannot_do / must_ask / KPI / 汇报关系 / 自主权 L0–L3 / 权限红线 |
| `intervention_deltas` | `InterventionDelta` | 人工接管增量：原输出、人工终稿、结构化 diff，是最高价值的学习信号 |
| `preference_memories` | `PreferenceMemory` | 偏好记忆：称呼、格式、结论先行等，实时注入提示词 |
| `learning_artifacts` | `LearningArtifact` | 学习工件基础：归因、目标层、建议、证据、风险、审批状态、版本、回滚 |

作用域统一为 `personal / team / organization`，为后续防投毒与团队共享留出字段。
`job_contracts` 对 `(tenant_id, employee_id)` 唯一；每次 PUT 版本号 +1，并有审计日志。

## 2. 接口

### 岗位契约

- `GET  /api/v1/digital-employees/{id}/contract`
- `PUT  /api/v1/digital-employees/{id}/contract`（仅人工，版本 +1，写审计）
- `POST /api/v1/digital-employees/{id}/contract/check`（预检某次工具调用）

### 偏好记忆

- `GET    /api/v1/preferences`
- `POST   /api/v1/preferences`（按 employee + key upsert，实时生效）
- `PATCH  /api/v1/preferences/{id}`
- `DELETE /api/v1/preferences/{id}`（软遗忘）
- `GET    /api/v1/preferences/context/{employee_id}`（查看将要注入的上下文）

### 接管增量

- `GET   /api/v1/interventions`
- `POST  /api/v1/interventions`（单次示范教学）
- `GET   /api/v1/interventions/{id}`（含 diff 摘要）
- `PATCH /api/v1/interventions/{id}`
- `POST  /api/v1/interventions/{id}/artifact`（一键提炼为学习工件，进入审批队列）

### 学习工件

- `GET  /api/v1/learning-artifacts`
- `POST /api/v1/learning-artifacts`
- `GET  /api/v1/learning-artifacts/{id}`
- `POST /api/v1/learning-artifacts/{id}/approve|reject|activate|rollback|archive`

状态流转：`pending_approval → approved → active → rolled_back`，
驳回为 `rejected`，归档为 `archived`。所有状态变更写审计日志。

## 3. 任务引擎联动

1. **规划**：自由任务规划时把契约与偏好记忆写入规划提示词；
   要求 must_ask 事项插入 human 步骤，不得规划 cannot_do 事项。
2. **工具执行前强制门禁**（`execute_steps` → `evaluate_tool_call`）：
   - `deny`：触碰 cannot_do / 禁用工具 / 只读契约 / L0 写操作 → 任务失败并审计；
   - `ask`：命中 must_ask、金额/条数阈值、L1 写操作 → 步骤进入 `waiting`，
     任务转 `waiting_human`，等待人工批准；
   - `allow`：自动执行。
3. **人工放行后的恢复**：批准契约门禁时，把 `plan[step].approved_gate=true`，
   门禁步骤置为 `cancelled`，`next_step_index` 指回同一步骤重新执行，
   避免“批准后被跳过”或“反复拦截”。
4. **LLM 步骤**：系统提示词追加契约上下文与偏好记忆，统一人格与边界。

### 权限红线字段（`red_lines`）

```json
{
  "read_only": false,
  "forbidden_tools": ["drop_database"],
  "allowed_tools": [],
  "amount_threshold": 500000,
  "amount_field": "amount",
  "count_threshold": 100,
  "count_field": "count",
  "sandbox_required": true
}
```

`allowed_tools` 非空时视为白名单；金额/条数会在 `arguments` 中递归查找对应字段。
按工具覆盖自主权：`autonomy_overrides = {"tool:send_email": "L1"}`。

> 存量员工未配置契约时按平台默认放行（`rule=no_contract`），以便平滑迁移；
> 新建员工建议先配置契约再上岗。

## 4. 接管增量采集路径

- **主路径**：任务 `waiting_human` 时，前端“纠正后批准”提交
  `final_output`；后端把等待步骤之前最近一次成功草稿与终稿做 diff 并入库。
- **手工路径**：`POST /interventions` 记录单次示范教学。
- **闭环**：`POST /interventions/{id}/artifact` 生成 `pending_approval` 学习工件，
  进入审批队列；审批 → 生效 → 可回滚。

diff 为结构化路径列表（`add/remove/change`），由纯函数 `compute_diff` 生成，已单测覆盖。

## 5. 前端入口

- 数字员工列表 →「岗位契约」抽屉：契约、自主权、红线、KPI 编辑。
- 运营 →「学习中心」：偏好记忆 / 接管增量 / 学习工件三个页签，
  支持新增偏好、查看 diff、一键提炼工件、通过/驳回/生效/回滚。
- 任务详情 → `waiting_human` 状态新增「纠正后批准」。

## 6. 验证

- `ruff check app tests` 通过。
- `pytest`：27 passed（新增 `tests/test_learning.py`，覆盖 diff 与契约判定）。
- `npm run build` 通过。
- 真实 PostgreSQL 冒烟：契约 CRUD、contract/check、偏好写入与上下文、
  接管增量、工件审批/生效/回滚、L1 门禁与放行后重跑均通过。

## 7. 下一轮建议

1. 失败归因分类器（知识缺失 / 检索未召回 / 工具用错 / 规划错误 / 风格 / 越权）。
2. 综合评估套件与影子试运行 / 上岗认证。
3. 学习工件的评估回归与金丝雀发布（`eval_result` / `rollout` 字段已预留）。
4. 契约变更时自动重跑受影响员工评估集。
5. 生产化：Alembic 基线、pgvector、Redis/Celery。
