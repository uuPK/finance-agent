# Agent Generation Review Process

## 1. Purpose

This document defines the trustworthy generation process for the Finance Agent project.

The system does not directly generate and execute SQL from a user question. Instead, it follows a staged process:

```text
User question
  -> Metadata retrieval
  -> QueryPlan Actor
  -> Review 1: QueryPlan review
  -> SQL Actor
  -> Review 2: SQL review
  -> SQL execution
  -> Review 3: Result and answer review
  -> Final response
```

Each review stage combines deterministic hard checks and LLM-based semantic checks. Hard checks have veto power. If a hard check fails, the result fails even if the LLM critic thinks it is acceptable.

## 2. Review Ownership

| Stage | Hard Checks | LLM Checks | Notes |
| --- | ---: | ---: | --- |
| QueryPlan review | 40% | 60% | Structure and required fields are rule-based; intent coverage is semantic. |
| SQL review | 80% | 20% | SQL safety must be parser/rule/metadata driven. |
| Result and answer review | 55% | 45% | Execution state, row count, and sensitive fields are rule-based; answer fidelity is semantic. |
| Overall | About 60% | About 40% | Hard checks are vetoes, not weighted votes. |

These percentages describe responsibility and design emphasis. They do not mean that a high LLM score can override a failed hard check.

## 3. Prompt Example Requirement

Every LLM-powered Agent and Critic prompt must include both positive and negative examples.

Reason:

LLMs are strong imitators. Clear examples strongly improve format compliance, reasoning quality, and consistency across similar questions.

Prompt examples must include:

- At least one correct example.
- At least one incorrect example.
- A short explanation of why the positive example passes.
- A short explanation of why the negative example fails.
- The exact JSON output shape expected from the Agent or Critic.

This requirement applies to:

- QueryPlan Actor
- PlanCritic
- SQL Actor
- SQLCritic
- ResultCritic
- AnswerCritic
- Clarification Agent

## 4. Review 1: QueryPlan Review

### 4.1 Position

QueryPlan review happens before SQL generation.

```text
User question
  -> MetadataRetriever
  -> QueryPlanActor
  -> PlanCritic
```

### 4.2 Goal

Check whether the QueryPlan accurately represents the user's business intent.

This stage does not review SQL. If the QueryPlan is wrong, the SQL can be syntactically valid but still useless.

### 4.3 Inputs

- User question
- Generated QueryPlan
- Retrieved metadata
- Business terms
- Metric definitions
- Similar question examples
- Previous critic feedback, if any

### 4.4 Hard Checks, 40%

Hard checks are deterministic and should be implemented with JSON Schema, Pydantic, enums, and simple rules.

Checks:

- QueryPlan conforms to the v1 schema.
- `version` exists.
- `plan_status` is one of `draft`, `ready`, `needs_clarification`, `invalid`.
- `intent` is a known enum value.
- `subject` exists when the user requests a concrete query.
- `metrics`, `filters`, `dimensions`, `grain`, and `output` have valid types.
- `output.limit` is within the allowed range.
- If `clarifications` is not empty, `plan_status` must be `needs_clarification`.
- If an unresolved metric or business term exists, `plan_status` must not be `ready`.
- Sensitive output requests must be marked for rejection or clarification.

### 4.5 LLM Checks, 60%

PlanCritic checks semantic coverage:

- Whether the intent matches the user question.
- Whether the subject is clear.
- Whether metrics are complete.
- Whether filters are complete.
- Whether the time range is missing.
- Whether the grain matches the expected output.
- Whether business terms are expanded into concrete definitions.
- Whether assumptions are reasonable.
- Whether user clarification is required.

### 4.6 PlanCritic Prompt Template

```text
You are the QueryPlan Critic for a financial data-query agent.

Your job is to review whether the QueryPlan accurately represents the user's natural-language request.

You only review. Do not generate SQL. Do not rewrite the full QueryPlan.
Use only the user question, QueryPlan, metadata, business terms, metric definitions, and prior feedback.
If information is insufficient, do not guess. Return needs_clarification.

Check:
1. Whether intent is correct.
2. Whether subject is clear.
3. Whether metrics are complete.
4. Whether filters are complete.
5. Whether time_range or metric-level time_window is missing.
6. Whether grain matches the user's target: list, summary, trend, or detail.
7. Whether business terms have concrete definitions.
8. Whether clarification is required.

Positive example:
User: "Find customers whose current assets are above 500k and who traded more than 3 times in the last 3 months."
QueryPlan includes:
- intent=customer_segmentation
- subject=customer
- metric current_total_asset
- metric trade_count_3m
- filter current_total_asset > 500000
- filter trade_count_3m > 3
- time_window last_3_months
- grain customer
Expected review:
pass=true, because all metrics, filters, time range, and grain are covered.

Negative example:
User: "Find customers who traded more than 3 times in the last 3 months."
QueryPlan includes trade_count but no time_window and no global time_range.
Expected review:
pass=false, error_type=missing_time_range, because the phrase "last 3 months" is not represented.

Return strict JSON:
{
  "pass": boolean,
  "score": number,
  "stage": "query_plan_review",
  "error_type": string | null,
  "reason": string,
  "evidence": string[],
  "repair_hint": string | null,
  "clarification_questions": [
    {
      "field": string,
      "question": string,
      "reason": string,
      "options": string[]
    }
  ],
  "confidence": number
}
```

### 4.7 Pass Criteria

QueryPlan review passes only when:

- Hard checks pass.
- PlanCritic returns `pass=true`.
- Critic confidence is at least `0.7`.
- No mandatory clarification remains.
- `plan_status` can be promoted to `ready`.

### 4.8 Failure Output

```json
{
  "pass": false,
  "stage": "query_plan_review",
  "error_type": "missing_time_range",
  "reason": "The user asked for last-three-month trading count, but QueryPlan has no time window.",
  "evidence": ["User phrase: last 3 months", "QueryPlan.metrics.trade_count has no time_window"],
  "repair_hint": "Add time_window.relative=last_3_months to the trading-count metric.",
  "confidence": 0.91
}
```

Common error types:

- `wrong_intent`
- `missing_subject`
- `wrong_grain`
- `missing_metric`
- `wrong_metric_definition`
- `missing_filter`
- `missing_time_range`
- `ambiguous_business_term`
- `needs_clarification`
- `unsafe_output_request`

## 5. Review 2: SQL Review

### 5.1 Position

SQL review happens after SQL generation and before SQL execution.

```text
SQLActor
  -> SQLGuardrail
  -> SQLCritic
  -> SQLExecutor
```

### 5.2 Goal

Check that SQL is safe, legal, executable, and faithful to the approved QueryPlan.

This stage is mostly deterministic. LLM review is only used for QueryPlan-to-SQL semantic consistency.

### 5.3 Inputs

- User question
- Approved QueryPlan
- Generated SQL
- Table metadata
- Column metadata
- Metric metadata
- Join relationships
- Security rules

### 5.4 Hard Checks, 80%

Hard checks should be implemented with `sqlglot`, metadata lookup, database explain, and fixed rules.

Checks:

- SQL parses successfully.
- Only `SELECT` is allowed.
- Forbidden operations are blocked:
  - `INSERT`
  - `UPDATE`
  - `DELETE`
  - `DROP`
  - `ALTER`
  - `TRUNCATE`
  - `CREATE`
- Tables must exist in metadata allowlist.
- Columns must exist in metadata.
- Sensitive columns are blocked by default.
- Metric formulas must come from metadata.
- Join paths must come from metadata.
- Query must include a row limit or be constrained by `MAX_RESULT_ROWS`.
- Optional: SQL must pass `EXPLAIN`.
- Optional: SQL must satisfy timeout and scan-risk constraints.

### 5.5 LLM Checks, 20%

SQLCritic checks semantic consistency:

- SQL covers all QueryPlan metrics.
- SQL covers all QueryPlan filters.
- SQL covers QueryPlan time ranges.
- SQL aggregation matches metric definitions.
- SQL `GROUP BY` matches QueryPlan grain.
- SQL return columns match `output.columns`.

### 5.6 SQLCritic Prompt Template

```text
You are the SQL-to-QueryPlan consistency critic.

Hard security checks have already been performed by code.
You cannot override failed hard checks.
Your only job is to judge whether the SQL faithfully implements the approved QueryPlan.

Do not generate a new full SQL query.
Only identify problems and give repair hints.

Check:
1. Whether SQL covers QueryPlan metrics.
2. Whether SQL covers QueryPlan filters.
3. Whether SQL covers QueryPlan time_range and metric time_window.
4. Whether SQL group by matches QueryPlan grain.
5. Whether SQL selected columns match output.columns.
6. Whether metric aggregation matches metric definitions.

Positive example:
QueryPlan requires:
- customer-level output
- current_total_asset > 500000
- trade_count_3m > 3
- last_3_months trade window
SQL selects customer_id, latest asset, count(trade_id), filters assets > 500000, filters trade_date >= current_date - interval '3 months', groups by customer_id.
Expected review:
pass=true, because SQL implements the metrics, filters, time window, and customer grain.

Negative example:
QueryPlan requires trade_count_3m > 3.
SQL counts all historical trades without a trade_date filter.
Expected review:
pass=false, error_type=missing_time_filter.

Return strict JSON:
{
  "pass": boolean,
  "score": number,
  "stage": "sql_review",
  "error_type": string | null,
  "reason": string,
  "evidence": string[],
  "repair_hint": string | null,
  "confidence": number
}
```

### 5.7 Pass Criteria

SQL review passes only when:

- All hard SQL checks pass.
- SQLCritic returns `pass=true`.
- Critic confidence is at least `0.7`.
- SQL is approved for execution.

### 5.8 Failure Output

```json
{
  "pass": false,
  "stage": "sql_review",
  "error_type": "missing_filter",
  "reason": "QueryPlan requires current assets above 500k, but SQL has no corresponding filter.",
  "evidence": ["QueryPlan filter: current_total_asset > 500000", "SQL WHERE clause does not contain asset filter"],
  "repair_hint": "Add the current asset filter according to the metric definition.",
  "confidence": 0.88
}
```

Common error types:

- `invalid_sql`
- `unsafe_sql`
- `unknown_table`
- `unknown_column`
- `sensitive_column`
- `wrong_metric_formula`
- `missing_join_path`
- `wrong_join`
- `missing_time_filter`
- `missing_filter`
- `wrong_group_by`
- `missing_limit`
- `performance_risk`

## 6. Review 3: Result and Answer Review

### 6.1 Position

Result and answer review happens after SQL execution and before the final response.

```text
SQLExecutor
  -> ResultHardValidator
  -> ResultCritic
  -> AnswerCritic
  -> FinalResponder
```

当前实现已经接入 ResultHardValidator 和 ResultCritic。AnswerCritic 与更完整的自然语言最终回答仍属于后续阶段。

### 6.2 Goal

Check that the execution result satisfies the QueryPlan and that the final natural-language answer is faithful to the data.

This stage does not prove business truth in an absolute sense. It checks reasonableness, consistency, and explainability based on the available result.

### 6.3 Inputs

- User question
- QueryPlan
- SQL
- SQL execution status
- Result columns
- Row count
- Summary statistics
- Desensitized sample rows
- Draft final answer
- Expected answer, if in evaluation mode

### 6.4 Hard Checks, 55%

Checks:

- SQL execution succeeded.
- SQL did not time out.
- Result columns are present.
- Row count respects `limit` and `MAX_RESULT_ROWS`.
- TopN row count is correct when applicable.
- Numeric values are not obviously invalid, such as negative trade counts.
- Sensitive fields are not returned or exposed.
- In evaluation mode, expected result checks pass.

### 6.5 LLM Checks, 45%

ResultCritic and AnswerCritic check:

- Result satisfies the user question.
- Empty result is plausible or requires a user-facing note.
- Result grain matches QueryPlan.
- Final answer is supported by returned fields and summaries.
- Final answer does not invent causes, numbers, or marketing suggestions.
- Final answer does not leak sensitive information.

### 6.6 ResultCritic Prompt Template

```text
You are the result and answer trustworthiness critic.

Judge whether SQL execution results and the draft answer satisfy the user question and QueryPlan.

Use only the provided column names, row count, summary statistics, desensitized sample rows, SQL, and QueryPlan.
Do not invent business causes.
Do not use facts that are not present in the result.
If the result cannot support the answer, fail the review.

Check:
1. Whether the result satisfies the user question.
2. Whether returned columns are complete.
3. Whether result grain is correct.
4. Whether row count matches output requirements.
5. Whether the answer is faithful to the result.
6. Whether sensitive data is exposed.
7. Whether an empty result should trigger condition-adjustment guidance.

Positive example:
User asks for a customer list.
QueryPlan grain is customer.
Result contains customer_id, current_total_asset, trade_count_3m with 80 rows.
Draft answer says "80 customers match the conditions" and lists the same fields.
Expected review:
pass=true, because answer and data are consistent.

Negative example:
User asks for a customer list.
Result contains only total_count=80.
Draft answer says "Here is the customer list."
Expected review:
pass=false, error_type=wrong_result_grain.

Return strict JSON:
{
  "pass": boolean,
  "score": number,
  "stage": "result_review",
  "error_type": string | null,
  "reason": string,
  "evidence": string[],
  "repair_hint": string | null,
  "user_message": string | null,
  "confidence": number
}
```

### 6.7 Pass Criteria

Result review passes only when:

- Hard result checks pass.
- ResultCritic returns `pass=true`.
- AnswerCritic returns `pass=true`, if separate.
- Critic confidence is at least `0.7`.
- No sensitive data is exposed.

### 6.8 Failure Output

```json
{
  "pass": false,
  "stage": "result_review",
  "error_type": "wrong_result_grain",
  "reason": "The user asked for a customer list, but the result only contains an aggregate count.",
  "evidence": ["QueryPlan grain: customer", "Result columns: total_count"],
  "repair_hint": "Regenerate SQL to return customer-level rows with the required metrics.",
  "user_message": "当前查询只得到汇总数量，尚未得到客户明细列表。",
  "confidence": 0.9
}
```

Common error types:

- `execution_error`
- `empty_result_unexpected`
- `wrong_result_columns`
- `wrong_result_grain`
- `wrong_row_count`
- `metric_value_anomaly`
- `filter_not_satisfied`
- `answer_data_mismatch`
- `sensitive_data_leak`
- `evaluation_mismatch`

## 7. Unclear User Requirements

If the user's request is unclear, the system must not force SQL generation.

### 7.1 Trigger Conditions

Clarification is required when:

- Metric definition is unclear, such as "high-value customers" or "active customers".
- Time range is unclear, such as "recently" or "good recent performance".
- Output target is unclear: list, count, summary, trend, or detail.
- Subject is unclear: customer, product, manager, or campaign.
- Conditions conflict, such as "no fund holding" and "fund holding amount > 0".
- User asks for sensitive fields, such as phone number, ID number, full name, or contact details.
- Required business term is absent from metadata and cannot be safely assumed.

### 7.2 Review Behavior

When clarification is required:

- QueryPlan review returns `pass=false`.
- `plan_status` becomes `needs_clarification`.
- SQL generation is skipped.
- The response returns one or more clarification questions.
- The frontend displays clarification questions instead of SQL.

### 7.3 Clarification Response

```json
{
  "plan_status": "needs_clarification",
  "answer": "当前问题需要进一步明确后才能生成可靠查询。",
  "clarifications": [
    {
      "field": "active_customer",
      "question": "你希望如何定义活跃客户？",
      "reason": "不同活跃口径会影响筛选结果。",
      "options": [
        "近30天交易次数 >= 3",
        "近90天交易次数 >= 3",
        "近90天交易金额 >= 10000"
      ]
    }
  ]
}
```

### 7.4 Clarification Agent Prompt Template

```text
You are the clarification agent for a financial data-query system.

Your job is to ask the minimum necessary clarification questions before SQL generation.
Do not ask questions that can be answered from metadata or safe defaults.
Do not ask more than 3 questions at once.
Each question must explain why clarification matters.

Positive example:
User: "Find active customers."
Metadata has multiple active-customer definitions.
Expected output:
Ask the user to choose one active-customer definition.

Negative example:
User: "Find customers whose current assets are above 500k."
The metric current_total_asset exists in metadata.
Expected output:
Do not ask clarification; proceed with QueryPlan generation.

Return strict JSON:
{
  "needs_clarification": boolean,
  "questions": [
    {
      "field": string,
      "question": string,
      "reason": string,
      "options": string[]
    }
  ]
}
```

## 8. Repair Strategy

### 8.1 Fallback Targets

| Failed Stage | Fallback Target |
| --- | --- |
| QueryPlan review | QueryPlan Actor |
| SQL review | SQL Actor |
| Result review, SQL issue | SQL Actor |
| Result review, semantic issue | QueryPlan Actor |
| Required clarification | User clarification |

### 8.2 Max Retry

Default:

```text
max_retry = 2
```

After max retries:

- If the problem is ambiguous terminology, return clarification questions.
- If SQL repeatedly fails, return failure reason and mark for human review.
- If the result is unexpectedly empty, explain that the conditions may be too strict or data may be unavailable.

## 9. Ensuring Critic Correctness

Critic correctness is improved by combining hard checks, structured outputs, examples, and continuous evaluation.

### 9.1 Hard Checks First

Any hard-check failure is a veto. The LLM critic cannot override it.

### 9.2 Structured Output Validation

Critic output must be strict JSON and must pass Pydantic validation.

If output is invalid:

- Retry formatting once.
- If still invalid, mark the critic review as failed.

### 9.3 Evidence Requirement

Critic must provide `evidence`.

Evidence must refer to one of:

- User question
- QueryPlan field
- SQL clause
- Metadata definition
- Result column
- Result summary

### 9.4 Confidence Threshold

If `confidence < 0.7`, the review does not auto-pass.

Low confidence triggers:

- repair,
- clarification,
- or human review, depending on the stage.

### 9.5 Actor-Critic Separation

Actor generates.

Critic reviews.

Critic does not directly rewrite final SQL or final answer. It returns error type, reason, evidence, and repair hint.

### 9.6 Positive and Negative Examples

Every prompt must include positive and negative examples. The examples should be close to customer-marketing data-query scenarios.

This reduces:

- Schema drift
- Over-approval
- Missing time ranges
- Missing filters
- Unsupported answer claims

### 9.7 Evaluation Set Calibration

Use evaluation cases to measure critic quality:

- False pass rate
- False block rate
- Clarification trigger accuracy
- Repair success rate
- Agreement with human review

### 9.8 Dual Critic for Complex Queries

For complex queries, enable two critics:

- Business semantic critic
- SQL/result consistency critic

The query proceeds only if both pass, or if hard checks plus configured manual override allow continuation.

### 9.9 Audit Logs

Save each review's:

- Input
- Output
- Error type
- Evidence
- Repair hint
- Confidence
- Final decision

Audit logs are required for debugging, evaluation, and demo explanation.

## 10. Final Response Content

Final user-facing response should include:

- Natural-language answer
- Result table or summary
- Clarification questions, if needed
- Assumptions used
- Metric definitions used

Debug mode may additionally show:

- QueryPlan
- SQL
- Three review results
- Repair count
- Guardrail details

## 11. Implementation Order

Development should proceed in this order:

1. QueryPlan Actor
2. QueryPlan hard checks
3. PlanCritic with positive and negative examples
4. SQL Actor
5. SQL hard Guardrail
6. SQLCritic with positive and negative examples
7. SQL executor
8. ResultCritic and AnswerCritic with positive and negative examples
9. Clarification Agent
10. Evaluation runner
11. Frontend review-process display
