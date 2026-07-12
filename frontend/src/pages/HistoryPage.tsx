import { Clock3, ExternalLink, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { listQueryRuns } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { getClientId } from "../lib/clientId";
import type { QueryRunSnapshot, RunStatus } from "../types/query";

export function HistoryPage({ onOpen }: { onOpen: (queryId: string) => void }) {
  const [items, setItems] = useState<QueryRunSnapshot[]>([]);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<RunStatus | "all">("all");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void listQueryRuns(getClientId())
      .then((response) => setItems(response.items))
      .catch((reason) => setError(reason instanceof Error ? reason.message : "加载历史失败"));
  }, []);

  const visible = useMemo(
    () => items.filter((item) => (status === "all" || item.status === status) && item.question.toLowerCase().includes(search.toLowerCase())),
    [items, search, status]
  );

  return (
    <div className="min-h-screen bg-surface px-4 py-6 sm:px-6">
      <div className="mx-auto max-w-6xl">
        <header>
          <h1 className="text-xl font-semibold text-ink">查询历史</h1>
          <p className="mt-1 text-sm text-muted">查看本浏览器发起的查询与完整执行记录</p>
        </header>
        <div className="mt-5 flex flex-col gap-3 border-y border-line bg-white px-4 py-3 sm:flex-row sm:items-center">
          <label className="flex flex-1 items-center gap-2"><Search className="h-4 w-4 text-muted" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索问题" className="h-9 w-full border-0 text-sm outline-none" /></label>
          <select value={status} onChange={(event) => setStatus(event.target.value as RunStatus | "all")} className="h-9 border border-line bg-white px-3 text-sm outline-none">
            <option value="all">全部状态</option><option value="running">进行中</option><option value="completed">已完成</option><option value="failed">未通过</option><option value="needs_clarification">待确认</option><option value="interrupted">已中断</option>
          </select>
        </div>
        {error ? <div className="mt-4 border-l-2 border-red-500 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
        <div className="mt-4 overflow-hidden border border-line bg-white">
          {visible.length ? visible.map((item) => (
            <button key={item.query_id} type="button" onClick={() => onOpen(item.query_id)} className="grid w-full gap-3 border-b border-line px-4 py-4 text-left last:border-0 hover:bg-slate-50 sm:grid-cols-[1fr_auto_auto] sm:items-center">
              <div className="min-w-0"><div className="truncate text-sm font-medium text-ink">{item.question}</div><div className="mt-1 flex items-center gap-2 text-xs text-muted"><Clock3 className="h-3.5 w-3.5" />{new Date(item.created_at).toLocaleString("zh-CN")}{item.elapsed_ms ? ` · ${(item.elapsed_ms / 1000).toFixed(1)} 秒` : ""}</div></div>
              <StatusBadge status={item.status} />
              <ExternalLink className="h-4 w-4 text-muted" />
            </button>
          )) : <div className="py-16 text-center text-sm text-muted">暂无符合条件的查询记录</div>}
        </div>
      </div>
    </div>
  );
}
