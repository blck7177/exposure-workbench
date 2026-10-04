"use client";

import React from "react";

import { getAnalystReport, type AnalystReport, type ReportRef } from "@/lib/api";

import { AnswerBlocks, type Block } from "./AnswerBlocks";

/**
 * What a specialist read, behind the answer.
 *
 * A turn has two kinds of writing in it. The lead's reply is the answer; behind
 * it, a specialist per task did its own reading and wrote it back in prose. Each
 * answer carries a chip per specialist, and opening one shows that reading drawn
 * like the answer: the same blocks, every supported figure opening the fact it
 * equals, with the observer's verification beside it. The chip says how the task
 * ended — returned, or stopped before it could write — because a task that
 * stopped is on the record as an attempt, not as a finding.
 */

/** The report a message's panel shows: the open one, and only when it is one
 *  of THIS message's. One panel is open at a time across the dock, so a chip
 *  clicked under one answer must not open a panel under every other. */
export function panelFor(open: ReportRef | null, reports?: ReportRef[]): ReportRef | null {
  if (!open || !reports?.some((r) => r.report_id === open.report_id)) return null;
  return open;
}

export function ReportChips({ reports, onOpen }: { reports?: ReportRef[]; onOpen: (r: ReportRef) => void }) {
  if (!reports?.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5 mt-1.5">
      {reports.map((r) => {
        const returned = r.status === "returned";
        return (
          <button
            key={r.report_id}
            type="button"
            onClick={() => onOpen(r)}
            title={returned
              ? "This specialist's reading, with the desk's verification of its figures. It does not certify that the question is complete."
              : "This task stopped before the specialist wrote its reading. What it read is on the record."}
            className={`font-mono text-[10px] rounded px-2 py-0.5 border transition-colors ${
              returned
                ? "text-teal-300 border-teal-800/60 bg-teal-950/40 hover:bg-teal-900/40"
                : "text-amber-400 border-amber-800/60 bg-amber-950/30 hover:bg-amber-900/30"
            }`}
          >
            {r.domain.replace(/_/g, " ")}
            <span aria-hidden className="ml-1.5 opacity-70">{returned ? "✓" : "—"}</span>
          </button>
        );
      })}
    </div>
  );
}

export function ReportPanel({
  sessionId, report, onClose, onOpenFact,
}: {
  sessionId: string;
  report: ReportRef;
  onClose: () => void;
  onOpenFact: (id: string) => void;
}) {
  const [full, setFull] = React.useState<AnalystReport | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  // No reset on the way in: the parent keys this component by report id, so a
  // different report is a different component and starts empty by construction.
  React.useEffect(() => {
    let live = true;
    getAnalystReport(sessionId, report.report_id)
      .then((r) => { if (live) setFull(r); })
      .catch(() => { if (live) setError("This report could not be opened."); });
    return () => { live = false; };
  }, [sessionId, report.report_id]);

  return <ReportPanelView report={report} full={full} error={error} onClose={onClose} onOpenFact={onOpenFact} />;
}

type Verification = { figures?: number; supported?: number; contradicted?: number; unsourced?: number; ambiguous?: number };

/** The panel as drawn from what has arrived — no fetch, so it can be rendered
 *  in a test for each of its states: opening, failed, returned, stopped. */
export function ReportPanelView({
  report, full, error, onClose, onOpenFact,
}: {
  report: ReportRef;
  full: AnalystReport | null;
  error: string | null;
  onClose: () => void;
  onOpenFact: (id: string) => void;
}) {
  const returned = full?.status === "returned";
  const stopReason = typeof full?.brief?.stop_reason === "string" ? full.brief.stop_reason : "";
  const v = (full?.verified ?? {}) as Verification;
  const problems = (v.contradicted ?? 0) + (v.unsourced ?? 0) + (v.ambiguous ?? 0);
  const analyses = (full?.brief?.analyses ?? []) as string[];

  return (
    <div className="border border-[#21262d] rounded-lg bg-[#12171f] text-[12px] text-slate-300">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[#21262d]">
        <span className="font-mono text-[10.5px] uppercase tracking-wide text-slate-500">
          {report.domain.replace(/_/g, " ")}
        </span>
        <span className={`font-mono text-[10px] ${returned ? "text-teal-400" : "text-amber-400"}`}>
          {full ? (returned ? "returned" : "stopped") : "…"}
        </span>
        <button type="button" onClick={onClose}
          className="ml-auto text-slate-500 hover:text-slate-300 text-[11px]">Close</button>
      </div>

      <div className="p-3 flex flex-col gap-3">
        {error && <p className="text-amber-400">{error}</p>}
        {!full && !error && <p className="text-slate-600">Opening…</p>}

        {full && full.title && <p className="text-slate-200">{full.title}</p>}

        {full && returned && full.blocks?.length > 0 && (
          <AnswerBlocks blocks={full.blocks as Block[]} onOpen={onOpenFact} />
        )}
        {full && returned && !(full.blocks?.length > 0) && full.text && (
          <p className="whitespace-pre-wrap">{full.text}</p>
        )}

        {full && returned && (
          <p className={`font-mono text-[10.5px] ${problems ? "text-amber-400" : "text-slate-500"}`}>
            {(v.figures ?? 0) === 0
              ? "No figures to check."
              : `${v.supported ?? 0} of ${v.figures} figures supported by the desk's analyses${problems ? `; ${problems} did not hold` : ""}.`}
            {analyses.length > 0 && ` ${analyses.length} analysis${analyses.length === 1 ? "" : "es"} recorded.`}
          </p>
        )}

        {full && !returned && (
          <div className="text-amber-200/80">
            <p>The task stopped before the specialist wrote its reading{stopReason ? `: ${stopReason.replace(/_/g, " ")}` : ""}.</p>
            {analyses.length > 0 && <p className="text-slate-400">What it analysed is on the record ({analyses.length} analysis{analyses.length === 1 ? "" : "es"}).</p>}
          </div>
        )}
      </div>
    </div>
  );
}
