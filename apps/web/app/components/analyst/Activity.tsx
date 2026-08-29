"use client";

import { Loader2 } from "lucide-react";

import type { AgentStep } from "@/lib/issuer";
import { AuditOnly, useAudit } from "../audit";

/**
 * What the analyst did on a turn (V13-S4/S6).
 *
 * The panel this replaces printed `get_portfolio_snapshot`, `evaluate_formula`,
 * `respond`, `gpt-5.4-mini-2026-03-17: 1 tool call` and `8963 in / 412 out`.
 * Every line true, none of it addressed to the person watching their own
 * question being worked on.
 *
 * The steps come with a `display` phrase the server renders from the call's own
 * arguments, and it is null for the rows that are not actions — an llm_call is
 * what the turn cost, a refusal is a call that did not happen. Those belong to
 * the audit layer, and dropping them here is what makes this list exactly the
 * things that were done.
 *
 * It stays after the answer, collapsed. Before this it appeared while the turn
 * was running and vanished when it finished, so the one moment a reader might
 * ask "how did it get that" was the one moment there was nothing to look at.
 */
export function Activity({ steps, seconds, running }: {
  steps: AgentStep[];
  seconds?: number | null;
  running?: boolean;
}) {
  const { audit } = useAudit();
  const actions = steps.filter((s) => s.display);
  const refused = steps.filter((s) => s.status === "rejected").length;
  if (actions.length === 0 && !running) return null;

  return (
    <details open={running} className="rounded border border-[#21262d] bg-[#11161d] text-[11.5px]">
      <summary className="flex items-center gap-2 px-2.5 py-1.5 cursor-pointer text-slate-500 select-none list-none">
        {running ? (
          <Loader2 className="w-3 h-3 animate-spin text-blue-400" />
        ) : (
          <span aria-hidden className="font-mono">▸</span>
        )}
        <span>
          {running ? "Working" : "Activity"} · {actions.length} step{actions.length === 1 ? "" : "s"}
        </span>
        {refused > 0 && (
          <span title="Look-ups the turn asked for after its allowance was spent"
            className="text-amber-500/80">· {refused} refused</span>
        )}
        {seconds != null && (
          <span className="ml-auto font-mono text-[10.5px]">{seconds}s</span>
        )}
      </summary>
      <ol className="px-3 pb-2 pt-0.5 m-0 list-decimal list-inside text-slate-400 space-y-1">
        {actions.map((s) => (
          <li key={s.seq} className="leading-snug">
            {s.display}
            <AuditOnly>
              <span className="block font-mono text-[10px] text-slate-600 pl-4">
                {s.tool_name ?? s.step_type}
                {s.evidence_refs?.length ? ` → ${s.evidence_refs.length} refs` : ""}
              </span>
            </AuditOnly>
          </li>
        ))}
      </ol>
      {audit && (
        <ol className="px-3 pb-2 m-0 border-t border-[#21262d] pt-1.5 font-mono text-[10px] text-slate-600 space-y-0.5">
          {steps.filter((s) => !s.display).map((s) => (
            <li key={`a-${s.seq}`}>
              {s.step_type}
              {s.tool_name ? ` · ${s.tool_name}` : ""}
              {s.status !== "completed" ? ` · ${s.status}` : ""}
              {s.result_summary ? ` · ${s.result_summary}` : ""}
              {s.prompt_tokens != null || s.completion_tokens != null
                ? ` · ${s.prompt_tokens ?? 0} in / ${s.completion_tokens ?? 0} out`
                : ""}
            </li>
          ))}
        </ol>
      )}
    </details>
  );
}
