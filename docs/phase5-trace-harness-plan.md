# Phase 5–6：Trace 与 Harness 联动实施计划

状态：Phase 5 与 Phase 6 已实现；此前按子步验收，本次依用户要求完成 Phase 6 剩余路线与整阶段验收。

## 为什么先补 Trace 契约

现有 `agent.query_events`、`agent.query_steps` 和 SSE 已能展示阶段事件，`ContextBundle.retrieval_trace` 保留检索证据，但还不能稳定重建一次运行的检索、校验、修复路由及成本。尤其现有 `attempt` 同时承载澄清轮次与阶段修复次数：`QueryService` 将两者相加，而 `query_steps` 以 `(query_id, step_name, attempt)` 唯一定位步骤，存在不同轮次覆盖同一步骤记录的风险。

Trace 是可审计的**结构化执行轨迹**，不是模型的隐藏推理过程。它只解释系统看到了什么证据、做了什么校验、为何选择某个动作以及结果如何。

## 契约与所有权

- `query_id` 就是整次运行的 Trace ID；沿用数据库 `event_id` 排序，不再制造第二个运行 ID。
- 单独使用 `clarification_round` 和 `stage_attempt`；兼容性字段 `attempt` 暂时保留供旧 SSE 客户端读取，但不再作为新步骤的唯一身份。
- 每个阶段调用有 `span_id`，其嵌套调用可带 `parent_span_id`。事件至少有 `schema_version`、阶段、类型、状态、发生时间；结束事件还含基于单调时钟的 `duration_ms`。
- 事件引用证据 ID、Context item ID、Plan provenance、校验结论、`FailureEvent` 和 `HarnessAction`，而非复制完整文档、Prompt 或结果行。
- `context_tokens_estimated` 与模型 API 返回的 `prompt_tokens` / `completion_tokens` 分开；用量缺失记 `null`，不伪装成零。
- HarnessState 是运行时状态与预算的唯一控制者；TraceRecorder 只追加事实，不自行路由、修复或重新调用模型。`QueryService` 继续作为 API facade。
- 关键路由、预算耗尽、澄清和终止动作要有持久事件；非关键遥测写入异常必须显式标记，不得因为补日志而重复执行 SQL 或 LLM。

## 联动顺序

```text
Harness 执行阶段并维护 State/Budget
  → Validator/Critic 给出结构化结果或 FailureEvent
  → FailureRouter 纯函数提出候选 HarnessAction（Phase 6）
  → Harness 检查预算并确定动作
  → Trace 记录证据、候选/最终动作和计数变化
  → Harness 只执行该动作对应的最小阶段
```

Trace 不能反向决定流程。检索、Context、Plan、SQL、执行、结果这六类阶段共享同一 `query_id`，但各自保留独立的 `stage_attempt`。澄清后的继续运行增加 `clarification_round`，不与任何修复计数相加。

## 实施子步

### Phase 5.0：协议和兼容性迁移（已完成，`9971590`）

1. 定义带校验的 Trace 事件/阶段模型与字段语义；所有新字段可选或有安全默认值，不破坏旧请求和事件读取。
2. 为现有 `query_events`、`query_steps` 增量增加轮次、阶段尝试、span 和耗时字段；步骤唯一键改为 `(query_id, clarification_round, step_name, stage_attempt)`。历史记录保留原值并标记旧版本，不猜测无法恢复的轮次。
3. 让当前事件发布链路明确传递轮次和阶段尝试，修正两者相加造成的碰撞；原有 SSE 结构保持可消费。
4. 测试同一运行中的“首轮修复 1 次”与“澄清后首轮”不互相覆盖、迁移可重复应用、旧记录仍可读取。

### Phase 5.1：TraceRecorder 和阶段适配（已完成，`254cf76`）

复用 `query_events` 作为追加日志、`query_steps` 作为兼容的阶段视图；记录检索排名/入选原因、Context 取舍、Plan 证据、校验结果、模型实际 token 与单调时钟耗时。沿用 SQL 执行明细表，以 `query_id`/`execution_id` 引用，不复制结果行。

实现边界：`trace.context_selection`、`trace.plan_evidence`、`trace.validation`、`trace.llm_call` 和 `trace.sql_execution` 是仅追加的遥测事件，不更新阶段视图或运行状态；阶段开始/结束事件复用同一 `span_id`，遥测以 `parent_span_id` 指向当前阶段。模型用量仅取 API 响应；未返回时为 `null`。遥测落库失败不重试模型或 SQL，下一条阶段事件带 `trace_warning`。

兼容边界：原有阶段事件和前端调试面板仍使用完整 QueryPlan、SQL、结果预览；新 `trace.*` 事件只记录引用和摘要，不复制完整 Prompt、元数据正文、SQL 或结果行。若未来要求统一缩减旧事件载荷，必须同步迁移前端读取方式；不能将旧载荷的存在误认为新 Trace 已覆盖所有历史数据的脱敏。

真实链路验收使用 `RUN_TRACE_LIVE_TESTS=1` 运行 `backend/tests/test_trace_live_integration.py`：调用当前配置的真实模型与 Milvus/智谱检索，只在测试进程内存保留响应和事件，不写入运行审计表。普通全量测试默认跳过它，避免意外调用付费 API。

### Phase 5.2：HarnessState 与 QueryService facade（已完成）

引入统一状态和预算，逐阶段搬迁编排；用相同的阶段坐标关联 Trace span 与已有的输入/输出证据引用。迁移期间旧 API、SSE、SQL Guardrail 和规则保护保持工作；不在此子步实现新的失败路由。

当前落地边界：每次 `QueryService.run` 创建一个仅驻留内存的 `HarnessState`，按澄清轮次维护阶段 `(stage, stage_attempt)`、Trace span、引用 ID、真实模型用量，以及独立的 Plan/SQL 修复预算。所有阶段事件和直接由模型包装器发出的遥测均经过同一事件出口：外部 sink 成功后才同步到状态；无 SSE sink 的直接查询 API 也维护相同状态。`QueryHarness` 接管接收问题、元数据检索、QueryPlan 生成/审核/修复的现有顺序，并给 SQL 修复预留预算；SQL 执行与结果校验仍沿用原逻辑。

预算耗尽时追加 `budget.exhausted` 事件，保留计数和上限，但不复制 Prompt、SQL 或结果行。此步只收拢运行状态与预算控制，不增加新的失败域路由，不删除原有规则生成兜底、硬校验或 SQL Guardrail，也不引入模拟模型。

### Phase 6：Failure-Domain Router

将 `FailureEvent → 候选动作 → 预算检查 → 最终动作 → 执行结果` 串为可审计轨迹；按失败域只重做必要阶段，不从头运行。每个失败恰有一个最终路由决定；达到预算上限时终止或澄清。

#### Phase 6.1：保守路由与审计闭环（已完成）

FailureRouter 只按明确的失败域和错误类型提出候选动作；QueryHarness 再检查模型可用性、修复预算和动作是否已实现，决定最终动作。Trace 记录路由 ID、失败阶段/安全化错误类型、来源阶段/span、候选动作、最终动作、裁决原因、预算计数与执行结果。原始 evidence 和 repair_hint 不写入 Trace。

首版可执行的局部动作是 Plan/SQL 修复；之后在 6.2–6.3 扩展了有证据的 Context/元数据刷新与执行重试。每次路由仍先记录候选，再由 Harness 检查证据、模型可用性及预算，写入最终动作和执行结局。

#### Phase 6.2：证据化元数据/Context 路由（已完成）

SQL 执行器保留 PostgreSQL SQLSTATE 与结构化缺失列诊断。只有当 SQL 解析结果恰为一个 `mart` allowlist 表、SQLDraft 表与之吻合，并由只读 `information_schema.columns` 证明实时数据库确有该列而当前 Context 没有时，才允许申请有预算的 `CONTEXT_REFRESH`。刷新复用 `SchemaContextProvider.expand` 的定向检索与检索预算，不让 Actor 直接访问 Milvus；取回后重审并重跑原 SQL，不额外生成 SQL。多表/歧义、数据库不可读、实时表结构不存在该列，以及刷新后仍缺字段都保守终止或进入既有 SQL 修复分类，并写入路由和执行 Trace。

当实时数据库已经没有该列、但本次 Context 仍有该列时，走有独立预算的 `METADATA_REFRESH`：从实时物理表结构及现有元数据重新构造**本次运行的内存快照**，确认旧列确已消失后才重新生成、审核 SQL；它不写入或自动修复 PostgreSQL 元数据目录及 Milvus 文档。若刷新无法验证表，或预算不足，直接终止。

Plan/SQL Critic 可输出结构化 `MissingContextRequest`；只有请求明确、数据库 Context 可用且预算允许时，Harness 才调用定向 `expand` 并重审相应阶段。没有具体请求的泛化“缺少元数据”判断不会触发任意检索。Plan 刷新后重新做证据约束；SQL 刷新后重审原 SQL。检索自身预算耗尽也会写入 `budget.exhausted`。

#### Phase 6.3：瞬时数据库故障与超时策略（已完成）

SQL 执行器保留 SQLSTATE，仅对明确的连接类、序列化冲突、死锁、资源不足等错误或连接失效，申请有界 `RETRY_EXECUTION`；锁等待超时也可重试。Harness 以封顶指数退避重新执行**同一条已审核 SQL**，不重复调用生成模型，也不跳过原先的 SQL 硬校验。`statement_timeout` 表示该 SQL 超出执行上限，走有预算的 SQL 优化修复；优化仍返回完全相同 SQL 时停止，避免重复超时。普通用户取消（即使同为 SQLSTATE `57014`）、未知执行错误和证据不足的故障均终止。

默认预算：`METADATA_REFRESH_LIMIT=1`、`SQL_EXECUTION_RETRY_LIMIT=2`、`SQL_EXECUTION_BACKOFF_MS=200`；退避单次封顶 2000 ms，SQL 修复仍受既有 `MAX_RETRY` 限制。每次路由及预算决议都保留在 Trace 中；预算耗尽只终止当前请求，不触发无限循环。

## 验收与后续

- 能按 `query_id` 和 `event_id` 重建阶段、澄清轮次、修复尝试及父子调用；事件不覆盖。
- 预算不超限，失败不重复触发动作；恢复运行不会误把旧轮次计入新轮次。
- 旧 API/SSE 读取兼容；Trace 不含 API Key、完整 Prompt、隐藏推理或敏感结果行。
- Phase 9 基于 Trace 统计成功率、实际模型 token 和成本；Phase 11 才用各阶段 P50/P95 优化性能；Phase 14 再扩展前端 Debug 展示。

本轮 Phase 6 验收覆盖纯路由、预算、真实 PostgreSQL `statement_timeout`（SQLSTATE `57014`）、真实智谱模型与 Milvus 检索，以及后端全量回归。实时外部链路测试显式启用 `RUN_TRACE_LIVE_TESTS=1`；普通测试不调用付费 API，也不运行 217 条基准问题或保存其结果。后续阶段仍按用户确认推进并及时推送 GitHub。
