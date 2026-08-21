"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { MessageSquare, Plus, Send, X, Wrench, Brain, Receipt, Send as SendIcon } from "lucide-react";
import { createSession, postMessage, getSessionDetail, type AgentStep } from "../../lib/issuer";
import { getMyUsage } from "@/lib/api";
import { apiErrorDetail, type ApiError } from "@/lib/http";
import type { Usage } from "@/lib/types";
import { CitationChip, openEvidence } from "./Evidence";
import { AuthGate } from "./Auth";

const LS_KEY = "ew_agent_session";

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
  const spent = pool.remaining === 0;
  return (
    <span
      title={`${pool.used} of ${pool.limit} chat turns used today — resets ${new Date(usage!.resets_at).toLocaleString()}`}
      className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${
        spent
          ? "text-amber-400 border-amber-900/60 bg-amber-950/30"
          : "text-slate-500 border-[#21262d]"
      }`}
    >
      {pool.remaining}/{pool.limit}
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
      const detail = apiErrorDetail(e);

      // The gate (401/404/409/429) rejects before handle_message runs, and
      // handle_message is what commits the user's message — so on any 4xx the
      // server holds no record of what we optimistically rendered. Leave it up
      // and it silently disappears on the next refresh. A 5xx means the turn
      // had already started, so the message IS persisted and the bubble stays.
      if (status && status < 500) setMessages((m) => m.slice(0, -1));

      if (detail?.error === "turn_in_flight") {
        // A concurrency signal, not an account — say it in words. The realistic
        // cause is a second tab (the session id lives in localStorage, shared
        // per origin) or a previous turn whose process died and whose lease has
        // not expired yet.
        setNotice("This session already has a turn running — it may be open in another tab. Wait for it to finish, or start a new session.");
      } else if (detail?.error === "session_context_exhausted") {
        // Not an account problem and not a transient one: this conversation is
        // finished. Say which, and say what to do — the only fix is a new session.
        setNotice(
          "This conversation has grown too long for one turn. Start a new session to carry on — " +
          "your earlier answers stay in the history."
        );
        setSessionId(null);
        localStorage.removeItem(LS_KEY);
      } else if (status === 404) {
        // The session the server is being asked about does not exist for this
        // user — most often a stale id from a previous account or a wiped
        // database. Same shape as the exhausted branch above: say it, drop the
        // id, and let the next send open a fresh one, because there is nothing
        // here for the user to fix by hand.
        setNotice("That conversation is no longer available — send your message again to start a new one.");
        setSessionId(null);
        localStorage.removeItem(LS_KEY);
      } else if (detail?.error === "tool_face_unavailable") {
        // V4-S1. The tool service is down or refused this turn; the API answers
        // 503 and the turn is over. The server's own sentence is shown rather
        // than a second wording of it: it was written for this reader, and two
        // copies would be two things to keep in step. The session is NOT
        // cleared — nothing is wrong with it, and the message is still in the
        // transcript because handle_message commits it before the loop starts.
        setNotice(String(detail.detail ?? "The analysis service is briefly unavailable — try again shortly."));
      } else if (detail?.error === "quota_exceeded") {
        // An account. Show the numbers as the server reported them rather than
        // paraphrasing: the user wants to know what they spent and when it resets.
        setNotice(
          `Daily limit reached: ${detail.used}/${detail.limit} ${String(detail.kind).replace(/_/g, " ")}s` +
          (detail.scope === "global" ? " across all users" : "") +
          `. Resets ${new Date(String(detail.resets_at)).toLocaleString()}.`
        );
      } else {
        setMessages((m) => [...m, { role: "assistant", text: `error: ${(e as Error).message}`, citations: [] }]);
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
          <div className="text-xs text-slate-600 mt-8 text-center px-4">
            Ask about any issuer — e.g. &ldquo;What is NVDA&rsquo;s gross margin?&rdquo; or &ldquo;Give me a brief on MSFT.&rdquo;
            <br />Every factual answer cites its evidence.
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
          <input value={input} onChange={(e) => setInput(e.target.value)}
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
