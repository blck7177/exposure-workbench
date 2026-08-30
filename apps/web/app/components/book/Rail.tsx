"use client";

import { useState } from "react";
import Link from "next/link";
import { Copy, Loader2, Plus, Upload } from "lucide-react";

import { AuditOnly } from "../audit";
import { fmtDate, fmtMoney } from "../charts/frame";
import { cloneDemoPortfolio } from "@/lib/api";
import { explainApiError } from "@/lib/errors";
import type { ExposureRunSummary, IssuerExposure, Portfolio } from "@/lib/types";

/**
 * The rail (V13-S6c).
 *
 * Three lists, and the third is the one that changed the page: the holdings are
 * here as links, so a book is a way into its issuers rather than a table you
 * read and then navigate away from by hand. The old rail listed books and runs
 * and nothing else, and the issuer pages — the deepest part of this product —
 * were reachable only by typing a URL.
 *
 * Runs are dated, not identified. A reader picking "Aug 20 · 3 warnings" is
 * choosing a day; `run_95ebe31c5e51` was choosing a row, and only the operator
 * has any use for that. It is one AuditOnly line away.
 */

function Section({ title, action, children }: {
  title: string; action?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <div className="pb-2">
      <div className="flex items-center gap-1 px-3 pt-3 pb-1.5">
        <span className="font-mono text-[10px] uppercase tracking-wider text-slate-600">{title}</span>
        {action}
      </div>
      {children}
    </div>
  );
}

export function Rail({
  portfolios, selectedId, onSelect, runs, selectedRunId, onSelectRun,
  issuers, ownsNothing, onNewBook, onCreated,
}: {
  portfolios: Portfolio[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  runs: ExposureRunSummary[];
  selectedRunId: string | null;
  onSelectRun: (id: string) => void;
  issuers: IssuerExposure[];
  ownsNothing: boolean;
  onNewBook: () => void;
  onCreated: (p: Portfolio) => void;
}) {
  return (
    <nav className="w-[228px] shrink-0 border-r border-[#21262d] bg-[#0d1117] overflow-y-auto flex flex-col"
      aria-label="Books and holdings">
      <Section title="Books" action={
        <button onClick={onNewBook} title="New book"
          className="ml-auto text-slate-600 hover:text-slate-300">
          <Plus className="w-3.5 h-3.5" />
        </button>
      }>
        {portfolios.map((p) => (
          <button key={p.id} onClick={() => onSelect(p.id)}
            className={`w-full text-left px-3 py-1.5 flex flex-col gap-0.5 border-l-2 transition-colors ${
              p.id === selectedId
                ? "border-blue-500 bg-[#161b22]"
                : "border-transparent hover:bg-[#11161d]"}`}>
            <span className="text-[12.5px] text-slate-200 truncate flex items-center gap-1.5">
              {p.name}
              {p.is_public && !p.is_own && (
                <span className="shrink-0 text-[9px] uppercase tracking-wide text-slate-500 border border-[#30363d] rounded px-1">
                  shared
                </span>
              )}
            </span>
            <span className="text-[10.5px] text-slate-500 truncate">
              {p.currency}{p.benchmark ? ` · vs ${p.benchmark}` : ""}
            </span>
          </button>
        ))}
        {ownsNothing && <FirstRun onCreated={onCreated} onUploadCsv={onNewBook} />}
      </Section>

      {runs.length > 0 && (
        <Section title="Updates">
          {runs.slice(0, 8).map((r) => (
            <button key={r.id} onClick={() => onSelectRun(r.id)}
              className={`w-full text-left px-3 py-1.5 flex flex-col gap-0.5 border-l-2 transition-colors ${
                r.id === selectedRunId
                  ? "border-blue-500 bg-[#161b22]"
                  : "border-transparent hover:bg-[#11161d]"}`}>
              <span className="text-[12px] text-slate-300 flex items-center gap-1.5">
                {fmtDate(r.as_of_date)}
                {r.status !== "completed" && (
                  <span className={`text-[9.5px] uppercase tracking-wide ${
                    r.status === "failed" ? "text-red-400" : "text-blue-400"}`}>
                    {r.status}
                  </span>
                )}
              </span>
              <AuditOnly>
                <span className="font-mono text-[9.5px] text-slate-600 truncate">
                  {r.id} · {r.triggered_by ?? "unrecorded"}
                </span>
              </AuditOnly>
            </button>
          ))}
        </Section>
      )}

      {issuers.length > 0 && (
        <Section title="Holdings">
          {[...issuers]
            .sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0))
            .map((i) => (
              <Link key={i.ticker} href={`/issuer/${i.ticker}${selectedId ? `?portfolio=${selectedId}` : ""}`}
                className="px-3 py-1 flex items-baseline gap-2 hover:bg-[#11161d] border-l-2 border-transparent">
                <span className="font-mono text-[11.5px] text-slate-300 w-12 shrink-0">{i.ticker}</span>
                <span className="text-[10.5px] text-slate-600 tabular-nums ml-auto">
                  {fmtMoney(i.market_value)}
                </span>
              </Link>
            ))}
        </Section>
      )}
    </nav>
  );
}

/**
 * The way in, for someone who has just signed up (V7-U2).
 *
 * The list a new account sees is never empty — RLS answers "mine plus public",
 * so the shared demo book is always in it — which made the rail look like a
 * populated desk and left no place to say "start here".
 */
function FirstRun({ onCreated, onUploadCsv }: {
  onCreated: (p: Portfolio) => void;
  onUploadCsv: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const clone = async () => {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    try {
      onCreated(await cloneDemoPortfolio());
    } catch (e) {
      // Shown, not logged and forgotten: this is the single action the card
      // exists for, and a button that quietly does nothing is a worse first
      // minute than the bare list it replaced.
      setNotice(explainApiError(e).notice);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="m-2 rounded-lg border border-dashed border-[#30363d] bg-[#11161d] p-2.5">
      <p className="text-[11px] text-slate-400 leading-relaxed">
        Nothing here is yours yet — the book above is the shared demo. Take a copy, or bring your own holdings.
      </p>
      <div className="mt-2.5 flex flex-col gap-1.5">
        <button onClick={clone} disabled={busy}
          className="w-full flex items-center justify-center gap-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-xs font-medium py-1.5 rounded-md transition-colors">
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Copy className="w-3.5 h-3.5" />}
          Copy the demo
        </button>
        <button onClick={onUploadCsv}
          className="w-full flex items-center justify-center gap-1.5 border border-[#30363d] hover:bg-white/5 text-slate-300 text-xs py-1.5 rounded-md transition-colors">
          <Upload className="w-3.5 h-3.5" /> Upload holdings
        </button>
      </div>
      {notice && <p className="mt-2 text-[10px] text-amber-400 leading-snug">{notice}</p>}
    </div>
  );
}
