import { ArrowRight, Download, MessageSquareWarning, RotateCcw, Send, Sparkles, Square, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createQueryRun,
  downloadQueryExport,
  getQueryRun,
  submitClarifications,
  submitQueryReview,
  subscribeToQueryRun
} from "../api/client";
import { ArtifactView } from "../components/ArtifactView";
import { StageTimeline } from "../components/StageTimeline";
import { StatusBadge } from "../components/StatusBadge";
import { getClientId } from "../lib/clientId";
import type { QueryEvent, QueryExportFormat, QueryRunSnapshot } from "../types/query";

const examples = [
  "查询当前资产大于50万的客户数量",
  "查询近三个月交易次数超过3次且当前资产大于50万的客户列表",
  "找出近三个月资产净流入明显但尚未持有基金产品的客户"
];

const terminalStatuses = new Set(["completed", "failed", "needs_clarification", "interrupted"]);
const lastEvent = (items: QueryEvent[]) => items[items.length - 1];

export function QueryWorkbench({
  activeRunId,
  onRunChange
}: {
  activeRunId: string | null;
  onRunChange: (queryId: string | null) => void;
}) {
  const [question, setQuestion] = useState(examples[0]);
  const [run, setRun] = useState<QueryRunSnapshot | null>(null);
  const [events, setEvents] = useState<QueryEvent[]>([]);
  const [selectedId, setSelectedId] = useState<number>();
  const [submitting, setSubmitting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewReason, setReviewReason] = useState("");
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const [reviewNotice, setReviewNotice] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const closeStreamRef = useRef<(() => void) | null>(null);
  const manualSelectionRef = useRef(false);

  const selectedEvent = useMemo(
    () => events.find((event) => event.event_id === selectedId) ?? lastEvent(events),
    [events, selectedId]
  );
  const timelineEvents = useMemo(() => {
    const latestByStage = new Map<string, QueryEvent>();
    events.forEach((event) => latestByStage.set(`${event.attempt}:${event.stage}`, event));
    return [...latestByStage.values()].sort((left, right) => left.event_id - right.event_id);
  }, [events]);

  const mergeEvent = useCallback((event: QueryEvent) => {
    setError(null);
    setReviewNotice("");
    setEvents((current) => {
      if (current.some((item) => item.event_id === event.event_id)) return current;
      return [...current, event].sort((left, right) => left.event_id - right.event_id);
    });
    setRun((current) =>
      current
        ? {
            ...current,
            current_stage: event.stage,
            status:
              event.type === "run.completed"
                ? "completed"
                : event.type === "run.failed"
                  ? "failed"
                  : event.type === "clarification.required"
                    ? "needs_clarification"
                    : "running"
          }
        : current
    );
    if (!manualSelectionRef.current) setSelectedId(event.event_id);
    if (["run.completed", "run.failed", "clarification.required"].includes(event.type)) {
      closeStreamRef.current?.();
      void getQueryRun(event.query_id).then((snapshot) => {
        setRun(snapshot);
        setEvents(snapshot.events);
        setSelectedId(lastEvent(snapshot.events)?.event_id);
      });
    }
  }, []);

  const connect = useCallback(
    (queryId: string, after: number) => {
      closeStreamRef.current?.();
      closeStreamRef.current = subscribeToQueryRun(
        queryId,
        after,
        mergeEvent,
        () => setError("实时连接暂时中断，系统会自动重连")
      );
    },
    [mergeEvent]
  );

  const loadRun = useCallback(
    async (queryId: string) => {
      setError(null);
      const snapshot = await getQueryRun(queryId);
      setRun(snapshot);
      setQuestion(snapshot.question);
      setEvents(snapshot.events);
      setSelectedId(lastEvent(snapshot.events)?.event_id);
      manualSelectionRef.current = false;
      if (!terminalStatuses.has(snapshot.status)) {
        connect(queryId, lastEvent(snapshot.events)?.event_id ?? 0);
      }
    },
    [connect]
  );

  useEffect(() => {
    if (activeRunId) void loadRun(activeRunId).catch((reason) => setError(String(reason)));
    return () => closeStreamRef.current?.();
  }, [activeRunId, loadRun]);

  async function handleRun() {
    if (!question.trim()) return;
    setSubmitting(true);
    setError(null);
    setRun(null);
    setEvents([]);
    setSelectedId(undefined);
    manualSelectionRef.current = false;
    try {
      const created = await createQueryRun(question.trim(), getClientId());
      onRunChange(created.query_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法启动查询");
    } finally {
      setSubmitting(false);
    }
  }

  function clearCurrentRun() {
    closeStreamRef.current?.();
    closeStreamRef.current = null;
    setRun(null);
    setEvents([]);
    setSelectedId(undefined);
    setError(null);
    manualSelectionRef.current = false;
    onRunChange(null);
  }

  async function handleClarification() {
    if (!run?.response?.query_plan?.clarifications) return;
    const payload = run.response.query_plan.clarifications.map((item) => ({
      field: item.field,
      value: answers[item.field]?.trim() ?? ""
    }));
    if (payload.some((item) => !item.value)) {
      setError("请完成所有需要确认的业务口径");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await submitClarifications(run.query_id, payload);
      setAnswers({});
      await loadRun(run.query_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "提交补充信息失败");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleExport(format: QueryExportFormat) {
    if (!run || run.status !== "completed") return;
    setExporting(true);
    setError(null);
    try {
      await downloadQueryExport(run.query_id, getClientId(), format);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法导出完整查询结果");
    } finally {
      setExporting(false);
    }
  }

  async function handleSubmitReview() {
    if (!run || run.status !== "completed") return;
    setReviewSubmitting(true);
    setError(null);
    try {
      const result = await submitQueryReview(run.query_id, getClientId(), reviewReason.trim() || undefined);
      const snapshot = await getQueryRun(run.query_id);
      setRun(snapshot);
      setReviewOpen(false);
      setReviewReason("");
      setReviewNotice(result.already_submitted ? "该结果已经在人工审核队列中。" : "已提交人工审核，复核人员将查看本次查询的计划、SQL 和结果。" );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "提交人工审核失败");
    } finally {
      setReviewSubmitting(false);
    }
  }

  const clarifications = run?.status === "needs_clarification" ? run.response?.query_plan?.clarifications ?? [] : [];

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col bg-surface lg:min-h-screen">
      <section className="border-b border-line bg-white px-4 py-4 sm:px-6">
        <div className="mx-auto max-w-[1500px]">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-xl font-semibold text-ink">智能问数</h1>
              <p className="mt-1 text-sm text-muted">可信查询过程与业务结果同步呈现</p>
            </div>
            <div className="flex items-center gap-2">
              {run?.status === "completed" ? (
                <button
                  type="button"
                  onClick={() => setReviewOpen(true)}
                  disabled={run.review_status === "pending" || run.review_status === "reviewed"}
                  className="inline-flex h-9 items-center gap-2 border border-line bg-white px-3 text-sm text-ink hover:bg-slate-50 disabled:cursor-default disabled:bg-slate-50 disabled:text-muted"
                >
                  <MessageSquareWarning className="h-4 w-4" />
                  {run.review_status === "reviewed" ? "已审核" : run.review_status === "pending" ? "审核中" : "提交审核"}
                </button>
              ) : null}
              {run?.status === "completed" ? (
                <label className="relative inline-flex h-9 items-center gap-2 border border-line bg-white px-2 text-sm text-ink hover:bg-slate-50">
                  <Download className="h-4 w-4" />
                  <select
                    aria-label="导出完整查询结果"
                    disabled={exporting}
                    value=""
                    onChange={(event) => {
                      const format = event.target.value as QueryExportFormat;
                      if (format) void handleExport(format);
                    }}
                    className="appearance-none bg-transparent pr-4 text-sm outline-none disabled:opacity-50"
                  >
                    <option value="" disabled>{exporting ? "正在导出" : "导出结果"}</option>
                    <option value="xlsx">Excel (.xlsx)</option>
                    <option value="csv">CSV (.csv)</option>
                    <option value="json">JSON (.json)</option>
                  </select>
                </label>
              ) : null}
              {run ? <StatusBadge status={run.status} /> : null}
            </div>
          </div>
          <div className="flex items-end gap-2 border border-line bg-white p-2 focus-within:border-accent">
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) void handleRun();
              }}
              rows={2}
              placeholder="输入客户、资产、交易或产品相关问题"
              className="min-h-14 flex-1 resize-none border-0 px-2 py-2 text-sm leading-6 outline-none"
            />
            <button
              type="button"
              onClick={handleRun}
              disabled={submitting || !question.trim()}
              title="运行查询"
              className="inline-flex h-10 items-center gap-2 rounded bg-accent px-4 text-sm font-medium text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Send className="h-4 w-4" />{submitting ? "提交中" : "运行"}
            </button>
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {examples.map((example) => (
              <button key={example} type="button" onClick={() => setQuestion(example)} className="rounded border border-line bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600 hover:border-slate-400 hover:bg-white">
                {example}
              </button>
            ))}
          </div>
          {error ? <div className="mt-3 border-l-2 border-red-500 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}
          {reviewNotice ? <div className="mt-3 border-l-2 border-teal-600 bg-teal-50 px-3 py-2 text-sm text-teal-900">{reviewNotice}</div> : null}
        </div>
      </section>

      {events.length ? (
        <main className="mx-auto grid w-full max-w-[1500px] flex-1 grid-cols-1 border-x border-line bg-white lg:grid-cols-[360px_minmax(0,1fr)]">
          <aside className="border-b border-line lg:border-b-0 lg:border-r">
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold text-ink">执行过程</h2>
                <p className="mt-0.5 text-xs text-muted">{timelineEvents.length} 个阶段 · {events.length} 条事件</p>
              </div>
              <div className="flex gap-1">
                <button type="button" title="回到最新步骤" onClick={() => { manualSelectionRef.current = false; setSelectedId(lastEvent(events)?.event_id); }} className="grid h-8 w-8 place-items-center rounded hover:bg-slate-100"><ArrowRight className="h-4 w-4" /></button>
                <button type="button" title="停止查看并清空当前视图" onClick={clearCurrentRun} className="grid h-8 w-8 place-items-center rounded hover:bg-slate-100"><Square className="h-4 w-4" /></button>
              </div>
            </div>
            <div className="max-h-[42vh] overflow-auto lg:max-h-[calc(100vh-260px)]"><StageTimeline events={timelineEvents} selectedId={selectedEvent?.event_id} onSelect={(event) => { setSelectedId(event.event_id); manualSelectionRef.current = true; }} /></div>
          </aside>
          <section className="min-w-0 overflow-auto"><ArtifactView event={selectedEvent} /></section>
        </main>
      ) : (
        <main className="grid flex-1 place-items-center px-6 py-16 text-center">
          <div className="max-w-md">
            <span className="mx-auto grid h-12 w-12 place-items-center rounded bg-teal-50 text-accent"><Sparkles className="h-6 w-6" /></span>
            <h2 className="mt-4 text-base font-semibold text-ink">准备开始可信查询</h2>
            <p className="mt-2 text-sm leading-6 text-muted">提交问题后，这里会实时展示元数据检索、查询计划、SQL 审核、执行与结果检查。</p>
          </div>
        </main>
      )}

      {clarifications.length ? (
        <section className="sticky bottom-0 z-20 border-t border-amber-200 bg-amber-50 px-4 py-4 sm:px-6">
          <div className="mx-auto max-w-[1500px]">
            <div className="mb-3 flex items-center gap-2"><RotateCcw className="h-4 w-4 text-amber-700" /><h2 className="text-sm font-semibold text-amber-950">需要确认业务口径</h2></div>
            <div className="grid gap-4 lg:grid-cols-2">
              {clarifications.map((item) => (
                <div key={item.field}>
                  <label className="text-sm font-medium text-amber-950">{item.question}</label>
                  <p className="mt-1 text-xs text-amber-800">{item.reason}</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {item.options.map((option) => (
                      <button key={option} type="button" onClick={() => setAnswers((current) => ({ ...current, [item.field]: option }))} className={`rounded border px-2.5 py-1.5 text-xs ${answers[item.field] === option ? "border-amber-700 bg-amber-700 text-white" : "border-amber-300 bg-white text-amber-900"}`}>{option}</button>
                    ))}
                  </div>
                  <input value={answers[item.field] ?? ""} onChange={(event) => setAnswers((current) => ({ ...current, [item.field]: event.target.value }))} placeholder="选择或输入明确口径" className="mt-2 h-9 w-full border border-amber-300 bg-white px-3 text-sm outline-none focus:border-amber-700" />
                </div>
              ))}
            </div>
            <button type="button" onClick={handleClarification} disabled={submitting} className="mt-4 inline-flex items-center gap-2 rounded bg-amber-800 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">继续查询<ArrowRight className="h-4 w-4" /></button>
          </div>
        </section>
      ) : null}

      {reviewOpen && run ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 px-4" role="dialog" aria-modal="true" aria-labelledby="review-dialog-title">
          <section className="w-full max-w-lg border border-line bg-white shadow-xl">
            <div className="flex items-start justify-between border-b border-line px-4 py-3">
              <div>
                <h2 id="review-dialog-title" className="text-sm font-semibold text-ink">提交人工审核</h2>
                <p className="mt-1 text-xs text-muted">复核人员将看到本次查询的脱敏计划、SQL、审核证据与结果。</p>
              </div>
              <button type="button" onClick={() => setReviewOpen(false)} title="关闭" className="grid h-8 w-8 place-items-center hover:bg-slate-100"><X className="h-4 w-4" /></button>
            </div>
            <div className="p-4">
              <p className="border-l-2 border-slate-300 pl-3 text-sm text-ink">{run.question}</p>
              <label className="mt-4 block text-xs font-medium text-muted">异议理由（可选）
                <textarea
                  value={reviewReason}
                  onChange={(event) => setReviewReason(event.target.value)}
                  maxLength={2000}
                  placeholder="例如：客户数量与业务台账不一致；也可以不填写直接提交。"
                  className="mt-1 min-h-28 w-full resize-y border border-line p-3 text-sm leading-6 text-ink outline-none focus:border-accent"
                />
              </label>
            </div>
            <div className="flex justify-end gap-2 border-t border-line px-4 py-3">
              <button type="button" onClick={() => setReviewOpen(false)} className="h-9 border border-line px-3 text-sm text-ink">取消</button>
              <button type="button" onClick={() => void handleSubmitReview()} disabled={reviewSubmitting} className="inline-flex h-9 items-center gap-2 bg-slate-900 px-3 text-sm font-medium text-white disabled:opacity-50"><MessageSquareWarning className="h-4 w-4" />{reviewSubmitting ? "提交中" : "提交审核"}</button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
