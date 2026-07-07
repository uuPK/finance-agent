# Metadata Design

## 元数据目标

元数据层负责把业务语言转换为数据库可执行结构，是系统稳定性的核心。

## 初始对象

- `table_metadata`: 表信息、主题域、业务描述。
- `column_metadata`: 字段信息、中文名、业务含义、敏感级别。
- `metric_metadata`: 指标名称、业务口径、公式、默认聚合。
- `business_terms`: 业务词典、同义词、默认口径。
- `join_relationships`: 表关联关系、join key、关系类型。
- `question_examples`: 问法样例、标准 QueryPlan、标准 SQL。

## 示例业务词

| 业务词 | 初始口径 |
| --- | --- |
| 高净值客户 | 当前资产 >= 500000 |
| 活跃客户 | 近 90 天交易次数 >= 3 |
| 沉默客户 | 近 90 天无交易 |
| 资产流入客户 | 近 90 天净流入 > 0 |
| 基金潜客 | 有可投资资产且无基金持仓 |

## 设计原则

- 不让模型凭空猜表、字段和指标。
- 所有指标必须能追溯到元数据定义。
- 所有 join 路径必须来自 `join_relationships`。
- 敏感字段默认禁止返回明细。
- 元数据可持续运营，后续支持页面化维护。

## 当前实现：结构化元数据召回

第一版已经实现 `backend/app/metadata/retriever.py`，暂不上向量数据库，先使用结构化关键词召回。

数据来源：

- `metadata.table_metadata`：召回候选业务表、视图、主题域和粒度。
- `metadata.column_metadata`：召回字段中文名、语义类型、敏感标记。
- `metadata.metric_metadata`：召回指标代码、指标名称、公式、来源表和必需过滤。
- `metadata.business_terms`：召回业务词、同义词、默认口径和是否需要澄清。
- `metadata.join_relationships`：召回可用 join 路径。
- `metadata.question_examples`：召回相似问法样例。

召回方式：

- 从用户问题和 QueryPlan 中抽取关键词、指标代码、候选表、粒度、输出字段。
- 对“当前资产、近三个月、交易次数、服务经理、基金、净流入、高净值、活跃”等常见中文业务词做别名扩展。
- 对表、字段、指标、业务词和样例做规则打分，优先 exact match，其次 contains，再其次 token overlap。
- 根据命中的指标来源表、业务词默认口径、QueryPlan 粒度扩展必要表，例如客户级指标自动补 `customer_info`，经理粒度自动补 `service_manager` 和 `service_relationship`。
- 只把命中的表、字段、指标、业务词、join 路径和样例放入 `metadata_context`，并在 `retrieval` 字段中保留命中关键词、召回置信度和证据。

接入位置：

- QueryPlanActor：生成 QueryPlan 前读取基于用户问题召回的元数据，避免编造业务口径。
- QueryPlanCritic：审核 QueryPlan 时检查 metric_code、business term、candidate_tables 是否有元数据依据。
- SQLActor：继续使用同一份 compact schema context 生成 SQL。
- SQLGuardrail：使用 `table_allowlist`、`allowed_columns_by_table`、`sensitive_columns` 做硬校验。

后续接 RAG 的升级点：

- 保留 `MetadataRetriever.retrieve(question, query_plan)` 接口不变。
- 将当前关键词打分替换或叠加为 hybrid retrieval：BM25/关键词 + 向量召回 + rerank。
- 向量库中建议放表描述、字段描述、指标口径、业务词定义、join path 描述和标准问法样例，不建议放大批明细业务数据。
- 召回结果仍需落回结构化 `metadata_context`，让 SQLGuardrail 可以继续做确定性校验。
