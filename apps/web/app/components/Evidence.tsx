"use client";

import { useEffect, useState, useCallback } from "react";
import { X, ChevronRight, ExternalLink } from "lucide-react";
import { getEvidence, type Evidence } from "../../lib/issuer";

// A citation is opened from anywhere via a window event, so the drawer stays
// decoupled from chips (in chat, brief, financials, monitor).
export function openEvidence(id: string) {
  window.dispatchEvent(new CustomEvent("open-evidence", { detail: { id } }));
}

const TYPE_COLOR: Record<string, string> = {
  fact: "text-sky-300 border-sky-800 bg-sky-950/40",
  calc: "text-violet-300 border-violet-800 bg-violet-950/40",
  chunk: "text-amber-300 border-amber-800 bg-amber-950/40",
  source: "text-emerald-300 border-emerald-800 bg-emerald-950/40",
  src: "text-emerald-300 border-emerald-800 bg-emerald-950/40",
  alert: "text-red-300 border-red-800 bg-red-950/40",
};

function kindOf(id: string): string {
  const p = id.split("_", 1)[0];
  return { fact: "fact", calc: "calc", chunk: "chunk", src: "source", alert: "alert" }[p] || p;
}

export function CitationChip({ id }: { id: string }) {
  const kind = kindOf(id);
  const cls = TYPE_COLOR[kind] || "text-slate-300 border-slate-700 bg-slate-800/40";
  return (
    <button
      onClick={() => openEvidence(id)}
      title={id}
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-mono leading-none mr-1 mb-1 hover:brightness-125 ${cls}`}
    >
      {kind}
      <span className="opacity-50">{id.slice(kind.length + 1, kind.length + 7)}</span>
    </button>
  );
}

function num(v: unknown): string {
  if (typeof v !== "number") return String(v);
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (Math.abs(v) < 1 && v !== 0) return `${(v * 100).toFixed(2)}%`;
  return v.toLocaleString();
}

export function EvidenceDrawer() {
  const [stack, setStack] = useState<Evidence[]>([]);
  const [loading, setLoading] = useState(false);

  const push = useCallback(async (id: string) => {
    setLoading(true);
    try {
      const ev = await getEvidence(id);
      setStack((s) => [...s, ev]);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const handler = (e: Event) => {
      const id = (e as CustomEvent).detail.id as string;
      setStack([]);
      push(id);
    };
    window.addEventListener("open-evidence", handler);
    return () => window.removeEventListener("open-evidence", handler);
  }, [push]);

  if (stack.length === 0) return null;
  const ev = stack[stack.length - 1];
  const cls = TYPE_COLOR[ev.type] || "text-slate-300";

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={() => setStack([])}>
      <div className="absolute inset-0 bg-black/40" />
      <div
        className="relative w-[440px] max-w-full h-full bg-[#0d1117] border-l border-[#21262d] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-[#0d1117] border-b border-[#21262d] px-4 py-3 flex items-center gap-2">
          {stack.length > 1 && (
            <button onClick={() => setStack((s) => s.slice(0, -1))} className="text-slate-400 hover:text-slate-200 text-xs">← back</button>
          )}
          <span className={`text-xs font-mono uppercase ${cls.split(" ")[0]}`}>{ev.type}</span>
          <span className="text-[10px] font-mono text-slate-600 truncate">{ev.id}</span>
          <button onClick={() => setStack([])} className="ml-auto text-slate-400 hover:text-slate-200"><X className="w-4 h-4" /></button>
        </div>

        <div className="p-4 space-y-4 text-sm">
          {loading && <div className="text-slate-500 text-xs">loading…</div>}

          <section>
            <div className="text-[10px] uppercase text-slate-500 mb-1.5">Body</div>
            <div className="space-y-1">
              {Object.entries(ev.body).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <span className="text-slate-500 text-xs w-32 shrink-0">{k}</span>
                  <span className="text-slate-200 text-xs break-words">
                    {k === "text" ? <span className="text-slate-300 leading-relaxed">{String(v).slice(0, 1500)}</span>
                      : typeof v === "object" ? <code className="text-[10px]">{JSON.stringify(v)}</code>
                        : num(v)}
                  </span>
                </div>
              ))}
            </div>
          </section>

          <section>
            <div className="text-[10px] uppercase text-slate-500 mb-1.5">Provenance</div>
            <div className="space-y-1">
              {Object.entries(ev.provenance).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <span className="text-slate-500 text-xs w-32 shrink-0">{k}</span>
                  {k === "source_url" || k === "url" ? (
                    <a href={String(v)} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline text-xs flex items-center gap-1 break-all">
                      {String(v).slice(0, 60)} <ExternalLink className="w-3 h-3 shrink-0" />
                    </a>
                  ) : (
                    <span className="text-slate-300 text-xs break-words">{typeof v === "object" ? JSON.stringify(v) : String(v)}</span>
                  )}
                </div>
              ))}
            </div>
          </section>

          {ev.upstream.length > 0 && (
            <section>
              <div className="text-[10px] uppercase text-slate-500 mb-1.5">Computed from ({ev.upstream.length})</div>
              <div className="flex flex-wrap gap-1">
                {ev.upstream.map((u) => (
                  <button key={u.id} onClick={() => push(u.id)}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded border border-[#21262d] hover:border-slate-600 text-[10px] font-mono text-slate-300">
                    {u.type} <ChevronRight className="w-3 h-3 opacity-50" />
                  </button>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

// Render text that may contain [[id]] citation markers as inline chips.
export function CitedText({ text }: { text: string | null }) {
  if (!text) return null;
  return <span className="whitespace-pre-wrap leading-relaxed">{text}</span>;
}
