"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { MessageSquare, Plus, Send, X, Wrench, Brain, Receipt, Send as SendIcon } from "lucide-react";
import { createSession, postMessage, getSessionDetail, type AgentStep } from "../../lib/issuer";
import { getMyUsage } from "@/lib/api";
import { type ApiError } from "@/lib/http";
import { explainApiError } from "@/lib/errors";
import type { Usage } from "@/lib/types";
import { CitationChip } from "./Evidence";
import { AuthGate } from "./Auth";

const LS_KEY = "ew_agent_session";

// The empty state's job is to show what this analyst is FOR, and the previous
// one line of prose could not: it named two questions of the same kind (a fact
// about one issuer) and neither could be clicked. These three are one per
// capability the product actually has — the book (portfolio tools), an issuer
// against filed evidence, and a delegated research run that comes back with a
// brief — so a stranger's first question lands somewhere the agent can answer
// from, instead of on the shape of question it has to refuse.
const SUGGESTIONS = [
  "What is my largest exposure?",
  "Why did NVDA move this week?",
  "Give me a brief on MSFT",
];

// gateFailed: the loop ended without the citation gate accepting an answer.
// Rendered as a refusal, because a paragraph saying "I could not produce an
// answer" styled exactly like a verified answer reads as one.
type ChatMsg = { role: string; text: string; citations: string[]; gateFailed?: boolean };

// One step in the live trace — machine-recorded (tool/delegation) solid, agent
// narration (think/respond) dashed, matching the audit "who recorded what" split.
function TraceLine({ s }: { s: AgentStep }) {
  // A third kind, and it belongs to neither side of that split. A tool call is
  // something the agent DID; a think is something it SAID. An llm_call is what
  // the turn cost — nobody chose it, nothing was retrieved, and it is recorded
  // on the way past rather than by anyone deciding to (V4-S2). So it is quieter
  // than both and does not borrow the wrench: it is not a tool.
  //
  // result_summary carries the model version the provider actually served and
  // how many calls it asked for; the tokens come from the step's own columns.
  // Both halves on one line because "which model" and "how much" is one
  // question — a version with no cost beside it invites the next reader to go
  // and look it up somewhere else.
  if (s.step_type === "llm_call") {
    const tokens =
      s.prompt_tokens === null && s.completion_tokens === null
        ? null
        : `${s.prompt_tokens ?? 0} in / ${s.completion_tokens ?? 0} out`;
    return (
      <div className="flex items-start gap-1.5 text-[10px] py-0.5 text-slate-600">
        <Receipt className="w-3 h-3 mt-0.5 shrink-0 opacity-40" />
        <span className="font-mono">{s.result_summary}</span>
        {tokens && <span className="font-mono tabular-nums opacity-60">{tokens}</span>}
      </div>
    );
  }

  const machine = s.step_type === "tool_call" || s.step_type === "delegation";
  const Icon = s.step_type === "think" ? Brain : s.step_type === "respond" ? SendIcon : Wrench;
  return (
    <div className={`flex items-start gap-1.5 text-[10px] py-0.5 ${machine ? "text-slate-400" : "text-slate-500 italic"}`}>
      <Icon className="w-3 h-3 mt-0.5 shrink-0 opacity-60" />
      <span className={`font-mono ${s.status === "rejected" ? "text-amber-400" : ""}`}>{s.tool_name || s.step_type}</span>
      {s.status === "rejected" && <span className="text-amber-500">rejected</span>}
      {s.evidence_refs?.length > 0 && <span className="opacity-50">→ {s.evidence_refs.length} refs</span>}
    </div>
  );
}

// Today's chat allowance. Renders nothing until a fetch succeeds, so a signed-out
// visitor (whose /me/usage 401s) simply never sees it.
function QuotaBadge({ usage }: { usage: Usage | null }) {
  const pool = usage?.pools.find((p) => p.kind === "chat_turn");
  if (!pool) return null;
  const spent = !pool.unlimited && pool.remaining === 0;
  return (
    <span
      title={
        pool.unlimited
          ? `${pool.used} chat turns today — this account is exempt from the daily limit`
          : `${pool.used} of ${pool.limit} chat turns used today — resets ${new Date(usage!.resets_at).toLocaleString()}`
      }
      className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${
        spent
          ? "text-amber-400 border-amber-900/60 bg-amber-950/30"
          : "text-slate-500 border-[#21262d]"
      }`}
    >
      {pool.unlimited ? `${pool.used}/∞` : `${pool.remaining}/${pool.limit}`}
    </span>
  );
}

export function ChatPanel() {
  const [open, setOpen] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // restore session across page navigations / refresh
  useEffect(() => {
    const sid = localStorage.getItem(LS_KEY);
    if (sid) { setSessionId(sid); getSessionDetail(sid).then((d) => {
      setMessages(d.messages.filter(m => m.content).map(m => ({ role: m.role, text: m.content || "", citations: m.citations || [] })));
      setSteps(d.steps);
    }).catch(() => {
      // BOTH, or the id lives on in state and every send goes to a session the
      // server cannot see. Clearing only storage looks like a fix and behaves
      // like one after a reload, which is the worst combination: the tab you
      // are in stays broken and the bug reads as intermittent. The realistic
      // way in is signing in as a different user — the id is per origin, the
      // session is per tenant, and RLS makes the other tenant's session a 404.
      localStorage.removeItem(LS_KEY);
      setSessionId(null);
    }); }
  }, []);

  const ensureSession = useCallback(async (): Promise<string> => {
    if (sessionId) return sessionId;
    const s = await createSession();
    localStorage.setItem(LS_KEY, s.id);
    setSessionId(s.id);
    return s.id;
  }, [sessionId]);

  const newSession = async () => {
    const s = await createSession();
    localStorage.setItem(LS_KEY, s.id);
    setSessionId(s.id); setMessages([]); setSteps([]);
  };

  // poll the trace while a turn is in flight (the Agent Monitor)
  useEffect(() => {
    if (!busy || !sessionId) return;
    const iv = setInterval(() => { getSessionDetail(sessionId).then((d) => setSteps(d.steps)).catch(() => {}); }, 1500);
    return () => clearInterval(iv);
  }, [busy, sessionId]);

  // Refresh the allowance when the panel opens and after every turn settles.
  // Guarded like the other effects here: a late response from a previous render
  // must not overwrite a newer one. Failure (including the 401 apiFetch throws
  // when signed out) leaves it null and the badge hidden — never throws.
  useEffect(() => {
    if (!open || busy) return;
    let ignore = false;
    getMyUsage()
      .then((u) => { if (!ignore) setUsage(u); })
      .catch(() => { if (!ignore) setUsage(null); });
    return () => { ignore = true; };
  }, [open, busy]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, steps]);

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setNotice(null);
    setMessages((m) => [...m, { role: "user", text, citations: [] }]);
    setBusy(true);
    try {
      const sid = await ensureSession();
      const r = await postMessage(sid, text);
      setMessages((m) => [...m, { role: "assistant", text: r.text, citations: r.citations || [],
                                 gateFailed: (r.meta as { gate?: string } | undefined)?.gate === "exhausted" }]);
      const d = await getSessionDetail(sid);
      setSteps(d.steps);
    } catch (e) {
      const status = (e as ApiError).status;

      // The gate (401/404/409/429) rejects before handle_message runs, and
      // handle_message is what commits the user's message — so on any 4xx the
      // server holds no record of what we optimistically rendered. Leave it up
      // and it silently disappears on the next refresh. A 5xx means the turn
      // had already started, so the message IS persisted and the bubble stays.
      if (status && status < 500) setMessages((m) => m.slice(0, -1));

      // One mapping from a server refusal to a sentence, shared with the issuer
      // page (lib/errors.ts). It also answers what to do about local state:
      // dropSession means this id will never be accepted again, so keeping it
      // would make every later send repeat this same failure.
      const { notice, dropSession } = explainApiError(e);
      setNotice(notice);
      if (dropSession) {
        setSessionId(null);
        localStorage.removeItem(LS_KEY);
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

  // recent steps (this turn's tail) shown as the live monitor
  const liveSteps = steps.slice(-8);

  return (
    <div className="fixed top-0 right-0 z-40 w-[400px] max-w-full h-screen bg-[#0d1117] border-l border-[#21262d] flex flex-col">
      <div className="h-10 border-b border-[#21262d] flex items-center px-3 gap-2 shrink-0">
        <MessageSquare className="w-4 h-4 text-blue-400" />
        <span className="text-sm text-slate-300">Analyst</span>
        <QuotaBadge usage={usage} />
        <button onClick={newSession} title="New session" className="ml-auto text-slate-400 hover:text-slate-200 flex items-center gap-1 text-xs">
          <Plus className="w-3.5 h-3.5" /> New
        </button>
        <button onClick={() => setOpen(false)} className="text-slate-400 hover:text-slate-200"><X className="w-4 h-4" /></button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 && (
          <div className="mt-8 px-4">
            <p className="text-xs text-slate-600 text-center">
              Ask about your book or any issuer. Every factual answer cites its evidence.
            </p>
            {/* Gated for the same reason the composer below is: a signed-out
                visitor has no input to fill, so an ungated suggestion would be a
                click that visibly does nothing.
                They fill the box rather than send. Two reasons, and the second
                is the load-bearing one: a ticker in a suggestion is a
                placeholder — the name the reader came here about is almost
                never MSFT — and a send charges a chat turn against a daily
                quota, so a mis-click would cost them one of a countable number
                of questions before they had asked anything they meant. */}
            <AuthGate fallback={null}>
              <div className="mt-3 space-y-1.5">
                {SUGGESTIONS.map((q) => (
                  <button
                    key={q}
                    onClick={() => { setInput(q); inputRef.current?.focus(); }}
                    className="w-full text-left text-xs text-slate-500 hover:text-slate-300 border border-[#21262d] hover:border-[#30363d] rounded-md px-2.5 py-1.5 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </AuthGate>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "text-right" : ""}>
            <div className={`inline-block max-w-[92%] px-3 py-2 rounded-lg text-sm text-left ${m.role === "user" ? "bg-blue-600/20 text-slate-200" : m.gateFailed ? "bg-amber-950/40 border border-amber-800/50 text-amber-200/90" : "bg-[#161b22] text-slate-300"}`}>
              {m.gateFailed && (
                <div className="text-[10px] uppercase tracking-wide text-amber-500/80 mb-1">unverified — nothing was answered</div>
              )}
              <div className="whitespace-pre-wrap leading-relaxed">{m.text}</div>
              {m.citations.length > 0 && (
                <div className="mt-1.5 flex flex-wrap">{m.citations.map((c) => <CitationChip key={c} id={c} />)}</div>
              )}
            </div>
          </div>
        ))}
        {busy && (
          <div className="bg-[#161b22]/60 rounded-lg p-2">
            <div className="text-[10px] uppercase text-slate-600 mb-1">working…</div>
            {liveSteps.map((s) => <TraceLine key={s.seq} s={s} />)}
          </div>
        )}
        <div ref={endRef} />
      </div>

      {notice && (
        <div className="border-t border-amber-900/50 bg-amber-950/20 px-3 py-2 text-xs text-amber-300 shrink-0">
          {notice}
        </div>
      )}

      <AuthGate
        fallback={
          <div className="border-t border-[#21262d] p-3 text-center text-xs text-slate-500 shrink-0">
            Sign in to chat with the analyst.
          </div>
        }
      >
        <div className="border-t border-[#21262d] p-2 flex gap-2 shrink-0">
          <input ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()} disabled={busy}
            placeholder="Ask about an issuer…"
            className="flex-1 bg-[#161b22] border border-[#21262d] rounded px-2.5 py-1.5 text-sm text-slate-200 outline-none focus:border-blue-600 disabled:opacity-50" />
          <button onClick={send} disabled={busy || !input.trim()}
            className="px-2.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white"><Send className="w-4 h-4" /></button>
        </div>
      </AuthGate>
    </div>
  );
}
