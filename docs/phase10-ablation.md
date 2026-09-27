# Phase 10：可执行消融实验

状态：开关、运行路径、可比性约束、按题型切分和 UI/API 已实现。本次只运行自动化/只读验收，**未调用模型跑官方案例，也未创建新的评测结果**。

## 实验变体

| 变体 | 实际执行差异 |
| --- | --- |
| `full` | 结构化 QueryPlan + 三阶段 LLM Critic + Milvus BM25/Dense RRF + 智谱 CrossEncoder |
| `no_query_plan` | 不调用 QueryPlanActor、计划校验/计划 Critic/计划修复；LLM 直接从问题与元数据生成 SQL，SQL/结果 Critic 对照原问题审核而不读取 QueryPlan。只创建一个不传给这些模型的 API 兼容空壳计划；SQL 硬校验、只读执行和结果硬校验保留。 |
| `no_critic` | 跳过计划、SQL、结果三个 LLM Critic；硬校验与 Harness 安全边界保留。 |
| `bm25_only` / `dense_only` | Milvus 只执行对应搜索通道，不执行另一通道。 |
| `bm25_dense` | 两通道结果轮流交错去重，不计算 RRF。 |
| `bm25_dense_rrf` | 两通道 RRF，关闭 CrossEncoder。 |
| `full_cross_encoder` | 与 `full` 等价的显式别名，便于读取方案原始实验名称。 |
| `legacy_retrieval` | PostgreSQL 旧检索器，无 Milvus/CrossEncoder。 |
| `hybrid_retrieval` | 与 `bm25_dense_rrf` 等价的显式别名。 |
| `critic_always` | 与 `full` 等价的 Critic 对照别名。 |
| `critic_conditional` | 仅在计划置信度 <0.85、多候选表、有澄清项或状态非 ready 时调用三个 LLM Critic；其余仍执行全部硬校验。规则固定，尚未按真实 Trace 调优。 |

这些开关只在评测请求中生效，不修改线上 QueryService 默认配置。原系统中的真实规则 SQL 生成与安全兜底未删除；仅 `no_query_plan` 对照臂绕开规则 SQL 模板，以免偷用结构化计划。

## 运行与可比性

先对现有库执行可重入的 `backend/db/migrations/013_ablation_runs.sql`（本地已执行）；新库 `backend/db/schema.sql` 已含相同列。在评测中心选择变体，填写同一个“对照组名称”，并保持题集、难度、上限一致。也可 POST `/api/evaluation/runs`：

```json
{
  "run_name": "phase10-full",
  "evaluation_mode": "full",
  "limit": 500,
  "ablation_variant": "full",
  "comparison_group": "phase10-2026-09"
}
```

每个变体均调用真实模型和真实检索器；运行会产生成本及 `evaluation`/`agent` 审计数据。系统在启动前只读验证 Milvus 文档 ID/内容哈希与 PostgreSQL 元数据一致，不在消融运行时同步或重新向量化。不同对照组变体必须有完全相同的模型提供方/模型/地址、嵌入与重排模型、提示词相关代码哈希、案例集合及标准答案哈希、重试和检索预算、温度 0、`mart` 和 `metadata` 表内容 SHA-256 指纹；不符返回 409。同组同一变体不可重复。运行结束再次计算数据库指纹，漂移则标记失败。`GET /api/evaluation/comparisons/{group}` 返回所有变体的结构化结果。密钥不进入指纹或响应。

这里的“同一 DB snapshot”是**内容指纹相同且运行前后未漂移**，不是 PostgreSQL 跨多次运行的同一 MVCC 事务快照；若别的进程在一次运行中修改又改回，前后指纹不能发现。Milvus 在每次检索前只读核对索引内容，但不能阻止外部并发改写。需要严格不可变快照时，应在隔离的数据库/索引副本上运行，并冻结写入。失败或进行中的变体不能用于效果结论。

## 指标解释

原有总正确率、Phase 9 检索/计划/成本/延迟/Critic 指标不变。新增单表、聚合、多表 JOIN、多时间窗、业务术语、歧义问题、挑战题七类独立分母；一个案例可以进入多个切片。前三类从标准 SQL 的 `mart` 物理表解析，多时间窗从标准计划或标签识别，业务术语由明确标签或标准计划的 business_term 引用识别，歧义由标准状态/标签识别，挑战由来源/标签识别。未有可靠证据的题不猜测归类；零样本准确率为 `null`，UI 显示“—”。No QueryPlan 的计划指标不应与 Full 当作同一机制的能力比较，重点比较结果正确性、执行、安全、调用和耗时。

下一阶段 Phase 11 需要先有用户认可的真实 Trace/消融数据，按阶段 P50/P95 找关键路径，再决定是否将 CrossEncoder 或 Critic 条件化；不能凭当前尚未运行的结果宣称哪个模块最慢。
