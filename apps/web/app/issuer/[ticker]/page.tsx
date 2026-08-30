"use client";

import { Suspense, use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, ExternalLink, FileText, Loader2, Play } from "lucide-react";

import { AuditOnly } from "../../components/audit";
import { AuthGate } from "../../components/Auth";
import { useDockContext } from "../../components/analyst/Dock";
import { AnswerText, idsIn } from "../../components/analyst/AnswerText";
import { CitationList } from "../../components/evidence/Cite";
import { useEvidence } from "../../components/evidence/Column";
import { fmtDate, fmtMoney, fmtPct } from "../../components/charts/frame";
import {
  BriefProvenance, Coverage, PriceVsBenchmark, Windows,
} from "../../components/issuer/panels";
import { getPositions } from "@/lib/api";
import {
  getCitationMap, getCoverage, getEvidenceLabels, getPriceIndex, getWindows,
  type CitationMap as CitationMapData, type CoverageRow, type EvidenceLabel,
  type PriceIndex, type ReportedWindows,
} from "@/lib/charts";
import { explainApiError, explainRunError } from "@/lib/errors";
import {
  getFilings, getFinancials, getLatestBrief, getResearchRun, getResearchSources,
  getSection, getSnapshot, startResearch,
  type Brief, type CalcRow, type FilingRow, type ResearchRun, type Snapshot, type SourceRow,
} from "@/lib/issuer";
import { collapseSteps, stepPhrase } from "../../components/steps";
import type { Position } from "@/lib/types";

/**
 * An issuer (V13-S6c).
 *
 * The tabs are the same five questions as before; what changed is that four of
 * them now answer with the engine's own structure instead of a list of
 * identifiers. Snapshot listed 33 metric chips with a period count each, which
 * answers neither "can you answer my question about this company" nor "how far
 * back does this go". Financials listed rows with `calc 2b5395` beside them.
 *
 * The most consequential panel is the window ladder, and it corrected me: I had
 * assumed two filings meant a quarterly series full of holes. They do not.
 * Apple's December quarter is the fiscal year minus its nine months — a figure
 * no filing states and this engine derives exactly — so the honest distinction
 * is reported versus derived, not held versus missing.
 */

const TABS = ["Overview", "Financials", "Filings", "Brief"] as const;
type Tab = (typeof TABS)[number];

// useSearchParams below bails the client tree out of prerendering up to the
// closest Suspense boundary, and a production build with no such boundary fails
// outright rather than degrading. The boundary is this shell, which renders the
// page's own background so the bail-out cannot flash white.
export default function IssuerPage({ params }: { params: Promise<{ ticker: string }> }) {
  return (
    <Suspense fallback={<div className="flex-1 bg-[#0d1117]" />}>
      <IssuerView params={params} />
    </Suspense>
  );
}

function IssuerView({ params }: { params: Promise<{ ticker: string }> }) {
  const { ticker } = use(params);
  const tk = ticker.toUpperCase();
  // Which book the reader came from. Absent is a real answer — a hand-typed
  // URL, an anonymous visitor, someone with no portfolio yet — and stays
  // absent: the literal demo id this used to send made every run a signed-in
  // user started read as the demo's, and the brief reasoned about the wrong
  // holdings.
  const portfolioId = useSearchParams().get("portfolio") ?? undefined;

  const [tab, setTab] = useState<Tab>("Overview");
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState<PriceIndex | null>(null);
  const [coverage, setCoverage] = useState<CoverageRow[] | null>(null);
  // The whole run, not just its status: the timeline and the failure sentence
  // both arrive on it, and one poll already carries all three.
  const [run, setRun] = useState<ResearchRun | null>(null);
  const runId = run?.id ?? null;
  const runStatus = run?.status ?? null;

  const { setContext } = useDockContext();
  useEffect(() => {
    setContext({ kind: "issuer", ticker: tk, name: snap?.company.name ?? null });
  }, [tk, snap?.company.name, setContext]);

  // explainApiError, not e.message: this branch is how `API 404:
  // {"detail":{"error":"unknown_ticker","ticker":"FOOBAR"}}` came to be rendered
  // in a red bar to anyone who mistyped a symbol — while lib/errors.ts already
  // held a sentence for that exact code, written for exactly this reader.
  useEffect(() => {
    let ignore = false;
    getSnapshot(tk).then((s) => { if (!ignore) setSnap(s); })
      .catch((e) => { if (!ignore) setError(explainApiError(e).notice); });
    getPriceIndex(tk).then((i) => { if (!ignore) setIndex(i); }).catch(() => setIndex(null));
    getCoverage(tk).then((c) => { if (!ignore) setCoverage(c.measures); }).catch(() => setCoverage([]));
    return () => { ignore = true; };
  }, [tk]);

  const runResearch = async () => {
    setError(null);
    try {
      setRun(await startResearch(tk, portfolioId));
    } catch (e) {
      setError(explainApiError(e).notice);
    }
  };

  // A poll that throws used to be an unhandled rejection, and the timeline
  // simply stopped moving on whatever step it had reached. It keeps polling
  // rather than giving up on the first failure — a worker restart is a normal
  // few seconds — but it will not stay quiet: after two consecutive failures
  // the panel says the state may be out of date, which is the honest
  // description of what is on screen.
  const [staleSince, setStaleSince] = useState(0);
  useEffect(() => {
    if (!runId || runStatus === "completed" || runStatus === "failed") return;
    const iv = setInterval(async () => {
      try {
        const r = await getResearchRun(runId);
        setStaleSince(0);
        setRun(r);
        if (r.status === "completed" || r.status === "failed") clearInterval(iv);
      } catch {
        setStaleSince((n) => n + 1);
      }
    }, 3000);
    return () => clearInterval(iv);
  }, [runId, runStatus]);

  const e = snap?.portfolio_exposure;
  const working = !!runStatus && runStatus !== "completed" && runStatus !== "failed";

  return (
    <>
      {portfolioId && <BookRail portfolioId={portfolioId} current={tk} />}

      <main className="flex-1 min-w-0 overflow-y-auto">
        <div className="max-w-[1180px] mx-auto px-5 py-4 flex flex-col gap-3">
          {/* who this is */}
          <div className="flex items-start gap-4 flex-wrap">
            <div className="min-w-0">
              <Link href="/"
                className="inline-flex items-center gap-1 text-[11.5px] text-slate-500 hover:text-slate-300">
                <ArrowLeft className="w-3 h-3" /> Back to the book
              </Link>
              <h1 className="text-lg font-semibold text-slate-100 mt-1">
                {snap?.company.name ?? tk}
                <span className="ml-2 font-mono text-sm text-slate-500">{tk}</span>
              </h1>
              <p className="text-[11.5px] text-slate-500 mt-0.5">
                {[snap?.company.industry || snap?.company.sector, snap?.company.exchange]
                  .filter(Boolean).join(" · ")}
                {e && <> · in this book <span className="text-slate-400">{fmtMoney(e.market_value)}</span>
                  {e.weight != null && <> · {fmtPct(e.weight, 2)}</>}</>}
              </p>
              <AuditOnly>
                <span className="block mt-1 font-mono text-[10px] text-slate-600">
                  CIK {snap?.company.cik ?? "—"}{portfolioId ? ` · ${portfolioId}` : ""}
                </span>
              </AuditOnly>
            </div>
            <div className="ml-auto flex items-center gap-2">
              {snap?.latest_filing?.source_url && (
                <a href={snap.latest_filing.source_url} target="_blank" rel="noreferrer"
                  className="flex items-center gap-1.5 rounded-md border border-[#30363d] px-2.5 py-1.5 text-[11.5px] text-slate-300 hover:border-slate-500">
                  Open the {snap.latest_filing.form_type} <ExternalLink className="w-3 h-3" />
                </a>
              )}
              <AuthGate fallback={<span className="text-[11px] text-slate-600">Sign in to research</span>}>
                <button onClick={runResearch} disabled={working}
                  className="flex items-center gap-1.5 rounded-md bg-blue-600 hover:bg-blue-500 disabled:opacity-40 px-3 py-1.5 text-xs font-medium text-white">
                  {working ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                  {working ? "Researching…" : "Refresh the brief"}
                </button>
              </AuthGate>
            </div>
          </div>

          {error && (
            <p className="rounded-md border border-amber-900/60 bg-amber-950/25 px-3 py-2 text-[12px] text-amber-300">
              {error}
            </p>
          )}

          {/* The panel appears as soon as a run exists and STAYS once it settles.
              It does not auto-hide: a timer would race the reader's attention, and
              on a failed run this is the only place the reason is written. */}
          {run && <ResearchProgress run={run} stale={staleSince >= 2} />}

          <div className="flex gap-1 border-b border-[#21262d]">
            {TABS.map((t) => (
              <button key={t} onClick={() => setTab(t)}
                className={`px-3 py-1.5 text-[12.5px] border-b-2 -mb-px transition-colors ${
                  tab === t ? "border-blue-500 text-slate-100" : "border-transparent text-slate-500 hover:text-slate-300"}`}>
                {t}
              </button>
            ))}
          </div>

          {tab === "Overview" && (
            <div className="flex flex-col gap-3">
              {index && <PriceVsBenchmark index={index} />}
              {coverage && coverage.length > 0 && <Coverage rows={coverage} />}
              {coverage?.length === 0 && (
                <p className="text-xs text-slate-500 py-8 text-center">
                  Nothing is ingested for {tk} yet — refresh the brief to read its filings.
                </p>
              )}
            </div>
          )}
          {tab === "Financials" && <FinancialsTab ticker={tk} coverage={coverage ?? []} />}
          {tab === "Filings" && <FilingsTab ticker={tk} />}
          {tab === "Brief" && <BriefTab ticker={tk} runStatus={runStatus} />}
          <div className="h-6" />
        </div>
      </main>
    </>
  );
}

// ── the book you came from, as a way back into it ────────────────────────────

function BookRail({ portfolioId, current }: { portfolioId: string; current: string }) {
  const [positions, setPositions] = useState<Position[]>([]);
  useEffect(() => {
    let ignore = false;
    getPositions(portfolioId).then((p) => { if (!ignore) setPositions(p); }).catch(() => {});
    return () => { ignore = true; };
  }, [portfolioId]);
  if (positions.length === 0) return null;
  return (
    <nav className="w-[228px] shrink-0 border-r border-[#21262d] bg-[#0d1117] overflow-y-auto"
      aria-label="Holdings of the book you came from">
      <div className="px-3 pt-3 pb-1.5 font-mono text-[10px] uppercase tracking-wider text-slate-600">
        Holdings
      </div>
      {[...positions]
        .sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0))
        .map((p) => (
          <Link key={p.id} href={`/issuer/${p.ticker}?portfolio=${portfolioId}`}
            className={`px-3 py-1 flex items-baseline gap-2 border-l-2 ${
              p.ticker === current
                ? "border-blue-500 bg-[#161b22]"
                : "border-transparent hover:bg-[#11161d]"}`}>
            <span className="font-mono text-[11.5px] text-slate-300 w-12 shrink-0">{p.ticker}</span>
            <span className="text-[10.5px] text-slate-600 tabular-nums ml-auto">
              {fmtMoney(p.market_value)}
            </span>
          </Link>
        ))}
    </nav>
  );
}

// ── a research run, while it is happening ────────────────────────────────────

function ResearchProgress({ run, stale }: { run: ResearchRun; stale: boolean }) {
  const steps = collapseSteps(run.workflow_events ?? []);
  const done = steps.filter((e) => e.status !== "running");
  const failed = run.status === "failed";
  return (
    <section className={`rounded-lg border px-4 py-3 ${
      failed ? "border-red-900/60 bg-red-950/20" : "border-[#21262d] bg-[#11161d]"}`}>
      <div className="flex items-center gap-2">
        {!failed && run.status !== "completed" && <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-400" />}
        <span className="text-[12.5px] text-slate-300">
          {failed ? "Research stopped"
            : run.status === "completed" ? "Research finished"
            : "Reading filings and current sources"}
        </span>
        <span className="text-[11px] text-slate-500">
          {done.length > 0 ? `step ${done.length}` : "queued — a worker picks this up within a few seconds"}
        </span>
      </div>
      {failed && (
        <p className="mt-1.5 text-[12px] text-red-300">
          {explainRunError(run.error_code, run.error_message)}
        </p>
      )}
      {steps.length > 0 && (
        <ol className="mt-1.5 flex flex-col gap-0.5 text-[11.5px] text-slate-500 max-h-44 overflow-y-auto">
          {steps.map((e) => (
            <li key={e.id} className="flex items-baseline gap-2">
              <span aria-hidden className={
                e.status === "failed" ? "text-amber-500"
                : e.status === "running" ? "text-blue-400"
                : "text-emerald-600"}>
                {e.status === "failed" ? "✕" : e.status === "running" ? "•" : "✓"}
              </span>
              <span className={`flex-1 ${e.status === "failed" ? "text-amber-400" : ""}`}>
                {stepPhrase(e)}
              </span>
            </li>
          ))}
        </ol>
      )}
      {stale && (
        <p className="mt-1.5 text-[10.5px] text-amber-400/80">
          Lost contact with the run — what is above may be out of date. Reload to check.
        </p>
      )}
      <AuditOnly>
        <span className="block mt-2 font-mono text-[10px] text-slate-600 break-all">
          {run.id}{run.error_code ? ` · ${run.error_code}` : ""}
          {run.agent_session_id ? ` · ${run.agent_session_id}` : ""}
        </span>
      </AuditOnly>
    </section>
  );
}

// ── financials ───────────────────────────────────────────────────────────────

function FinancialsTab({ ticker, coverage }: { ticker: string; coverage: CoverageRow[] }) {
  const flows = coverage.filter((c) => c.kind === "flow");
  const [metric, setMetric] = useState("revenue");
  const [windows, setWindows] = useState<ReportedWindows | null>(null);
  const [calcs, setCalcs] = useState<CalcRow[] | null>(null);
  const { open } = useEvidence();

  useEffect(() => {
    let ignore = false;
    getWindows(ticker, metric).then((w) => { if (!ignore) setWindows(w); }).catch(() => setWindows(null));
    return () => { ignore = true; };
  }, [ticker, metric]);
  useEffect(() => {
    getFinancials(ticker).then((d) => setCalcs(d.calcs)).catch(() => setCalcs([]));
  }, [ticker]);

  const options = flows.length > 0
    ? flows.map((f) => ({ metric: f.metric, label: f.label }))
    : [{ metric: "revenue", label: "Revenue" }];

  return (
    <div className="flex flex-col gap-3">
      {windows && (
        <Windows data={windows} metrics={options} metric={metric} onMetric={setMetric} />
      )}
      {calcs && calcs.length > 0 && (
        <section className="rounded-lg border border-[#21262d] bg-[#11161d]">
          <header className="flex items-center gap-2 px-4 py-2.5 border-b border-[#21262d]">
            <h3 className="text-sm font-medium text-slate-200">Baseline measures</h3>
            <span className="text-[11px] text-slate-500">{calcs.length} · every one a ledgered calculation</span>
          </header>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[10px] uppercase tracking-wide text-slate-500">
                  <th className="text-left font-medium py-1.5 px-4">Measure</th>
                  <th className="text-right font-medium py-1.5 px-2">Latest</th>
                  <th className="text-left font-medium py-1.5 px-2">Period</th>
                  <th className="text-left font-medium py-1.5 px-4">Basis</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#21262d]">
                {calcs.map((r, i) => {
                  const label = r.display ?? r.label ?? r.operation;
                  if (r.unavailable) {
                    return (
                      <tr key={`u${i}`}>
                        <td className="py-1.5 px-4 text-slate-500">{label}</td>
                        <td className="py-1.5 px-2 text-slate-600 text-[11px]" colSpan={3}>{r.unavailable}</td>
                      </tr>
                    );
                  }
                  return (
                    <tr key={r.calc_id ?? `c${i}`} className="hover:bg-[#161b22]">
                      <td className="py-1.5 px-4 text-slate-300">{label}</td>
                      <td className="py-1.5 px-2 text-right tabular-nums text-slate-100">{money(latestVal(r))}</td>
                      <td className="py-1.5 px-2 text-slate-500">{fmtDate(latestPeriod(r)) || "—"}</td>
                      <td className="py-1.5 px-4">
                        {r.calc_id && (
                          <button onClick={() => open(r.calc_id as string)}
                            className="text-[11px] text-teal-400 hover:text-teal-300 hover:underline">
                            how this was worked out
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {coverage.length > 0 && <Coverage rows={coverage} />}
    </div>
  );
}

function money(v: number | null): string {
  if (v == null) return "—";
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) < 1 && v !== 0) return `${(v * 100).toFixed(2)}%`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/** The latest point of a calc series, or the scalar value. */
function latestVal(r: CalcRow): number | null {
  if (r.result?.value !== undefined) return r.result.value;
  const pts = r.result?.points;
  if (Array.isArray(pts) && pts.length) return pts[pts.length - 1].value;
  return null;
}
function latestPeriod(r: CalcRow): string {
  const pts = r.result?.points;
  // v2 series points end on `end` (a window) or `as_of` (an instant); v1 rows used period_end.
  if (Array.isArray(pts) && pts.length) {
    const p = pts[pts.length - 1];
    return p.end ?? p.as_of ?? p.period_end ?? "";
  }
  return "";
}

// ── filings ──────────────────────────────────────────────────────────────────

function FilingsTab({ ticker }: { ticker: string }) {
  const [filings, setFilings] = useState<FilingRow[] | null>(null);
  const [sec, setSec] = useState<{ title: string; item_code: string; text: string } | null>(null);
  useEffect(() => { getFilings(ticker).then((d) => setFilings(d.filings)).catch(() => setFilings([])); }, [ticker]);
  if (!filings) return <p className="text-xs text-slate-500 py-6">Loading…</p>;
  if (filings.length === 0) {
    return <p className="text-xs text-slate-500 py-8 text-center">
      No filings are ingested for {ticker} — refresh the brief to read them.
    </p>;
  }
  return (
    <div className="flex gap-3 min-h-[420px]">
      <div className="w-64 shrink-0 flex flex-col gap-2">
        {filings.map((f) => (
          <div key={f.accession} className="rounded-lg border border-[#21262d] bg-[#11161d] p-3">
            <div className="flex items-center gap-2 text-[12.5px]">
              <FileText className="w-3.5 h-3.5 text-slate-500" />
              <span className="font-medium text-slate-200">{f.form_type}</span>
              <span className="text-[11px] text-slate-500">{fmtDate(f.filing_date)}</span>
            </div>
            <div className="mt-1.5 flex flex-col">
              {f.sections.map((s) => (
                <button key={s.id} onClick={() => getSection(s.id).then(setSec)}
                  className="text-left text-[11px] text-slate-400 hover:text-teal-300 truncate py-0.5">
                  {s.item_code} <span className="text-slate-600">{s.title}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="flex-1 min-w-0 rounded-lg border border-[#21262d] bg-[#11161d] p-4 overflow-y-auto max-h-[70vh]">
        {sec ? (
          <>
            <h3 className="text-[12.5px] font-medium text-slate-200 mb-2">{sec.item_code} · {sec.title}</h3>
            <p className="text-[11.5px] text-slate-400 whitespace-pre-wrap leading-relaxed">
              {sec.text.slice(0, 20000)}
            </p>
          </>
        ) : (
          <p className="text-xs text-slate-500">Choose a section to read it.</p>
        )}
      </div>
    </div>
  );
}

// ── the brief ────────────────────────────────────────────────────────────────

function BriefTab({ ticker, runStatus }: { ticker: string; runStatus: string | null }) {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [map, setMap] = useState<CitationMapData | null>(null);
  const [sources, setSources] = useState<SourceRow[]>([]);
  const [labels, setLabels] = useState<Record<string, EvidenceLabel>>({});
  const { open } = useEvidence();

  const load = useCallback(() => {
    getLatestBrief(ticker).then((d) => { setBrief(d.brief); setLoaded(true); }).catch(() => setLoaded(true));
    getCitationMap(ticker).then(setMap).catch(() => setMap(null));
    getResearchSources(ticker).then((d) => setSources(d.sources)).catch(() => setSources([]));
  }, [ticker]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (runStatus === "completed") load(); }, [runStatus, load]);

  // One request for every caption on the page, rather than one per chip.
  useEffect(() => {
    if (!brief) return;
    const ids = idsIn(
      [brief.financial_summary, brief.key_changes, brief.management_explanation,
       brief.market_context, brief.portfolio_implications, brief.open_questions]
        .filter(Boolean).join("\n"),
      brief.citations);
    if (ids.length === 0) return;
    let ignore = false;
    getEvidenceLabels(ids).then((r) => { if (!ignore) setLabels(r.labels); }).catch(() => {});
    return () => { ignore = true; };
  }, [brief]);

  if (!loaded) return <p className="text-xs text-slate-500 py-6">Loading…</p>;

  const blocks: [string, string | null][] = brief ? [
    ["Financial summary", brief.financial_summary],
    ["Key changes", brief.key_changes],
    ["What management said", brief.management_explanation],
    ["Market and industry context", brief.market_context],
    ["What it means for this book", brief.portfolio_implications],
    ["Open questions", brief.open_questions],
  ] : [];

  return (
    <div className="flex flex-col gap-3">
      {map && map.sections.length > 0 && <BriefProvenance map={map} />}

      {!brief ? (
        <p className="text-xs text-slate-500 py-8 text-center">
          No brief for {ticker} yet — refresh the brief to have one written.
        </p>
      ) : (
        <section className="rounded-lg border border-[#21262d] bg-[#11161d]">
          <header className="flex items-center gap-3 px-4 py-2.5 border-b border-[#21262d]">
            <h3 className="text-sm font-medium text-slate-200">Issuer brief</h3>
            <span className="text-[11px] text-slate-500">
              {brief.citations.length} citations · {fmtDate(brief.created_at)}
            </span>
            <AuditOnly>
              <span className="ml-auto font-mono text-[10px] text-slate-600">
                {brief.id} · {brief.research_run_id}
              </span>
            </AuditOnly>
          </header>
          <div className="px-4 py-3 flex flex-col gap-4 text-[12.5px] text-slate-300">
            {blocks.filter(([, body]) => body).map(([title, body]) => (
              <div key={title}>
                <h4 className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">{title}</h4>
                <AnswerText text={body as string} citations={brief.citations}
                  labels={labels} onOpen={open} />
              </div>
            ))}
            <CitationList citations={brief.citations} labels={labels} onOpen={open} />
          </div>
        </section>
      )}

      {sources.length > 0 && (
        <section className="rounded-lg border border-[#21262d] bg-[#11161d]">
          <header className="flex items-center gap-2 px-4 py-2.5 border-b border-[#21262d]">
            <h3 className="text-sm font-medium text-slate-200">External sources</h3>
            <span className="text-[11px] text-slate-500">{sources.length}</span>
          </header>
          <ul className="divide-y divide-[#21262d]">
            {sources.map((s) => (
              <li key={s.id} className="px-4 py-2.5">
                <a href={s.url} target="_blank" rel="noreferrer"
                  className="text-[12.5px] text-teal-400 hover:text-teal-300 hover:underline inline-flex items-baseline gap-1">
                  {s.title || s.url} <ExternalLink className="w-3 h-3 shrink-0 self-center" />
                </a>
                <p className="text-[10.5px] text-slate-500 mt-0.5">
                  {[s.publisher, s.published_date ? fmtDate(s.published_date) : null]
                    .filter(Boolean).join(" · ")}
                </p>
                {s.snippet && <p className="text-[11.5px] text-slate-400 mt-1 line-clamp-2">{s.snippet}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
