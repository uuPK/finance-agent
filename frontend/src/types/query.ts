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
