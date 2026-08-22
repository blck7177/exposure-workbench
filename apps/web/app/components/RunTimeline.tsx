"use client";

import { CheckCircle2, Loader2, AlertTriangle, Clock } from "lucide-react";
import { formatDuration, statusColor } from "@/lib/formatting";

/**
 * The outer timeline of a run, wherever a run is being watched (V7).
 *
 * Extracted from the portfolio page so the issuer page can show the same thing:
 * both are a person waiting on a worker, and the exposure run was the only one
 * that told them anything. Shared rather than copied because the collapse below
 * is a decision, not formatting — a second copy would drift the moment one page
 * learned about a step type the other had not met yet.
 */

export type TimelineEvent = {
  id: number;
  step_name: string;
  status: string;
  message: string | null;
  duration_ms: number | null;
  payload_summary?: Record<string, unknown>;
};

export function StepIcon({ status }: { status: string }) {
  if (status === "completed") return <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />;
  if (status === "running")   return <Loader2 className="w-4 h-4 text-blue-400 animate-spin shrink-0" />;
  if (status === "failed")    return <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />;
  return <Clock className="w-4 h-4 text-slate-500 shrink-0" />;
}

/**
 * One row per step name, keeping the LAST event for each.
 *
 * A step emits a row when it starts and another when it ends, and a retried
 * step emits more; showing them all makes a five-step pipeline look like eleven
 * and puts a stale "running" under the "completed" that replaced it.
 */
export function collapseSteps(events: TimelineEvent[]): TimelineEvent[] {
  return Object.values(
    events.reduce<Record<string, TimelineEvent>>((acc, ev) => {
      acc[ev.step_name] = ev;
      return acc;
    }, {})
  );
}

export function RunTimeline({
  events, emptyText = "Waiting for worker...",
}: {
  events: TimelineEvent[];
  emptyText?: string;
}) {
  const steps = collapseSteps(events);
  if (steps.length === 0) return <p className="text-xs text-slate-600">{emptyText}</p>;

  return (
    <div className="space-y-2">
      {steps.map((ev) => (
        <div key={ev.id} className="flex items-start gap-2">
          <StepIcon status={ev.status} />
          <div className="min-w-0 flex-1">
            <p className="text-xs text-slate-300 leading-tight">{ev.message || ev.step_name}</p>
            <div className="flex items-center gap-2 mt-0.5">
              <span className={`text-[10px] ${statusColor(ev.status)}`}>{ev.status}</span>
              {ev.duration_ms && (
                <span className="text-[10px] text-slate-600">{formatDuration(ev.duration_ms)}</span>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
