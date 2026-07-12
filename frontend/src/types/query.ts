export interface QueryRequest {
  question: string;
  user_id?: string;
  include_debug?: boolean;
}

export interface QueryMetric {
  name: string;
  metric_code?: string;
  definition_id?: string;
  aggregation?: string;
  alias?: string;
  time_window?: QueryPlan["time_range"];
  filters: QueryFilter[];
  is_resolved?: boolean;
  requires_clarification?: boolean;
}

export interface QueryFilter {
  term: string;
  operator: string;
  value: {
    raw: unknown;
    normalized?: unknown;
    value_type: string;
  };
  field_code?: string;
  metric_code?: string;
  source?: string;
  is_resolved?: boolean;
  requires_clarification?: boolean;
}

export interface QueryPlan {
  version: string;
  plan_status: "draft" | "ready" | "needs_clarification" | "invalid";
  intent: string;
  scenario: string;
  question?: string;
  subject?: {
    name: string;
    entity_type: string;
    is_resolved?: boolean;
  };
  entities: Array<{
    name: string;
    entity_type: string;
    is_resolved?: boolean;
  }>;
  metrics: QueryMetric[];
  dimensions: Array<{
    name: string;
    dimension_code?: string;
    role: string;
    alias?: string;
    is_resolved?: boolean;
  }>;
  filters: QueryFilter[];
  time_range?: {
    label?: string;
    start?: string;
    end?: string;
    relative?: string;
    granularity: string;
    anchor_date?: string;
    is_resolved?: boolean;
  };
  grain?: {
    level: string;
    keys: string[];
    description?: string;
    is_resolved?: boolean;
  };
  data_requirements: {
    domains: string[];
    candidate_tables: string[];
    required_join_paths: string[];
  };
  order_by: Array<{
    term: string;
    direction: "asc" | "desc";
    metric_code?: string;
    field_code?: string;
  }>;
  output: {
    format: "table" | "summary" | "chart" | "sql_only";
    columns: string[];
    limit: number;
    include_sql: boolean;
    include_explanation: boolean;
  };
  safety: {
    readonly: boolean;
    max_rows: number;
    allow_sensitive_fields: boolean;
    require_limit: boolean;
    require_metric_definition: boolean;
  };
  clarifications: Array<{
    field: string;
    question: string;
    reason: string;
    options: string[];
  }>;
  assumptions: Array<{
    field: string;
    value: unknown;
    reason: string;
    source: string;
  }>;
  confidence: number;
}

export interface GuardrailCheck {
  name: string;
  passed: boolean;
  message: string;
  severity: "info" | "warning" | "error";
}

export interface AgentStep {
  name: string;
  status: "pending" | "running" | "passed" | "failed" | "skipped";
  summary: string;
  details: Record<string, unknown>;
}

export interface QueryResponse {
  query_id: string;
  status: "planned" | "completed" | "failed" | "needs_clarification";
  answer: string;
  query_plan?: QueryPlan;
  sql?: string;
  result_preview: Array<Record<string, unknown>>;
  guardrail_checks: GuardrailCheck[];
  steps: AgentStep[];
  retry_count: number;
  elapsed_ms: number;
}

export type RunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "needs_clarification"
  | "interrupted";

export interface QueryEvent {
  event_id: number;
  query_id: string;
  type: string;
  stage: string;
  status: AgentStep["status"];
  attempt: number;
  summary: string;
  output: Record<string, unknown>;
  occurred_at: string;
}

export interface QueryRunSnapshot {
  query_id: string;
  user_id?: string;
  question: string;
  status: RunStatus;
  current_stage?: string;
  retry_count: number;
  elapsed_ms?: number;
  error_type?: string;
  error_message?: string;
  clarification_context: Record<string, unknown>;
  response?: QueryResponse;
  events: QueryEvent[];
  created_at: string;
  updated_at: string;
}

export interface QueryRunList {
  items: QueryRunSnapshot[];
  total: number;
  limit: number;
  offset: number;
}

export type QueryExportFormat = "xlsx" | "csv" | "json";

export type EvaluationDifficulty = "simple" | "medium" | "complex";

export interface EvaluationRunSummary {
  eval_run_id: string;
  run_name: string;
  status: string;
  total_cases: number;
  passed_cases: number;
  review_queued_cases: number;
  average_elapsed_ms?: number;
  dataset_version?: string;
  started_at: string;
  finished_at?: string;
}

export interface EvaluationResultSummary {
  eval_result_id: string;
  case_id: string;
  case_code: string;
  question: string;
  difficulty: EvaluationDifficulty;
  expected_status: string;
  passed: boolean;
  executable: boolean;
  result_correct?: boolean;
  plan_score?: number;
  sql_score?: number;
  result_score?: number;
  elapsed_ms?: number;
  failure_type?: string;
  failure_reason?: string;
  auto_decision: string;
  review_priority?: string;
  review_status: string;
  risk_reasons: string[];
}

export interface EvaluationRunDetail extends EvaluationRunSummary {
  results: EvaluationResultSummary[];
}

export interface EvaluationDashboard {
  total_cases: number;
  active_cases: number;
  executable_rate: number;
  result_accuracy: number;
  first_pass_rate: number;
  repaired_pass_rate: number;
  average_elapsed_ms?: number;
  pending_review_count: number;
  reviewed_count: number;
  latest_run?: EvaluationRunSummary;
}

export interface ReviewBatchSummary {
  review_batch_id: string;
  batch_name: string;
  status: string;
  item_count: number;
  dataset_version?: string;
  created_at: string;
}

export interface ReviewItemDetail {
  review_item_id: string;
  review_batch_id: string;
  status: string;
  priority: string;
  risk_reasons: string[];
  case_code: string;
  question: string;
  difficulty: EvaluationDifficulty;
  expected_status: string;
  expected_query_plan: Record<string, unknown>;
  expected_sql?: string;
  expected_result: Record<string, unknown>;
  generated_query_plan: Record<string, unknown>;
  generated_sql?: string;
  generated_response: Record<string, unknown>;
  auto_decision: string;
  failure_type?: string;
  failure_reason?: string;
  elapsed_ms?: number;
}

export interface ReviewDecisionPayload {
  review_item_id: string;
  reviewer_id: string;
  verdict: "correct" | "incorrect" | "needs_clarification" | "insufficient_data";
  error_class?: string;
  severity: "minor" | "major" | "blocking";
  corrected_query_plan?: Record<string, unknown>;
  corrected_sql?: string;
  corrected_result?: Record<string, unknown>;
  reviewer_note?: string;
  confidence?: number;
  source_checksum?: string;
}
