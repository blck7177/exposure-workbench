"use client";

import { useState } from "react";
import { X, Upload, Copy, Loader2, AlertTriangle } from "lucide-react";
import { createPortfolio, cloneDemoPortfolio } from "@/lib/api";
import type { Portfolio } from "@/lib/types";
import { AuthGate } from "./Auth";

type Problem = { row?: number; ticker?: string; reason: string };

// Parse the 422 {problems:[...]} body the API returns for a bad CSV.
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
  const [csv, setCsv] = useState("");
  const [busy, setBusy] = useState(false);
  const [problems, setProblems] = useState<Problem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const reset = () => { setName(""); setCsv(""); setProblems(null); setError(null); };
  const close = () => { reset(); onClose(); };

  const run = async (fn: () => Promise<Portfolio>) => {
    setBusy(true); setProblems(null); setError(null);
    try {
      const p = await fn();
      reset();
      onCreated(p);
    } catch (e) {
      const probs = extractProblems(e);
      if (probs) setProblems(probs);
      else setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onFile = async (f: File | null) => {
    if (f) setCsv(await f.text());
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={close}>
      <div className="absolute inset-0 bg-black/50" />
      <div
        className="relative w-[460px] max-w-full bg-[#0d1117] border border-[#21262d] rounded-lg shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#21262d]">
          <span className="text-sm font-semibold text-slate-200">New portfolio</span>
          <button onClick={close} className="text-slate-400 hover:text-slate-200"><X className="w-4 h-4" /></button>
        </div>

        <AuthGate
          fallback={
            <div className="p-6 text-center text-sm text-slate-400">
              Sign in to create your own portfolio.
            </div>
          }
        >
          <div className="p-4 space-y-4">
            <div>
              <label className="text-[11px] uppercase tracking-wide text-slate-500">Name</label>
              <input
                value={name} onChange={(e) => setName(e.target.value)}
                placeholder="My Portfolio"
                className="mt-1 w-full bg-[#161b22] border border-[#21262d] rounded px-2.5 py-1.5 text-sm text-slate-200 outline-none focus:border-blue-600"
              />
            </div>

            <div>
              <div className="flex items-center justify-between">
                <label className="text-[11px] uppercase tracking-wide text-slate-500">Holdings (CSV)</label>
                <label className="text-[11px] text-sky-400 hover:underline cursor-pointer">
                  choose file
                  <input type="file" accept=".csv,text/csv" className="hidden"
                    onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
                </label>
              </div>
              <textarea
                value={csv} onChange={(e) => setCsv(e.target.value)}
                rows={5} placeholder={"ticker,quantity,cost_basis\nAAPL,10,150\nMSFT,5"}
                className="mt-1 w-full bg-[#161b22] border border-[#21262d] rounded px-2.5 py-1.5 text-xs font-mono text-slate-200 outline-none focus:border-blue-600 resize-none"
              />
              <p className="text-[10px] text-slate-600 mt-1">
                Supported tickers only (the covered set). Any bad row rejects the whole upload.
              </p>
            </div>

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
                onClick={() => run(() => createPortfolio(name, csv.trim() || undefined))}
                disabled={busy || !name.trim()}
                className="flex-1 flex items-center justify-center gap-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-sm font-medium py-2 rounded-md transition-colors"
              >
                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                Create
              </button>
              <button
                onClick={() => run(() => cloneDemoPortfolio())}
                disabled={busy}
                title="Copy the demo portfolio's holdings into a new one you own"
                className="flex items-center justify-center gap-1.5 border border-[#30363d] hover:bg-white/5 text-slate-300 text-sm py-2 px-3 rounded-md transition-colors"
              >
                <Copy className="w-4 h-4" /> Clone demo
              </button>
            </div>
          </div>
        </AuthGate>
      </div>
    </div>
  );
}
