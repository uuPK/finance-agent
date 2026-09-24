# Phase 5–6：Trace 与 Harness 联动实施计划

状态：已确认的增补方案；按子步实施、验证、单独推送，下一子步须经用户确认。

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

### Phase 5.1：TraceRecorder 和阶段适配（已实现，待用户验收）

复用 `query_events` 作为追加日志、`query_steps` 作为兼容的阶段视图；记录检索排名/入选原因、Context 取舍、Plan 证据、校验结果、模型实际 token 与单调时钟耗时。沿用 SQL 执行明细表，以 `query_id`/`execution_id` 引用，不复制结果行。

实现边界：`trace.context_selection`、`trace.plan_evidence`、`trace.validation`、`trace.llm_call` 和 `trace.sql_execution` 是仅追加的遥测事件，不更新阶段视图或运行状态；阶段开始/结束事件复用同一 `span_id`，遥测以 `parent_span_id` 指向当前阶段。模型用量仅取 API 响应；未返回时为 `null`。遥测落库失败不重试模型或 SQL，下一条阶段事件带 `trace_warning`。

兼容边界：原有阶段事件和前端调试面板仍使用完整 QueryPlan、SQL、结果预览；新 `trace.*` 事件只记录引用和摘要，不复制完整 Prompt、元数据正文、SQL 或结果行。若未来要求统一缩减旧事件载荷，必须同步迁移前端读取方式；不能将旧载荷的存在误认为新 Trace 已覆盖所有历史数据的脱敏。

真实链路验收使用 `RUN_TRACE_LIVE_TESTS=1` 运行 `backend/tests/test_trace_live_integration.py`：调用当前配置的真实模型与 Milvus/智谱检索，只在测试进程内存保留响应和事件，不写入运行审计表。普通全量测试默认跳过它，避免意外调用付费 API。

### Phase 5.2：HarnessState 与 QueryService facade

引入统一状态和预算，逐阶段搬迁编排，阶段输入/输出与 Trace span 一一对应。迁移期间旧 API、SSE、SQL Guardrail 和规则保护保持工作；不在此子步实现新的失败路由。

### Phase 6：Failure-Domain Router

将 `FailureEvent → 候选动作 → 预算检查 → 最终动作 → 执行结果` 串为可审计轨迹；按失败域只重做必要阶段，不从头运行。每个失败恰有一个最终路由决定；达到预算上限时终止或澄清。

## 验收与后续

- 能按 `query_id` 和 `event_id` 重建阶段、澄清轮次、修复尝试及父子调用；事件不覆盖。
- 预算不超限，失败不重复触发动作；恢复运行不会误把旧轮次计入新轮次。
- 旧 API/SSE 读取兼容；Trace 不含 API Key、完整 Prompt、隐藏推理或敏感结果行。
- Phase 9 基于 Trace 统计成功率、实际模型 token 和成本；Phase 11 才用各阶段 P50/P95 优化性能；Phase 14 再扩展前端 Debug 展示。

每个子步结束跑现有测试与新增回归，单独提交并推送 GitHub，等待用户确认后继续。
