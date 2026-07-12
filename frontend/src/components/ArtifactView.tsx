import { AlertTriangle, CheckCircle2, Code2, Database, FileJson2 } from "lucide-react";

import type { QueryEvent, QueryResponse } from "../types/query";
import { stageLabels } from "../lib/stages";
import { ResultTable } from "./ResultTable";
import { StatusBadge } from "./StatusBadge";

export function ArtifactView({ event }: { event?: QueryEvent }) {
  if (!event) {
    return <div className="grid h-full place-items-center p-10 text-sm text-muted">选择一个步骤查看阶段产物</div>;
  }
  const response = event.output.response as QueryResponse | undefined;
  const rows = (event.output.result_preview as Array<Record<string, unknown>> | undefined) ?? response?.result_preview;
  const sql = (event.output.sql as string | undefined) ?? response?.sql;
  const queryPlan = event.output.query_plan ?? response?.query_plan;
  const checks = (event.output.checks as Array<Record<string, unknown>> | undefined) ?? [];

  return (
    <div className="min-w-0">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <p className="text-xs font-medium text-muted">阶段产物 · 第 {event.attempt + 1} 次尝试</p>
          <h2 className="mt-1 text-base font-semibold text-ink">{stageLabels[event.stage] ?? event.stage}</h2>
          <p className="mt-1 text-sm text-muted">{event.summary}</p>
        </div>
        <StatusBadge status={event.status} />
      </header>

      <div className="space-y-6 p-5">
        {response ? (
          <section>
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink">
              <CheckCircle2 className="h-4 w-4 text-emerald-600" />查询回答
            </div>
            <p className="border-l-2 border-emerald-500 pl-4 text-sm leading-7 text-slate-700">{response.answer}</p>
          </section>
        ) : null}

        {rows ? (
          <section>
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink">
              <Database className="h-4 w-4 text-blue-600" />结果数据
              <span className="font-normal text-muted">{rows.length} 行预览</span>
            </div>
            <ResultTable rows={rows} />
          </section>
        ) : null}

        {sql ? (
          <section>
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink"><Code2 className="h-4 w-4 text-violet-600" />SQL</div>
            <pre className="max-h-80 overflow-auto border border-line bg-slate-950 p-4 text-xs leading-6 text-slate-100"><code>{sql}</code></pre>
          </section>
        ) : null}

        {checks.length ? (
          <section>
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink"><AlertTriangle className="h-4 w-4 text-amber-600" />检查结果</div>
            <div className="divide-y divide-line border border-line">
              {checks.map((check, index) => (
                <div key={index} className="px-4 py-3 text-sm">
                  <div className="font-medium text-ink">{String(check.error_type ?? check.stage ?? `检查 ${index + 1}`)}</div>
                  <div className="mt-1 leading-6 text-muted">{String(check.reason ?? "已完成检查")}</div>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {queryPlan ? <JsonArtifact title="QueryPlan" value={queryPlan} /> : null}
        {!response && !rows && !sql && !checks.length && !queryPlan ? <JsonArtifact title="结构化输出" value={event.output} /> : null}
      </div>
    </div>
  );
}

function JsonArtifact({ title, value }: { title: string; value: unknown }) {
  return (
    <section>
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink"><FileJson2 className="h-4 w-4 text-slate-600" />{title}</div>
      <pre className="max-h-96 overflow-auto border border-line bg-slate-50 p-4 text-xs leading-6 text-slate-700">{JSON.stringify(value, null, 2)}</pre>
    </section>
  );
}
