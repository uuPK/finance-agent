import type {
  EvaluationDashboard,
  EvaluationRunDetail,
  EvaluationRunSummary,
  QueryEvent,
  QueryExportFormat,
  QueryRequest,
  QueryResponse,
  QueryRunList,
  QueryRunSnapshot,
  MetadataBusinessTerm,
  MetadataJoin,
  MetadataMetric,
  MetadataOverview,
  MetadataQuestionExample,
  MetadataTable,
  MetadataTableDetail,
  ReviewBatchSummary,
  ReviewDecisionPayload,
  ReviewItemDetail
} from "../types/query";

export async function runQuery(payload: QueryRequest): Promise<QueryResponse> {
  const response = await fetch("/api/chat/query", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    throw new Error(`Query failed with status ${response.status}`);
  }

  return response.json();
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `请求失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}

export async function createQueryRun(question: string, userId: string) {
  const response = await fetch("/api/chat/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, user_id: userId })
  });
  return parseResponse<{ query_id: string; status: string; stream_url: string }>(response);
}

export async function getQueryRun(queryId: string): Promise<QueryRunSnapshot> {
  return parseResponse(await fetch(`/api/chat/runs/${queryId}`));
}

export async function listQueryRuns(userId: string): Promise<QueryRunList> {
  return parseResponse(
    await fetch(`/api/chat/runs?user_id=${encodeURIComponent(userId)}&limit=100`)
  );
}

export async function submitClarifications(
  queryId: string,
  answers: Array<{ field: string; value: string }>
): Promise<QueryRunSnapshot> {
  const response = await fetch(`/api/chat/runs/${queryId}/clarifications`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers })
  });
  return parseResponse(response);
}

export async function submitQueryReview(
  queryId: string,
  userId: string,
  reason?: string
): Promise<{ review_item_id: string; review_batch_id: string; status: string; already_submitted: boolean }> {
  return parseResponse(
    await fetch(`/api/chat/runs/${queryId}/reviews`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, reason: reason || null })
    })
  );
}

export async function downloadQueryExport(
  queryId: string,
  userId: string,
  format: QueryExportFormat
): Promise<void> {
  const response = await fetch(
    `/api/chat/runs/${queryId}/export?user_id=${encodeURIComponent(userId)}&format=${format}`
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `导出失败（${response.status}）`);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const matchedName = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  const fallbackName = `finance-agent-result.${format}`;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = matchedName ?? fallbackName;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export async function getMetadataOverview(): Promise<MetadataOverview> {
  return parseResponse(await fetch("/api/metadata/overview"));
}

export async function listMetadataTables(search = ""): Promise<MetadataTable[]> {
  const suffix = search ? `?search=${encodeURIComponent(search)}` : "";
  return parseResponse(await fetch(`/api/metadata/tables${suffix}`));
}

export async function getMetadataTable(tableName: string): Promise<MetadataTableDetail> {
  return parseResponse(await fetch(`/api/metadata/tables/${encodeURIComponent(tableName)}`));
}

export async function listMetadataMetrics(search = ""): Promise<MetadataMetric[]> {
  const suffix = search ? `?search=${encodeURIComponent(search)}` : "";
  return parseResponse(await fetch(`/api/metadata/metrics${suffix}`));
}

export async function listMetadataTerms(search = ""): Promise<MetadataBusinessTerm[]> {
  const suffix = search ? `?search=${encodeURIComponent(search)}` : "";
  return parseResponse(await fetch(`/api/metadata/terms${suffix}`));
}

export async function listMetadataJoins(): Promise<MetadataJoin[]> {
  return parseResponse(await fetch("/api/metadata/joins"));
}

export async function listMetadataExamples(): Promise<MetadataQuestionExample[]> {
  return parseResponse(await fetch("/api/metadata/examples"));
}

const eventTypes = [
  "run.created",
  "stage.started",
  "stage.completed",
  "stage.failed",
  "clarification.required",
  "clarification.received",
  "run.completed",
  "run.failed"
];

export function subscribeToQueryRun(
  queryId: string,
  after: number,
  onEvent: (event: QueryEvent) => void,
  onError: () => void
): () => void {
  const source = new EventSource(`/api/chat/runs/${queryId}/events?after=${after}`);
  const listener = (message: MessageEvent<string>) => {
    onEvent(JSON.parse(message.data) as QueryEvent);
  };
  eventTypes.forEach((type) => source.addEventListener(type, listener as EventListener));
  source.onerror = onError;
  return () => source.close();
}

export async function getEvaluationDashboard(): Promise<EvaluationDashboard> {
  return parseResponse(await fetch("/api/evaluation/dashboard"));
}

export async function listEvaluationRuns(): Promise<EvaluationRunSummary[]> {
  return parseResponse(await fetch("/api/evaluation/runs"));
}

export async function getEvaluationRun(runId: string): Promise<EvaluationRunDetail> {
  return parseResponse(await fetch(`/api/evaluation/runs/${runId}`));
}

export async function createEvaluationRun(payload: {
  run_name: string;
  difficulty?: string;
  limit: number;
  evaluation_mode: "smoke" | "full";
}): Promise<{ eval_run_id: string; status: string }> {
  return parseResponse(
    await fetch("/api/evaluation/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
  );
}

export async function createReviewBatch(payload: {
  eval_run_id: string;
  batch_name: string;
  max_items: number;
  created_by: string;
}): Promise<ReviewBatchSummary> {
  return parseResponse(
    await fetch("/api/evaluation/review-batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
  );
}

export async function listReviewBatches(): Promise<ReviewBatchSummary[]> {
  return parseResponse(await fetch("/api/evaluation/review-batches"));
}

export async function listReviewItems(options: {
  batchId?: string;
  status?: "pending" | "reviewed" | "all";
} = {}): Promise<ReviewItemDetail[]> {
  const params = new URLSearchParams({ status: options.status ?? "pending" });
  if (options.batchId) params.set("batch_id", options.batchId);
  return parseResponse(await fetch(`/api/evaluation/review-items?${params}`));
}

export async function importReviewDecisions(
  decisions: ReviewDecisionPayload[]
): Promise<{ accepted: number; rejected: string[] }> {
  return parseResponse(
    await fetch("/api/evaluation/review-imports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decisions })
    })
  );
}
