"use client";

import { useEffect, useState, useCallback, use, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Play, Loader2, FileText, ExternalLink } from "lucide-react";
import {
  getSnapshot, getFinancials, getFilings, getSection, getResearchSources, getLatestBrief,
  startResearch, getResearchRun,
  type Snapshot, type CalcRow, type FilingRow, type SourceRow, type Brief, type ResearchRun,
} from "../../../lib/issuer";
import { explainApiError } from "../../../lib/errors";
import { CitationChip, EvidenceDrawer } from "../../components/Evidence";
import { RunTimeline } from "../../components/RunTimeline";
import { ChatPanel } from "../../components/ChatPanel";

const TABS = ["Snapshot", "Financials", "Filings", "Research", "Brief"] as const;
type Tab = (typeof TABS)[number];

function fmt(v: unknown): string {
  if (typeof v !== "number") return v == null ? "—" : String(v);
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) < 1 && v !== 0) return `${(v * 100).toFixed(2)}%`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

// latest point of a calc series result, or the scalar value
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

// useSearchParams below bails the client tree out of prerendering up to the
// closest Suspense boundary, and a production build with no such boundary fails
// outright rather than degrading. The boundary is this shell, which renders the
// page's own background so the bail-out cannot flash white.
export default function IssuerPage({ params }: { params: Promise<{ ticker: string }> }) {
  return (
    <Suspense fallback={<div className="h-screen bg-[#0d1117]" />}>
      <IssuerView params={params} />
    </Suspense>
  );
}

function IssuerView({ params }: { params: Promise<{ ticker: string }> }) {
  const { ticker } = use(params);
  const tk = ticker.toUpperCase();
  // Which book the reader came from. Absent is a real answer — a hand-typed URL,
  // an anonymous visitor, someone with no portfolio yet — and stays absent: the
  // literal demo id this used to send made every run a signed-in user started
  // read as the demo's, and the brief reasoned about the wrong holdings.
  const portfolioId = useSearchParams().get("portfolio") ?? undefined;
  const [tab, setTab] = useState<Tab>("Snapshot");
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The whole run, not just its status: the timeline and the failure sentence
  // both arrive on it, and one poll already carries all three.
  const [run, setRun] = useState<ResearchRun | null>(null);
  const runId = run?.id ?? null;
  const runStatus = run?.status ?? null;

  useEffect(() => { getSnapshot(tk).then(setSnap).catch((e) => setError(e.message)); }, [tk]);

  const runResearch = async () => {
    setError(null);
    try {
      setRun(await startResearch(tk, portfolioId));
    } catch (e) {
      setError(explainApiError(e).notice);
    }
  };

  // A poll that throws used to be an unhandled rejection, and the timeline
  // simply stopped moving on whatever step it had reached. That was survivable
  // when the page showed a spinner; now that the steps ARE the narrative, a
  // frozen one is worse than no narrative, because it reads as a run that hung
  // rather than a page that lost contact.
  //
  // It keeps polling rather than giving up on the first failure: a worker
  // restart or a brief 503 is a normal few seconds, and abandoning a live run
  // over one would be the more common wrong answer. What it will not do is stay
  // quiet — after two consecutive failures the panel says the state may be out
  // of date, which is the honest description of what is on screen.
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

  return (
    <div className="h-screen flex flex-col bg-[#0d1117] text-[#e6edf3]">
      <header className="h-12 border-b border-[#21262d] flex items-center px-4 gap-3 shrink-0">
        <Link href="/" className="text-slate-400 hover:text-slate-200 flex items-center gap-1 text-sm">
          <ArrowLeft className="w-4 h-4" /> Portfolio
        </Link>
        <div className="h-4 w-px bg-[#21262d]" />
        <span className="font-semibold">{tk}</span>
        <span className="text-sm text-slate-500">{snap?.company.name}</span>
        {snap?.company.sector && <span className="text-xs text-slate-600 px-2 py-0.5 rounded border border-[#21262d]">{snap.company.industry || snap.company.sector}</span>}
        <div className="ml-auto flex items-center gap-2">
          {runStatus && runStatus !== "completed" && runStatus !== "failed" && (
            <span className="text-xs text-amber-400 flex items-center gap-1"><Loader2 className="w-3 h-3 animate-spin" /> research {runStatus}…</span>
          )}
          {runStatus === "completed" && <span className="text-xs text-emerald-400">research complete</span>}
          {runStatus === "failed" && <span className="text-xs text-red-400">research failed</span>}
          <button onClick={runResearch} disabled={!!runStatus && runStatus !== "completed" && runStatus !== "failed"}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-sm">
            <Play className="w-3.5 h-3.5" /> Run research
          </button>
        </div>
      </header>

      {error && <div className="px-4 py-2 text-xs text-red-400 bg-red-950/30 border-b border-red-900/40">{error}</div>}

      {/* The panel appears as soon as a run exists and STAYS once it settles.
          Both halves are about someone who looked away: before the first event
          lands there is nothing to show but the fact that the run was accepted,
          so it says that rather than rendering an empty box, which reads as a
          click that missed; and it does not auto-hide, because a timer would
          race the reader's attention and on a failed run this is the only place
          the reason is written. Starting the next run replaces it. */}
      {run && (
        <div className="px-4 py-3 border-b border-[#21262d] shrink-0">
          <div className="text-[10px] uppercase text-slate-500 mb-2">Research run</div>
          <div className="max-h-48 overflow-y-auto">
            <RunTimeline events={run.workflow_events}
              emptyText="Queued — a worker picks this up within a few seconds." />
          </div>
          {run.status === "failed" && run.error_message && (
            <div className="mt-2 text-xs text-red-300">{run.error_message}</div>
          )}
          {staleSince >= 2 && (
            <div className="mt-2 text-[10px] text-amber-400/80">
              Lost contact with the run — the steps above may be out of date. Reload to check.
            </div>
          )}
        </div>
      )}

      <div className="border-b border-[#21262d] flex px-4 gap-1 shrink-0">
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-3 py-2 text-sm border-b-2 -mb-px ${tab === t ? "border-blue-500 text-slate-100" : "border-transparent text-slate-500 hover:text-slate-300"}`}>{t}</button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        {tab === "Snapshot" && <SnapshotTab snap={snap} />}
        {tab === "Financials" && <FinancialsTab ticker={tk} />}
        {tab === "Filings" && <FilingsTab ticker={tk} />}
        {tab === "Research" && <ResearchTab ticker={tk} />}
        {tab === "Brief" && <BriefTab ticker={tk} runStatus={runStatus} />}
      </div>

      <EvidenceDrawer />
      <ChatPanel />
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border border-[#21262d] rounded-lg p-4 bg-[#0d1117]">
      <div className="text-[10px] uppercase text-slate-500 mb-2">{title}</div>
      {children}
    </div>
  );
}

function SnapshotTab({ snap }: { snap: Snapshot | null }) {
  if (!snap) return <div className="text-slate-500 text-sm">loading…</div>;
  const e = snap.portfolio_exposure;
  return (
    <div className="grid grid-cols-2 gap-4 max-w-4xl">
      <Card title="Company">
        <div className="space-y-1 text-sm">
          <Row k="Name" v={snap.company.name} />
          <Row k="CIK" v={snap.company.cik} />
          <Row k="Exchange" v={snap.company.exchange} />
          <Row k="Industry" v={snap.company.industry} />
        </div>
      </Card>
      <Card title="Latest filing">
        {snap.latest_filing ? (
          <div className="space-y-1 text-sm">
            <Row k="Form" v={snap.latest_filing.form_type} />
            <Row k="Filed" v={snap.latest_filing.filing_date} />
            <div className="pt-1"><a href={snap.latest_filing.source_url || "#"} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline text-xs flex items-center gap-1">{snap.latest_filing.accession} <ExternalLink className="w-3 h-3" /></a></div>
          </div>
        ) : <div className="text-slate-600 text-sm">not ingested — run research</div>}
      </Card>
      <Card title="Portfolio exposure">
        {e ? (
          <div className="space-y-1 text-sm">
            <Row k="Market value" v={fmt(e.market_value)} />
            <Row k="Weight" v={fmt(e.weight)} />
          </div>
        ) : <div className="text-slate-600 text-sm">no exposure recorded</div>}
      </Card>
      <Card title="Available financial data">
        <div className="flex flex-wrap gap-1">
          {snap.available_metrics.map((m) => (
            <span key={m.metric} className="text-[10px] px-1.5 py-0.5 rounded border border-[#21262d] text-slate-400">{m.metric} <span className="opacity-50">{m.periods}</span></span>
          ))}
        </div>
      </Card>
    </div>
  );
}

function Row({ k, v }: { k: string; v: unknown }) {
  return <div className="flex gap-2"><span className="text-slate-500 w-28 shrink-0">{k}</span><span className="text-slate-200">{v == null ? "—" : String(v)}</span></div>;
}

function FinancialsTab({ ticker }: { ticker: string }) {
  const [calcs, setCalcs] = useState<CalcRow[] | null>(null);
  useEffect(() => { getFinancials(ticker).then((d) => setCalcs(d.calcs)).catch(() => setCalcs([])); }, [ticker]);
  if (!calcs) return <div className="text-slate-500 text-sm">loading…</div>;
  if (calcs.length === 0) return <div className="text-slate-600 text-sm">No baseline metrics yet — run research to compute them.</div>;
  return (
    <div className="max-w-3xl">
      <div className="text-xs text-slate-500 mb-3">Every value is a ledgered calculation — click its chip to trace the inputs.</div>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-slate-500 text-xs border-b border-[#21262d]"><th className="py-1.5">Metric</th><th>Latest</th><th>Period</th><th>Evidence</th></tr></thead>
        <tbody>
          {calcs.map((r) => {
            // V10: the recipe names its rows; the operation-derived label is the fallback for v1 rows.
            const label = r.label ?? `${r.operation}${r.params?.series?.metric ? ` · ${r.params.series.metric}` : r.params?.a?.metric ? ` · ${r.params.a.metric}/${r.params.b?.metric}` : ""}`;
            if (r.unavailable) {
              return (
                <tr key={label} className="border-b border-[#161b22]">
                  <td className="py-1.5 text-slate-500 font-mono text-xs">{label}</td>
                  <td className="text-slate-600 text-xs" colSpan={3}>unavailable — {r.unavailable}</td>
                </tr>
              );
            }
            return (
              <tr key={r.calc_id ?? label} className="border-b border-[#161b22]">
                <td className="py-1.5 text-slate-300 font-mono text-xs">{label}</td>
                <td className="text-slate-100">{fmt(latestVal(r))}</td>
                <td className="text-slate-500 text-xs">{latestPeriod(r)}</td>
                <td>{r.calc_id ? <CitationChip id={r.calc_id} /> : null}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function FilingsTab({ ticker }: { ticker: string }) {
  const [filings, setFilings] = useState<FilingRow[] | null>(null);
  const [sec, setSec] = useState<{ title: string; item_code: string; text: string } | null>(null);
  useEffect(() => { getFilings(ticker).then((d) => setFilings(d.filings)).catch(() => setFilings([])); }, [ticker]);
  if (!filings) return <div className="text-slate-500 text-sm">loading…</div>;
  if (filings.length === 0) return <div className="text-slate-600 text-sm">No filings ingested — run research.</div>;
  return (
    <div className="flex gap-4 h-full">
      <div className="w-72 shrink-0 space-y-3">
        {filings.map((f) => (
          <div key={f.accession} className="border border-[#21262d] rounded-lg p-3">
            <div className="flex items-center gap-2 text-sm"><FileText className="w-3.5 h-3.5 text-slate-500" /><span className="font-medium">{f.form_type}</span><span className="text-xs text-slate-500">{f.filing_date}</span></div>
            <div className="mt-2 space-y-0.5">
              {f.sections.map((s) => (
                <button key={s.id} onClick={() => getSection(s.id).then(setSec)}
                  className="block w-full text-left text-xs text-slate-400 hover:text-sky-300 truncate py-0.5">
                  {s.item_code} <span className="text-slate-600">{s.title}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="flex-1 border border-[#21262d] rounded-lg p-4 overflow-y-auto">
        {sec ? (
          <><div className="text-sm text-slate-300 mb-2 font-medium">{sec.item_code} · {sec.title}</div>
            <div className="text-xs text-slate-400 whitespace-pre-wrap leading-relaxed">{sec.text.slice(0, 20000)}</div></>
        ) : <div className="text-slate-600 text-sm">Select a filing section to read it.</div>}
      </div>
    </div>
  );
}

function ResearchTab({ ticker }: { ticker: string }) {
  const [sources, setSources] = useState<SourceRow[] | null>(null);
  useEffect(() => { getResearchSources(ticker).then((d) => setSources(d.sources)).catch(() => setSources([])); }, [ticker]);
  if (!sources) return <div className="text-slate-500 text-sm">loading…</div>;
  if (sources.length === 0) return <div className="text-slate-600 text-sm">No external research yet — run research to gather current context.</div>;
  return (
    <div className="max-w-3xl space-y-3">
      {sources.map((s) => (
        <div key={s.id} className="border border-[#21262d] rounded-lg p-3">
          <a href={s.url} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline text-sm flex items-center gap-1">{s.title || s.url} <ExternalLink className="w-3 h-3 shrink-0" /></a>
          <div className="text-[10px] text-slate-500 mt-0.5">{s.publisher} {s.published_date && `· ${s.published_date}`} {s.search_query && `· query: ${s.search_query}`}</div>
          {s.snippet && <div className="text-xs text-slate-400 mt-1.5 line-clamp-3">{s.snippet}</div>}
        </div>
      ))}
    </div>
  );
}

function BriefTab({ ticker, runStatus }: { ticker: string; runStatus: string | null }) {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [loaded, setLoaded] = useState(false);
  const load = useCallback(() => { getLatestBrief(ticker).then((d) => { setBrief(d.brief); setLoaded(true); }); }, [ticker]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (runStatus === "completed") load(); }, [runStatus, load]);

  if (!loaded) return <div className="text-slate-500 text-sm">loading…</div>;
  if (!brief) return <div className="text-slate-600 text-sm">No brief yet — click &ldquo;Run research&rdquo; to generate an Issuer Risk Brief.</div>;

  const blocks: [string, string | null][] = [
    ["Financial summary", brief.financial_summary],
    ["Key changes", brief.key_changes],
    ["Management explanation", brief.management_explanation],
    ["Market & industry context", brief.market_context],
    ["Portfolio implications", brief.portfolio_implications],
    ["Open questions", brief.open_questions],
  ];
  return (
    <div className="max-w-3xl space-y-4">
      <div className="text-xs text-slate-500">Issuer Risk Brief · {brief.citations.length} citations · every claim traceable</div>
      {blocks.map(([title, text]) => text && (
        <div key={title}>
          <div className="text-[10px] uppercase text-slate-500 mb-1">{title}</div>
          <div className="text-sm text-slate-300 whitespace-pre-wrap leading-relaxed">{text}</div>
        </div>
      ))}
      <div className="pt-2 border-t border-[#21262d]">
        <div className="text-[10px] uppercase text-slate-500 mb-1.5">Evidence ({brief.citations.length})</div>
        <div className="flex flex-wrap">{brief.citations.map((c) => <CitationChip key={c} id={c} />)}</div>
      </div>
    </div>
  );
}
