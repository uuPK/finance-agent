import { AlertCircle, CheckCircle2, Circle, Clock3, HelpCircle, PauseCircle } from "lucide-react";

import type { AgentStep, RunStatus } from "../types/query";

type Status = AgentStep["status"] | RunStatus;

const statusMeta: Record<string, { label: string; className: string; icon: typeof Circle }> = {
  queued: { label: "排队中", className: "bg-slate-100 text-slate-700", icon: Clock3 },
  pending: { label: "待执行", className: "bg-slate-100 text-slate-700", icon: Circle },
  running: { label: "进行中", className: "bg-blue-50 text-blue-700", icon: Clock3 },
  passed: { label: "已通过", className: "bg-emerald-50 text-emerald-700", icon: CheckCircle2 },
  completed: { label: "已完成", className: "bg-emerald-50 text-emerald-700", icon: CheckCircle2 },
  failed: { label: "未通过", className: "bg-red-50 text-red-700", icon: AlertCircle },
  skipped: { label: "已跳过", className: "bg-slate-100 text-slate-600", icon: PauseCircle },
  needs_clarification: { label: "待确认", className: "bg-amber-50 text-amber-800", icon: HelpCircle },
  interrupted: { label: "已中断", className: "bg-orange-50 text-orange-700", icon: PauseCircle }
};

export function StatusBadge({ status }: { status: Status }) {
  const meta = statusMeta[status] ?? statusMeta.pending;
  const Icon = meta.icon;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium ${meta.className}`}>
      <Icon className={`h-3.5 w-3.5 ${status === "running" ? "animate-spin" : ""}`} />
      {meta.label}
    </span>
  );
}
