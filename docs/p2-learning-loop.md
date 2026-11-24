# P2：金丝雀发布、经验共享、主动学习、周复盘、专家轨迹与回放（已实现）

对应 `docs/requirements-agentic-workforce.md` 的 P2 路线图与 M10 调教台。
P0/P1 见 `docs/p0-contract-learning.md`、`docs/p1-evaluation-loop.md`、
`docs/p1-skill-marketplace.md`。

## 1. 影子 / 金丝雀 / 全量发布

学习工件状态新增 `shadow`、`canary`，`rollout` 记录发布策略。

- `POST /learning-artifacts/{id}/rollout` `{mode: shadow|canary|full, traffic, note}`
- `POST /learning-artifacts/{id}/promote`：`approved → shadow → canary(10%) → active(100%)`
- `GET /learning-artifacts/{id}/rollout`：发布状态 + 观测指标（样本、成功率、接管率、一次通过率）
- 可见性：
  - `shadow` 不注入真实输出，只做观测；
  - `canary` 按 `sha256(trace_id + artifact_id) % 100 < traffic*100` 命中；
  - `active` 全量注入。
- 生效内容：`proposal.content/rule/name` 会进入任务规划、LLM 步骤、综合评估与
  工件生效评估的 system prompt；可用
  `GET /digital-employees/{id}/artifacts/context` 查看。

## 2. 团队级 / 组织级经验共享

- `POST /learning-artifacts/{id}/share` `{scope: team|organization, note}`
  生成一条 `pending_approval` 副本，保留原工件溯源。
- 审批 + 生效后：
  - `organization` 作用域对所有员工可见；
  - `team` 作用域对同团队成员可见（通过 `team_members` 解析）。
- 共享仍走审批，避免“一个客户的特例污染全局”。

## 3. 主动学习预算

- 表：`learning_questions`
- 每日预算取 `digital_employees.config.active_learning_budget`，默认 3。
- `POST /learning-questions`：问题 + 选项 + 默认建议；预算耗尽返回 400。
- `POST /learning-questions/{id}/answer`：回答后自动生成
  `semantic_memory` 学习工件（待审批），并写入提问记录。
- `POST /learning-questions/{id}/dismiss`、`GET /digital-employees/{id}/learning-budget`。

### 3.1 自动触发

`POST /learning/jobs/daily-batch` 会补归因最近窗口内未归因的失败任务，并按优先级
自动发起结构化提问（仍受每日预算约束、7 天内相同问题去重）：

1. **must_ask**：任务因 `contract.must_ask` 停在人工确认，询问后续默认处理方式；
2. **低置信度**：归因置信度低于 `LEARNING_AUTO_QUESTION_CONFIDENCE`；
3. **同类复发**：窗口内同一归因类别出现次数达到
   `LEARNING_AUTO_QUESTION_RECURRENCE`。

越权/合规类失败不会进入自动提问。自动提问带 `（自动触发）` 前缀，回答后仍走
学习工件审批队列。

## 4. 成长周报

- 表：`weekly_reviews`
- `POST /weekly-reviews/generate` `{employee_id?, week_start?}`
- `POST /weekly-reviews/generate-batch` `{week_start?, force?, deliver?}`：
  为上一自然周有任务的员工批量生成；同周期已存在则跳过，`force` 可覆盖。
- `POST /weekly-reviews/{id}/deliver`：把周报 JSON 推送到
  `WEEKLY_REVIEW_DELIVERY_URL` 配置的 webhook，状态落为
  `delivered` / `delivery_failed`，投递结果写入 `learned.delivery`。
- 指标：任务量、成功率、一次通过率、接管率、归因分布、工件、提问、试运行。
- Top 错误 + 对应修复建议 + 摘要；不选员工时生成租户周报。
- `GET /weekly-reviews`、`GET /weekly-reviews/{id}`。

### 4.1 定时学习节奏

API 进程内启动 `run_learning_scheduler`，按 UTC 执行：

- 每日 `LEARNING_DAILY_AT`（默认 `02:00`）执行日结批量归因 + 自动提问；
- 每周 `LEARNING_WEEKLY_WEEKDAY`（默认周一）`LEARNING_WEEKLY_AT`（默认 `09:00`）
  生成上一自然周周报，并在配置 webhook 时自动投递；
- 进程晚启动会补跑当天/本周尚未执行的批次；失败任务归因与周报均幂等，
  多实例重复执行不会产生重复数据；
- `GET /learning/scheduler/status` 查看配置与最近执行记录；
- `LEARNING_SCHEDULER_ENABLED=false` 可关闭定时器，仅保留手动接口。

## 5. 专家轨迹蒸馏

- `GET /expert-trajectories/candidates`：成功任务按尝试次数、接管情况排序，
  标注 `high/medium` 质量。
- `POST /expert-trajectories/distill` `{instance_id, name?, scope}`：
  把成功步骤序列蒸馏为 `procedural_memory` 学习工件（待审批），
  包含每步名称、类型、工具、输入与输出摘要。

## 6. 轨迹逐帧回放

- `GET /tasks/instances/{id}/replay`：任务摘要、帧序列（步骤输入/输出/耗时/错误）、
  关联接管增量与失败归因。
- 前端任务中心新增「回放」：上一帧/播放/下一帧、帧选择、当前帧详情。

## 7. 前端

- 「学习中心」新增页签：主动提问、周复盘、专家轨迹；调教台时间线继续汇总四类事件。
- 主动提问页签新增「执行日结」；周复盘页签新增「批量周报」；周报抽屉支持手动投递。
- 数字履历抽屉新增能力雷达图与近 30 天学习曲线（成功率/接管率 + 任务量）。
- 工件抽屉新增：影子/金丝雀/全量发布、分阶段推进、共享到团队/组织、发布观测。
- 任务中心新增轨迹回放抽屉。

## 8. 验证

- `ruff check app tests` 通过。
- `pytest`：100 passed（含 `DE_INTEGRATION_TESTS=1`；调度时间窗、自动提问候选、
  雷达/趋势、tokenizer、LLM 归因/推荐、反思与重试边界、知识库绑定、
  训练回调指标合并、工作台/对话/契约 ask-confirm-deny）。
- `DE_INTEGRATION_TESTS=1 pytest tests/test_db_integration.py`：3 passed
  （数字履历雷达/趋势、批量周报、岗位模板知识库自动绑定、
  对话契约 ask/confirm/deny，均在事务内回滚）。
- `npm run build` 通过。
- PostgreSQL 冒烟：
  - 工件影子不注入、金丝雀 10%、全量生效；
  - 组织共享副本审批/生效后被另一员工读取；
  - 每日提问预算 2 次，第 3 次 400；回答生成 semantic_memory 工件；
  - 周报生成并汇总学习数据；
  - 成功任务可蒸馏为工件，回放返回帧与关联事件。

## 9. 边界

1. 金丝雀只控制“是否注入工件内容”，任务路由本身不受影响。
2. 周报按任务 `created_at` 统计；一次通过率用“成功数 - 接管数”近似。
3. 主动提问的答案以学习工件进入审批，不直接写 RAG 知识库。
4. 团队共享依赖 `team_members` 关系；未入团队的员工只看个人与组织经验。
5. 回放展示已落库的步骤轨迹，不捕获进程内瞬时状态。
6. 定时器按 UTC 解释且运行在 API 进程内；多实例依赖幂等查询去重。
7. webhook 投递是通用通道，邮件/IM 适配器可在此之上扩展。
