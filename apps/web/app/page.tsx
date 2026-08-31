"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Loader2, Play } from "lucide-react";

import { AuthGate, SignedInProbe } from "./components/Auth";
import { PortfolioModal } from "./components/PortfolioModal";
import { useDockContext } from "./components/analyst/Dock";
import { fmtDate } from "./components/charts/frame";
import { Rail } from "./components/book/Rail";
import {
  FactorBetas, FactorCorrelations, MandateBook, Stress, ValueAndDrawdown, WhereTheDayWent,
} from "./components/book/panels";
import {
  AuditStrip, Briefing, FreshnessLine, Holdings, RunRail, Tiles, Warnings, WhatThisRunFound,
  readStepFacts,
} from "./components/book/sections";
import { createRun, getFreshness, getPositions, getRun, listPortfolios, listRuns } from "@/lib/api";
import {
  getFactorCorrelation, getHistory, getLimitBook, getStress,
  type FactorCorrelation, type History, type LimitBook, type Scenario,
} from "@/lib/charts";
import { explainApiError, explainRunError } from "@/lib/errors";
import type {
  ExposureRun, ExposureRunSummary, Freshness, Portfolio, Position,
} from "@/lib/types";

/**
 * The book (V13-S6c).
 *
 * What this page used to be: three fixed panels — a list, a workflow runner and
 * a dashboard — with the runner in the middle third of the screen. The middle
 * third is the most valuable space on the page and it was spent on machinery
 * that matters for nineteen seconds a day. Every figure it showed was true and
 * none of it was addressed to somebody looking at their own book.
 *
 * What it is now: the book, top to bottom, in the order a reader asks about it —
 * how old is this, what happened, what is it worth, what is wrong, what is in
 * it, why did it move, what would break it, what does the desk say. The run
 * itself is a folded line at the bottom, and the ids that used to head the page
 * are behind the audit switch.
 *
 * The reads are deliberately separate calls. A page that waited for all five
 * would show nothing until the slowest returned, and four of them are answers
 * about a run that has already finished.
 */
const LAST_BOOK = "ew_book";

export default function BookPage() {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  // The reader's explicit choice, and only that. What is actually shown is
  // derived below: null here means "has not chosen", which is a different thing
  // from "nothing is open".
  const [chosenPortfolioId, setChosenPortfolioId] = useState<string | null>(null);
  // null until the probe reports: "not known yet" and "signed out" must stay
  // distinguishable, see the selection below.
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Derived while rendering, not set from an effect: the default is a function
  // of who is asking and what came back, so computing it here means there is
  // never a paint with nothing open followed by a correction.
  //
  // Picking the first row was right while every visitor was anonymous and the
  // first row was the shared demo. It stopped being right the moment accounts
  // existed: a signed-in user who owns nothing had the demo opened FOR them,
  // and the panel that fills the screen showed $10.8M with nothing on it saying
  // whose. Showing one person's money as another's is the one thing this
  // product must never do, even for the seconds it takes to read the rail.
  const defaultPortfolioId =
    signedIn === null || portfolios.length === 0
      ? null
      : signedIn
        ? (portfolios.find((p) => p.is_own)?.id ?? null)
        : portfolios[0].id;
  const portfolioId = chosenPortfolioId ?? defaultPortfolioId;

  const [positions, setPositions] = useState<Position[]>([]);
  const [runs, setRuns] = useState<ExposureRunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [run, setRun] = useState<ExposureRun | null>(null);
  const [freshness, setFreshness] = useState<Freshness | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [limitBook, setLimitBook] = useState<LimitBook | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null);
  const [correlation, setCorrelation] = useState<FactorCorrelation | null>(null);
  const [launching, setLaunching] = useState(false);

  const portfolio = portfolios.find((p) => p.id === portfolioId) ?? null;
  const { setContext, ask } = useDockContext();

  useEffect(() => {
    listPortfolios()
      .then((data) => {
        setPortfolios(data);
        // Which book the reader had open last time, restored only if it is
        // still one of theirs — RLS decides that, and a remembered id that no
        // longer resolves must not become a selection. Per browser, like the
        // audit switch: it is where you were, not something the account owns.
        try {
          const last = window.localStorage.getItem(LAST_BOOK);
          if (last && data.some((p) => p.id === last)) setChosenPortfolioId(last);
        } catch {
          // A private window, or site data blocked. The default below applies.
        }
      })
      // A transport string in the top bar is a sentence nobody can act on, and
      // lib/errors.ts already has one (V13-S2).
      .catch((e) => setError(explainApiError(e).notice));
  }, []);

  // Tell the dock what is on screen, so its suggestions are about this book.
  useEffect(() => {
    setContext({ kind: "book", portfolioId, name: portfolio?.name ?? null });
  }, [portfolioId, portfolio?.name, setContext]);

  useEffect(() => {
    if (!portfolioId) return;
    let ignore = false;   // drop results that resolve after a book switch
    getPositions(portfolioId).then((p) => { if (!ignore) setPositions(p); }).catch(() => {});
    getFreshness(portfolioId).then((f) => { if (!ignore) setFreshness(f); }).catch(() => {});
    getHistory(portfolioId).then((h) => { if (!ignore) setHistory(h); }).catch(() => setHistory(null));
    listRuns(portfolioId).then((data) => {
      if (ignore) return;
      setRuns(data);
      if (data.length > 0) setSelectedRunId((cur) => cur ?? data[0].id);
    }).catch(() => {});
    return () => { ignore = true; };
  }, [portfolioId]);

  // Poll while a run is in flight, then stop. The old page polled every two
  // seconds forever, which turned an open tab into a load generator against a
  // run that finished on Aug 27.
  useEffect(() => {
    if (!selectedRunId) return;
    let ignore = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = async () => {
      try {
        const r = await getRun(selectedRunId);
        if (ignore) return;
        setRun(r);
        if (r.status === "pending" || r.status === "running") {
          timer = setTimeout(poll, 2000);
        } else if (portfolioId) {
          listRuns(portfolioId).then((d) => { if (!ignore) setRuns(d); }).catch(() => {});
          getFreshness(portfolioId).then((f) => { if (!ignore) setFreshness(f); }).catch(() => {});
        }
      } catch {
        // A poll that fails is not a page that fails: the run's own panels are
        // already on screen and stay there.
      }
    };
    void poll();
    return () => { ignore = true; if (timer) clearTimeout(timer); };
  }, [selectedRunId, portfolioId]);

  // The panels that read a finished run. Nothing is asked of a run still going:
  // its limit book and stress rows do not exist yet.
  useEffect(() => {
    if (!selectedRunId || run?.status !== "completed" || run.id !== selectedRunId) return;
    let ignore = false;
    getLimitBook(selectedRunId).then((b) => { if (!ignore) setLimitBook(b); }).catch(() => setLimitBook(null));
    getStress(selectedRunId).then((s) => { if (!ignore) setScenarios(s.scenarios); }).catch(() => setScenarios(null));
    getFactorCorrelation(selectedRunId)
      .then((c) => { if (!ignore) setCorrelation(c); }).catch(() => setCorrelation(null));
    return () => { ignore = true; };
  }, [selectedRunId, run?.status, run?.id]);

  const selectPortfolio = (id: string) => {
    setChosenPortfolioId(id);
    try { window.localStorage.setItem(LAST_BOOK, id); } catch { /* not remembering is not a failure */ }
    setRun(null); setSelectedRunId(null); setRuns([]);
    setHistory(null); setLimitBook(null); setScenarios(null); setCorrelation(null);
  };

  const selectRun = (id: string) => {
    setSelectedRunId(id);
    setLimitBook(null); setScenarios(null); setCorrelation(null);
  };

  const onPortfolioCreated = useCallback((created: Portfolio) => {
    listPortfolios().then((data) => {
      setPortfolios(data);
      setChosenPortfolioId(created.id);
      setRun(null); setSelectedRunId(null); setRuns([]);
      setHistory(null); setLimitBook(null); setScenarios(null); setCorrelation(null);
    }).catch(() => {});
  }, []);

  const update = async () => {
    if (!portfolioId || launching) return;
    setLaunching(true);
    setError(null);
    try {
      const created = await createRun(portfolioId);
      setRun(created);
      setSelectedRunId(created.id);
      setLimitBook(null); setScenarios(null); setCorrelation(null);
    } catch (e) {
      setError(explainApiError(e).notice);
    } finally {
      setLaunching(false);
    }
  };

  const ownsNothing = !!signedIn && portfolios.length > 0 && !portfolios.some((p) => p.is_own);
  const metrics = run?.metrics ?? null;
  const facts = readStepFacts(run?.workflow_events ?? []);
  const alerts = run?.risk_alerts ?? [];
  const inFlight = run?.status === "pending" || run?.status === "running";
  // The server's own name for each check, so an alert can be read without the
  // key it was filed under. Built from the limit book rather than a table here:
  // an alert's key IS a check's key.
  const checkLabels = Object.fromEntries((limitBook?.checks ?? []).map((c) => [c.key, c.label]));
  // The regression's own names for its factors, so `Where the day went` and
  // `Factor betas` and the correlation grid all say `Small cap`, not one of
  // them saying `small_cap`.
  const factorNames = Object.fromEntries(
    (correlation?.tickers ?? []).map((t, i) => [t, correlation?.labels[i] ?? t]));

  return (
    <>
      <SignedInProbe onChange={setSignedIn} />
      <PortfolioModal open={modalOpen} onClose={() => setModalOpen(false)}
        onCreated={(p) => { setModalOpen(false); onPortfolioCreated(p); }} />

      <Rail
        portfolios={portfolios}
        selectedId={portfolioId}
        onSelect={selectPortfolio}
        runs={runs}
        selectedRunId={selectedRunId}
        onSelectRun={selectRun}
        issuers={run?.issuer_exposures ?? []}
        ownsNothing={ownsNothing}
        onNewBook={() => setModalOpen(true)}
        onCreated={onPortfolioCreated}
      />

      <main className="flex-1 min-w-0 overflow-y-auto">
        <div className="max-w-[1180px] mx-auto px-5 py-4 flex flex-col gap-3">
          {/* title */}
          <div className="flex items-start gap-4 flex-wrap">
            <div className="min-w-0">
              <h1 className="text-lg font-semibold text-slate-100 truncate">
                {portfolio?.name ?? (signedIn === null ? " " : "No book open")}
              </h1>
              {portfolio && (
                <p className="text-[11.5px] text-slate-500 mt-0.5">
                  {portfolio.is_public && !portfolio.is_own ? "Shared demo book · " : ""}
                  {portfolio.currency}
                  {portfolio.benchmark ? ` · benchmark ${portfolio.benchmark}` : ""}
                  {positions.length > 0 ? ` · ${positions.length} holdings` : ""}
                </p>
              )}
              <div className="mt-1"><FreshnessLine freshness={freshness} /></div>
            </div>
            {portfolio && (
              <div className="ml-auto flex items-center gap-2">
                <AuthGate fallback={
                  <span className="text-[11px] text-slate-600">Sign in to update this book</span>
                }>
                  <button onClick={update} disabled={launching || inFlight}
                    className="flex items-center gap-1.5 rounded-md bg-blue-600 hover:bg-blue-500 disabled:opacity-40 px-3 py-1.5 text-xs font-medium text-white transition-colors">
                    {launching || inFlight
                      ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      : <Play className="w-3.5 h-3.5" />}
                    {inFlight ? "Updating…" : "Update exposure"}
                  </button>
                </AuthGate>
              </div>
            )}
          </div>

          {error && (
            <p className="flex items-center gap-2 rounded-md border border-amber-900/60 bg-amber-950/25 px-3 py-2 text-[12px] text-amber-300">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" /> {error}
            </p>
          )}

          {run?.status === "failed" && (
            <p className="flex items-center gap-2 rounded-md border border-red-900/60 bg-red-950/25 px-3 py-2 text-[12px] text-red-300">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
              {explainRunError(
                run.workflow_events?.find((e) => e.status === "failed")?.error?.code,
                run.error_message)}
            </p>
          )}

          {run && metrics && (
            <>
              <WhatThisRunFound run={run} metrics={metrics} alerts={alerts}
                sectors={run.sector_exposures ?? []} checks={facts.evaluated} />
              <Tiles metrics={metrics} history={history}
                checks={facts.evaluated == null ? null
                  : { evaluated: facts.evaluated, fired: alerts.length }} />
            </>
          )}

          <AuditStrip signedIn={signedIn} />

          {history && history.points.length > 1 && <ValueAndDrawdown history={history} />}

          <Warnings alerts={alerts} labels={checkLabels} onAsk={ask} />

          {run && <Holdings issuers={run.issuer_exposures ?? []} asOf={run.as_of_date}
              portfolioId={portfolioId} onAsk={ask} />}

          {run && (run.factor_attributions?.length ?? 0) > 0 && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              <WhereTheDayWent
                factors={run.factor_attributions}
                issuers={run.issuer_exposures ?? []}
                dailyReturn={metrics?.daily_return ?? null}
                dailyPnl={metrics?.daily_pnl ?? null} names={factorNames} />
              {limitBook && <MandateBook book={limitBook} inert={facts.inertOverrides} />}
            </div>
          )}

          {run && (run.factor_attributions?.length ?? 0) > 0 && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              <FactorBetas factors={run.factor_attributions} names={factorNames}
                collinear={!!correlation?.collinear} maxVif={correlation?.max_vif ?? null} />
              {correlation && <FactorCorrelations corr={correlation} />}
            </div>
          )}

          {scenarios && scenarios.length > 0 && run && <Stress scenarios={scenarios} runId={run.id} />}

          {run?.daily_report && (
            <Briefing report={run.daily_report} checked={facts.numbersChecked} />
          )}

          {run && <RunRail run={run} />}

          {portfolio && !run && (
            <p className="text-xs text-slate-500 py-8 text-center">
              {inFlight
                ? "The first update is running — the panels fill in as it finishes."
                : "No exposure update has been run on this book yet."}
            </p>
          )}

          {!portfolio && signedIn !== null && (
            <p className="text-xs text-slate-500 py-8 text-center">
              Choose a book on the left, or take a copy of the shared demo.
            </p>
          )}
          <div className="h-6" />
        </div>
      </main>
    </>
  );
}
