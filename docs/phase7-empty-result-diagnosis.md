# Phase 7：结果状态与空结果诊断

状态：已实现。

## 契约

运行状态 `status=completed` 表示 SQL 通过审核、执行和结果硬校验；零行不是执行错误。结果另有独立的 `result_status`：成功返回记录时为 `HAS_ROWS`，成功返回零行时为 `EMPTY_RESULT`，未得到可用结果时为 `null`。该字段及可选的 `empty_result_diagnosis` 随 `QueryResponse` 保存在原有 `final_response` JSON 中；不改变旧运行状态、导出和评测所依赖的 `completed` 语义。旧响应缺少新字段时仍可读取。

## 诊断边界

仅在成功执行、零行且结果硬校验通过后启动。第一版只接受 `mart` allowlist 内**单表、2–3 个简单 AND 谓词**；不支持 JOIN、OR、子查询、GROUP BY、DISTINCT、OFFSET、函数谓词等复杂结构。谓词只能引用该表物理字段与字面量。复杂或无法验证的 SQL 返回 `unsupported`，绝不猜测条件原因。

对于 `A AND B AND C`，诊断器以一条只读 `COUNT(*) FILTER (WHERE ...)` 聚合 SQL，同时计算 `count(A)`、`count(B)`、`count(C)`、`count(A AND B)`、`count(A AND B AND C)`。探针由解析后的 AST 生成，重新经过 SQL Guardrail，并在只读事务中运行；独立 `statement_timeout` 默认 3 秒、最多 5 秒。探针失败不会把原本成功的零行查询变成错误。它不执行条件放宽后的明细查询，不修改原 SQL，不生成新的 SQL，也不保存探针返回的原始计数或结果行。

只有各单项均非空、各前缀交集非空且完整交集为零，才记为 `plausible_valid_empty`，回答“当前条件组合下没有符合条件的数据”。某个单项本身为空时记为 `predicate_empty`；更早的交集为空或探针与原结果不一致时记为 `inconclusive`。无法支持或探针失败分别为 `unsupported`、`probe_failed`；这些情形只说明未能确认原因，不自动修 SQL。由于原查询与探针不在同一事务快照，诊断结论使用“plausible”，不宣称数学上绝对确定。

Trace 追加 `trace.empty_result_diagnosis`，仅含状态、原因代码、谓词数量和各检查是否非空，不包含 SQL、字面量、原始计数或数据行；SSE 及 `steps` 增加 `diagnose_empty_result` 阶段。前端在 `completed` 运行旁单独显示“结果为空”标识。

## 配置与验收

- `.env` 可设置 `EMPTY_RESULT_DIAGNOSTIC_TIMEOUT_SECONDS=3`，运行时强制限制在 1–5 秒。
- `backend/tests/test_empty_result_diagnostic.py` 覆盖三谓词交集、单项为空、复杂 SQL 拒绝、探针失败、运行/结果双状态及不触发 SQL 重生成。
- 设置 `RUN_TRACE_DB_TESTS=1` 时额外使用本地种子 PostgreSQL 做只读集成验收；该测试不调用模型，不保存业务行或基准题结果。
