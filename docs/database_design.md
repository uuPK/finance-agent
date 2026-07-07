# 数据库设计方案

## 1. 目标与范围

本方案用于支撑“Agentic 智能问数在客户营销场景的应用”的核心查询闭环：

```text
自然语言问题 -> QueryPlan -> SQL 生成与审核 -> PostgreSQL 执行 -> 结果校验 -> 最终回答
```

当前阶段重点放在业务查询层，也就是 SQL 实际查询的数据结构。元数据召回、RAG、正式赛事数据导入可以后续接入，但数据库设计需要提前保留接口。

设计目标：

- 支持客户营销场景下的客户筛选、指标查询、排名、趋势分析、明细查询。
- 支持单表单指标、多表单指标、多表多指标、跨主题域查询。
- 支持执行后结果校验，包括字段、行数、粒度、敏感字段、空结果、业务条件一致性。
- 支持完整日志存储，便于后续 debug、评测、失败样本沉淀和 prompt 迭代。
- 使用可替换的业务数据层，后续赛事正式表结构到来后尽量少改 Agent 主流程。

## 2. Schema 分层

建议在同一个 PostgreSQL 数据库中划分 4 个 schema。

| schema | 作用 | 当前优先级 |
| --- | --- | --- |
| `mart` | 业务查询层，存放客户、经理、产品、资产、持仓、交易、流入流出等数据 | 最高 |
| `metadata` | AI 友好元数据层，存放表、字段、指标、业务词、join 路径、样例 | 高 |
| `agent` | Agent 运行日志层，存放 QueryPlan、SQL、审核、执行、结果校验日志 | 高 |
| `evaluation` | 离线评测层，存放标准问答对、预期结果、评测批次和评分 | 中 |

当前先实现 `mart` 和 `agent` 的核心结构；`metadata` 已有初始 SQLAlchemy 模型，后续配合 RAG 继续增强。

当前落库脚本位于 `backend/db/schema.sql`。为了复用早期已经建立的 SQL 骨架，物理表名采用更短的业务命名，例如 `mart.customer_info`、`mart.customer_asset_daily`、`mart.customer_trade`。本文档中的 `dim_`、`fact_` 命名可理解为建模角色说明，不强制作为物理表名。

## 3. 业务查询层设计

赛题数据集描述中明确提到：客户信息表、服务经理信息表、产品信息表、服务关系表、公共维表、客户持仓表、客户资产表、客户交易表、客户资产流入流出表。下面的 `mart` 结构按这些表域设计。

### 3.1 客户信息表：`mart.customer_info`

客户维表，用于客户画像、分群、明细查询。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `customer_id` | uuid primary key | 脱敏客户主键 |
| `customer_no` | varchar(64) | 脱敏客户编号 |
| `customer_name_masked` | varchar(128) | 脱敏客户名称，用于演示，不存真实姓名 |
| `gender` | varchar(16) | 性别代码 |
| `birth_date` | date | 出生日期 |
| `age_band` | varchar(32) | 年龄段 |
| `customer_level` | varchar(32) | 客户等级 |
| `risk_level` | varchar(32) | 风险等级 |
| `open_date` | date | 开户日期 |
| `branch_code` | varchar(64) | 分支机构代码 |
| `customer_status` | varchar(32) | 客户状态 |
| `created_at` | timestamptz | 创建时间 |
| `updated_at` | timestamptz | 更新时间 |

常见查询：

- 高净值客户筛选。
- 某地区、某等级、某年龄段客户数量。
- 客户基础画像与资产、交易指标联查。

### 3.2 服务经理信息表：`mart.service_manager`

服务经理维表，用于按经理、团队、机构汇总客户和资产。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `manager_id` | uuid primary key | 服务经理主键 |
| `manager_no` | varchar(64) | 服务经理编号 |
| `manager_name_masked` | varchar(128) | 脱敏经理名称 |
| `org_code` | varchar(64) | 所属机构编号 |
| `branch_code` | varchar(64) | 分支机构编号 |
| `manager_status` | varchar(32) | 在职、离职、停用等 |
| `created_at` | timestamptz | 创建时间 |
| `updated_at` | timestamptz | 更新时间 |

常见查询：

- 各服务经理名下客户数。
- 各服务经理名下总资产、净流入、交易活跃度排名。
- 按机构、团队汇总营销客群。

### 3.3 产品信息表：`mart.product_info`

产品维表，用于持仓、交易、产品偏好分析。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `product_id` | uuid primary key | 产品主键 |
| `product_code` | varchar(64) | 产品编号 |
| `product_name` | varchar(256) | 产品名称 |
| `product_type` | varchar(64) | 基金、股票、债券、理财等 |
| `risk_level` | varchar(32) | 产品风险等级 |
| `issuer` | varchar(128) | 发行方 |
| `product_status` | varchar(32) | 在售、停售、到期等 |
| `created_at` | timestamptz | 创建时间 |
| `updated_at` | timestamptz | 更新时间 |

常见查询：

- 某类产品持仓客户。
- 某类产品交易金额。
- 识别基金潜客、债券潜客、理财潜客。

### 3.4 服务关系表：`mart.service_relationship`

客户与服务经理的关系表，支持当前归属和历史归属。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `relationship_id` | uuid primary key | 关系编号 |
| `customer_id` | uuid | 客户主键 |
| `manager_id` | uuid | 服务经理主键 |
| `relationship_type` | varchar(32) | 主服务、协同服务等 |
| `start_date` | date | 关系开始日期 |
| `end_date` | date | 关系结束日期，当前关系为空 |
| `is_primary` | boolean | 是否主服务关系 |
| `created_at` | timestamptz | 创建时间 |
| `updated_at` | timestamptz | 更新时间 |

常见查询：

- 当前经理名下客户。
- 经理维度资产汇总。
- 历史客户迁移或服务关系变化分析。

### 3.5 公共维表：`mart.public_dimension`

统一维护枚举代码，避免在 prompt 和 SQL 中硬编码中文枚举。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `dimension_id` | uuid primary key | 维度记录主键 |
| `dimension_type` | varchar(64) | 代码类型，如 gender、risk_level、customer_level |
| `dimension_code` | varchar(64) | 代码值 |
| `dimension_name` | varchar(128) | 中文展示名 |
| `parent_code` | varchar(64) | 上级代码 |
| `sort_order` | integer | 排序 |
| `is_active` | boolean | 是否启用 |

建议 `(dimension_type, dimension_code)` 建唯一约束。

### 3.6 客户资产日表：`mart.customer_asset_daily`

客户资产事实表，客户-日期粒度，是营销筛选中最核心的指标来源。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `asset_snapshot_id` | uuid primary key | 资产快照编号 |
| `customer_id` | uuid | 客户主键 |
| `as_of_date` | date | 统计日期 |
| `total_asset` | numeric(20, 2) | 总资产 |
| `cash_asset` | numeric(20, 2) | 现金资产 |
| `security_market_value` | numeric(20, 2) | 证券市值 |
| `fund_market_value` | numeric(20, 2) | 基金市值 |
| `product_market_value` | numeric(20, 2) | 产品市值 |
| `net_asset` | numeric(20, 2) | 净资产 |
| `asset_level` | varchar(32) | 资产等级 |
| `created_at` | timestamptz | 创建时间 |
| `updated_at` | timestamptz | 更新时间 |

建议唯一约束：`(customer_id, as_of_date)`。

常见指标：

- 当前资产：最近统计日 `total_asset`。
- 高净值客户：当前资产大于等于指定阈值。
- 资产趋势：按日、月统计资产变化。
- 客户资产结构：现金、基金、股票、债券、理财占比。

### 3.7 客户持仓日表：`mart.customer_position_daily`

客户-产品-日期粒度，用于产品持仓与潜客识别。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `position_snapshot_id` | uuid primary key | 持仓快照编号 |
| `customer_id` | uuid | 客户主键 |
| `product_id` | uuid | 产品主键 |
| `as_of_date` | date | 统计日期 |
| `position_quantity` | numeric(20, 4) | 持仓数量 |
| `market_value` | numeric(20, 2) | 市值 |
| `cost_amount` | numeric(20, 2) | 成本金额 |
| `unrealized_profit_loss` | numeric(20, 2) | 未实现盈亏 |
| `holding_days` | integer | 持仓天数 |
| `created_at` | timestamptz | 创建时间 |
| `updated_at` | timestamptz | 更新时间 |

建议唯一约束：`(customer_id, product_id, as_of_date)`。

常见查询：

- 持有某类产品的客户。
- 未持有基金但有可用资金的基金潜客。
- 产品持仓规模排名。

### 3.8 客户交易表：`mart.customer_trade`

交易流水表，用于活跃度、偏好、交易金额、交易次数等分析。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `trade_id` | uuid primary key | 交易编号 |
| `customer_id` | uuid | 客户主键 |
| `product_id` | uuid | 产品主键 |
| `trade_date` | date | 交易日期 |
| `trade_time` | time | 交易时间 |
| `trade_type` | varchar(32) | 买入、卖出、申购、赎回等 |
| `market` | varchar(32) | 市场 |
| `security_code` | varchar(64) | 证券或产品代码 |
| `trade_amount` | numeric(20, 2) | 交易金额 |
| `trade_quantity` | numeric(20, 4) | 交易数量 |
| `fee_amount` | numeric(20, 2) | 手续费 |
| `realized_profit_loss` | numeric(20, 2) | 已实现盈亏 |
| `channel` | varchar(64) | APP、柜台、电话等 |
| `created_at` | timestamptz | 创建时间 |

常见指标：

- 近 90 天交易次数。
- 近 30 天交易金额。
- 活跃客户：近 N 天交易次数大于等于阈值。
- 沉默客户：近 N 天无交易。

### 3.9 客户资产流入流出表：`mart.customer_asset_flow`

客户-日期粒度，用于净流入、流失预警、营销效果分析。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `flow_id` | uuid primary key | 资金流水编号 |
| `customer_id` | uuid | 客户主键 |
| `product_id` | uuid | 产品主键，可为空 |
| `occur_date` | date | 发生日期 |
| `flow_type` | varchar(32) | 银证转入、银证转出、产品赎回等 |
| `amount` | numeric(20, 2) | 发生金额 |
| `channel` | varchar(64) | 渠道 |
| `remark` | varchar(256) | 备注 |
| `created_at` | timestamptz | 创建时间 |

常见指标：

- 近 90 天净流入。
- 近 30 天大额流出客户。
- 资产流入客户：净流入大于 0。

### 3.10 可选营销扩展表

赛题数据集没有明确列出营销活动表，但业务场景中提到“基于营销效果快速调整营销策略”。为了演示营销闭环，可以后续增加两张可选表：

- `mart.marketing_campaign`：营销活动。
- `mart.marketing_touch`：客户触达、响应、转化记录。

这两张表不作为第一阶段必须实现项，避免偏离赛题给定数据集。

## 4. 测试数据构造方案

在正式赛事脱敏数据到来前，先构造一批可重复生成的模拟数据，用于测试 SQL 生成、执行、结果校验和评测。

建议使用固定随机种子生成，保证每次本地、CI、多人协同环境得到同样的数据。

### 4.1 初始数据规模

| 表 | 建议规模 |
| --- | --- |
| `mart.customer_info` | 500 个客户 |
| `mart.service_manager` | 约 30 个服务经理 |
| `mart.product_info` | 约 80 个产品 |
| `mart.service_relationship` | 约 550 条关系，包含少量历史关系 |
| `mart.public_dimension` | 约 30 到 80 条枚举 |
| `mart.customer_asset_daily` | 近 180 天，每天约 500 条，约 90,000 条 |
| `mart.customer_position_daily` | 近 180 天，每 7 天生成快照，约 30,000 到 60,000 条 |
| `mart.customer_trade` | 约 10,000 到 25,000 条交易流水 |
| `mart.customer_asset_flow` | 约 12,000 到 30,000 条流水 |

这个规模足够测试复杂查询、join、聚合、日期过滤和性能，但仍然适合本地 Docker PostgreSQL。

### 4.2 数据分布建议

为了让测试问题有稳定答案，模拟数据不要完全随机，需要构造业务分布：

- 客户等级：普通客户、潜力客户、金卡客户、白金客户、私行客户。
- 资产分布：长尾分布，少量高净值客户，大量普通客户。
- 年龄段：20-30、31-40、41-50、51-60、60+。
- 风险等级：保守、稳健、平衡、积极、进取。
- 产品类型：基金、股票、债券、理财、现金管理。
- 交易行为：部分客户高频交易，部分客户沉默。
- 流入流出：部分客户持续净流入，部分客户近期大额流出。

需要刻意生成几类可验证客群：

- 高净值客户：当前资产 `>= 500000`。
- 活跃客户：近 90 天交易次数 `>= 3`。
- 沉默客户：近 90 天无交易。
- 资产流入客户：近 90 天净流入 `> 0`。
- 基金潜客：有可用资金且当前无基金持仓。
- 大额流失风险客户：近 30 天净流入 `< -100000`。

当前 seed 脚本为 `backend/db/seed_synthetic_data.py`，默认参数：

```bash
cd backend
python db/seed_synthetic_data.py --reset --customers 500 --days 180
```

`--reset` 会清空 synthetic `mart` 和 `metadata` 数据后重新生成，适合本地开发环境。后续接入赛事正式脱敏数据后，不应再对正式库使用 `--reset`。

### 4.3 测试数据安全原则

- 不使用真实客户姓名、手机号、证件号、银行卡号。
- 客户名称使用 `客户000001` 这类脱敏名称。
- 经理名称使用 `经理001` 这类脱敏名称。
- 不生成任何可识别个人身份的信息。
- 如果后续引入手机号、邮箱字段，只能使用明显虚构值，并默认标记为敏感字段，禁止明细返回。

## 5. 业务层索引与性能建议

因为赛题要求分钟级返回，而不是毫秒级，所以第一阶段不需要过度优化，但要保证常见查询不会明显卡住。

建议索引：

| 表 | 索引 |
| --- | --- |
| `customer_info` | `customer_id`、`customer_level`、`risk_level`、`branch_code` |
| `service_manager` | `manager_id`、`org_code`、`branch_code` |
| `service_relationship` | `customer_id`、`manager_id`、`is_primary` |
| `product_info` | `product_id`、`product_type` |
| `customer_asset_daily` | `(as_of_date, customer_id)`、`customer_id`、`as_of_date` |
| `customer_position_daily` | `(as_of_date, customer_id)`、`product_id`、`customer_id` |
| `customer_trade` | `trade_date`、`customer_id`、`product_id`、`trade_type` |
| `customer_asset_flow` | `occur_date`、`customer_id`、`flow_type` |

如果数据量继续增加，可以再做：

- 按日期对事实表分区。
- 建近 30 天、近 90 天客户特征快照表。
- 给常用指标做物化视图，例如当前资产、近 90 天交易次数、近 90 天净流入。

第一阶段建议先不做复杂分区，避免迁移和 seed 复杂度过高。

## 6. Agent 日志存储设计

日志不是简单打印文本，而是要能支撑 debug、可视化、评测、失败归因和 prompt 迭代。

### 6.1 查询主日志：`agent.query_runs`

每次用户问题对应一条主记录。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `query_id` | uuid primary key | 查询运行 ID |
| `user_id` | varchar(128) | 用户 ID，可为空 |
| `question` | text | 用户原始问题 |
| `status` | varchar(32) | completed、failed、needs_clarification 等 |
| `final_answer` | text | 最终回答 |
| `final_sql` | text | 最终执行 SQL |
| `retry_count` | integer | 总修复次数 |
| `elapsed_ms` | integer | 总耗时 |
| `error_type` | varchar(64) | 失败类型 |
| `error_message` | text | 失败信息 |
| `created_at` | timestamptz | 创建时间 |
| `updated_at` | timestamptz | 更新时间 |

### 6.2 阶段日志：`agent.stage_logs`

记录 QueryPlan、SQL、Result 等阶段的输入输出。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `stage_log_id` | uuid primary key | 阶段日志 ID |
| `query_id` | uuid | 查询运行 ID |
| `stage_name` | varchar(64) | query_plan_actor、plan_critic、sql_actor、sql_guardrail、sql_critic、sql_executor、result_validator 等 |
| `attempt` | integer | 第几次尝试 |
| `stage_status` | varchar(32) | passed、failed、skipped |
| `input_payload` | jsonb | 阶段输入 |
| `output_payload` | jsonb | 阶段输出 |
| `error_type` | varchar(64) | 错误类型 |
| `error_message` | text | 错误信息 |
| `elapsed_ms` | integer | 阶段耗时 |
| `created_at` | timestamptz | 创建时间 |

### 6.3 LLM 调用日志：`agent.llm_call_logs`

记录模型调用，但不能记录 API Key。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `llm_call_id` | uuid primary key | LLM 调用 ID |
| `query_id` | uuid | 查询运行 ID |
| `stage_name` | varchar(64) | 所属阶段 |
| `provider` | varchar(32) | deepseek、openai 等 |
| `model` | varchar(64) | 模型名称 |
| `prompt_version` | varchar(64) | prompt 版本 |
| `system_prompt` | text | 系统提示词，可按环境决定是否保存全文 |
| `user_prompt` | text | 用户提示词，可按环境决定是否保存全文 |
| `response_text` | text | 模型原始响应 |
| `parsed_payload` | jsonb | 解析后的 JSON |
| `token_usage` | jsonb | token 用量 |
| `elapsed_ms` | integer | 调用耗时 |
| `error_message` | text | 错误信息 |
| `created_at` | timestamptz | 创建时间 |

注意：

- 不允许存储 API Key。
- 如果后续接真实业务数据，prompt 日志需要脱敏或只保存 hash。
- 本地开发环境可以保存完整 prompt，生产或演示环境建议增加 `LOG_PROMPT_BODY=false` 配置。

### 6.4 SQL 执行日志：`agent.sql_execution_logs`

记录 SQL 是否真正执行成功。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `execution_id` | uuid primary key | 执行 ID |
| `query_id` | uuid | 查询运行 ID |
| `attempt` | integer | 第几次 SQL 尝试 |
| `sql_text` | text | SQL |
| `execution_status` | varchar(32) | success、failed、timeout |
| `row_count` | integer | 返回行数 |
| `result_schema` | jsonb | 返回字段结构 |
| `result_preview` | jsonb | 结果预览，限制行数 |
| `elapsed_ms` | integer | 执行耗时 |
| `error_message` | text | 执行错误 |
| `created_at` | timestamptz | 创建时间 |

### 6.5 结果校验日志：`agent.result_validation_logs`

记录执行后再次校验的结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `validation_id` | uuid primary key | 校验 ID |
| `query_id` | uuid | 查询运行 ID |
| `execution_id` | uuid | SQL 执行 ID |
| `hard_checks` | jsonb | 硬规则校验详情 |
| `critic_review` | jsonb | LLM ResultCritic 审核结果 |
| `passed` | boolean | 是否通过 |
| `score` | numeric(5, 2) | 评分 |
| `error_type` | varchar(64) | 错误类型 |
| `repair_hint` | text | 修复建议 |
| `created_at` | timestamptz | 创建时间 |

## 7. 执行后结果校验规则

SQL 执行后先做硬规则校验，再做 LLM ResultCritic。硬规则拥有否决权。

### 7.1 硬规则校验

- SQL 必须执行成功。
- SQL 执行耗时不能超过配置值。
- 返回行数不能超过 `max_result_rows`。
- API 返回给前端的 `result_preview` 还需要受 `result_preview_rows` 二次限制，避免大结果集进入响应体或 LLM 上下文。
- 返回字段必须覆盖 QueryPlan 的 `output.columns`。
- 不能返回敏感字段。
- 返回粒度必须符合 QueryPlan，例如客户明细、经理汇总、产品汇总不能混淆。
- 有时间范围的问题，结果必须体现时间过滤。
- 有排序要求的问题，结果需要符合排序方向。
- 空结果需要判断是否可接受，不可接受时触发修复。

### 7.2 LLM ResultCritic

LLM ResultCritic 主要判断语义一致性：

- 结果是否回答了用户问题。
- 指标含义是否符合业务口径。
- 维度和筛选条件是否遗漏。
- 结果解释是否夸大或编造。

LLM 只能给出评分和修复建议，不能绕过硬规则。

## 8. RAG 接入建议

后续 RAG 不建议直接从业务数据表里召回，而应该优先召回“元数据和业务知识”。业务数据用于 SQL 执行，RAG 用于帮助模型理解 schema、指标、口径、join 路径和样例。

### 8.1 可召回内容

建议把以下内容做成 RAG 文档单元：

- 表卡片：表名、中文名、主题域、粒度、业务描述、适用场景。
- 字段卡片：字段名、中文名、类型、含义、是否敏感、常见过滤方式。
- 指标卡片：指标名、公式、默认聚合、时间口径、来源表、必需过滤条件。
- 业务词卡片：高净值客户、活跃客户、沉默客户、基金潜客等业务定义。
- Join 路径卡片：哪些表可以 join，join key 是什么，关系类型是什么。
- 问答样例卡片：用户问题、标准 QueryPlan、标准 SQL、预期结果说明。
- 失败案例卡片：历史错误 SQL、错误原因、修复建议。

### 8.2 召回方式

第一阶段可以不用复杂向量数据库，先做数据库内结构化召回：

- 根据用户问题提取关键词。
- 查 `metadata.table_metadata`、`column_metadata`、`metric_metadata`、`business_terms`。
- 按主题域、别名、指标名、业务词做精确或模糊匹配。

第二阶段再接混合召回：

- 结构化过滤：场景、主题域、表名、指标名、是否敏感。
- 向量召回：召回业务描述、指标口径、问答样例。
- 关键词召回：用于精确匹配字段名、指标名、枚举值。
- 重排：优先保留指标定义、join 路径、同主题域表。

如果希望少引入组件，可以直接使用 PostgreSQL + `pgvector`；如果后续数据规模更大，再考虑独立向量库。

### 8.3 RAG 与 Guardrail 的关系

RAG 只提供上下文，不能作为最终可信来源。最终可信来源必须是结构化元数据表和硬规则校验。

推荐原则：

- LLM 不能使用未召回、未注册的表。
- LLM 不能使用未注册的字段。
- LLM 不能自行编造指标公式。
- Join 路径必须来自 `metadata.join_relationships`。
- 敏感字段策略必须来自 `metadata.column_metadata` 或 `metadata.rule_constraints`。

### 8.4 面向 prompt 的上下文控制

每次 SQL 生成不应该塞入全量 schema，而是只塞入和当前 QueryPlan 相关的上下文：

- 候选表 Top 5 到 Top 8。
- 候选指标 Top 5。
- 候选字段按表组织，每表保留核心字段。
- 必需 join 路径。
- 1 到 3 个相似问答样例。
- 明确禁止项，例如敏感字段、不可用表、不可用指标。

这样可以减少 token、降低幻觉，并保障分钟级返回。

## 9. 后续实施步骤

建议按下面顺序推进：

1. 已应用 `backend/db/schema.sql`，创建 `mart`、`metadata`、`agent`、`evaluation` schema。
2. 已运行 `backend/db/seed_synthetic_data.py`，生成 500 客户 synthetic 测试数据。
3. 已编写只读 SQL Executor，限制超时、行数和语句类型。
4. 已接入 SQL 执行日志和结果校验日志；阶段日志可在后续细化为全量落库。
5. 已实现 ResultHardValidator，并将结果校验失败反馈回 SQL Actor 修复循环。
6. 下一步接入 LLM ResultCritic，补充结果语义审核。
7. 后续接入分页/异步导出，支持大结果集的受控查看。
8. 后续接入 metadata retriever 和 RAG。

第一阶段完成后，系统就可以走通：

```text
QueryPlan -> SQL -> 审核 -> 执行 PostgreSQL -> 结果硬校验 -> 日志记录
```

第二阶段再走通：

```text
元数据召回/RAG -> 更准确的 QueryPlan 和 SQL -> ResultCritic 自动修复
```
