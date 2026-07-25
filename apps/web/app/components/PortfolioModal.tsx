"use client";

import { useEffect, useRef, useState } from "react";
import { X, Upload, Copy, Loader2, AlertTriangle, Search, Trash2 } from "lucide-react";
import { createPortfolio, cloneDemoPortfolio, searchSecurities, type SecurityHit } from "@/lib/api";
import type { Portfolio } from "@/lib/types";
import { AuthGate } from "./Auth";

type Problem = { row?: number; ticker?: string; reason: string };
type Picked = { ticker: string; name: string | null; qty: string };

function extractProblems(err: unknown): Problem[] | null {
  const msg = err instanceof Error ? err.message : String(err);
  const i = msg.indexOf("{");
  if (i < 0) return null;
  try {
    const body = JSON.parse(msg.slice(i));
    const p = body?.detail?.problems ?? body?.problems;
    return Array.isArray(p) ? p : null;
  } catch {
    return null;
  }
}

export function PortfolioModal({
  open, onClose, onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (p: Portfolio) => void;
}) {
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<Picked[]>([]);
  const [csv, setCsv] = useState("");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SecurityHit[]>([]);
  const [busy, setBusy] = useState(false);
  const [problems, setProblems] = useState<Problem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  // debounced typeahead over the universe. `active` drops a stale response so a
  // slower earlier query can't overwrite the latest one.
  useEffect(() => {
    if (debounce.current) clearTimeout(debounce.current);
    const q = query.trim();
    if (!q) { setHits([]); return; }
    let active = true;
    debounce.current = setTimeout(() => {
      searchSecurities(q)
        .then((r) => { if (active) setHits(r); })
        .catch(() => { if (active) setHits([]); });
    }, 300);
    return () => { active = false; if (debounce.current) clearTimeout(debounce.current); };
  }, [query]);

  if (!open) return null;

  const reset = () => {
    setName(""); setPicked([]); setCsv(""); setQuery(""); setHits([]);
    setProblems(null); setError(null);
  };
  const close = () => { reset(); onClose(); };

  const addHit = (h: SecurityHit) => {
    setQuery(""); setHits([]);
    setPicked((p) => p.some((x) => x.ticker === h.ticker) ? p
      : [...p, { ticker: h.ticker, name: h.name, qty: "" }]);
  };
  const setQty = (t: string, qty: string) =>
    setPicked((p) => p.map((x) => x.ticker === t ? { ...x, qty } : x));
  const removePick = (t: string) => setPicked((p) => p.filter((x) => x.ticker !== t));

  // raw CSV + picked rows -> one payload. Raw goes FIRST so a pasted header row
  // stays on line 1 (parse_csv only strips a leading "ticker" header).
  const buildCsv = (): string => {
    const raw = csv.trim();
    const lines = picked.filter((x) => x.qty.trim()).map((x) => `${x.ticker},${x.qty.trim()}`);
    return [...(raw ? [raw] : []), ...lines].join("\n");
  };

  const run = async (fn: () => Promise<Portfolio>) => {
    setBusy(true); setProblems(null); setError(null);
    try {
      onCreated(await fn());
      reset();
    } catch (e) {
      const probs = extractProblems(e);
      if (probs) setProblems(probs);
      else setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onFile = async (f: File | null) => { if (f) setCsv(await f.text()); };
  const hasHoldings = picked.some((x) => x.qty.trim()) || csv.trim().length > 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={close}>
      <div className="absolute inset-0 bg-black/50" />
      <div
        className="relative w-[500px] max-w-full bg-[#0d1117] border border-[#21262d] rounded-lg shadow-xl max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#21262d] sticky top-0 bg-[#0d1117]">
          <span className="text-sm font-semibold text-slate-200">New portfolio</span>
          <button onClick={close} className="text-slate-400 hover:text-slate-200"><X className="w-4 h-4" /></button>
        </div>

        <AuthGate
          fallback={
            <div className="p-6 text-center text-sm text-slate-400">Sign in to create your own portfolio.</div>
          }
        >
          <div className="p-4 space-y-4">
            <div>
              <label className="text-[11px] uppercase tracking-wide text-slate-500">Name</label>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="My Portfolio"
                className="mt-1 w-full bg-[#161b22] border border-[#21262d] rounded px-2.5 py-1.5 text-sm text-slate-200 outline-none focus:border-blue-600" />
            </div>

            {/* Typeahead search over the universe */}
            <div className="relative">
              <label className="text-[11px] uppercase tracking-wide text-slate-500">Add holdings</label>
              <div className="mt-1 flex items-center gap-1.5 bg-[#161b22] border border-[#21262d] rounded px-2.5 py-1.5 focus-within:border-blue-600">
                <Search className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                <input value={query} onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search ticker or company name…"
                  className="flex-1 bg-transparent text-sm text-slate-200 outline-none" />
              </div>
              {hits.length > 0 && (
                <div className="absolute z-10 left-0 right-0 mt-1 bg-[#161b22] border border-[#30363d] rounded shadow-lg max-h-56 overflow-y-auto">
                  {hits.map((h) => (
                    <button key={h.ticker} onClick={() => addHit(h)}
                      className="w-full text-left px-3 py-1.5 hover:bg-white/5 flex items-center gap-2">
                      <span className="font-mono text-xs text-slate-200 w-16 shrink-0">{h.ticker}</span>
                      <span className="text-xs text-slate-400 truncate flex-1">{h.name}</span>
                      <span className="text-[9px] text-slate-500 shrink-0">{h.exchange}</span>
                      {h.is_etf && <span className="text-[9px] text-amber-400 shrink-0">ETF</span>}
                      {h.has_prices ? <span className="text-[9px] text-emerald-400 shrink-0">price✓</span>
                        : <span className="text-[9px] text-slate-600 shrink-0">price?</span>}
                      {h.has_cik && <span className="text-[9px] text-sky-400 shrink-0">research✓</span>}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Picked rows with quantity inputs */}
            {picked.length > 0 && (
              <div className="space-y-1">
                {picked.map((x) => (
                  <div key={x.ticker} className="flex items-center gap-2 text-sm">
                    <span className="font-mono text-xs text-slate-200 w-16 shrink-0">{x.ticker}</span>
                    <span className="text-xs text-slate-500 truncate flex-1">{x.name}</span>
                    <input type="number" min="0" step="any" value={x.qty}
                      onChange={(e) => setQty(x.ticker, e.target.value)} placeholder="qty"
                      className="w-20 bg-[#161b22] border border-[#21262d] rounded px-2 py-1 text-xs text-slate-200 outline-none focus:border-blue-600" />
                    <button onClick={() => removePick(x.ticker)} className="text-slate-500 hover:text-red-400">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Secondary: paste / upload CSV */}
            <details className="text-xs">
              <summary className="text-slate-500 cursor-pointer hover:text-slate-300">or paste / upload CSV</summary>
              <div className="mt-2">
                <label className="text-[11px] text-sky-400 hover:underline cursor-pointer">
                  choose file
                  <input type="file" accept=".csv,text/csv" className="hidden"
                    onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
                </label>
                <textarea value={csv} onChange={(e) => setCsv(e.target.value)} rows={3}
                  placeholder={"ticker,quantity,cost_basis\nAAPL,10,150"}
                  className="mt-1 w-full bg-[#161b22] border border-[#21262d] rounded px-2.5 py-1.5 text-xs font-mono text-slate-200 outline-none focus:border-blue-600 resize-none" />
              </div>
            </details>

            {problems && (
              <div className="rounded border border-red-500/30 bg-red-900/10 p-2.5">
                <div className="flex items-center gap-1.5 text-xs text-red-400 mb-1">
                  <AlertTriangle className="w-3.5 h-3.5" /> {problems.length} problem(s) — nothing was saved
                </div>
                <ul className="text-[11px] text-slate-400 space-y-0.5 max-h-32 overflow-y-auto">
                  {problems.map((p, i) => (
                    <li key={i} className="font-mono">
                      {p.row ? `row ${p.row} ` : ""}{p.ticker ? `${p.ticker}: ` : ""}{p.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {error && <div className="text-xs text-red-400">{error}</div>}

            <div className="flex items-center gap-2 pt-1">
              <button
                onClick={() => run(() => createPortfolio(name, hasHoldings ? buildCsv() : undefined))}
                disabled={busy || !name.trim()}
                className="flex-1 flex items-center justify-center gap-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-sm font-medium py-2 rounded-md transition-colors">
                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                Create
              </button>
              <button
                onClick={() => run(() => cloneDemoPortfolio())} disabled={busy}
                title="Copy the demo portfolio's holdings into a new one you own"
                className="flex items-center justify-center gap-1.5 border border-[#30363d] hover:bg-white/5 text-slate-300 text-sm py-2 px-3 rounded-md transition-colors">
                <Copy className="w-4 h-4" /> Clone demo
              </button>
            </div>
            <p className="text-[10px] text-slate-600">
              New tickers pull ~1y of prices on first use. Any unsupported/unpriceable row rejects the whole upload.
            </p>
          </div>
        </AuthGate>
      </div>
    </div>
  );
}
