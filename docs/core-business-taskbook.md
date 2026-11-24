# 核心业务逻辑落地任务书

> 版本：2026-11-24  
> 适用范围：`app/domains/*` 后端与 `frontend/src`  
> 关联文档：`docs/requirements-agentic-workforce.md`、`docs/ui-refactor-taskbook.md`

## 0. 纠正后的核心模型

之前的理解错误是把“个性化 Agent”当成员工本身。正确模型是：

```text
Agent（可复用能力单元）
  ├── 模型 / 系统提示词 / 工具 / 能力 / 运行参数
  └── 可被多个数字员工复用（1:N）

DigitalEmployee（任职实例）
  ├── agent_id → 绑定一个已有 Agent
  ├── 岗位契约 / 人格 / 技能 / 分层记忆 / 偏好
  ├── 项目 / 团队 / 任务 / 会话
  └── 个性化发生在员工层，不复制 Agent
```

- 创建数字员工时选择已有 Agent。
- 员工行为 = Agent 能力 + 员工契约/人格/技能/记忆 + 当前任务/会话上下文。
- 一个 Agent 可服务多个员工；Agent 页面能看到“被哪些员工使用”。
- 员工的工作台、对话、项目、Token 是新的核心对象。

## 1. 领域模型与迁移

新增/调整表：

### 1.1 `digital_employees`

```text
+ agent_id  INTEGER NULL REFERENCES agents(id) INDEX
```

- 允许为空，兼容存量员工；新建员工建议必须选择。
- 员工级 `model_provider/model_name/system_prompt` 保留，用于覆盖/兜底。
- 生效模型优先级：员工显式配置 > Agent 配置 > 全局默认。

### 1.2 `projects`

```text
id, tenant_id, code, name, description,
status(active/paused/archived), owner_employee_id,
token_budget, config JSON, created_by, created_at, updated_at
```

### 1.3 `project_members`

```text
id, project_id, employee_id, role(owner/member/reviewer), created_at
UNIQUE(project_id, employee_id)
```

### 1.4 `task_instances`

```text
+ project_id INTEGER NULL REFERENCES projects(id) INDEX
```

### 1.5 `conversations`

```text
id, tenant_id, mode(direct/group), title, status(active/archived),
project_id NULL, last_message_at, created_by, created_at, updated_at
```

### 1.6 `conversation_members`

```text
id, conversation_id, employee_id, role(owner/member), created_at
UNIQUE(conversation_id, employee_id)
```

### 1.7 `chat_messages`

```text
id, tenant_id, conversation_id, employee_id NULL,
role(user/assistant/tool/system), content Text,
tool_calls JSON, tokens INTEGER, cost FLOAT,
trace_id, status(sent/failed/pending_approval),
metadata JSON, created_by, created_at
INDEX(conversation_id, created_at), INDEX(employee_id, created_at)
```

`tool_calls` 结构：

```json
[
  {
    "tool": "crm.query",
    "arguments": {"customer": "A"},
    "success": true,
    "output": {"...": "..."},
    "error": null,
    "latency_ms": 120,
    "decision": "allow|ask|deny",
    "requires_confirmation": false
  }
]
```

`ask` 的工具不执行，写入 assistant 消息的 `metadata.pending_tools`，
下一条用户消息包含“确认/批准/同意”时执行。

### 1.8 Token 明细

不新增明细表，统一从两处聚合：

- `task_steps`：`tokens/cost/step_type/tool_code/name/created_at` + `task_instances`
- `chat_messages`：`tokens/cost/conversation_id/created_at` + `conversations`

对外统一为 `token_events`：

```json
{
  "source": "task|chat",
  "occurred_at": "...",
  "employee_id": 1,
  "context_id": 12,
  "context_title": "核对 A 客户回款",
  "project_id": 3,
  "project_name": "回款专项",
  "action": "调用 CRM 查询 / 第 2 轮回复",
  "action_type": "tool|llm|knowledge|chat",
  "tool_code": "crm.query",
  "model": "deepseek-chat",
  "tokens": 1234,
  "cost": 0.0012,
  "trace_id": "..."
}
```

## 2. 核心服务

### 2.1 Agent 绑定

- `POST/PATCH /digital-employees` 接受 `agent_id`。
- 校验：Agent 属于当前租户、状态 `active`。
- 员工详情/列表返回 `agent_id`、`agent_name`、`agent_code`。
- 未绑定 Agent 的存量员工：
  - 工作台提示“绑定 Agent”；
  - 对话可用员工自身模型/提示词兜底，但不推荐。

### 2.2 员工工作台

`GET /digital-employees/{id}/workbench`

返回：

```json
{
  "employee": {...},
  "agent": {...},
  "status": "idle|working|waiting|offline",
  "current_task": {...},
  "last_active_at": "...",
  "recent_tasks": [...],
  "projects": [...],
  "token_summary": {"today": 0, "7d": 0, "30d": 0, "cost_7d": 0},
  "conversations": [...]
}
```

### 2.3 对话

#### 会话

- `POST /conversations`
  - `mode=direct` + `employee_id`：复用该员工已有 active direct 会话，否则创建。
  - `mode=group` + `employee_ids[]`：至少 2 人，创建群聊。
  - 可选 `project_id`、`title`。
- `GET /conversations?employee_id=&mode=`
- `GET /conversations/{id}`：会话 + 参与者 + 最近 100 条消息。
- `POST /conversations/{id}/members`、`DELETE .../{employee_id}`
- `POST /conversations/{id}/archive`

#### 发消息

`POST /conversations/{id}/messages`

```json
{
  "content": "帮我查一下 A 客户回款",
  "target_employee_ids": [1, 2],
  "routing_mode": "auto|all|explicit"
}
```

流程：

1. 校验发送者是会话参与者/管理员。
2. 持久化 user message。
3. 确定回复员工：
   - direct：唯一员工；
   - group + explicit：指定员工；
   - group + all：全部成员；
   - group + auto：按 message 与岗位/技能/Agent 能力打分，选 Top1；
     全为 0 分时回退到全部成员。
4. 对每个回复员工：
   - 加载 employee、agent、契约、人格、技能、记忆、项目上下文。
   - 组装 system prompt：
     `Agent system_prompt + build_employee_prompt + 对话规则 + 群聊规则`。
   - 加载工具：`agent.tools ∪ 员工技能 tool_codes`，仅启用工具。
   - 调用 LLM 工具循环（最多 `agent.config.max_steps`，默认 6）。
   - 每个工具执行前调用 `evaluate_tool_call`：
     - `allow`：执行并写 tool result；
     - `ask`：不执行，记录 pending，要求用户确认；
     - `deny`：不执行，记录红线原因。
   - 累计 tokens/cost，持久化 assistant message + tool_calls。
   - 写审计 `conversation.message`。
5. 返回 user message + 所有员工回复。

群聊消息上下文：

- 包含 user 消息与各员工历史回复，assistant 历史带 `[员工名]` 前缀。
- 每个员工只以自己的身份回复，不替其他员工发言。

#### 待确认工具

- `ask` 的调用写入 assistant message `metadata.pending_tools`。
- 用户下一条消息包含“确认/批准/同意”时，先执行 pending 工具，再让模型基于结果回复。
- 用户拒绝或改口时清空 pending。
- P2 可升级为独立审批卡片（复用审批流）。

#### Token/成本

- 每次 LLM 调用返回的 `total_tokens` 累加到 assistant message。
- `cost = tokens / 1000 * settings.llm_cost_per_1k_tokens`。
- 工具调用本身不产生额外 LLM token，但记录耗时与结果。

### 2.4 项目

- `POST/GET/PATCH /projects`
- `GET /projects/{id}`：成员、任务、会话、Token 汇总。
- `POST/DELETE /projects/{id}/members`
- `POST/DELETE /projects/{id}/tasks`
- `GET /digital-employees/{id}/projects`
- Token 汇总：任务步骤 + 会话消息，按项目归集。

### 2.5 Token 明细

`GET /digital-employees/{id}/token-usage?days=30&group_by=day|source|tool|project`

返回：

```json
{
  "days": 30,
  "total_tokens": 123456,
  "total_cost": 0.12,
  "by_day": [{"date": "2026-11-24", "tokens": 1234, "cost": 0.001}],
  "by_source": {"task": 1000, "chat": 234},
  "by_tool": {"crm.query": 500},
  "events": [...]
}
```

### 2.6 员工状态

- `working`：存在 `running` 任务；
- `waiting`：存在 `waiting_human` 任务；
- `offline`：员工 `disabled`；
- 否则 `idle`。

## 3. API 清单

```text
PATCH /api/v1/digital-employees/{id}                 # agent_id
GET   /api/v1/digital-employees/{id}/workbench
GET   /api/v1/digital-employees/{id}/token-usage
GET   /api/v1/digital-employees/{id}/projects

POST  /api/v1/projects
GET   /api/v1/projects
GET   /api/v1/projects/{id}
PATCH /api/v1/projects/{id}
POST  /api/v1/projects/{id}/members
DELETE/api/v1/projects/{id}/members/{employee_id}
POST  /api/v1/projects/{id}/tasks
DELETE/api/v1/projects/{id}/tasks/{instance_id}

POST  /api/v1/conversations
GET   /api/v1/conversations
GET   /api/v1/conversations/{id}
POST  /api/v1/conversations/{id}/messages
POST  /api/v1/conversations/{id}/members
DELETE/api/v1/conversations/{id}/members/{employee_id}
POST  /api/v1/conversations/{id}/archive
```

## 4. 安全与治理

- 所有查询强制 `tenant_id`。
- 会话参与者才能读写会话；管理员可管理会话成员。
- 工具执行前必须走岗位契约；`deny` 永不执行。
- `ask` 必须人工确认；群聊中确认只对当前员工有效。
- 每次对话、工具调用、项目变更写审计。
- 聊天内容不写入日志正文；只记录长度、token、工具名、trace。
- 群聊自动路由失败时回退全员，不静默丢弃消息。

## 5. 测试

- 单元：路由打分、Token 聚合、待确认工具解析、Agent 生效模型优先级。
- 集成（`DE_INTEGRATION_TESTS=1`）：
  - 员工绑定 Agent 后工作台返回 Agent；
  - 创建项目、加入成员、关联任务；
  - 创建 direct/group 会话；
  - 发送消息（mock LLM / 真实 LLM 冒烟）持久化消息与 token；
  - 契约 deny 的工具不执行；
  - Token 明细能按任务/会话/工具归集。
- UI：员工工作台、员工坞、直接对话、群聊、Token 页。
- 回归：现有 P0–P3、学习中心、Agent、任务中心冒烟不退化。

## 6. 验收标准

- [ ] 新建员工可选择已有 Agent；Agent 可被多个员工复用。
- [ ] 选中员工出现员工坞，显示状态、当前任务、今日 Token。
- [ ] 工作台返回工作/项目/Token/会话数据。
- [ ] 直接对话可调用工具，工具调用可见，tokens 落库。
- [ ] 契约 `deny` 的工具不执行；`ask` 需确认。
- [ ] 群聊可创建、可增删成员、可选择自动/全员/指定路由。
- [ ] Token 明细能回答“在哪里、做了什么、怎么消耗”。
- [ ] 项目可关联任务与会话，并汇总 Token。
- [ ] Alembic 迁移无漂移；`pytest`、`ruff`、`npm run build` 通过。

## 7. 分期

- **P0**：`agent_id`、工作台 API、direct 会话、Chat 服务、Token 汇总。
- **P1**：项目模型/API、Token 明细、会话历史。
- **P2**：群聊、自动路由、待确认工具、@提及。
- **P3**：项目看板、Agent 使用关系、全站权限与审计细化。

## 8. 实现进度（2026-11-24）

P0/P1 核心已落地：

- [x] `digital_employees.agent_id` + Agent 归属校验；创建/更新员工可绑定 Agent
- [x] `projects` / `project_members` / `task_instances.project_id`
- [x] `conversations` / `conversation_members` / `chat_messages`
- [x] `GET /digital-employees/{id}/workbench`
- [x] `GET /digital-employees/{id}/token-usage`：任务步骤 + 对话消息统一归集
- [x] 直接对话 / 群聊；auto/all/explicit 路由
- [x] 对话工具循环：Agent 工具 + 员工技能工具，执行前走岗位契约
- [x] `ask` 写 pending，用户“确认”后执行；`deny` 永不执行
- [x] Token/cost 落库；对话/工具/项目审计
- [x] Alembic 迁移 `a1b2c3d4e5f6`；`alembic check` 无漂移
- [x] PostgreSQL 集成测试：工作台/项目/直接对话/群聊/ask-confirm-deny
- [x] Agent 使用关系反查：列表统计 + `GET /agents/{id}/employees` + 使用方抽屉
- [x] 新建 Agent 分步向导（身份/模型/工具/提示词/预览）
- [x] 项目卡片/看板 + 项目详情抽屉（成员、任务、会话、Token 预算）
- [x] 任务/会话与项目关联/取消；`GET /projects` 聚合统计；工作台加入项目/关联任务
- [x] 群聊 @提及与「指定员工」路由；待确认工具独立审批卡片与逐条决策接口
- [x] Token 明细按来源/项目/工具筛选，统计联动；CSV 导出（BOM + 公式转义）
- [x] 对话输入器：发消息/创建任务、`/` 指令、`@` 引用员工/文件/会话；上下文注入
- [x] SSE 流式输出、停止生成与重试；对话附件上传/下载/删除与上下文注入
- [x] Alembic `b2c3d4e5f6a7`（`chat_attachments`）；`pytest`（含集成）：106 passed
- [x] 冒烟数据与产品数据分离：前端默认只显示 `active` 员工/Agent，提供“显示停用”开关；
  `scripts/cleanup_smoke_data.py` 可停用冒烟员工/Agent、归档测试会话

> 产品语义：**同一类功能只需要一个数字员工**（绑定一个 Agent）；多个员工只用于
> 不同岗位契约/身份、不同客户或群聊参与者。冒烟脚本创建的 A/B 员工是测试夹具，
> 不是产品设计；运行后应清理或让其保持 disabled。

待 P2/P3：

- 群聊 @提及与更精细的路由策略
- 待确认工具的独立审批卡片/审批流复用
- 项目看板与任务/会话关联 UI
- Agent 页面反查使用员工、创建向导
- 对话流式输出、停止/重试、附件
- 全站权限细化与聊天内容合规策略
