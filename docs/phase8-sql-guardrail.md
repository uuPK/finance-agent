# Phase 8：SQL Guardrail 增强与可选 EXPLAIN

状态：已实现。

## JOIN 路径契约

继续使用现有 `SQLGuardrail`、SQL Critic 与 Harness 修复链，不替换它们。`SchemaContextProvider` 在原来给模型的有限 `join_relationships` 之外，新增仅供 Guardrail 使用的 `join_relationship_allowlist`：从 PostgreSQL 的**全部启用关联**中取两端为 `mart` 且物理字段仍存在的表/列对。检索和 Context 预算不会缩小此硬规则目录；它也不进入模型的 `prompt_context`。定向 Context 扩充时，以新加载的完整目录替换旧目录快照，而不是拼接有限召回证据。表与字段的现有白名单仍独立生效。

Guardrail 按每个 SELECT 的直接 `FROM`/`JOIN` 顺序识别物理表及别名，核对 `ON` 中的等值键或 `USING` 列。直接物理表 JOIN 必须有目录中的双向关联键；键错、关联未登记或 `ON ... OR ...` 不能通过。`CROSS JOIN`、缺少条件或 `ON true` 等无键笛卡尔 JOIN 单独作为硬失败。多跳 JOIN 可逐跳使用不同已登记路径。硬失败仍进入原有 Harness SQL 修复流程，不会绕过原有安全检查。

CTE、派生表、自 JOIN，以及未提供完整目录的旧/自定义上下文，暂时无法可靠证明底层路径，记为通过但带 `warning` 的 `join_path_consistency`；不假装已验证，也不在本阶段强行拒绝既有复杂查询。对含派生表的完整血缘分析属于后续增强范围。

## 可选的 PostgreSQL 查询计划预检

默认 `ENABLE_SQL_EXPLAIN_CHECK=false`。开启后，仅在 SQL 硬校验通过、调用 SQL Critic 前，对多表/复杂 SELECT 执行 `EXPLAIN (FORMAT JSON)`。它运行于只读事务中，设置独立 `statement_timeout`（默认 3 秒，运行时限制 1–5 秒），随后回滚；**不使用 `ANALYZE`，不会执行目标 SELECT**。简单单表查询直接跳过；检查异常、超时或计划格式不符只记 `failed/skipped`，不会把原查询改为失败。

计划遍历最多 256 个节点，只记录根节点估计行数/成本、节点数量与风险标记：`estimated_large_scan`、`estimated_large_join_output`、`estimated_high_cost`、`possible_cartesian_join`。后一个标记只是保守启发式，不能替代 Join Path 硬规则；所有估计风险均只作提示，不触发自动 SQL 修复。Trace 的 `trace.sql_plan` 和 `sql_explain_review` 阶段仅保存这些摘要，不保存完整计划、SQL 或结果行。PostgreSQL 将普通 `EXPLAIN` 定义为展示查询计划；`ANALYZE` 才会实际执行语句，详见 [官方说明](https://www.postgresql.org/docs/current/sql-explain.html)。

## 配置与验收

- `.env.example` 提供 `ENABLE_SQL_EXPLAIN_CHECK`、`SQL_EXPLAIN_TIMEOUT_SECONDS`、`SQL_EXPLAIN_MAX_PLAN_ROWS`、`SQL_EXPLAIN_MAX_TOTAL_COST`。估计阈值只影响提示，不影响查询准入。修改 `.env` 后重启后端。
- `backend/tests/test_sql_guardrail.py` 覆盖已登记多跳、错误键、未登记路径、OR、笛卡尔 JOIN、派生表兼容与本地 PostgreSQL 完整目录。
- `backend/tests/test_sql_plan_inspector.py` 覆盖只读无 `ANALYZE`、简单查询跳过、计划风险分类、检查失败不阻断 SQL Critic 与本地 PostgreSQL 真实计划。
- 可用 `RUN_TRACE_DB_TESTS=1` 运行本地数据库集成测试；默认测试不依赖数据库。EXPLAIN 是估计值，不能作为运行时性能或结果正确性的证明。
