import {
  Activity,
  CheckCircle2,
  ClipboardCheck,
  Download,
  FileUp,
  Gauge,
  Play,
  RefreshCw,
  ShieldAlert
} from "lucide-react";
import { ChangeEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  createEvaluationRun,
  createReviewBatch,
  getEvaluationDashboard,
  getEvaluationRun,
  importReviewDecisions,
  listEvaluationRuns,
  listReviewItems
} from "../api/client";
import type {
  EvaluationDashboard,
  EvaluationRunDetail,
  EvaluationRunSummary,
  ReviewDecisionPayload,
  ReviewItemDetail
} from "../types/query";

const metricCards = [
  { key: "executable_rate" as const, label: "SQL 可执行率", icon: Activity },
  { key: "first_pass_rate" as const, label: "一次通过率", icon: CheckCircle2 },
  { key: "repaired_pass_rate" as const, label: "修复后通过率", icon: RefreshCw },
  { key: "result_accuracy" as const, label: "结果准确率", icon: Gauge }
];

const priorityClass: Record<string, string> = {
  blocking: "bg-rose-100 text-rose-700",
  high: "bg-amber-100 text-amber-800",
  normal: "bg-slate-100 text-slate-700"
};

function formatPercent(value?: number) {
  return value === undefined ? "--" : `${value.toFixed(1)}%`;
}

function formatDuration(value?: number) {
  return value === undefined ? "--" : `${(value / 1000).toFixed(1)} 秒`;
}

export function EvaluationCenter() {
  const [dashboard, setDashboard] = useState<EvaluationDashboard | null>(null);
  const [runs, setRuns] = useState<EvaluationRunSummary[]>([]);
  const [selectedRun, setSelectedRun] = useState<EvaluationRunDetail | null>(null);
  const [reviewItems, setReviewItems] = useState<ReviewItemDetail[]>([]);
  const [selectedItem, setSelectedItem] = useState<ReviewItemDetail | null>(null);
  const [difficulty, setDifficulty] = useState("");
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState("");
  const [reviewerId, setReviewerId] = useState("reviewer-01");
  const [verdict, setVerdict] = useState<ReviewDecisionPayload["verdict"]>("incorrect");
  const [severity, setSeverity] = useState<ReviewDecisionPayload["severity"]>("major");
  const [note, setNote] = useState("");

  const loadRun = useCallback(async (runId: string) => {
    const detail = await getEvaluationRun(runId);
    setSelectedRun(detail);
  }, []);

  const load = useCallback(async () => {
    const [nextDashboard, nextRuns, nextItems] = await Promise.all([
      getEvaluationDashboard(),
      listEvaluationRuns(),
      listReviewItems()
    ]);
    setDashboard(nextDashboard);
    setRuns(nextRuns);
    setReviewItems(nextItems);
    setSelectedItem((current) => nextItems.find((item) => item.review_item_id === current?.review_item_id) ?? nextItems[0] ?? null);
    setSelectedRun((current) => {
      const runId = current?.eval_run_id ?? nextRuns[0]?.eval_run_id;
      if (runId) void loadRun(runId);
      return current;
    });
  }, [loadRun]);

  useEffect(() => {
    void load().catch((error: Error) => setMessage(error.message));
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (runs.some((run) => run.status === "running")) void load().catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [load, runs]);

  const selectedResults = selectedRun?.results ?? [];
  const hasRunningRun = running || runs.some((run) => run.status === "running");
  const exportBaseUrl = selectedItem ? `/api/evaluation/review-batches/${selectedItem.review_batch_id}/export` : "";

  async function startEvaluation() {
    setRunning(true);
    setMessage("");
    try {
      const created = await createEvaluationRun({
        run_name: `workbench-${new Date().toISOString().slice(0, 19)}`,
        difficulty: difficulty || undefined,
        limit: difficulty ? 20 : 15,
        evaluation_mode: difficulty ? "smoke" : "full"
      });
      await loadRun(created.eval_run_id);
      await load();
      setMessage("评测任务已启动，结果会持续写入当前批次。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "无法启动评测任务。");
    } finally {
      setRunning(false);
    }
  }

  async function buildReviewBatch() {
    try {
      const batch = await createReviewBatch({
        batch_name: `review-${new Date().toISOString().slice(0, 10)}`,
        max_items: 50,
        created_by: reviewerId || "system"
      });
      await load();
      setMessage(`已创建人工复核批次，包含 ${batch.item_count} 个案例。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "无法创建复核批次。");
    }
  }

  async function submitReview() {
    if (!selectedItem || !reviewerId) return;
    try {
      const result = await importReviewDecisions([
        {
          review_item_id: selectedItem.review_item_id,
          reviewer_id: reviewerId,
          verdict,
          severity,
          reviewer_note: note || undefined,
          confidence: 0.9
        }
      ]);
      await load();
      setNote("");
      setMessage(result.accepted ? "人工复核结论已回写，并进入可追溯评测记录。" : result.rejected.join("；"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "无法提交人工复核结论。");
    }
  }

  async function importJsonl(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const parsed = text.trim().startsWith("[")
        ? JSON.parse(text)
        : text.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
      const result = await importReviewDecisions(parsed as ReviewDecisionPayload[]);
      await load();
      setMessage(`已导入 ${result.accepted} 条人工复核结论。${result.rejected.join("；")}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "导入文件格式不正确。");
    } finally {
      event.target.value = "";
    }
  }

  const reviewStats = useMemo(() => `${dashboard?.reviewed_count ?? 0} 已复核 / ${dashboard?.pending_review_count ?? 0} 待复核`, [dashboard]);

  return (
    <div className="min-h-screen bg-surface px-4 py-6 sm:px-6">
      <div className="mx-auto max-w-7xl">
        <header className="flex flex-col gap-4 border-b border-line pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div><h1 className="text-xl font-semibold text-ink">评测与人工复核中心</h1><p className="mt-1 text-sm text-muted">基准案例、自动评分与人工裁定在同一条可审计链路中运行。</p></div>
          <div className="flex flex-wrap items-center gap-2">
            <select value={difficulty} onChange={(event) => setDifficulty(event.target.value)} className="h-9 border border-line bg-white px-3 text-sm text-ink">
              <option value="">完整评测集</option><option value="simple">简单案例冒烟</option><option value="medium">中等案例冒烟</option><option value="complex">复杂案例冒烟</option>
            </select>
            <button type="button" onClick={() => void startEvaluation()} disabled={hasRunningRun} className="inline-flex h-9 items-center gap-2 bg-slate-900 px-3 text-sm font-medium text-white disabled:opacity-50"><Play className="h-4 w-4" />{hasRunningRun ? "评测运行中" : "运行评测"}</button>
            <button type="button" onClick={() => void buildReviewBatch()} className="inline-flex h-9 items-center gap-2 border border-line bg-white px-3 text-sm font-medium text-ink"><ClipboardCheck className="h-4 w-4" />生成复核批次</button>
          </div>
        </header>

        {message && <p className="mt-4 border-l-2 border-teal-600 bg-teal-50 px-3 py-2 text-sm text-teal-900">{message}</p>}

        <section className="mt-5 grid border-l border-t border-line bg-white sm:grid-cols-2 lg:grid-cols-4">
          {metricCards.map((metric) => { const Icon = metric.icon; return <div key={metric.key} className="border-b border-r border-line p-4"><Icon className="h-5 w-5 text-slate-500" /><div className="mt-4 text-2xl font-semibold text-ink">{formatPercent(dashboard?.[metric.key])}</div><div className="mt-1 text-sm text-muted">{metric.label}</div></div>; })}
        </section>

        <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="border border-line bg-white">
            <div className="flex items-center justify-between border-b border-line px-4 py-3"><div><h2 className="text-sm font-semibold text-ink">评测批次</h2><p className="mt-1 text-xs text-muted">{dashboard?.active_cases ?? 0} 个活跃基准案例，平均耗时 {formatDuration(dashboard?.average_elapsed_ms)}</p></div></div>
            <div className="max-h-48 overflow-auto">
              {runs.map((run) => <button key={run.eval_run_id} type="button" onClick={() => void loadRun(run.eval_run_id)} className={`grid w-full grid-cols-[1fr_auto_auto] gap-3 border-b border-line px-4 py-3 text-left text-sm hover:bg-slate-50 ${selectedRun?.eval_run_id === run.eval_run_id ? "bg-slate-50" : ""}`}><span className="min-w-0"><span className="block truncate font-medium text-ink">{run.run_name}</span><span className="mt-1 block text-xs text-muted">{new Date(run.started_at).toLocaleString()}</span></span><span className="self-center text-xs text-muted">{run.passed_cases}/{run.total_cases}</span><span className={`self-center text-xs font-medium ${run.status === "completed" ? "text-emerald-700" : run.status === "failed" ? "text-rose-700" : "text-amber-700"}`}>{run.status === "running" ? "运行中" : run.status === "completed" ? "已完成" : "失败"}</span></button>)}
              {!runs.length && <p className="p-6 text-sm text-muted">尚未运行评测。</p>}
            </div>
            <div className="overflow-x-auto border-t border-line">
              <table className="w-full min-w-[720px] text-left text-sm"><thead className="sticky top-0 bg-slate-50 text-xs text-muted"><tr><th className="px-4 py-3 font-medium">案例</th><th className="px-4 py-3 font-medium">难度</th><th className="px-4 py-3 font-medium">结果</th><th className="px-4 py-3 font-medium">评分</th><th className="px-4 py-3 font-medium">人工路由</th><th className="px-4 py-3 font-medium">耗时</th></tr></thead><tbody>{selectedResults.map((result) => <tr key={result.eval_result_id} className="border-t border-line"><td className="max-w-72 px-4 py-3"><span className="font-mono text-xs text-muted">{result.case_code}</span><span className="mt-1 block truncate text-ink">{result.question}</span></td><td className="px-4 py-3 text-muted">{result.difficulty}</td><td className={`px-4 py-3 font-medium ${result.passed ? "text-emerald-700" : "text-rose-700"}`}>{result.passed ? "通过" : "待处理"}</td><td className="px-4 py-3 text-muted">{result.result_score ?? 0}/100</td><td className="px-4 py-3">{result.review_priority ? <span className={`px-2 py-1 text-xs ${priorityClass[result.review_priority]}`}>{result.review_priority}</span> : <span className="text-xs text-muted">自动通过</span>}</td><td className="px-4 py-3 text-muted">{formatDuration(result.elapsed_ms)}</td></tr>)}{selectedRun && !selectedResults.length && <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-muted">评测正在写入结果。</td></tr>}</tbody></table>
            </div>
          </div>

          <aside className="border border-line bg-white">
            <div className="border-b border-line px-4 py-3"><h2 className="text-sm font-semibold text-ink">人工复核队列</h2><p className="mt-1 text-xs text-muted">{reviewStats}</p></div>
            <div className="max-h-[540px] overflow-auto">
              {reviewItems.map((item) => <button key={item.review_item_id} type="button" onClick={() => setSelectedItem(item)} className={`w-full border-b border-line px-4 py-3 text-left hover:bg-slate-50 ${item.review_item_id === selectedItem?.review_item_id ? "bg-slate-50" : ""}`}><div className="flex items-center justify-between gap-2"><span className="font-mono text-xs text-muted">{item.case_code}</span><span className={`px-2 py-1 text-xs ${priorityClass[item.priority] ?? priorityClass.normal}`}>{item.priority}</span></div><p className="mt-2 line-clamp-2 text-sm text-ink">{item.question}</p><p className="mt-2 truncate text-xs text-muted">{item.risk_reasons.join(" / ")}</p></button>)}
              {!reviewItems.length && <p className="p-6 text-sm text-muted">暂无待复核案例。</p>}
            </div>
          </aside>
        </section>

        <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="border border-line bg-white">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3"><div><h2 className="text-sm font-semibold text-ink">复核工作面</h2><p className="mt-1 text-xs text-muted">只呈现业务口径、证据、SQL 与脱敏结果，不呈现模型隐藏推理。</p></div>{selectedItem && <div className="flex gap-2"><a href={`${exportBaseUrl}?format=csv`} className="inline-flex h-8 items-center gap-1 border border-line px-2 text-xs text-ink"><Download className="h-3.5 w-3.5" />CSV</a><a href={`${exportBaseUrl}?format=jsonl`} className="inline-flex h-8 items-center gap-1 border border-line px-2 text-xs text-ink"><Download className="h-3.5 w-3.5" />JSONL</a></div>}</div>
            {selectedItem ? <div className="grid divide-y divide-line lg:grid-cols-2 lg:divide-x lg:divide-y-0"><Artifact title="标准业务口径" value={{ expected_status: selectedItem.expected_status, query_plan: selectedItem.expected_query_plan, sql: selectedItem.expected_sql, result: selectedItem.expected_result }} /><Artifact title="Agent 实际产物" value={{ query_plan: selectedItem.generated_query_plan, sql: selectedItem.generated_sql, response: selectedItem.generated_response, failure: selectedItem.failure_reason }} /></div> : <div className="p-8 text-sm text-muted">选择一条人工复核任务后查看详情。</div>}
          </div>
          <div className="border border-line bg-white p-4"><div className="flex items-center gap-2"><ShieldAlert className="h-4 w-4 text-amber-700" /><h2 className="text-sm font-semibold text-ink">提交人工裁定</h2></div><label className="mt-4 block text-xs font-medium text-muted">审核人<input value={reviewerId} onChange={(event) => setReviewerId(event.target.value)} className="mt-1 h-9 w-full border border-line px-2 text-sm text-ink" /></label><div className="mt-3 grid grid-cols-2 gap-3"><label className="text-xs font-medium text-muted">结论<select value={verdict} onChange={(event) => setVerdict(event.target.value as ReviewDecisionPayload["verdict"])} className="mt-1 h-9 w-full border border-line bg-white px-2 text-sm text-ink"><option value="correct">正确</option><option value="incorrect">错误</option><option value="needs_clarification">应澄清</option><option value="insufficient_data">数据不足</option></select></label><label className="text-xs font-medium text-muted">严重程度<select value={severity} onChange={(event) => setSeverity(event.target.value as ReviewDecisionPayload["severity"])} className="mt-1 h-9 w-full border border-line bg-white px-2 text-sm text-ink"><option value="minor">轻微</option><option value="major">主要</option><option value="blocking">阻断</option></select></label></div><label className="mt-3 block text-xs font-medium text-muted">复核说明<textarea value={note} onChange={(event) => setNote(event.target.value)} className="mt-1 min-h-28 w-full resize-y border border-line p-2 text-sm text-ink" /></label><button type="button" onClick={() => void submitReview()} disabled={!selectedItem} className="mt-4 inline-flex h-9 w-full items-center justify-center gap-2 bg-slate-900 px-3 text-sm font-medium text-white disabled:opacity-50"><ClipboardCheck className="h-4 w-4" />回写裁定</button><label className="mt-4 flex h-9 cursor-pointer items-center justify-center gap-2 border border-line text-sm text-ink"><FileUp className="h-4 w-4" />导入 JSON / JSONL<input type="file" accept=".json,.jsonl,.ndjson" onChange={(event) => void importJsonl(event)} className="hidden" /></label></div>
        </section>
      </div>
    </div>
  );
}

function Artifact({ title, value }: { title: string; value: Record<string, unknown> }) {
  return <section className="min-w-0 p-4"><h3 className="text-xs font-semibold text-muted">{title}</h3><pre className="mt-3 max-h-[380px] overflow-auto whitespace-pre-wrap break-words bg-slate-50 p-3 text-xs leading-5 text-slate-700">{JSON.stringify(value, null, 2)}</pre></section>;
}
