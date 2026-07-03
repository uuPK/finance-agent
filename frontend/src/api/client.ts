import type { QueryRequest, QueryResponse } from "../types/query";

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
