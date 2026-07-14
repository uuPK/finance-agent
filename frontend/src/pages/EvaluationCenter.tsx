import {
  Activity,
  CheckCircle2,
  ClipboardCheck,
  Download,
  FileCheck2,
  FileCode2,
  FileUp,
  Gauge,
  Play,
  RefreshCw,
  ShieldAlert,
  TableProperties
} from "lucide-react";
import { ChangeEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  createEvaluationRun,
  createReviewBatch,
  getEvaluationDashboard,
  getEvaluationRun,
  importReviewDecisions,
  listEvaluationRuns,
  listReviewBatches,
  listReviewItems
} from "../api/client";
import type {
  EvaluationDashboard,
  EvaluationRunDetail,
  EvaluationRunSummary,
  ReviewBatchSummary,
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

const priorityLabel: Record<string, string> = {
  blocking: "阻断",
  high: "高",
  normal: "常规"
};

const verdictLabel: Record<NonNullable<ReviewItemDetail["verdict"]>, string> = {
  correct: "正确",
  incorrect: "错误",
  needs_clarification: "需要澄清",
  insufficient_data: "数据不足"
};

const failureReviewReasons = new Set(["status_mismatch", "not_executable", "result_mismatch", "runtime_error"]);

function reviewRouteLabel(riskReasons: string[]) {
  return riskReasons.some((reason) => failureReviewReasons.has(reason)) ? "失败确认" : "风险抽检";
}

const errorClasses = [
  ["wrong_metric", "指标口径错误"],
  ["wrong_filter", "筛选条件错误"],
  ["wrong_time_window", "时间范围错误"],
  ["wrong_grain", "统计粒度错误"],
  ["wrong_join", "关联关系错误"],
  ["unsafe_sql", "SQL 安全或合规问题"],
  ["result_mismatch", "结果与业务事实不一致"],
  ["insufficient_metadata", "元数据或样本不足"],
  ["other", "其他" ]
] as const;

function formatPercent(value?: number) {
  return value === undefined ? "--" : `${value.toFixed(1)}%`;
}

function formatDuration(value?: number) {
  return value === undefined ? "--" : `${(value / 1000).toFixed(1)} 秒`;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asRows(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "--";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(displayValue).join("、");
  return JSON.stringify(value);
}

function parseJsonObject(value: string, field: string): Record<string, unknown> | undefined {
  if (!value.trim()) return undefined;
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${field}必须是 JSON 对象。`);
  }
  return parsed as Record<string, unknown>;
}

export function EvaluationCenter() {
  const [dashboard, setDashboard] = useState<EvaluationDashboard | null>(null);
  const [runs, setRuns] = useState<EvaluationRunSummary[]>([]);
  const [selectedRun, setSelectedRun] = useState<EvaluationRunDetail | null>(null);
  const [batches, setBatches] = useState<ReviewBatchSummary[]>([]);
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null);
  const [batchScope, setBatchScope] = useState<"current" | "feedback" | "history">("current");
  const [reviewFilter, setReviewFilter] = useState<"pending" | "reviewed">("pending");
  const [reviewItems, setReviewItems] = useState<ReviewItemDetail[]>([]);
  const [selectedItem, setSelectedItem] = useState<ReviewItemDetail | null>(null);
  const [difficulty, setDifficulty] = useState("");
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState("");
  const [reviewerId, setReviewerId] = useState("reviewer-01");
  const [verdict, setVerdict] = useState<ReviewDecisionPayload["verdict"]>("incorrect");
  const [severity, setSeverity] = useState<ReviewDecisionPayload["severity"]>("major");
  const [errorClass, setErrorClass] = useState("");
  const [note, setNote] = useState("");
  const [correctedPlan, setCorrectedPlan] = useState("");
  const [correctedSql, setCorrectedSql] = useState("");
  const [correctedResult, setCorrectedResult] = useState("");

  const loadRun = useCallback(async (runId: string) => {
    const detail = await getEvaluationRun(runId);
    setSelectedRun(detail);
  }, []);

  const loadOverview = useCallback(async () => {
    const [nextDashboard, nextRuns, nextBatches] = await Promise.all([
      getEvaluationDashboard(),
      listEvaluationRuns(),
      listReviewBatches()
    ]);
    setDashboard(nextDashboard);
    setRuns(nextRuns);
    setBatches(nextBatches);
    setSelectedRun((current) => {
      const runId = current?.eval_run_id ?? nextRuns[0]?.eval_run_id;
      if (runId) void loadRun(runId);
      return current;
    });
  }, [loadRun]);

  const loadReviewItems = useCallback(async (batchId: string, status: "pending" | "reviewed") => {
    const nextItems = await listReviewItems({ batchId, status });
    setReviewItems(nextItems);
    setSelectedItem((current) => nextItems.find((item) => item.review_item_id === current?.review_item_id) ?? nextItems[0] ?? null);
  }, []);

  useEffect(() => {
    void loadOverview().catch((error: Error) => setMessage(error.message));
  }, [loadOverview]);

  useEffect(() => {
    if (!activeBatchId) {
      setReviewItems([]);
      setSelectedItem(null);
      return;
    }
    void loadReviewItems(activeBatchId, reviewFilter).catch((error: Error) => setMessage(error.message));
  }, [activeBatchId, loadReviewItems, reviewFilter]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (runs.some((run) => run.status === "running")) void loadOverview().catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [loadOverview, runs]);

  useEffect(() => {
    if (!selectedItem) return;
    setVerdict(selectedItem.verdict ?? "incorrect");
    setSeverity(selectedItem.severity ?? "major");
    setErrorClass(selectedItem.error_class ?? "");
    setNote(selectedItem.reviewer_note ?? "");
    setCorrectedPlan(Object.keys(selectedItem.corrected_query_plan ?? {}).length ? JSON.stringify(selectedItem.corrected_query_plan, null, 2) : "");
    setCorrectedSql(selectedItem.corrected_sql ?? "");
    setCorrectedResult(Object.keys(selectedItem.corrected_result ?? {}).length ? JSON.stringify(selectedItem.corrected_result, null, 2) : "");
  }, [selectedItem]);

  const selectedResults = selectedRun?.results ?? [];
  const selectedFailureReviews = selectedResults.filter((result) => !result.passed && result.review_priority).length;
  const selectedRiskReviews = selectedResults.filter((result) => result.passed && result.review_priority).length;
  const visibleBatches = useMemo(() => batches.filter((batch) => {
    if (batchScope === "current") return Boolean(selectedRun && batch.eval_run_id === selectedRun.eval_run_id);
    if (batchScope === "feedback") return batch.batch_type === "user_feedback";
    return batch.batch_type === "legacy_backlog";
  }), [batchScope, batches, selectedRun]);
  const activeBatch = batches.find((batch) => batch.review_batch_id === activeBatchId) ?? null;
  const hasRunningRun = running || runs.some((run) => run.status === "running");
  const exportBaseUrl = activeBatch ? `/api/evaluation/review-batches/${activeBatch.review_batch_id}/export` : "";
  const needsCorrection = verdict === "incorrect" || verdict === "needs_clarification";
  const isReviewReady = Boolean(selectedItem && reviewerId.trim() && (verdict === "correct" || errorClass));
  const reviewStats = useMemo(() => activeBatch
    ? `${activeBatch.reviewed_count} 已复核 / ${activeBatch.pending_count} 待复核`
    : "尚未选择复核批次", [activeBatch]);

  useEffect(() => {
    setActiveBatchId((current) => visibleBatches.some((batch) => batch.review_batch_id === current)
      ? current
      : visibleBatches[0]?.review_batch_id ?? null);
  }, [visibleBatches]);

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
      await loadOverview();
      setMessage("评测任务已启动，结果会持续写入当前批次记录。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "无法启动评测任务。");
    } finally {
      setRunning(false);
    }
  }

  async function buildReviewBatch() {
    if (!selectedRun) return;
    try {
      const batch = await createReviewBatch({
        eval_run_id: selectedRun.eval_run_id,
        batch_name: `review-${new Date().toISOString().slice(0, 10)}`,
        max_items: 50,
        created_by: reviewerId || "system"
      });
      await loadOverview();
      setBatchScope("current");
      setReviewFilter("pending");
      setActiveBatchId(batch.review_batch_id);
      setMessage(batch.item_count
        ? `已创建“${batch.batch_name}”，包含 ${batch.item_count} 条待复核任务。`
        : "当前没有符合路由规则的新任务，已保留空复核批次以便审计追踪。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "无法创建复核批次。");
    }
  }

  function loadStandardCorrection() {
    if (!selectedItem) return;
    setCorrectedPlan(JSON.stringify(selectedItem.expected_query_plan, null, 2));
    setCorrectedSql(selectedItem.expected_sql ?? "");
    setCorrectedResult(JSON.stringify(selectedItem.expected_result, null, 2));
    setMessage("已将标准业务口径载入修正草稿，请根据实际判断确认后再提交。");
  }

  async function submitReview() {
    if (!selectedItem || !isReviewReady) return;
    try {
      const decision: ReviewDecisionPayload = {
        review_item_id: selectedItem.review_item_id,
        reviewer_id: reviewerId.trim(),
        verdict,
        error_class: errorClass || undefined,
        severity,
        reviewer_note: note.trim() || undefined,
        confidence: 0.9
      };
      if (needsCorrection) {
        decision.corrected_query_plan = parseJsonObject(correctedPlan, "修正后的查询计划");
        decision.corrected_sql = correctedSql.trim() || undefined;
        decision.corrected_result = parseJsonObject(correctedResult, "修正后的标准结果");
      }
      const result = await importReviewDecisions([decision]);
      await loadOverview();
      if (activeBatchId) await loadReviewItems(activeBatchId, reviewFilter);
      setMessage(result.accepted
        ? "人工复核结论已写入审计记录；完整的修正 SQL 与标准结果会在安全校验后沉淀为回归样本。"
        : result.rejected.join("；"));
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
      await loadOverview();
      if (activeBatchId) await loadReviewItems(activeBatchId, reviewFilter);
      setMessage(`已导入 ${result.accepted} 条人工结论${result.rejected.length ? `；${result.rejected.join("；")}` : "。"}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "导入文件格式不正确。");
    } finally {
      event.target.value = "";
    }
  }

  return (
    <div className="min-h-screen overflow-x-hidden bg-surface px-4 py-6 sm:px-6">
      <div className="mx-auto max-w-7xl">
        <header className="flex flex-col gap-4 border-b border-line pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h1 className="text-xl font-semibold text-ink">评测与人工复核中心</h1>
            <p className="mt-1 text-sm text-muted">基准案例、自动评分与人工裁定运行在同一条可审计链路中。</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select value={difficulty} onChange={(event) => setDifficulty(event.target.value)} className="h-9 border border-line bg-white px-3 text-sm text-ink">
              <option value="">完整评测集</option><option value="simple">简单案例冒烟</option><option value="medium">中等案例冒烟</option><option value="complex">复杂案例冒烟</option>
            </select>
            <button type="button" onClick={() => void startEvaluation()} disabled={hasRunningRun} className="inline-flex h-9 items-center gap-2 bg-slate-900 px-3 text-sm font-medium text-white disabled:opacity-50"><Play className="h-4 w-4" />{hasRunningRun ? "评测运行中" : "运行评测"}</button>
            <button type="button" onClick={() => void buildReviewBatch()} disabled={!selectedRun || selectedRun.status !== "completed"} className="inline-flex h-9 items-center gap-2 border border-line bg-white px-3 text-sm font-medium text-ink disabled:opacity-50"><ClipboardCheck className="h-4 w-4" />为本次生成复核批次</button>
          </div>
        </header>

        {message && <p className="mt-4 border-l-2 border-teal-600 bg-teal-50 px-3 py-2 text-sm text-teal-900">{message}</p>}

        <section className="mt-5 grid border-l border-t border-line bg-white sm:grid-cols-2 lg:grid-cols-4">
          {metricCards.map((metric) => {
            const Icon = metric.icon;
            return <div key={metric.key} className="border-b border-r border-line p-4"><Icon className="h-5 w-5 text-slate-500" /><div className="mt-4 text-2xl font-semibold text-ink">{formatPercent(dashboard?.[metric.key])}</div><div className="mt-1 text-sm text-muted">{metric.label}</div></div>;
          })}
        </section>

        <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="border border-line bg-white">
            <div className="flex items-center justify-between border-b border-line px-4 py-3"><div><h2 className="text-sm font-semibold text-ink">评测批次</h2><p className="mt-1 text-xs text-muted">{dashboard?.active_cases ?? 0} 个活跃基准案例，平均耗时 {formatDuration(dashboard?.average_elapsed_ms)}</p></div></div>
            <div className="max-h-48 overflow-auto">
              {runs.map((run) => <button key={run.eval_run_id} type="button" onClick={() => { setBatchScope("current"); void loadRun(run.eval_run_id); }} className={`grid w-full grid-cols-[1fr_auto_auto] gap-3 border-b border-line px-4 py-3 text-left text-sm hover:bg-slate-50 ${selectedRun?.eval_run_id === run.eval_run_id ? "bg-slate-50" : ""}`}><span className="min-w-0"><span className="block truncate font-medium text-ink">{run.run_name}</span><span className="mt-1 block text-xs text-muted">{new Date(run.started_at).toLocaleString()}</span></span><span className="self-center text-right text-xs"><span className="block font-medium text-emerald-700">{run.passed_cases}/{run.total_cases} 通过</span><span className="mt-1 block text-amber-700">{run.review_queued_cases} 条待复核</span></span><span className={`self-center text-xs font-medium ${run.status === "completed" ? "text-emerald-700" : run.status === "failed" ? "text-rose-700" : "text-amber-700"}`}>{run.status === "running" ? "运行中" : run.status === "completed" ? "已完成" : "失败"}</span></button>)}
              {!runs.length && <p className="p-6 text-sm text-muted">尚未运行评测。</p>}
            </div>
            {selectedRun && <div className="grid border-t border-line bg-slate-50 sm:grid-cols-3"><div className="border-b border-line px-4 py-3 sm:border-b-0 sm:border-r"><p className="text-xs text-muted">自动评测</p><p className="mt-1 text-sm font-semibold text-ink">{selectedRun.passed_cases}/{selectedRun.total_cases} 通过</p></div><div className="border-b border-line px-4 py-3 sm:border-b-0 sm:border-r"><p className="text-xs text-muted">人工复核</p><p className="mt-1 text-sm font-semibold text-ink">{selectedRun.review_queued_cases} 条待复核</p></div><div className="px-4 py-3"><p className="text-xs text-muted">复核构成</p><p className="mt-1 text-sm font-semibold text-ink">{selectedFailureReviews} 条失败确认 + {selectedRiskReviews} 条风险抽检</p></div></div>}
            <div className="overflow-x-auto border-t border-line">
              <table className="w-full min-w-[720px] text-left text-sm"><thead className="sticky top-0 bg-slate-50 text-xs text-muted"><tr><th className="px-4 py-3 font-medium">案例</th><th className="px-4 py-3 font-medium">难度</th><th className="px-4 py-3 font-medium">结果</th><th className="px-4 py-3 font-medium">评分</th><th className="px-4 py-3 font-medium">人工路由</th><th className="px-4 py-3 font-medium">耗时</th></tr></thead><tbody>{selectedResults.map((result) => <tr key={result.eval_result_id} className="border-t border-line"><td className="max-w-72 px-4 py-3"><span className="font-mono text-xs text-muted">{result.case_code}</span><span className="mt-1 block truncate text-ink">{result.question}</span></td><td className="px-4 py-3 text-muted">{result.difficulty}</td><td className={`px-4 py-3 font-medium ${result.passed ? "text-emerald-700" : "text-rose-700"}`}>{result.passed ? "通过" : "待处理"}</td><td className="px-4 py-3 text-muted">{result.result_score ?? 0}/100</td><td className="px-4 py-3">{result.review_priority ? <span><span className={`px-2 py-1 text-xs ${priorityClass[result.review_priority]}`}>{result.passed ? "风险抽检" : "失败确认"}</span><span className="ml-2 text-xs text-muted">{priorityLabel[result.review_priority] ?? result.review_priority}</span></span> : <span className="text-xs text-muted">无需复核</span>}</td><td className="px-4 py-3 text-muted">{formatDuration(result.elapsed_ms)}</td></tr>)}{selectedRun && !selectedResults.length && <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-muted">评测正在写入结果。</td></tr>}</tbody></table>
            </div>
          </div>

          <aside className="border border-line bg-white">
            <div className="border-b border-line px-4 py-3"><h2 className="text-sm font-semibold text-ink">复核批次</h2><p className="mt-1 text-xs text-muted">当前评测、业务异议和历史积压分别管理。</p><div className="mt-3 grid grid-cols-3 border border-line"><button type="button" onClick={() => setBatchScope("current")} className={`h-8 text-xs ${batchScope === "current" ? "bg-slate-900 text-white" : "bg-white text-muted"}`}>当前评测</button><button type="button" onClick={() => setBatchScope("feedback")} className={`h-8 border-l border-line text-xs ${batchScope === "feedback" ? "bg-slate-900 text-white" : "bg-white text-muted"}`}>业务反馈</button><button type="button" onClick={() => setBatchScope("history")} className={`h-8 border-l border-line text-xs ${batchScope === "history" ? "bg-slate-900 text-white" : "bg-white text-muted"}`}>历史积压</button></div></div>
            <div className="max-h-[440px] overflow-auto">
              {visibleBatches.map((batch) => <button key={batch.review_batch_id} type="button" onClick={() => { setActiveBatchId(batch.review_batch_id); setReviewFilter(batch.pending_count ? "pending" : "reviewed"); }} className={`w-full border-b border-line px-4 py-3 text-left hover:bg-slate-50 ${batch.review_batch_id === activeBatchId ? "bg-slate-50" : ""}`}><div className="flex items-center justify-between gap-3"><span className="truncate text-sm font-medium text-ink">{batch.batch_name}</span><span className={`shrink-0 px-2 py-1 text-xs ${batch.status === "completed" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-700"}`}>{batch.status === "completed" ? "已完成" : "进行中"}</span></div><p className="mt-2 text-xs text-muted">{batch.reviewed_count} 已复核 / {batch.pending_count} 待复核 · {new Date(batch.created_at).toLocaleString()}</p></button>)}
              {!visibleBatches.length && <p className="p-6 text-sm text-muted">{batchScope === "current" ? "本次评测尚未生成复核批次。" : batchScope === "feedback" ? "暂无业务用户提交的异议。" : "暂无历史积压批次。"}</p>}
            </div>
          </aside>
        </section>

        <section className="mt-5 grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
          <aside className="border border-line bg-white">
            <div className="border-b border-line px-4 py-3"><div className="flex items-center justify-between"><h2 className="text-sm font-semibold text-ink">人工复核队列</h2><span className="text-xs text-muted">{reviewStats}</span></div><div className="mt-3 grid grid-cols-2 border border-line"><button type="button" onClick={() => setReviewFilter("pending")} className={`h-8 text-xs ${reviewFilter === "pending" ? "bg-slate-900 text-white" : "bg-white text-muted"}`}>待复核</button><button type="button" onClick={() => setReviewFilter("reviewed")} className={`h-8 border-l border-line text-xs ${reviewFilter === "reviewed" ? "bg-slate-900 text-white" : "bg-white text-muted"}`}>已复核</button></div></div>
            <div className="max-h-[640px] overflow-auto">
              {reviewItems.map((item) => <button key={item.review_item_id} type="button" onClick={() => setSelectedItem(item)} className={`w-full border-b border-line px-4 py-3 text-left hover:bg-slate-50 ${item.review_item_id === selectedItem?.review_item_id ? "bg-slate-50" : ""}`}><div className="flex items-center justify-between gap-2"><span className="font-mono text-xs text-muted">{item.case_code}</span><span className={`px-2 py-1 text-xs ${priorityClass[item.priority] ?? priorityClass.normal}`}>{item.source_type === "user_feedback" ? "用户异议" : reviewRouteLabel(item.risk_reasons)}</span></div><p className="mt-2 line-clamp-2 text-sm text-ink">{item.question}</p><p className="mt-2 truncate text-xs text-muted">{item.verdict ? `${verdictLabel[item.verdict]} · ${item.reviewer_id ?? ""}` : item.source_type === "user_feedback" ? item.user_reason || "用户未填写异议理由" : item.risk_reasons.join(" / ")}</p></button>)}
              {!reviewItems.length && <p className="p-6 text-sm text-muted">{activeBatch ? "此筛选下暂无任务。" : "请选择或生成复核批次。"}</p>}
            </div>
          </aside>

          <div className="min-w-0 space-y-5">
            <section className="border border-line bg-white">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3"><div><h2 className="text-sm font-semibold text-ink">复核工作面</h2><p className="mt-1 text-xs text-muted">展示业务口径、审核证据、SQL 和脱敏结果；不展示模型隐藏推理、提示词、密钥或连接信息。</p></div>{activeBatch && <div className="flex gap-2"><a href={`${exportBaseUrl}?format=csv`} className="inline-flex h-8 items-center gap-1 border border-line px-2 text-xs text-ink"><Download className="h-3.5 w-3.5" />CSV</a><a href={`${exportBaseUrl}?format=jsonl`} className="inline-flex h-8 items-center gap-1 border border-line px-2 text-xs text-ink"><Download className="h-3.5 w-3.5" />JSONL</a></div>}</div>
              {selectedItem ? <ReviewWorkspace item={selectedItem} /> : <div className="p-8 text-sm text-muted">选择一条人工复核任务后查看详情。</div>}
            </section>

            <section className="border border-line bg-white p-4">
              <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><ShieldAlert className="h-4 w-4 text-amber-700" /><div><h2 className="text-sm font-semibold text-ink">提交人工裁定</h2><p className="mt-1 text-xs text-muted">评测案例可沉淀修正事实；业务反馈保留人工裁定和审计记录。</p></div></div>{needsCorrection && selectedItem?.source_type === "evaluation" && <button type="button" onClick={loadStandardCorrection} className="inline-flex h-8 items-center gap-1 border border-line px-2 text-xs text-ink"><FileCheck2 className="h-3.5 w-3.5" />载入标准口径</button>}</div>
              {selectedItem?.status === "reviewed" ? <ReviewedDecision item={selectedItem} /> : <div className="mt-4 grid gap-3 lg:grid-cols-2"><label className="text-xs font-medium text-muted">审核人<input value={reviewerId} onChange={(event) => setReviewerId(event.target.value)} className="mt-1 h-9 w-full border border-line px-2 text-sm text-ink" /></label><label className="text-xs font-medium text-muted">结论<select value={verdict} onChange={(event) => setVerdict(event.target.value as ReviewDecisionPayload["verdict"])} className="mt-1 h-9 w-full border border-line bg-white px-2 text-sm text-ink"><option value="correct">正确</option><option value="incorrect">错误</option><option value="needs_clarification">需要澄清</option><option value="insufficient_data">数据不足</option></select></label><label className="text-xs font-medium text-muted">错误分类{verdict !== "correct" && <span className="ml-1 text-rose-700">必填</span>}<select value={errorClass} onChange={(event) => setErrorClass(event.target.value)} disabled={verdict === "correct"} className="mt-1 h-9 w-full border border-line bg-white px-2 text-sm text-ink disabled:bg-slate-50"><option value="">请选择</option>{errorClasses.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="text-xs font-medium text-muted">严重程度<select value={severity} onChange={(event) => setSeverity(event.target.value as ReviewDecisionPayload["severity"])} className="mt-1 h-9 w-full border border-line bg-white px-2 text-sm text-ink"><option value="minor">轻微</option><option value="major">主要</option><option value="blocking">阻断</option></select></label><label className="lg:col-span-2 text-xs font-medium text-muted">复核说明<textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="记录业务判断、差异原因或补充依据" className="mt-1 min-h-24 w-full resize-y border border-line p-2 text-sm text-ink" /></label>{needsCorrection && <><label className="lg:col-span-2 text-xs font-medium text-muted">修正后的查询计划（JSON）<textarea value={correctedPlan} onChange={(event) => setCorrectedPlan(event.target.value)} placeholder='{"intent": "..."}' className="mt-1 min-h-32 w-full resize-y border border-line p-2 font-mono text-xs leading-5 text-ink" /></label><label className="lg:col-span-2 text-xs font-medium text-muted">修正后的只读 SQL<label className="ml-1 font-normal text-muted">提供后将进行 SQL 安全校验并作为回归候选</label><textarea value={correctedSql} onChange={(event) => setCorrectedSql(event.target.value)} placeholder="SELECT ..." className="mt-1 min-h-28 w-full resize-y border border-line p-2 font-mono text-xs leading-5 text-ink" /></label><label className="lg:col-span-2 text-xs font-medium text-muted">修正后的标准结果（JSON）<textarea value={correctedResult} onChange={(event) => setCorrectedResult(event.target.value)} placeholder='{"columns": [], "rows": []}' className="mt-1 min-h-32 w-full resize-y border border-line p-2 font-mono text-xs leading-5 text-ink" /></label></>}<div className="flex flex-wrap gap-2 lg:col-span-2"><button type="button" onClick={() => void submitReview()} disabled={!isReviewReady} className="inline-flex h-9 items-center gap-2 bg-slate-900 px-3 text-sm font-medium text-white disabled:opacity-50"><ClipboardCheck className="h-4 w-4" />回写裁定</button><label className="inline-flex h-9 cursor-pointer items-center gap-2 border border-line px-3 text-sm text-ink"><FileUp className="h-4 w-4" />导入 JSON / JSONL<input type="file" accept=".json,.jsonl,.ndjson" onChange={(event) => void importJsonl(event)} className="hidden" /></label></div></div>}
            </section>
          </div>
        </section>
      </div>
    </div>
  );
}

function ReviewWorkspace({ item }: { item: ReviewItemDetail }) {
  const response = asRecord(item.generated_response);
  const expectedRows = asRows(asRecord(item.expected_result).rows);
  const actualRows = asRows(response.result_preview);
  const planEvidence = Object.entries(item.generated_query_plan).filter(([key]) => ["intent", "metrics", "dimensions", "filters", "time_range", "confidence", "plan_status"].includes(key));
  const evidence = [
    ["自动裁定", item.auto_decision],
    ["路由原因", item.risk_reasons.join("、")],
    ["失败类型", item.failure_type],
    ["失败原因", item.failure_reason],
    ["执行耗时", formatDuration(item.elapsed_ms)],
    ["最终状态", response.status],
    ["返回行数", response.row_count]
  ] as const;
  return <div>
    {item.source_type === "user_feedback" && <div className="border-b border-amber-200 bg-amber-50 px-4 py-3"><p className="text-xs font-semibold text-amber-950">业务用户主动提交审核</p><p className="mt-1 text-xs leading-5 text-amber-900">{item.user_reason || "用户未填写异议理由，请结合 Agent 产物和业务数据进行复核。"}</p></div>}
    <div className="grid border-b border-line lg:grid-cols-[minmax(0,1fr)_260px]">
      <div className="min-w-0 p-4"><p className="font-mono text-xs text-muted">{item.case_code}</p><p className="mt-2 text-sm text-ink">{item.question}</p></div>
      <div className="border-t border-line p-4 lg:border-l lg:border-t-0"><span className={`px-2 py-1 text-xs ${priorityClass[item.priority] ?? priorityClass.normal}`}>{priorityLabel[item.priority] ?? item.priority} 优先级</span><p className="mt-3 text-xs text-muted">难度：{item.difficulty} · 预期状态：{item.expected_status}</p></div>
    </div>
    <div className="grid divide-y divide-line xl:grid-cols-2 xl:divide-x xl:divide-y-0">
      <section className="min-w-0 p-4"><div className="flex items-center gap-2"><FileCheck2 className="h-4 w-4 text-emerald-700" /><h3 className="text-sm font-semibold text-ink">{item.source_type === "user_feedback" ? "人工复核依据" : "标准业务口径"}</h3></div>{item.source_type === "user_feedback" ? <p className="mt-4 text-xs leading-5 text-muted">真实业务问数没有预置标准答案。复核人员需依据业务口径、元数据和查询证据独立判断。</p> : <><PlanDetails entries={Object.entries(item.expected_query_plan)} empty="未提供标准查询计划。" /><SqlBlock sql={item.expected_sql} empty="未提供标准 SQL。" /><ResultTable rows={expectedRows} empty="未提供标准结果预览。" /></>}</section>
      <section className="min-w-0 p-4"><div className="flex items-center gap-2"><FileCode2 className="h-4 w-4 text-slate-700" /><h3 className="text-sm font-semibold text-ink">Agent 实际产物</h3></div><PlanDetails entries={planEvidence} empty="未生成可展示的查询计划。" /><SqlBlock sql={item.generated_sql} empty="未生成 SQL。" /><ResultTable rows={actualRows} empty="未返回结果预览。" /><div className="mt-4 border-t border-line pt-3"><h4 className="text-xs font-semibold text-muted">审核证据</h4><dl className="mt-2 grid gap-x-4 gap-y-2 sm:grid-cols-2">{evidence.filter(([, value]) => value !== undefined && value !== null && value !== "").map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-xs text-muted">{label}</dt><dd className="mt-0.5 break-words text-xs text-ink">{displayValue(value)}</dd></div>)}</dl>{typeof response.answer === "string" && <p className="mt-3 border-l-2 border-slate-300 pl-3 text-xs leading-5 text-slate-700">{response.answer}</p>}</div></section>
    </div>
  </div>;
}

function PlanDetails({ entries, empty }: { entries: [string, unknown][]; empty: string }) {
  return <div className="mt-4">{entries.length ? <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-2">{entries.map(([key, value]) => <div key={key} className="min-w-0"><dt className="text-xs text-muted">{key}</dt><dd className="mt-0.5 break-words text-xs leading-5 text-ink">{displayValue(value)}</dd></div>)}</dl> : <p className="text-xs text-muted">{empty}</p>}</div>;
}

function SqlBlock({ sql, empty }: { sql?: string; empty: string }) {
  return <div className="mt-4"><h4 className="text-xs font-semibold text-muted">SQL</h4>{sql ? <pre className="mt-2 max-h-44 overflow-auto whitespace-pre-wrap break-words border border-line bg-slate-50 p-3 font-mono text-xs leading-5 text-slate-700">{sql}</pre> : <p className="mt-2 text-xs text-muted">{empty}</p>}</div>;
}

function ResultTable({ rows, empty }: { rows: Record<string, unknown>[]; empty: string }) {
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))].slice(0, 12);
  return <div className="mt-4"><h4 className="flex items-center gap-2 text-xs font-semibold text-muted"><TableProperties className="h-3.5 w-3.5" />结果预览</h4>{rows.length ? <div className="mt-2 overflow-x-auto border border-line"><table className="w-full min-w-max text-left text-xs"><thead className="bg-slate-50 text-muted"><tr>{columns.map((column) => <th key={column} className="whitespace-nowrap px-3 py-2 font-medium">{column}</th>)}</tr></thead><tbody>{rows.slice(0, 20).map((row, index) => <tr key={index} className="border-t border-line">{columns.map((column) => <td key={column} className="max-w-48 truncate px-3 py-2 text-ink" title={displayValue(row[column])}>{displayValue(row[column])}</td>)}</tr>)}</tbody></table></div> : <p className="mt-2 text-xs text-muted">{empty}</p>}</div>;
}

function ReviewedDecision({ item }: { item: ReviewItemDetail }) {
  return <div className="mt-4 border-l-2 border-emerald-600 bg-emerald-50 px-3 py-3 text-sm text-emerald-950"><div className="flex flex-wrap items-center gap-x-3 gap-y-1"><span className="font-medium">已裁定：{item.verdict ? verdictLabel[item.verdict] : "--"}</span><span>审核人：{item.reviewer_id ?? "--"}</span><span>严重程度：{item.severity ?? "--"}</span></div><p className="mt-2 text-xs">错误分类：{item.error_class ?? "--"}{item.reviewer_note ? `；${item.reviewer_note}` : ""}</p>{item.reviewed_at && <p className="mt-1 text-xs">提交时间：{new Date(item.reviewed_at).toLocaleString()}</p>}</div>;
}
