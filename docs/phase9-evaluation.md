# Phase 9：分层 Evaluation 指标

状态：指标采集、存储和展示已实现；本阶段**未运行或保存新的模型基准结果**。

## 数据流

评测仍由 `EvaluationManager` 调用真实 `QueryService`，最终结果正确性仍使用内部完整 `EvaluationExecutionArtifact`，不使用 UI 的 `result_preview`。仅在评测模式下，服务内部额外携带元数据检索标识及 Harness 计数；它们是 `QueryResponse` 私有属性，不出现在普通 API 或响应序列化中。评测管理器临时接收 Trace 的阶段状态、耗时和模型用量；不收集提示词、SQL、结果行或元数据正文。每题结构化指标写入 `evaluation.eval_results.metrics`，批次详情 API 汇总有标签的样本，前端显示数值及有效样本数。

## 指标口径与不可用值

| 类别 | 实现口径 |
| --- | --- |
| Retrieval | 从标准 SQL 可证明的物理表、限定字段、等值 JOIN 路径，以及标准 QueryPlan 明示的指标代码构成 gold；与检索器最终候选集比较，分别报告表、字段、指标、JOIN 路径 Recall@K。此处 K 是当前检索配置下的最终候选集，包含必要锚点/路径补全，不代表裸 Dense/BM25 的原始 TopK。|
| QueryPlan | 只按标准计划明确提供的 intent、指标、过滤、时间和粒度标签计算覆盖率/准确率；澄清准确率比较标准 `completed`/`needs_clarification` 与实际是否要求澄清，同时计入不必要澄清。语义准确率是可用子项的均值，不把未标注子项算作正确。|
| Runtime | 一次成功以 `completed` 且零重试为准；修复/重试成功率仅以实际发生相应动作的题为分母。|
| Cost | 统计模型调用、输入/输出 token、Context 估计 token、单题耗时；批次 P50/P95 为 nearest-rank 分位数。缺少 provider 用量时 token 为 `null`。|
| Critic | 记录 Critic 阶段的模型 token、阶段耗时和 Critic 失败后的最终修复成功。`false_pass` / `false_block` 暂为 `null`：目前标准集没有**每个 Critic 草稿决策**的人工真值，不能用最终答案对错倒推其误判。|

`null` 表示无标准标签或无可靠观测，**不等于 0%**。批次详情提供 `*_samples` 分母；旧批次没有新指标，保留原有评分/结果不变。标准 SQL 中无法安全解析的复杂 JOIN 不会被猜成 gold。指标只用于观测，不改变在线 Guardrail、Critic、Harness 决策和人工复核流程。

## 部署与验收

新库的 `backend/db/schema.sql` 已含 `metrics` 列。现有库先执行可重复的 `backend/db/migrations/012_evaluation_metrics.sql`，再启动新版后端。`backend/tests/test_phase9_evaluation_metrics.py` 覆盖真实结构的 JOIN/字段召回、缺失标签、分母和分位数、私有数据不序列化，以及与既有完整结果评分的兼容。

要得到完整 Phase 9 的实际模型数值，需要用户决定何时运行固定的官方/挑战/全量评测。运行会调用真实模型、产生费用并写入新的评测批次；本阶段遵照先前“不保存例子结果”的要求，没有自动启动这类运行。Critic 误放行/误拦截还需要补充草稿级人工标注，不能宣称已具备可信数值。
