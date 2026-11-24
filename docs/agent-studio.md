# Agent Studio 与分层记忆（需求文档补全第一批）

对应 `docs/requirements-agentic-workforce.md` 的 M1 人格层、M3 分层记忆、
7.2 业务结果回执、7.7 入职引导、M8 协作路由，以及提示词预算反模式防御。

## 1. 人格表现层（M1）

表：`persona_profiles`（每员工一条）

字段：语气、称呼习惯、输出格式、汇报风格、禁忌词、落款、是否启用 LLM 统一润色、
额外要求、版本。每次保存版本 +1，仅管理员可改。

接口：

- `GET /api/v1/digital-employees/{id}/persona`
- `PUT /api/v1/digital-employees/{id}/persona`（管理员）
- `GET /api/v1/digital-employees/{id}/persona/context`

生效方式：

- 人格上下文注入规划、LLM 步骤、综合评估、工件生效评估、技能升级评估；
- `polish_enabled=true` 时，LLM 步骤输出后经一次“只改表达、不改事实”的润色；
- 禁忌词检查结果写入步骤输出 `persona_warnings`，不直接篡改事实。

## 2. 分层记忆（M3 / 7.4）

| 层 | 当前实现 |
| --- | --- |
| 工作记忆 | 任务上下文与步骤结果 |
| 情景记忆 | 任务实例、接管增量；可压缩为工件 |
| 语义记忆 | `target_layer=semantic_memory` 学习工件 |
| 程序记忆 | `target_layer=procedural_memory` 学习工件 |
| 偏好记忆 | `preference_memories` |

### 冲突消解

语义事实生效时，如果 `proposal.key/subject/topic/name/fact` 相同，旧事实会转为
`superseded`，并在 `rollout` 中记录 `superseded_by` 与时间；历史保留、可追溯。
注入提示词时只取 `active/canary`，不会同时读到新旧两个版本。

### 遗忘与压缩

- 偏好与学习工件支持 `expires_at`；`scripts/maintenance.py` 会把过期项归档；
- `POST /api/v1/digital-employees/{id}/memories/compress` 把 N 天前的情景记忆
  压缩为一条程序记忆候选，进入审批队列。

### 接口

- `GET /api/v1/digital-employees/{id}/memories?layer=`
- `POST /api/v1/digital-employees/{id}/memories/compress`（管理员）
- 学习工件 `superseded` 状态加入版本谱系与状态流转。

## 3. 业务结果回执（7.2 Outcome Telemetry）

表：`outcome_events`

- 支持 `payment_received / email_replied / ticket_closed / reimbursement_rejected / custom`；
- 关联员工、任务实例、学习工件；记录成功/失败、金额、业务载荷与发生时间；
- `GET/POST /api/v1/outcome-events`、`GET /api/v1/outcome-events/stats`；
- 员工数字履历与周复盘会统计各类型成功率。

## 4. 入职引导与示范库（7.7）

- `POST /api/v1/digital-employees/{id}/onboarding/import`
  - 输入 JD / SOP / 制度文本；
  - 有 LLM 时抽取角色、can_do、cannot_do、must_ask、KPI；
  - 无 LLM 时用确定性启发式抽取；
  - 可生成岗位契约 **草稿**（不直接生效）；
  - 可同时把原文导入知识库并分块/向量化。
- 示范案例表：`few_shot_examples`
  - `GET/POST /api/v1/digital-employees/{id}/few-shot-examples`
  - `POST /api/v1/digital-employees/{id}/onboarding/examples` 批量导入；
  - 启用案例自动进入规划与 LLM 步骤的 Few-shot 上下文。
- `GET /api/v1/digital-employees/{id}/onboarding/status` 查看契约、案例与认证状态。

## 5. 提示词预算（反模式防御）

员工 `config.prompt_token_budget` 控制装配后的上下文预算：

- 按“契约 > 人格 > 偏好 > 技能 > 经验 > 示范 > 协作”优先级装配；
- 超出预算时截断最后一段并标注“已按提示词预算压缩”；
- `0` 表示不限制；
- 统一由 `app/domains/workforce/prompting.py` 装配，避免各入口提示词不一致。

## 6. 协作路由（M8）

- `GET /api/v1/digital-employees/{id}/routing?topic=`
- 根据团队成员、角色、岗位与已装配技能打分，返回“该问谁”；
- 同时注入规划与 LLM 步骤上下文，减少“不知道找谁问”。

## 7. 数字履历增强

`GET /api/v1/digital-employees/{id}/profile` 新增：

- `recurrence`：同类归因重复次数；
- `outcome_counts`：业务回执成功/总数；
- `few_shot_count`、`prompt_budget`；
- 分层记忆总览由 `/memories` 提供。

## 8. 验证

- `pytest`：73 passed（新增人格上下文/禁忌词、预算截断、路由打分、
  入职启发式抽取、记忆 key、触发器、幻觉支撑度、岗位模板种子、
  多模态识别/表格解析、隐式信号 schema 测试）。
- PostgreSQL 冒烟：
  - 人格保存与上下文生成；
  - JD 导入生成契约草稿；
  - 批量示范案例；
  - 同一语义 key 新旧事实 → 旧事实 `superseded`，提示词只注入新值；
  - 情景压缩生成待审批工件；
  - 业务回执写入并出现在履历统计；
  - 固定任务在新的统一提示词装配下正常执行；
  - 岗位模板应用：技能装配、人设写入、契约草稿、评估套件提示；
  - 触发器手动触发与到期调度均能创建任务；
  - 幻觉检测：有来源支撑 1.0，编造内容 0.0。
- Alembic：`7273f304149c`（head），`alembic check` 无漂移。

## 9. 任务触发器与主动汇报（M6）

表：`task_triggers`

- `interval`：每 N 秒执行；
- `daily`：每日固定 UTC 时间（HH:MM）；
- `event`：外部事件触发，`POST /task-triggers/events/{event_name}`。

接口：

- `GET/POST /api/v1/task-triggers`
- `PATCH/DELETE /api/v1/task-triggers/{id}`
- `POST /api/v1/task-triggers/{id}/fire`（立即执行一次）
- `POST /api/v1/task-triggers/events/{event_name}`（事件驱动）

调度：

- 内联模式下随 API 启动 `run_trigger_scheduler`；
- `scripts/worker.py` 也会启动触发器调度；
- 到期触发器创建 `task_instance`，由 DB Worker 或 Celery 执行；
- 主动汇报 = 每日触发器 + 报表任务定义。

前端：任务中心新增「触发器」页签，可创建、启停、立即触发。

## 10. 岗位模板五件套（第 4 章）

表：`job_templates`（平台内置 9 个岗位）

每个模板包含：技能包、工具组、知识库声明、人设、岗位契约、评估套件编码。
接口：

- `GET /api/v1/job-templates`、`GET /{code}`
- `POST /api/v1/digital-employees/{id}/apply-job-template`

应用效果：

- 按模板装配技能（自动解析依赖、报告冲突）；
- 写入人格风格；
- 生成岗位契约 **草稿**（不直接生效）；
- 自动绑定知识库：`bind_knowledge_bases=true`（默认）时校验模板声明的 KB ID
  是否存在且启用，写入 `digital_employees.config.knowledge_base_ids`；
  不存在的 ID 会在结果 `knowledge_bases.missing` 与 notes 中列出；
- 评估套件若未就绪会给出提示，需人工绑定。

知识库绑定后的行为：

- 员工绑定了 KB 时，自由任务规划只看到这些 KB；
- 知识检索 / GraphRAG 步骤若引用未绑定 KB，会直接失败，避免越权检索；
- 空列表表示不限制（可看到租户内全部启用 KB）。
- 管理接口：
  - `GET /api/v1/digital-employees/{id}/knowledge-bases`
  - `PUT /api/v1/digital-employees/{id}/knowledge-bases` `{knowledge_base_ids: []}`

前端：「组织与团队 → 岗位模板」，可搜索并一键应用到员工。

## 11. 幻觉检测

表：`hallucination_checks`

- `POST /api/v1/hallucination/check`：答案 + 来源列表；
- `GET /api/v1/hallucination/checks`：历史记录；
- 逐句计算与来源的 token 重合度：
  - 单句支撑度 ≥ 0.35 视为支撑；
  - 整体支撑句占比 ≥ 0.6 视为 grounded；
  - 返回每句的 `support` 与 `grounded`，便于定位未支撑表述。

当前为确定性规则实现，不调用 LLM；适合作为任务后置审核和人工复核辅助。

前端：「知识与风控 → 幻觉检测」。

## 12. 多模态解析

表：`multimodal_extractions`

- `POST /api/v1/multimodal/extract`（multipart）
  - 本地解析：`.txt/.md/.csv/.tsv/.json`；
  - 图片/音频/PDF：需要 `MULTIMODAL_PROVIDER_URL`，转发 multipart 给外部 OCR/ASR/PDF 服务；
  - 可传 `knowledge_base_id` 直接把解析文本写入知识库并分块/向量化。
- `GET /api/v1/multimodal/extractions`
- 上限 `MULTIMODAL_MAX_BYTES`（默认 20MB）。
- 前端：「知识与风控 → 多模态解析」。

## 13. 隐式学习信号

表：`implicit_signals`

- 类型：`repeat_question / rephrase / abandon / copy_segment / custom`；
- `GET/POST /api/v1/implicit-signals`、`GET /stats`；
- 任务取消时自动记录 `abandon`；
- 信号进入员工数字履历与周复盘统计；
- 前端：学习中心「隐式信号」页签。

## 14. 需求文档剩余项

尚未实现：

1. 日结批量归因 / 周报定时生成与投递（触发器已具备，尚未编排）；
2. 主动学习的自动触发条件（低置信度、must_ask、同类失败率高）；
3. 提示词 Token 真实计量（当前为字符估算）；
4. LLM 归因与 LLM 技能推荐（规则版已可用）；
5. 数字履历的能力雷达图与学习曲线。
