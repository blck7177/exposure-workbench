"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { MessageSquare, Plus, Send, X, Wrench, Brain, Send as SendIcon } from "lucide-react";
import { createSession, postMessage, getSessionDetail, type AgentStep } from "../../lib/issuer";
import { CitationChip, openEvidence } from "./Evidence";

const LS_KEY = "ew_agent_session";

type ChatMsg = { role: string; text: string; citations: string[] };

// One step in the live trace — machine-recorded (tool/delegation) solid, agent
// narration (think/respond) dashed, matching the audit "who recorded what" split.
function TraceLine({ s }: { s: AgentStep }) {
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

export function ChatPanel() {
  const [open, setOpen] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  // restore session across page navigations / refresh
  useEffect(() => {
    const sid = localStorage.getItem(LS_KEY);
    if (sid) { setSessionId(sid); getSessionDetail(sid).then((d) => {
      setMessages(d.messages.filter(m => m.content).map(m => ({ role: m.role, text: m.content || "", citations: m.citations || [] })));
      setSteps(d.steps);
    }).catch(() => localStorage.removeItem(LS_KEY)); }
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

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, steps]);

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text, citations: [] }]);
    setBusy(true);
    try {
      const sid = await ensureSession();
      const r = await postMessage(sid, text);
      setMessages((m) => [...m, { role: "assistant", text: r.text, citations: r.citations || [] }]);
      const d = await getSessionDetail(sid);
      setSteps(d.steps);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", text: `error: ${(e as Error).message}`, citations: [] }]);
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
            <div className={`inline-block max-w-[92%] px-3 py-2 rounded-lg text-sm text-left ${m.role === "user" ? "bg-blue-600/20 text-slate-200" : "bg-[#161b22] text-slate-300"}`}>
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

      <div className="border-t border-[#21262d] p-2 flex gap-2 shrink-0">
        <input value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()} disabled={busy}
          placeholder="Ask about an issuer…"
          className="flex-1 bg-[#161b22] border border-[#21262d] rounded px-2.5 py-1.5 text-sm text-slate-200 outline-none focus:border-blue-600 disabled:opacity-50" />
        <button onClick={send} disabled={busy || !input.trim()}
          className="px-2.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white"><Send className="w-4 h-4" /></button>
      </div>
    </div>
  );
}
