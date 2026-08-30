"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { X } from "lucide-react";

import { getEvidence, type Evidence } from "@/lib/issuer";
import { EvidenceCard } from "./cards";

/**
 * The evidence column (V13-S3/S6).
 *
 * It used to be a drawer at z-50 over a chat panel at z-40, so opening a
 * citation covered the answer that made it. That is backwards: the reader is
 * checking a specific sentence, and the thing they are checking it against
 * should sit BESIDE it. A column in the grid, not a layer over it.
 *
 * The stack is a trail, not a history: a calculation to its input facts to the
 * filing they came from is a real path through the evidence, and `back` walks
 * it. Opening a new citation from the page starts a new trail rather than
 * pushing onto the old one, because those are two different questions.
 */

type EvidenceState = {
  open: (id: string) => void;
  close: () => void;
  stack: (Evidence & { label?: string })[];
  loading: boolean;
  error: string | null;
  back: () => void;
  isOpen: boolean;
};

const Ctx = createContext<EvidenceState>({
  open: () => {}, close: () => {}, stack: [], loading: false, error: null,
  back: () => {}, isOpen: false,
});

export function EvidenceProvider({ children }: { children: React.ReactNode }) {
  const [stack, setStack] = useState<(Evidence & { label?: string })[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const push = useCallback(async (id: string, fresh: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const ev = await getEvidence(id);
      setStack((s) => (fresh ? [ev] : [...s, ev]));
    } catch {
      // The one sentence a reader can act on. An id that no longer resolves is
      // almost always a wiped database or another tenant's row, and neither is
      // something they can fix — so it says what it is rather than showing them
      // a transport string.
      setError("That evidence is no longer available.");
      if (fresh) setStack([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const open = useCallback((id: string) => { void push(id, true); }, [push]);
  const drill = useCallback((id: string) => { void push(id, false); }, [push]);
  const close = useCallback(() => { setStack([]); setError(null); }, []);
  const back = useCallback(() => setStack((s) => s.slice(0, -1)), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  const isOpen = stack.length > 0 || loading || error != null;

  return (
    <Ctx.Provider value={{ open, close, stack, loading, error, back, isOpen }}>
      {children}
      <EvidenceColumnBody drill={drill} />
    </Ctx.Provider>
  );
}

export function useEvidence() {
  return useContext(Ctx);
}

function EvidenceColumnBody({ drill }: { drill: (id: string) => void }) {
  const { stack, loading, error, back, close, isOpen } = useEvidence();
  if (!isOpen) return null;
  const top = stack[stack.length - 1];
  return (
    // w-[360px]: the column is a fixed lane in the workspace, not a thing the
    // page has to size. shrink-0 so a wide table in the main pane cannot squeeze
    // the evidence a reader opened to check it against.
    <aside className="w-[360px] shrink-0 border-l border-[#21262d] bg-[#11161d] flex flex-col min-h-0 overflow-hidden"
      aria-label="Evidence">
      <header className="h-10 flex items-center gap-2 px-3 border-b border-[#21262d] shrink-0">
        {stack.length > 1 && (
          <button onClick={back} className="text-xs text-slate-400 hover:text-slate-200">← back</button>
        )}
        <span className="font-mono text-[10px] uppercase tracking-wider text-teal-400">Evidence</span>
        <button onClick={close} className="ml-auto text-slate-500 hover:text-slate-200" aria-label="Close">
          <X className="w-4 h-4" />
        </button>
      </header>
      <div className="overflow-y-auto p-4">
        {loading && stack.length === 0 && <p className="text-xs text-slate-500">Loading…</p>}
        {error && <p className="text-xs text-amber-400">{error}</p>}
        {top && <EvidenceCard evidence={top} onOpen={drill} />}
      </div>
    </aside>
  );
}
