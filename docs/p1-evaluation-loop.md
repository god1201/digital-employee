# P1：失败归因、综合评估与上岗认证（已实现）

对应 `docs/requirements-agentic-workforce.md` 的 7.3 学习流水线、7.9 学习成效度量、
M9 试运行与考核，以及 P1 路线图。P0 的契约 / 接管增量 / 偏好记忆 / 学习工件见
`docs/p0-contract-learning.md`。

## 1. 失败归因分类器

表：`failure_attributions`（`FailureAttribution`）

| 类别 | 判定线索 | 路由动作 |
| --- | --- | --- |
| `knowledge_missing` | 知识步骤检索结果为空 | `create_knowledge_ticket` |
| `retrieval_miss` | 有结果但 Top1 相似度 < 0.35 | `retune_chunk` |
| `tool_misuse` | 工具步骤报错、参数/HTTP/超时 | `fix_tool_schema` |
| `planning_error` | 规划为空、步骤缺失、接管新增结构字段 | `add_sop_step` |
| `style_mismatch` | 接管 diff 只改写文本字段 | `update_persona` |
| `permission_violation` | 契约拦截、访问拒绝、越权 | `tighten_permission`（禁止学习） |
| `intent_misunderstanding` | 意图/歧义/需求不明确 | `collect_intent_samples` |
| `unknown` | 未命中规则 | `manual_review` |

自动采集：

- 任务首次失败时，`engine._fail_instance` 自动归因（不含重试造成的重复失败）。
- 人工“纠正后批准”生成接管增量时，自动按 diff 归因（文本改写 vs 结构缺失）。
- 也可手工调用 `POST /attributions/analyze` 预览或落库。

LLM 归因（可选）：

- `POST /attributions/analyze` 增加 `use_llm`，先让 LLM 从固定类别中选择并给出
  证据，失败或未配置时自动回退规则。
- `POST /attributions/{id}/reanalyze-llm` 对单条归因做 LLM 复核并更新
  `source=llm`；已生成学习工件或已解决的归因不允许直接复核。
- 日结批次在 `LLM_ATTRIBUTION_ENABLED=true` 时自动复核窗口内低置信度、尚未生成
  工件的规则归因（`LLM_ATTRIBUTION_MIN_CONFIDENCE` / `MAX_PER_RUN` 可调）。
- LLM 只能返回预定义类别，越权/合规类失败始终不进入 LLM 学习复核。

接口：

- `GET /api/v1/attributions`
- `POST /api/v1/attributions/analyze`（`persist=false` 只预览）
- `GET/PATCH /api/v1/attributions/{id}`
- `POST /api/v1/attributions/{id}/artifact`（越权类会被拒绝）

### 1.1 反思与自我修正

任务图新增 `reflect` 节点：`perceive → plan → execute → verify → reflect`。
规划失败、执行失败或校验未通过都会进入反思，而不是直接静默结束。

- 反思结果写入 `task_steps`（`step_type=reflection`，名称「反思与修正」）与
  `task_instances.output.reflection`，可在逐帧回放与任务详情中查看。
- 规则反思给出根因、修正提示、建议与 `retryable`：
  - 可重试：`planning_error`、`retrieval_miss`、`intent_misunderstanding`、`unknown`；
  - 不可重试：知识缺失、工具错误、风格不符、越权/合规、预算超限、取消、未配置
    LLM Key 等。
- 自动重试：
  - 仅对 `task_type=free` 的任务生效，固定任务禁止自动重试，避免重复不可逆工具动作；
  - 默认最多 1 次（`REFLECTION_MAX_RETRIES`），且受 `max_attempts` 约束；
  - 重试前清空旧计划、把反思提示写入 `input._reflection_hint`，下一次规划会带上
    「上次失败反思」，避免重复同一错误。
- 可选 LLM 反思：`REFLECTION_LLM_ENABLED=true` 时用 LLM 补充诊断与修正提示；
  LLM 只能收紧重试安全边界，不能把规则判定为不可重试的失败改成可重试。
- 同一任务实例只保留一条失败归因，反思/重试不会重复写归因。

配置：

```env
REFLECTION_ENABLED=true
REFLECTION_AUTO_RETRY=true
REFLECTION_LLM_ENABLED=false
REFLECTION_MAX_RETRIES=1
```

## 2. 综合评估套件

表：`evaluation_suites` / `evaluation_cases` / `evaluation_runs`

- 套件绑定员工，带 `threshold`、`regression_tolerance`、`enforce_on_activate`。
- 用例支持：
  - `assertion`：直接比对本次传入的 `outputs[case_id]`；
  - `llm`：用员工 system prompt + 契约 + 偏好记忆调用模型作答。
- 打分：关键词召回（权重 0.7）+ 文本相似度（0.3）；支持 `exact` 精确匹配。
- 通过条件：`score >= threshold` 且相对最近一次成功基线下降不超过
  `regression_tolerance`（默认 0.02）。

接口：

- `GET/POST /api/v1/evaluation-suites`
- `GET/PATCH/DELETE /api/v1/evaluation-suites/{id}`
- `GET/POST /api/v1/evaluation-suites/{id}/cases`
- `PATCH/DELETE /api/v1/evaluation-cases/{id}`
- `POST /api/v1/evaluation-suites/{id}/run`
- `GET /api/v1/evaluation-runs`、`GET /api/v1/evaluation-runs/{id}`

**生效门禁**：`POST /learning-artifacts/{id}/activate` 时，若员工存在启用且
`enforce_on_activate=true` 的套件，会先跑评估：

- 任一失败 → 学习工件保持 `approved`，返回 400，并落库评估记录与审计；
- 全部通过 → 工件转 `active`，`eval_result.activation` 记录分数与基线。

> 注意：`assertion` 用例需要显式传入输出；生效门禁没有输出来源，会把它们记为
> 0 分。若只想手工评估，请把套件的 `enforce_on_activate` 设为 false，或使用
> `llm` 用例做自动回归。

## 3. 影子试运行与上岗认证

表：`employee_trials`（`EmployeeTrial`）

- `POST /api/v1/digital-employees/{id}/trials`
  - `mode=shadow`：样本不足时状态 `running`，够样本后给出 passed/failed；
  - `mode=certification`：样本数 < `sample_size` 直接 `failed /
    insufficient_samples`；否则按一次通过率判定 `go_live` 或 `downgrade`。
- 指标：样本数、成功率、接管率、一次通过率、平均尝试次数、样本是否充足。
- 认证结果写入 `digital_employees.config.certification`。

接口：

- `POST/GET /api/v1/digital-employees/{id}/trials`
- `GET /api/v1/trials`（全局列表）
- `GET /api/v1/trials/{id}`
- `GET /api/v1/digital-employees/{id}/profile`（数字履历）

数字履历包含：任务状态分布、一次通过率、接管率、学习工件状态分布、
失败归因分布、最近试运行与认证状态。

## 4. 前端

- 「学习中心」新增三个页签：失败归因、评估套件、试运行。
  - 失败归因：查看信号、修复建议、一键转学习工件、标记已解决。
  - 评估套件：管理用例、执行评估、查看最近运行与明细。
  - 试运行：发起影子/认证、查看指标与样本明细。
- 数字员工列表新增「数字履历」抽屉。

## 5. 验证

- `ruff check app tests scripts` 通过。
- `pytest`：35 passed（新增归因规则与打分测试）。
- `npm run build` 通过。
- PostgreSQL 冒烟：
  - 接管文本 diff → `style_mismatch` → 转学习工件；
  - assertion 套件好/坏输出 → 1.0 / 0.0，基线 1.0，delta -1.0；
  - 开启强制评估后激活工件被 400 拦截，评估记录落库；停用套件后可激活；
  - 认证样本不足 → `insufficient_samples`；影子样本不足 → `running`；
  - 工具报错任务 → 自动归因 `tool_misuse` / `fix_tool_schema`。

## 6. 已知边界与下一步

1. 规则归因始终可用；LLM 归因是可选复核，默认关闭，失败自动回退规则。
2. `llm` 评估用例依赖 `LLM_API_KEY`；未配置时整批 LLM 用例会失败并阻止生效。
3. 试运行基于员工最近任务样本，不会自动生成新的影子任务；后续可接任务定义
   批量跑影子集。
4. 技能市场（Skill Marketplace、依赖/冲突/权限并集）与调教台版本树尚未实现。
5. 生产化（Alembic、Redis/Celery、pgvector）仍待 P0/P1 之后。
