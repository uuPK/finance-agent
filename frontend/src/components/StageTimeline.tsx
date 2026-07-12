import { ChevronRight } from "lucide-react";

import type { QueryEvent } from "../types/query";
import { stageLabels } from "../lib/stages";
import { StatusBadge } from "./StatusBadge";

export function StageTimeline({
  events,
  selectedId,
  onSelect
}: {
  events: QueryEvent[];
  selectedId?: number;
  onSelect: (event: QueryEvent) => void;
}) {
  return (
    <ol className="divide-y divide-line">
      {events.map((event) => {
        const selected = selectedId === event.event_id;
        return (
          <li key={event.event_id}>
            <button
              type="button"
              onClick={() => onSelect(event)}
              className={`grid w-full grid-cols-[28px_1fr_auto] gap-2 px-4 py-3 text-left transition-colors ${selected ? "bg-blue-50/70" : "hover:bg-slate-50"}`}
            >
              <span className="mt-1 flex h-6 w-6 items-center justify-center rounded bg-slate-100 text-xs font-semibold text-slate-600">
                {event.attempt + 1}
              </span>
              <span className="min-w-0">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-ink">{stageLabels[event.stage] ?? event.stage}</span>
                  <StatusBadge status={event.status} />
                </span>
                <span className="mt-1 block text-xs leading-5 text-muted">{event.summary}</span>
              </span>
              <ChevronRight className="mt-2 h-4 w-4 text-slate-400" />
            </button>
          </li>
        );
      })}
    </ol>
  );
}
