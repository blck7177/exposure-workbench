"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { MessageSquare, Plus, Send } from "lucide-react";

import { getMyUsage } from "@/lib/api";
import { explainApiError } from "@/lib/errors";
import { getEvidenceLabels, type EvidenceLabel } from "@/lib/charts";
import { type ApiError } from "@/lib/http";
import {
  createSession, getSessionDetail, listSessions, postMessage,
  type AgentStep, type SessionSummary, type Verified,
} from "@/lib/issuer";
import type { Usage } from "@/lib/types";
import { AuthGate } from "../Auth";
import { CitationList } from "../evidence/Cite";
import { useEvidence } from "../evidence/Column";
import { Activity } from "./Activity";
import { AnswerText, idsIn } from "./AnswerText";
import { AnswerBlocks, type Block } from "./AnswerBlocks";
import { VerifiedBadge } from "./Verified";

/**
 * The analyst dock (V13-S6).
 *
 * Mounted by the layout, not by each page, and that is a decision Next 16 made
 * for us: cacheComponents is off, so nothing preserves component state across a
 * navigation. A dock owned by the page unmounted on every move between the book
 * and an issuer, which is exactly when somebody is mid-conversation about the
 * thing they just clicked.
 *
 * What it knows that its predecessor did not: which page it is on. The
 * suggestions, the placeholder and the header all follow, so a reader on Apple
 * is not offered "Give me a brief on MSFT" — the ticker in a suggestion is a
 * placeholder, and the name the reader came here about is the one on screen.
 */

// ── which page the dock is looking at ────────────────────────────────────────

export type DockContext =
  | { kind: "book"; portfolioId: string | null; name: string | null }
  | { kind: "issuer"; ticker: string; name: string | null };

const CtxContext = createContext<{
  context: DockContext;
  setContext: (c: DockContext) => void;
  ask: (q: string) => void;
}>({ context: { kind: "book", portfolioId: null, name: null }, setContext: () => {}, ask: () => {} });

/** Tell the dock what is on screen. Called once per page, from an effect, so a
 *  navigation updates it without the dock re-mounting. */
export function useDockContext() {
  return useContext(CtxContext);
}

export function DockContextProvider({ children }: { children: React.ReactNode }) {
  const [context, setContext] = useState<DockContext>({ kind: "book", portfolioId: null, name: null });
  const askRef = useRef<(q: string) => void>(() => {});
  const ask = useCallback((q: string) => askRef.current(q), []);
  return (
    <CtxContext.Provider value={{ context, setContext, ask }}>
      <AskBridge askRef={askRef} />
      {children}
    </CtxContext.Provider>
  );
}

// The dock registers its own composer setter here, so any row on any page can
// hand it a question without the two knowing about each other.
const bridge: { set: ((q: string) => void) | null } = { set: null };
function AskBridge({ askRef }: { askRef: React.RefObject<(q: string) => void> }) {
  askRef.current = (q: string) => bridge.set?.(q);
  return null;
}

const LS_KEY = "ew_agent_session";

type ChatMsg = {
  role: string;
  text: string;
  citations: string[];
  gateFailed?: boolean;
  verified?: Verified;
  // V14-C. Present on an answer whose figures were slots; absent on every
  // answer written before the exit changed, which keeps its prose renderer.
  blocks?: Block[];
  seconds?: number;
};

/** Suggestions are templates over what is on screen, not model output: they are
 *  deterministic, they cost nothing, and a suggested question that turns out to
 *  be unanswerable is worse than none. */
function suggestionsFor(context: DockContext): string[] {
  // Every question here was asked of the deployed desk on 2026-09-02 and
  // answered with figures on the table (docs/spikes/V20_COVERAGE.md and the
  // R20 battery). A question that leans on a withheld measure (VaR, stress)
  // or on a shape the model still gets wrong (ranking run rows) is not here.
  if (context.kind === "issuer") {
    const t = context.ticker;
    return [
      `Add up ${t}'s debt — long-term, current portion, short-term — then net the cash off so I have net debt.`,
      `How has ${t}'s revenue grown over the last four quarters?`,
      `Search the web for the latest news on ${t} from the past week and tell me what happened.`,
    ];
  }
  return [
    "What is my largest exposure right now?",
    "Why did the book move on the last run?",
    "Which limits am I closest to breaching, and how much room is left on each?",
    "Put MSFT, AAPL and GOOGL 2025 full-year net income side by side in a table.",
  ];
}

export function AnalystDock() {
  const { context } = useDockContext();
  const evidence = useEvidence();

  const [open, setOpen] = useState(true);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [labels, setLabels] = useState<Record<string, EvidenceLabel>>({});
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Any row on any page can put a question in the composer.
  useEffect(() => {
    bridge.set = (q: string) => {
      setOpen(true);
      setInput(q);
      requestAnimationFrame(() => inputRef.current?.focus());
    };
    return () => { bridge.set = null; };
  }, []);

  const loadLabels = useCallback(async (ids: string[]) => {
    const wanted = ids.filter((id) => !(id in labels));
    if (wanted.length === 0) return;
    try {
      const { labels: got } = await getEvidenceLabels(wanted);
      setLabels((prev) => ({ ...prev, ...got }));
    } catch {
      // A chip without a label falls back to its id in the title attribute; the
      // answer itself is unaffected, so this must not surface as an error.
    }
  }, [labels]);

  // Restore the conversation across navigations and reloads. BOTH the stored id
  // and the state are cleared when the server does not know it, or every later
  // send goes to a session that is not there — the tab you are in stays broken
  // and the bug reads as intermittent.
  useEffect(() => {
    let sid: string | null = null;
    try { sid = localStorage.getItem(LS_KEY); } catch { sid = null; }
    if (!sid) return;
    setSessionId(sid);
    getSessionDetail(sid).then((d) => {
      const msgs = d.messages.filter((m) => m.content).map((m) => ({
        role: m.role,
        text: m.content ?? "",
        citations: m.citations ?? [],
        gateFailed: (m.meta as { gate?: string } | undefined)?.gate === "exhausted",
        verified: (m.meta as { verified?: Verified } | undefined)?.verified,
        blocks: (m.meta as { blocks?: Block[] } | undefined)?.blocks,
      }));
      setMessages(msgs);
      setSteps(d.steps);
      void loadLabels(msgs.flatMap((m) => idsIn(m.text, m.citations)));
    }).catch(() => {
      try { localStorage.removeItem(LS_KEY); } catch { /* nothing to clear */ }
      setSessionId(null);
    });
    // Once, on mount: this is a restore, not a subscription.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!open) return;
    listSessions().then(setSessions).catch(() => setSessions([]));
  }, [open, sessionId]);

  useEffect(() => {
    if (!busy || !sessionId) return;
    const iv = setInterval(() => {
      getSessionDetail(sessionId).then((d) => setSteps(d.steps)).catch(() => {});
    }, 1500);
    return () => clearInterval(iv);
  }, [busy, sessionId]);

  useEffect(() => {
    if (!open || busy) return;
    let ignore = false;
    getMyUsage()
      .then((u) => { if (!ignore) setUsage(u); })
      .catch(() => { if (!ignore) setUsage(null); });
    return () => { ignore = true; };
  }, [open, busy]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, steps]);

  const ensureSession = useCallback(async (): Promise<string> => {
    if (sessionId) return sessionId;
    const s = await createSession();
    try { localStorage.setItem(LS_KEY, s.id); } catch { /* not remembering is survivable */ }
    setSessionId(s.id);
    return s.id;
  }, [sessionId]);

  const newSession = async () => {
    const s = await createSession();
    try { localStorage.setItem(LS_KEY, s.id); } catch { /* as above */ }
    setSessionId(s.id);
    setMessages([]);
    setSteps([]);
  };

  const openSession = async (id: string) => {
    try { localStorage.setItem(LS_KEY, id); } catch { /* as above */ }
    setSessionId(id);
    const d = await getSessionDetail(id);
    const msgs = d.messages.filter((m) => m.content).map((m) => ({
      role: m.role,
      text: m.content ?? "",
      citations: m.citations ?? [],
      gateFailed: (m.meta as { gate?: string } | undefined)?.gate === "exhausted",
      verified: (m.meta as { verified?: Verified } | undefined)?.verified,
      blocks: (m.meta as { blocks?: Block[] } | undefined)?.blocks,
    }));
    setMessages(msgs);
    setSteps(d.steps);
    void loadLabels(msgs.flatMap((m) => idsIn(m.text, m.citations)));
  };

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setNotice(null);
    setMessages((m) => [...m, { role: "user", text, citations: [] }]);
    setBusy(true);
    const started = Date.now();
    try {
      const sid = await ensureSession();
      const r = await postMessage(sid, text);
      const meta = r.meta as { gate?: string; verified?: Verified; blocks?: Block[] } | undefined;
      setMessages((m) => [...m, {
        role: "assistant", text: r.text, citations: r.citations ?? [],
        gateFailed: meta?.gate === "exhausted",
        blocks: meta?.blocks,
        verified: meta?.verified,
        seconds: Math.round((Date.now() - started) / 1000),
      }]);
      void loadLabels(idsIn(r.text, r.citations));
      const d = await getSessionDetail(sid);
      setSteps(d.steps);
    } catch (e) {
      const status = (e as ApiError).status;
      // On any 4xx the gate refused before the turn was committed, so the server
      // holds no record of what we optimistically rendered; leaving it up means
      // it disappears on the next refresh. A 5xx means the turn had started and
      // the message IS persisted, so the bubble stays.
      if (status && status < 500) setMessages((m) => m.slice(0, -1));
      const { notice: sentence, dropSession } = explainApiError(e);
      setNotice(sentence);
      if (dropSession) {
        setSessionId(null);
        try { localStorage.removeItem(LS_KEY); } catch { /* nothing to clear */ }
      }
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button onClick={() => setOpen(true)}
        className="fixed bottom-4 right-4 z-40 flex items-center gap-2 px-3 py-2 rounded-full bg-blue-600 hover:bg-blue-500 text-white text-sm shadow-lg">
        <MessageSquare className="w-4 h-4" /> Ask the analyst
      </button>
    );
  }

  const heading = context.kind === "issuer"
    ? (context.name ?? context.ticker)
    : (context.name ?? "this book");
  const pool = usage?.pools.find((p) => p.kind === "chat_turn");

  return (
    // order-last: EvidenceProvider renders the evidence column after its own
    // children, and the dock is one of those children — so without this the
    // evidence a reader opened would appear on the far side of the dock,
    // away from the answer that cited it.
    <aside className="w-[380px] shrink-0 order-last border-l border-[#21262d] bg-[#11161d] flex flex-col min-h-0" aria-label="Analyst">
      <header className="h-10 flex items-center gap-2 px-3 border-b border-[#21262d] shrink-0">
        <MessageSquare className="w-3.5 h-3.5 text-blue-400 shrink-0" />
        <span className="text-sm text-slate-300 truncate">Analyst</span>
        <span className="font-mono text-[10px] text-slate-500 border border-[#30363d] rounded px-1.5 py-px truncate">
          {context.kind === "issuer" ? context.ticker : "book"}
        </span>
        <button onClick={newSession} title="New conversation"
          className="ml-auto text-slate-500 hover:text-slate-200 flex items-center gap-1 text-xs">
          <Plus className="w-3.5 h-3.5" /> New
        </button>
        <button onClick={() => setOpen(false)} className="text-slate-500 hover:text-slate-200 text-xs">
          Hide
        </button>
      </header>

      {sessions.length > 1 && messages.length === 0 && (
        <div className="px-3 py-2 border-b border-[#21262d] shrink-0">
          <div className="font-mono text-[10px] uppercase tracking-wider text-slate-600 mb-1">
            Earlier conversations
          </div>
          <div className="flex flex-col gap-0.5 max-h-28 overflow-y-auto">
            {sessions.filter((s) => s.title).slice(0, 8).map((s) => (
              <button key={s.id} onClick={() => openSession(s.id)}
                className="text-left text-[11.5px] text-slate-400 hover:text-slate-200 truncate rounded px-1 py-0.5 hover:bg-[#161b22]">
                {s.title}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3 min-h-0">
        {messages.length === 0 && (
          <p className="text-xs text-slate-600 text-center mt-6 px-4 leading-relaxed">
            Ask about {heading} or any issuer. Every figure in an answer is checked
            against the evidence cited for it before you see it.
          </p>
        )}

        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex flex-col items-end" : "flex flex-col gap-1.5"}>
            {m.role !== "user" && (
              <div className="flex items-center gap-2 flex-wrap">
                {m.gateFailed ? (
                  <span className="font-mono text-[10.5px] uppercase tracking-wide text-amber-500">
                    Not answered — nothing here is verified
                  </span>
                ) : (
                  <VerifiedBadge verified={m.verified} />
                )}
                {m.seconds != null && (
                  <span className="ml-auto font-mono text-[10px] text-slate-600">{m.seconds}s</span>
                )}
              </div>
            )}
            <div className={`inline-block max-w-[94%] px-3 py-2 rounded-lg text-[12.5px] leading-relaxed text-left ${
              m.role === "user"
                ? "bg-blue-600/20 text-slate-200 border border-blue-500/25"
                : m.gateFailed
                  ? "bg-amber-950/40 border border-amber-800/50 text-amber-100/90"
                  : "bg-[#171d26] border border-[#21262d] text-slate-300"
            }`}>
              {m.role === "user" ? (
                <span className="whitespace-pre-wrap">{m.text}</span>
              ) : (
                m.blocks ? (
                  // V14-C. A v1 answer keeps its prose renderer: the figures are
                  // IN its sentences and its spans were recorded against that
                  // string. Migrating them would mean inventing slots for
                  // numbers nobody recorded as slots.
                  <AnswerBlocks blocks={m.blocks} onOpen={evidence.open} />
                ) : (
                  <AnswerText text={m.text} citations={m.citations}
                    matches={m.verified?.matches} labels={labels} onOpen={evidence.open} />
                )
              )}
              {m.role !== "user" && (
                <CitationList citations={m.citations} labels={labels} onOpen={evidence.open} />
              )}
            </div>
          </div>
        ))}

        {(busy || messages.length > 0) && (
          <Activity steps={steps.slice(-12)} running={busy}
            seconds={messages[messages.length - 1]?.seconds} />
        )}
        <div ref={endRef} />
      </div>

      {notice && (
        <div className="border-t border-amber-900/50 bg-amber-950/20 px-3 py-2 text-xs text-amber-300 shrink-0">
          {notice}
        </div>
      )}

      <AuthGate fallback={
        <div className="border-t border-[#21262d] p-3 text-center text-xs text-slate-500 shrink-0">
          Sign in to ask the analyst.
        </div>
      }>
        <div className="border-t border-[#21262d] p-2.5 flex flex-col gap-2 shrink-0">
          {messages.length === 0 && (
            <div className="flex flex-col gap-1">
              <div className="font-mono text-[10px] uppercase tracking-wider text-slate-600 px-0.5">
                Ask about {context.kind === "issuer" ? context.ticker : "this book"}
              </div>
              {suggestionsFor(context).map((q) => (
                <button key={q} onClick={() => { setInput(q); inputRef.current?.focus(); }}
                  className="text-left text-[12px] text-slate-400 hover:text-slate-200 border border-[#21262d] hover:border-[#30363d] bg-[#171d26] rounded px-2.5 py-1.5">
                  {q}
                </button>
              ))}
            </div>
          )}
          <div className="flex gap-2 items-center">
            <input ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void send(); }}
              disabled={busy}
              placeholder={context.kind === "issuer" ? `Ask about ${context.ticker}…` : "Ask about this book or any issuer…"}
              className="flex-1 bg-[#171d26] border border-[#30363d] rounded px-2.5 py-2 text-[12.5px] text-slate-200 outline-none focus:border-blue-600 disabled:opacity-50" />
            <button onClick={() => void send()} disabled={busy || !input.trim()}
              aria-label="Send"
              className="w-9 h-9 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white flex items-center justify-center">
              <Send className="w-4 h-4" />
            </button>
          </div>
          {/* Beside the thing it qualifies, not in a footer. The guidance on
              caveats is unanimous that a disclaimer far from the decision is a
              disclaimer nobody reads, and this is the decision point. */}
          <div className="flex justify-between gap-3 text-[10.5px] text-slate-600 leading-snug">
            <span>
              Research tool, not investment advice. Figures are checked against filings
              and this desk&rsquo;s own calculations — verify before acting.
            </span>
            {pool && (
              <span className="font-mono whitespace-nowrap">
                {pool.unlimited ? `${pool.used} asked` : `${pool.remaining} left`}
              </span>
            )}
          </div>
        </div>
      </AuthGate>
    </aside>
  );
}
