# Phase 13：元数据候选治理（后端）

Phase 11 按要求跳过；本阶段不修改前端，也不自动运行或保存真实模型评测。现有库须执行 `backend/db/migrations/014_metadata_candidates.sql`；新部署的 `backend/db/schema.sql` 已包含相同结构。本机开发库已应用 014。原有 `RuleBasedQueryPlanActor`、SQL Guardrail、物理业务表和既有评测集不变。

## 写入路径

`POST /api/evaluation/review-imports` 仍保留审核决定和 review 状态，但不再直接写 active metadata 或 `evaluation.eval_cases`。合法的 `metadata_changes`、经 SQL Guardrail 检查的修正样例，以及标准答案修正会成为 `metadata.metadata_candidates` 中的独立候选。返回的 `metadata_changes_applied` 恒为 0，新增 `metadata_candidates_created` 表示候选数。修正 SQL 必须同时附有审核者提供的 QueryPlan 与 `corrected_result.rows`；信息不完整时拒绝该条导入，避免自动执行未确认 SQL 后污染标准答案。

审核 SQL 的安全白名单直接读取完整的实时 `mart` 物理表/字段、active 敏感字段和有效 JOIN 目录，不受单个问题的检索 TopK 或提示词预算裁剪；安全元数据读取失败时拒绝审核，不执行 SQL。`needs_clarification` 审核若未提供新的 `corrected_result`，候选沿用现有案例的结果标准，不把它清空；晋级前 active 标准答案不变。

每条候选带 `metadata_version`、来源 `review_item_id` / 可用时的 `source_query_id`、`reviewer_id`、`created_at`、`supersedes`。同一审核项的同一实体不允许重复候选。生产元数据读取仍只看 active 表，不看 candidate 表。

## 状态与 API

```text
candidate → approved → evaluating → ready → promoted → rolled_back
                 ↘ rejected ←───────┘
```

API 均在 `/api/evaluation/metadata-candidates` 下：`GET /` 列表、`GET /{id}` 详情、`POST /{id}/approve`（`{"approved_by":"另一位审核者"}`）、`POST /{id}/reject`（`{"reason":"..."}`）、`POST /{id}/regression`（`{"baseline_eval_run_id":"..."}`）、`POST /{id}/promote`、`POST /{id}/rollback`。批准者不得与提交候选的审核者相同。晋级只接受 `ready` 且回归证据仍完整的候选；回滚只接受 `promoted`，若其后已有已晋级版本或 active 行被外部修改则拒绝覆盖。

回归必须由操作者显式发起，调用真实 LLM、智谱 embedding/rerank 和 Milvus，可能产生费用并保存新的评测批次。它要求一个已完成、`full`、具有 Phase 10 `comparison_manifest` 的生产基线；样本、模型、提示词、预算和数据库指纹须仍一致。基线原样本在内存中加载，仅对候选来源案例应用经审核的标准答案修正；不改生产 `eval_cases`。候选 metadata 仅在回归进程内叠加到检索文档及 SchemaContext，Milvus 使用候选专属 collection；`_case_override` / `_source_case_id` 等治理字段不会进入检索文档。对非来源案例不允许由通过变失败；来源案例必须通过；样本集合、manifest、运行状态不一致均拒绝晋级。候选回归结果、生产快照与候选版本在晋级时再次检查。

回归失败时标记 `rejected`，无需回滚生产数据，因为此前从未进入 active。已晋级候选可以显式 rollback：新建项变为 inactive，更新项恢复前一版本，案例标准答案恢复前值。候选专属 Milvus collection 暂保留供审计；目前没有自动清理命令。

## 边界与后续验收

这套门槛覆盖 **review 导入路径**。项目原有 `/api/metadata` 直接 CRUD 仍是手工管理入口，能绕过候选流程；服务目前没有用户认证/RBAC，不应对不可信网络开放治理写接口。前端审批界面、统一权限及候选 collection 生命周期需另外设计，不能把自填的 `approved_by` 当作可信身份认证。

本阶段验证了迁移、本地候选事务隔离、API 列表和后端回归测试；没有按之前要求启动真实模型基线或候选回归，因此没有声称线上准确率和晋级路径已用真实模型端到端验证。来源样例本身可能含 SQL 范例；其来源题通过不是独立泛化证据，最终放行仍依赖其余基线案例不退化，后续可增加独立留出集。
