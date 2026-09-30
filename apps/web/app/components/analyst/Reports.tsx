"use client";

import React from "react";

import { getAnalystReport, type AnalystReport, type ReportRef } from "@/lib/api";

import { AnswerBlocks, type Block } from "./AnswerBlocks";

/**
 * What a domain analyst read, behind the answer (V36).
 *
 * A turn now has two kinds of writing in it. The lead analyst's reply is the
 * answer; behind it, one domain analyst per topic did the work and wrote up its
 * own reading. The reply states what the question asked for and nothing more,
 * which is right — and it means the reasoning that produced it used to have
 * nowhere to live.
 *
 * So each answer carries a chip per analyst, and opening one shows that
 * analyst's report rendered exactly like the answer: same blocks, same figures,
 * each opening the fact it equals. The chip says whether the report passed the
 * same check the answer passed, because a report that did not is on the record
 * as an attempt and must not read as a finding — a refused one shows what went
 * wrong with it instead of its prose.
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
      {reports.map((r) => (
        <button
          key={r.report_id}
          type="button"
          onClick={() => onOpen(r)}
          title={r.status === "returned" || r.status === "stopped"
            ? "Retrieved evidence and checked notes. This does not certify that the question is complete."
            : r.status === "verified"
            ? "This analyst's full reading, checked against the same evidence as the answer."
            : "This analyst's reading did not pass the check. It is on the record; its figures are not quotable."}
          className={`font-mono text-[10px] rounded px-2 py-0.5 border transition-colors ${
            r.status === "verified"
              ? "text-teal-300 border-teal-800/60 bg-teal-950/40 hover:bg-teal-900/40"
              : "text-amber-400 border-amber-800/60 bg-amber-950/30 hover:bg-amber-900/30"
          }`}
        >
          {r.domain.replace(/_/g, " ")}
          <span aria-hidden className="ml-1.5 opacity-70">{r.status === "verified" ? "✓" : "—"}</span>
        </button>
      ))}
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
  // Clearing state inside the effect would render the old report once first.
  React.useEffect(() => {
    let live = true;
    getAnalystReport(sessionId, report.report_id)
      .then((r) => { if (live) setFull(r); })
      .catch(() => { if (live) setError("This report could not be opened."); });
    return () => { live = false; };
  }, [sessionId, report.report_id]);

  return <ReportPanelView report={report} full={full} error={error} onClose={onClose} onOpenFact={onOpenFact} />;
}

/** The panel as drawn from what has arrived — no fetch, so it can be rendered
 *  in a test for each of its states: opening, failed, checked, refused. */
export function ReportPanelView({
  report, full, error, onClose, onOpenFact,
}: {
  report: ReportRef;
  full: AnalystReport | null;
  error: string | null;
  onClose: () => void;
  onOpenFact: (id: string) => void;
}) {
  const findings = (full?.brief?.findings ?? []) as { want: number; finding: string }[];
  const notDone = (full?.brief?.not_done ?? []) as { want: number; why: string }[];
  const caveats = (full?.brief?.caveats ?? []) as string[];
  const evidenceHandoff = full?.brief?.protocol === "evidence-v2";
  const evidence = (evidenceHandoff ? full?.brief?.evidence ?? [] : []) as { id: string; row: string }[];
  const stopReason = typeof full?.brief?.stop_reason === "string" ? full.brief.stop_reason : "";
  const stopped = evidenceHandoff && stopReason !== "submitted";

  return (
    <div className="border border-[#21262d] rounded-lg bg-[#12171f] text-[12px] text-slate-300">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[#21262d]">
        <span className="font-mono text-[10.5px] uppercase tracking-wide text-slate-500">
          {report.domain.replace(/_/g, " ")}
        </span>
        <span className={`font-mono text-[10px] ${full?.status === "verified" ? "text-teal-400" : "text-amber-400"}`}>
          {full ? (evidenceHandoff ? (stopped ? "stopped" : "returned") : full.status === "verified" ? "checked" : "not checked") : "…"}
        </span>
        <button type="button" onClick={onClose}
          className="ml-auto text-slate-500 hover:text-slate-300 text-[11px]">Close</button>
      </div>

      <div className="p-3 flex flex-col gap-3">
        {error && <p className="text-amber-400">{error}</p>}
        {!full && !error && <p className="text-slate-600">Opening…</p>}

        {full && full.title && <p className="text-slate-200">{full.title}</p>}

        {!evidenceHandoff && findings.length > 0 && (
          <ol className="flex flex-col gap-1.5 list-none p-0 m-0">
            {findings.map((f) => (
              <li key={f.want} className="flex gap-2">
                <span className="font-mono text-[10px] text-slate-600 pt-0.5">{f.want}</span>
                <span>{f.finding}</span>
              </li>
            ))}
          </ol>
        )}

        {!evidenceHandoff && notDone.length > 0 && (
          <div className="flex flex-col gap-1">
            <span className="font-mono text-[10px] uppercase tracking-wide text-slate-500">Not settled</span>
            {notDone.map((d) => (
              <p key={d.want} className="text-slate-400">{d.why}</p>
            ))}
          </div>
        )}

        {(full?.status === "verified" || evidenceHandoff) && full && full.blocks?.length > 0 && (
          <div className="border-t border-[#21262d] pt-3">
            <AnswerBlocks blocks={full.blocks as Block[]} onOpen={onOpenFact} />
          </div>
        )}

        {evidenceHandoff && (
          <>
            <p className="text-slate-400">Evidence and checked notes from this task. The question may still need further analysis.</p>
            {stopped && <p className="text-amber-200/80">The task stopped: {stopReason.replace(/_/g, " ")}. Retrieved evidence and accepted notes remain available.</p>}
            {evidence.length > 0 && <ul className="flex flex-col gap-2 list-none p-0 m-0">
              {evidence.map((e) => <li key={e.id}>
                <button type="button" onClick={() => onOpenFact(e.id)} className="text-left text-teal-300 hover:underline break-words">
                  {e.row.replace(/^\[f_[^\]]+\]\s*/, "")}
                </button>
              </li>)}
            </ul>}
            {!!full?.problems?.length && <p className="text-amber-200/80">Some submitted items did not pass checks and are omitted.</p>}
          </>
        )}

        {full && !evidenceHandoff && full.status !== "verified" && (
          <div className="border-t border-amber-900/40 pt-3 text-amber-200/80">
            <p>The desk did not accept this reading, so its text is not shown.</p>
            {full.problems?.length > 0 && (
              <ul className="mt-1 font-mono text-[10.5px] text-amber-400/80 list-none p-0">
                {full.problems.slice(0, 5).map((p: { reason?: string }, i: number) => (
                  <li key={i}>{p.reason}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {!evidenceHandoff && caveats.length > 0 && (
          <div className="border-t border-[#21262d] pt-2 text-slate-500">
            {caveats.map((c, i) => <p key={i}>{c}</p>)}
          </div>
        )}
      </div>
    </div>
  );
}
