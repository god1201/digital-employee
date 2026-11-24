# P1：技能市场与调教台（已实现）

对应 `docs/requirements-agentic-workforce.md` 第六章（Skill Marketplace）与 M10 调教台。
P0/P1 学习闭环见 `docs/p0-contract-learning.md`、`docs/p1-evaluation-loop.md`。

## 1. 技能包（五件套）

表：`skill_packages`（`SkillPackage`），同一 code 的每个版本一行。

| 字段 | 含义 |
| --- | --- |
| `code / name / category / version` | 编码、名称、分类（language/data/process/audit/learning）、版本 |
| `status` | `draft / published / deprecated` |
| `is_builtin` | `tenant_id` 为空表示平台内置 |
| `algorithm` | 算法能力说明 |
| `tool_codes` | 工具权限声明 |
| `knowledge_base_ids` | 依赖知识库 |
| `prompt_template` | 结构化输出提示词 |
| `eval_case_ids` | 自带评估用例（预留，当前由员工综合评估套件承担回归） |
| `dependencies` | `[{"code": "...", "min_version": 1}]` |
| `conflicts_with` | 禁止同时装配的技能编码 |
| `permissions` | `read_only / amount_threshold / risk_level / data_scopes` |
| `common_combos` | 常见组合推荐 |

装配记录表：`employee_skills`（`EmployeeSkill`），`(tenant_id, employee_id, skill_code)` 唯一，
记录当前 `skill_id / version / status / source`。

## 2. 装配语义

- **依赖解析**：`resolve_install_plan` 递归解析依赖并按依赖优先排序；缺失依赖、版本不足、
  依赖环都会报错。
- **冲突检测**：`conflicts_with` 与安装计划或已启用技能取交集，命中即 409。
- **权限并集**：`merge_permissions` 计算只读/可写、最高风险等级、最紧金额阈值、
  数据范围与工具编码并集；安装响应用 `warnings` 提示风险升级、数据范围扩大、
  只读变可写、金额阈值收紧。
- **安装**：同一版本重复安装幂等；已装不同版本提示使用升级接口。
- **升级**：解析最新版本及依赖，必要时一并升级；若员工有启用的评估套件，
  升级前跑一次、升级后再跑一次，任一 suite 下降超过 `regression_tolerance`
  会回滚技能版本、删除本次新增依赖、落库评估记录并返回 400。
- **复制**：`POST /employees/{target}/skills/copy` 按源员工已装版本复制并解析依赖。
- **推荐**：`GET .../skills/recommend?need=...&use_llm=false|true`
  - 默认规则打分（名称/描述/标签/分类/常见组合），返回可解释 reason；
  - `use_llm=true` 时把候选技能目录交给 LLM 选择，只接受目录内编码，
    返回 `source=llm`；未配置或失败自动回退规则。
- **技能生效**：`build_skills_context` 把启用技能的名称、版本、提示词、工具与知识库
  注入自由任务规划、LLM 步骤、综合评估与工件生效评估的 system prompt。

## 3. 接口

技能市场：

- `GET /api/v1/skill-packages`（每个 code 最新版本，支持 category / keyword / include_drafts）
- `GET /api/v1/skill-packages/{code}`（含版本历史）
- `GET /api/v1/skill-packages/{code}/versions`
- `POST /api/v1/skill-packages`（创建 v1 草稿）
- `POST /api/v1/skill-packages/{code}/versions`（创建新版本草稿）
- `POST /api/v1/skill-packages/{package_id}/publish`
- `DELETE /api/v1/skill-packages/{package_id}`（下架）

员工装配：

- `GET /api/v1/digital-employees/{id}/skills`
- `GET /api/v1/digital-employees/{id}/skills/context`
- `GET /api/v1/digital-employees/{id}/skills/recommend?need=...`
- `POST /api/v1/digital-employees/{id}/skills`
- `POST /api/v1/digital-employees/{id}/skills/copy`
- `DELETE /api/v1/digital-employees/{id}/skills/{code}`（停用）
- `POST /api/v1/digital-employees/{id}/skills/{code}/toggle`
- `POST /api/v1/digital-employees/{id}/skills/{code}/upgrade`

## 4. 调教台

- `GET /api/v1/learning-artifacts/{id}/lineage`：沿 `supersedes_id / rollback_of` 返回版本谱系。
- `POST /api/v1/learning-artifacts/{id}/new-version`：创建 v+1 草稿并挂到版本树。
- `GET /api/v1/timeline?employee_id=&limit=`：接管增量、学习工件、失败归因、试运行
  汇总时间线，支撑“轨迹回放 + Diff + 回滚”的调教入口。
- 前端「学习中心 → 调教台」按时间线查看事件并直接打开对应抽屉；
  `ArtifactDrawer` 增加版本谱系与「新建版本」。

## 5. 前端

- 新增「技能市场」页：分类/关键词筛选、创建技能包、详情与版本历史、发布、安装。
- 数字员工「技能装配」抽屉：已装技能、升级、启停、从其他员工复制、组合推荐、
  注入提示词的技能上下文与权限并集。
- 「学习中心」新增「调教台」页签。

## 6. 验证

- `ruff check app tests scripts` 通过。
- `pytest`：39 passed（新增技能权限并集与上下文测试）。
- `npm run build` 通过。
- PostgreSQL 冒烟：
  - 安装 `data.report` 自动带上 `data.sql_query`，权限并集告警正确；
  - 自定义 v1 → v2 升级成功；
  - 跨员工复制成功；
  - 冲突技能返回 409；
  - 工件新版本与谱系 v1/v2 正确；
  - 时间线聚合四类事件；
  - 技能上下文包含依赖技能。

## 7. 边界

1. 技能包当前是“提示词 + 工具/知识库/权限声明”的装配单元；工具实际执行仍受
   `tools`、授权与准入规则约束。
2. 推荐默认是确定性关键词打分；LLM 推荐为可选路径，需要配置 `LLM_API_KEY`。
3. 依赖升级取每个 code 的最新发布版本，不做多约束求解。
4. 技能自带 `eval_case_ids` 尚未执行，回归由员工综合评估套件承担。
5. 调教台暂未实现操作轨迹逐帧回放与金丝雀发布；版本谱系、Diff 与回滚已可用。
