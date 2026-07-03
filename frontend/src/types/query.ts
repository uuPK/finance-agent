export interface QueryRequest {
  question: string;
  user_id?: string;
  include_debug?: boolean;
}

export interface QueryMetric {
  name: string;
  definition_id?: string;
  aggregation?: string;
}

export interface QueryFilter {
  term: string;
  operator: string;
  value: unknown;
}

export interface QueryPlan {
  intent: string;
  subject?: string;
  metrics: QueryMetric[];
  dimensions: string[];
  filters: QueryFilter[];
  tables: string[];
  grain?: string;
  limit?: number;
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
