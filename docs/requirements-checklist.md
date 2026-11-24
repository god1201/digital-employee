# 需求文档逐条对照（requirements-agentic-workforce）

图例：✅ 已实现　🟡 部分实现 / 有明确边界　⛔ 未实现

## 0. 术语与总体架构

| 条目 | 状态 | 落地位置 |
| --- | --- | --- |
| 四层解耦（人格/技能/记忆/契约） | ✅ | persona / skills / learning / contracts |
| 铁律 1：技能只输出结构化结果，人格层统一润色 | ✅ | `workforce/persona`、`workforce/prompting.py` |
| 铁律 2：契约层禁止自主学习修改 | ✅ | 契约仅管理员接口；学习工件不能改契约 |
| 分层记忆 + RAG | ✅ | `learning/memory.py`、`knowledge/*` |

## 1. Agent 能力栈

| 条目 | 状态 | 说明 |
| --- | --- | --- |
| RAG + Rerank | ✅ | 向量/关键词/GraphRAG；Rerank 用混合打分 |
| 多模态 OCR/ASR/表格 | ✅ | 本地文本/CSV/JSON；图片/音频/PDF 走 HTTP Provider |
| 长上下文 + 记忆压缩 | ✅ | 情景压缩工件 + 提示词预算 |
| 任务规划（ReAct/Plan） | ✅ | LangGraph perceive→plan→execute→verify |
| 工具调用 / MCP | ✅ | 工具执行器 + 准入 + MCP |
| 反思与自我修正 | ✅ | 独立 `reflect` 节点；规则/可选 LLM 反思、自由任务有限自动重试、提示注入下次规划 |
| 多 Agent / 多员工协作 | ✅ | `employee`/`parallel` 步骤、协作会话 |
| 在线反馈 / 专家轨迹 / DPO | ✅ | 反馈、轨迹蒸馏、偏好对/导出/派发；真实小模型 DPO/SFT trainer 已验证 |
| 主动学习 | ✅ | 预算、结构化提问、回答入库 |
| 持续评估回归 | ✅ | 综合评估套件 + 工件/技能生效门禁 |
| 人格 / 主动汇报 / HITL | ✅ | 人设、每日触发器、任务恢复 |
| 治理与安全 | ✅ | 最小权限、审计、风控、沙箱、幻觉检测 |

## 2. 岗位模板库（第 4 章）

| 条目 | 状态 | 说明 |
| --- | --- | --- |
| 8–10 个岗位模板 | ✅ | 内置 9 个（客服/销售/行政/财务/HR/数据/市场/法务/项目经理） |
| 五件套 | ✅ | 技能、工具、知识库声明、人设、契约、评估套件编码 |
| 一键装配 | ✅ | `apply-job-template`；技能/人设/契约草稿 |
| 知识库自动绑定 | ✅ | 应用模板时校验并写入 `employee.config.knowledge_base_ids`；规划/执行只允许绑定范围内的知识库 |

## 3. Agent Studio 十大配置域

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| M1 身份与人格 | ✅ | 风格卡、称呼、格式、禁忌词、统一润色 |
| M2 岗位契约 | ✅ | can_do/cannot_do/must_ask/KPI/自主权/红线 |
| M3 记忆与经验 | ✅ | 五层记忆、冲突 supersede、压缩、过期遗忘 |
| M4 自主学习 | ✅ | 接管/归因/工件/评估/审批/回滚 |
| M5 技能装配 | ✅ | 市场、依赖、冲突、权限并集、升级回归 |
| M6 工作流与触发器 | ✅ | 间隔/每日/事件；主动汇报 |
| M7 工具与权限红线 | ✅ | 工具白名单、只读、阈值、沙箱 |
| M8 协作与社交图谱 | ✅ | 团队协作、并行委派、“该问谁”路由 |
| M9 试运行与考核 | ✅ | 评估套件、影子/认证、数字履历 |
| M10 调教台与可观测 | ✅ | 时间线、版本谱系、Diff、回滚、逐帧回放 |

M9 的雷达图/学习曲线已补齐：`GET /digital-employees/{id}/profile` 返回
`capability_radar`，`GET .../profile/trend` 返回按天聚合的学习曲线。

## 4. 技能市场（第六章）

| 条目 | 状态 | 说明 |
| --- | --- | --- |
| 技能五件套封装 | ✅ | 算法/工具/知识库/提示词/评估用例字段 |
| 依赖解析/冲突/权限并集 | ✅ | 安装、升级、复制、告警 |
| 版本与升级回归 | ✅ | 升级前后跑评估，退化自动回滚 |
| 跨模板取件/组合 | ✅ | 技能可自由装配，常见组合推荐 |
| AI 组合推荐 | ✅ | 规则打分 + 可选 LLM 推荐；只接受候选目录编码，失败回退规则 |

## 5. 持续学习（第七章）

| 条目 | 状态 | 说明 |
| --- | --- | --- |
| 7.1 学习目标分层 | ✅ | 事实/做法/偏好/参数/能力缺口 |
| 7.2 六路信号 | ✅ | 接管、显式反馈、结果回执、专家轨迹、主动提问、隐式信号 |
| 7.3 采集→归因→提炼→验证→灰度→固化 | ✅ | 规则归因、工件、评估、影子/金丝雀、回滚 |
| 归因为 LLM | ✅ | 规则归因 + 可选 LLM 复核；日结可自动复核低置信度规则归因，失败回退规则 |
| 7.4 五层记忆 | ✅ | 工作/情景/语义/程序/偏好 |
| 冲突消解 / 遗忘 / 压缩 | ✅ | superseded、expires_at、情景压缩 |
| 学习作用域隔离 | ✅ | personal/team/organization + 审批 |
| 7.5 实时/日结/周复盘 | ✅ | 实时偏好；日结批量归因；周报定时生成与 webhook 投递 |
| 7.6 主动学习 | ✅ | 预算、选项化、回答入库；must_ask/低置信度/同类复发自动触发 |
| 7.7 入职引导 | ✅ | JD/SOP 抽取、契约草稿、案例、导师 HITL、认证 |
| 7.8 学习工件结构 | ✅ | 溯源、证据、评估、风险、版本、回滚 |
| 7.9 成效度量 | ✅ | 接管率、一次通过、复发、知识覆盖；提示词按 tiktoken 真实计量，缺失时回退估算 |

## 6. 管理员入口与治理

| 条目 | 状态 |
| --- | --- |
| 单次示范教学 | ✅ |
| 学习工件审批队列 | ✅ |
| 员工数字履历 | ✅（含能力雷达图与学习曲线） |
| 权限最小化/审计/风控/沙箱 | ✅ |
| 幻觉检测 | ✅ |
| 行为可溯源到学习工件 | ✅ |

## 7. 路线图与生产化

| 阶段 | 状态 |
| --- | --- |
| P0 契约/接管/偏好/工件 | ✅ |
| P1 归因/评估/试运行/技能市场/调教台 | ✅ |
| P2 影子/金丝雀/周报/主动学习/共享/专家轨迹/回放 | ✅ |
| P3 DPO 数据/多员工/能力迁移 | ✅（小模型真实 DPO/SFT；大规模训练需外部算力） |
| 生产化 Alembic/队列/索引/可观测/安全 | ✅（真实 Redis/Celery、pgvector 0.8.1 已联调） |

## 8. 环境联调状态

代码级需求已全部落地，环境联调也已完成：

- 真实 Redis 7.2.4 + Celery Worker
- pgvector 0.8.1（`de-pg` 内源码编译，`VECTOR_BACKEND=pgvector`）
- 真实小模型 DPO/SFT trainer（`scripts/trainer_dpo.py`）走通
  偏好对 → 导出 → 派发 → 真实梯度训练 → `running/succeeded` 回调
- 参考 trainer（`scripts/trainer_reference.py`）保留用于快速契约测试

唯一保留的边界是 **大规模 DPO/SFT 仍需外部 GPU 算力**；平台负责数据集、
派发、回调令牌、训练台账与模型产物，当前已验证 102M 参数中文小模型的
真实 DPO 训练（CPU，2 步）。

关键接口 PostgreSQL 集成测试与 Playwright UI 回归已补：
`DE_INTEGRATION_TESTS=1 pytest tests/test_db_integration.py`、
`scripts/p3_ui_smoke.py`、`scripts/llm_features_smoke.py`、
`scripts/trainer_smoke.py`。

## 9. 快捷索引

- `docs/p0-contract-learning.md`：契约/接管/偏好/工件
- `docs/p1-evaluation-loop.md`：归因/评估/试运行
- `docs/p1-skill-marketplace.md`：技能市场/调教台
- `docs/p2-learning-loop.md`：金丝雀/共享/主动学习/周报/专家/回放
- `docs/p3-collaboration-dpo-migration.md`：协作/DPO/能力迁移
- `docs/agent-studio.md`：人格/记忆/回执/入职/预算/路由/触发器/模板/幻觉
- `docs/production.md`、`docs/deployment.md`：生产化与部署
- `scripts/reflection_smoke.py`：反思与自我修正
- `scripts/knowledge_binding_smoke.py`：员工知识库绑定
- `scripts/llm_features_smoke.py`：LLM 归因与技能推荐
- `scripts/learning_scheduler_smoke.py`：日结/自动提问/周报
- `scripts/trainer_dpo.py`：真实小模型 DPO/SFT trainer
- `scripts/trainer_reference.py`：参考外部 trainer（契约测试）
- `scripts/trainer_smoke.py`：数据集导出/派发/回调联调

## 10. 数字员工工作台（2026-11-24 方向纠偏）

核心模型纠正：**Agent 是可复用能力单元，数字员工绑定 Agent**；
个性化发生在员工层（契约/人格/技能/记忆/项目/会话），不复制 Agent。

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Agent → 员工绑定 | ✅ | `digital_employees.agent_id`；创建时卡片选择 Agent，可复用 |
| 员工工作台 | ✅ | `GET /digital-employees/{id}/workbench`；概览/工作/项目/Token/配置 |
| 左下角员工坞 | ✅ | 全局常驻：状态、当前任务、今日 Token、去对话/拉群/工作台 |
| 直接对话 | ✅ | `conversations/messages`；类大模型窗口；SSE 流式、停止/重试、附件上传下载；支持发消息/创建任务、`/` 指令、`@` 引用文件/会话 |
| 工具调用与契约 | ✅ | allow 执行、ask 待确认、deny 拦截；Token 落库 |
| 群聊 | ✅ | 多员工会话；auto/all/explicit 路由；独立回复气泡 |
| 项目 | ✅ | `projects` / `project_members` / 任务与会话关联 / Token 汇总；卡片与看板、详情抽屉 |
| Token 明细 | ✅ | 任务步骤 + 对话消息统一为 `token_events`；按天/来源/项目/工具筛选，CSV 导出 |
| UI 重构 | 🟡 | 工作台/员工坞/直接对话/群聊（@提及、指定路由、工具逐条审批）、Agent 反查与创建向导、项目卡片/看板、Token 筛选导出已完成；流式输出、全站视觉待 P1/P2 |
| 演示数据收敛 | ✅ | 默认只显示 active；清理脚本停用冒烟员工/Agent，只保留一个演示员工+通用助手 Agent |

配套任务书：`docs/ui-refactor-taskbook.md`、`docs/core-business-taskbook.md`。
