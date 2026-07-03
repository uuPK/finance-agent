# QueryPlan Standard v1

## 目标

QueryPlan 是自然语言问题和 SQL 之间的中间协议。它的作用不是替代 SQL，而是在 SQL 生成前把业务语义结构化，让 Actor、Critic、Guardrail、评测模块和前端展示使用同一份可检查对象。

本阶段 QueryPlan 不绑定赛事最终数据库结构。它只表达业务意图、指标、维度、筛选、时间、粒度、输出和安全约束。等赛事数据结构明确后，再由元数据层把 QueryPlan 编译为具体 SQL。

## 设计原则

1. 先表达业务语义，再映射数据库结构。
2. 所有不确定口径必须进入 `clarifications` 或 `assumptions`。
3. 指标、业务词、表、字段、join 路径都应通过 `metadata_ref` 追溯来源。
4. Critic 只判断 QueryPlan 是否覆盖用户意图，不直接改写 SQL。
5. SQLActor 只能基于通过 Critic 的 QueryPlan 生成 SQL。

## 顶层结构

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `version` | string | QueryPlan 标准版本，当前为 `1.0`。 |
| `plan_status` | enum | `draft`、`ready`、`needs_clarification`、`invalid`。 |
| `intent` | enum | 用户意图类型。 |
| `scenario` | string | 业务场景，默认 `customer_marketing`。 |
| `question` | string | 原始用户问题。 |
| `subject` | object | 查询主体，比如客户、服务经理、产品。 |
| `entities` | array | 问题中出现的业务实体。 |
| `metrics` | array | 需要计算或返回的指标。 |
| `dimensions` | array | 展示、分组、下钻或分区维度。 |
| `filters` | array | 全局筛选条件。 |
| `time_range` | object | 全局时间范围。 |
| `grain` | object | 查询粒度，比如客户级、经理级、产品级。 |
| `data_requirements` | object | 候选主题域、表、join 路径和元数据引用。 |
| `order_by` | array | 排序条件。 |
| `output` | object | 输出格式、字段、行数限制。 |
| `safety` | object | 只读、敏感字段、最大行数等安全要求。 |
| `clarifications` | array | 需要用户澄清的问题。 |
| `assumptions` | array | 系统使用的默认假设。 |
| `confidence` | number | Actor 对 QueryPlan 的信心，范围 `0` 到 `1`。 |

## Intent 枚举

| 值 | 场景 |
| --- | --- |
| `customer_segmentation` | 客群筛选。 |
| `metric_query` | 指标查询。 |
| `ranking_query` | TopN、排序、名单优先级。 |
| `trend_analysis` | 趋势分析。 |
| `detail_lookup` | 明细查询。 |
| `marketing_effect_analysis` | 营销效果分析。 |
| `metadata_question` | 询问指标口径、字段含义、表关系。 |
| `unclear` | 意图不明确。 |

## 关键子结构

### subject / entities

```json
{
  "name": "客户",
  "entity_type": "customer",
  "metadata_ref": null,
  "is_resolved": false
}
```

`entity_type` 可选值：

- `customer`
- `manager`
- `product`
- `campaign`
- `organization`
- `unknown`

### metrics

```json
{
  "name": "当前资产",
  "metric_code": "current_total_asset",
  "definition_id": "metric:current_total_asset",
  "aggregation": "latest",
  "alias": "当前资产",
  "time_window": null,
  "filters": [],
  "metadata_ref": {
    "ref_type": "metric",
    "ref_id": "metric:current_total_asset",
    "code": "current_total_asset",
    "name": "当前资产"
  },
  "is_resolved": true,
  "requires_clarification": false
}
```

指标必须尽量映射到指标库。没有指标库引用时，`requires_clarification` 或 `is_resolved=false` 必须体现出来。

### filters

```json
{
  "term": "当前资产",
  "operator": ">=",
  "value": {
    "raw": "50万",
    "normalized": 500000,
    "value_type": "number"
  },
  "field_code": null,
  "metric_code": "current_total_asset",
  "source": "user",
  "metadata_ref": null,
  "is_resolved": true,
  "requires_clarification": false
}
```

`source` 可选值：

- `user`: 用户明确提出。
- `business_term`: 由业务词展开。
- `metric_definition`: 由指标口径带出。
- `default`: 系统默认假设。
- `critic_repair`: Critic 修复建议带出。

### time_range

```json
{
  "label": "近三个月",
  "start": null,
  "end": null,
  "relative": "last_3_months",
  "granularity": "day",
  "anchor_date": null,
  "is_resolved": false
}
```

在没有系统日期或业务日历时，可以先保留 `relative`，由 SQL 编译阶段再解析为具体日期。

### grain

```json
{
  "level": "customer",
  "keys": ["customer_id"],
  "description": "客户级",
  "is_resolved": true
}
```

粒度是 Critic 的重点检查项。比如用户要客户名单，粒度通常是客户级；用户要按服务经理汇总，粒度通常是服务经理级。

### data_requirements

```json
{
  "domains": ["customer", "asset", "trade"],
  "candidate_tables": ["customer_info", "customer_asset_daily", "customer_trade"],
  "required_join_paths": ["customer_info.customer_id -> customer_trade.customer_id"],
  "required_metadata_refs": []
}
```

这些字段表达候选数据需求，不代表最终 SQL 必须逐字使用这些表。最终表名和 join 路径要由元数据层确认。

### safety

```json
{
  "readonly": true,
  "max_rows": 1000,
  "allow_sensitive_fields": false,
  "require_limit": true,
  "require_metric_definition": true
}
```

默认不允许返回敏感字段明细。需要敏感字段时必须由权限模块明确放行。

## 完整示例

用户问题：

```text
查询近三个月交易次数超过3次且当前资产大于50万的客户列表
```

QueryPlan：

```json
{
  "version": "1.0",
  "plan_status": "ready",
  "intent": "customer_segmentation",
  "scenario": "customer_marketing",
  "question": "查询近三个月交易次数超过3次且当前资产大于50万的客户列表",
  "subject": {
    "name": "客户",
    "entity_type": "customer",
    "metadata_ref": null,
    "is_resolved": true
  },
  "entities": [
    {
      "name": "客户",
      "entity_type": "customer",
      "metadata_ref": null,
      "is_resolved": true
    }
  ],
  "metrics": [
    {
      "name": "近三个月交易次数",
      "metric_code": "trade_count_3m",
      "definition_id": "metric:trade_count_3m",
      "aggregation": "count",
      "alias": "近三个月交易次数",
      "time_window": {
        "label": "近三个月",
        "start": null,
        "end": null,
        "relative": "last_3_months",
        "granularity": "day",
        "anchor_date": null,
        "is_resolved": false
      },
      "filters": [],
      "metadata_ref": null,
      "is_resolved": true,
      "requires_clarification": false
    },
    {
      "name": "当前资产",
      "metric_code": "current_total_asset",
      "definition_id": "metric:current_total_asset",
      "aggregation": "latest",
      "alias": "当前资产",
      "time_window": null,
      "filters": [],
      "metadata_ref": null,
      "is_resolved": true,
      "requires_clarification": false
    }
  ],
  "dimensions": [
    {
      "name": "客户",
      "dimension_code": "customer_id",
      "role": "display",
      "alias": "客户",
      "metadata_ref": null,
      "is_resolved": true
    }
  ],
  "filters": [
    {
      "term": "近三个月交易次数",
      "operator": ">",
      "value": {
        "raw": 3,
        "normalized": 3,
        "value_type": "number"
      },
      "field_code": null,
      "metric_code": "trade_count_3m",
      "source": "user",
      "metadata_ref": null,
      "is_resolved": true,
      "requires_clarification": false
    },
    {
      "term": "当前资产",
      "operator": ">",
      "value": {
        "raw": "50万",
        "normalized": 500000,
        "value_type": "number"
      },
      "field_code": null,
      "metric_code": "current_total_asset",
      "source": "user",
      "metadata_ref": null,
      "is_resolved": true,
      "requires_clarification": false
    }
  ],
  "time_range": {
    "label": "近三个月",
    "start": null,
    "end": null,
    "relative": "last_3_months",
    "granularity": "day",
    "anchor_date": null,
    "is_resolved": false
  },
  "grain": {
    "level": "customer",
    "keys": ["customer_id"],
    "description": "客户级",
    "is_resolved": true
  },
  "data_requirements": {
    "domains": ["customer", "asset", "trade"],
    "candidate_tables": [],
    "required_join_paths": [],
    "required_metadata_refs": []
  },
  "order_by": [],
  "output": {
    "format": "table",
    "columns": ["客户", "当前资产", "近三个月交易次数"],
    "limit": 100,
    "include_sql": true,
    "include_explanation": true
  },
  "safety": {
    "readonly": true,
    "max_rows": 1000,
    "allow_sensitive_fields": false,
    "require_limit": true,
    "require_metric_definition": true
  },
  "clarifications": [],
  "assumptions": [],
  "confidence": 0.86
}
```

## Actor 输出要求

Actor 生成 QueryPlan 时必须遵守：

1. `question` 必须保留原始问题。
2. 无法确定的指标口径不得硬猜，必须进入 `clarifications` 或 `assumptions`。
3. 若用户要求名单，`grain` 通常必须是实体级，如 `customer`。
4. 若用户要求汇总，`dimensions` 必须包含分组维度。
5. 涉及“近期”“活跃”“高净值”等词时，必须标注来源是业务词或默认假设。
6. `plan_status=ready` 只表示计划可交给 SQLActor，不表示 SQL 可执行。

## Critic 检查点

PlanCritic 至少检查：

- 意图是否匹配用户问题。
- 主体是否明确。
- 指标是否遗漏。
- 筛选条件是否遗漏。
- 时间范围是否遗漏或无法解析。
- 粒度是否与输出目标一致。
- 业务词是否展开为明确口径。
- 是否需要澄清。
- 输出行数和敏感字段策略是否合理。

Critic 输出结构建议：

```json
{
  "pass": false,
  "error_type": "missing_time_range",
  "reason": "用户要求近三个月交易次数，但 QueryPlan 没有全局或指标级时间窗口。",
  "repair_hint": "为 trade_count_3m 增加 time_window.relative=last_3_months。"
}
```

## 和后续模块的关系

- MetadataRetriever: 给 Actor 提供 `metadata_ref` 候选。
- QueryPlanActor: 生成或修复 QueryPlan。
- PlanCritic: 审 QueryPlan，不审 SQL。
- SQLActor: 只消费 `plan_status=ready` 的 QueryPlan。
- SQLGuardrail: 检查 SQL 是否符合 QueryPlan 和安全规则。
- Evaluation: 对比生成 QueryPlan 与标准 QueryPlan 的指标、维度、筛选和粒度。
