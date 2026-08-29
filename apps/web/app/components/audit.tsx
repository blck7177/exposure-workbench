"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

/**
 * The audit layer (V13-S4/S6).
 *
 * Everything this desk records stays recorded. What changes is who it is
 * addressed to: a reader gets the answer and the evidence behind it, and the
 * person running the desk can turn on the layer that shows how it was produced
 * — run and task ids, the model and what the turn cost, the raw tool names, the
 * mapping and primitive versions on a piece of evidence.
 *
 * None of that is secret, and hiding it would be the wrong reading of this
 * batch. It is machinery, and machinery on the page a stranger reads first is
 * what made `Run ID run_95ebe31c5e51` and `gpt-5.4-mini-2026-03-17 · 8963 in /
 * 412 out` the second and third things a visitor saw. FINRA's 2026 report
 * expects prompts, responses and model versions to be RETAINED, which is an
 * argument for keeping them, not for rendering them.
 *
 * Per browser, not per account: it is a way of looking, like a zoom level, and
 * it survives a reload because somebody debugging their own desk should not
 * have to switch it on at every navigation. localStorage is read defensively —
 * a private window throws on access rather than returning null.
 */

const KEY = "ew_audit_layer";

type AuditState = { audit: boolean; setAudit: (v: boolean) => void };

const AuditContext = createContext<AuditState>({ audit: false, setAudit: () => {} });

export function AuditProvider({ children }: { children: React.ReactNode }) {
  const [audit, setAuditState] = useState(false);

  // Read after mount, never during render: the server renders this tree too, and
  // a value taken from localStorage while rendering is a hydration mismatch that
  // shows up as a flash of the wrong layer.
  useEffect(() => {
    try {
      if (window.localStorage.getItem(KEY) === "1") setAuditState(true);
    } catch {
      // A private window, or site data blocked. The layer simply starts off.
    }
  }, []);

  const setAudit = useCallback((v: boolean) => {
    setAuditState(v);
    try {
      window.localStorage.setItem(KEY, v ? "1" : "0");
    } catch {
      // Not being able to remember the choice is not a reason to refuse it.
    }
  }, []);

  return <AuditContext.Provider value={{ audit, setAudit }}>{children}</AuditContext.Provider>;
}

export function useAudit(): AuditState {
  return useContext(AuditContext);
}

/**
 * Something only the operator should be reading.
 *
 * A component rather than a CSS class so the content is not in the DOM at all
 * when the layer is off — which is what makes "the reader's layer renders no
 * internal ids" a property a test can check by reading the rendered page.
 */
export function AuditOnly({ children }: { children: React.ReactNode }) {
  const { audit } = useAudit();
  return audit ? <>{children}</> : null;
}

export function AuditToggle() {
  const { audit, setAudit } = useAudit();
  return (
    <button
      onClick={() => setAudit(!audit)}
      aria-pressed={audit}
      title="Show how these answers were produced — ids, model, tool calls"
      className={`text-xs px-2 py-1 rounded border transition-colors ${
        audit
          ? "border-[#30363d] bg-[#1d2530] text-slate-200"
          : "border-transparent text-slate-500 hover:text-slate-300"
      }`}>
      Audit
    </button>
  );
}
