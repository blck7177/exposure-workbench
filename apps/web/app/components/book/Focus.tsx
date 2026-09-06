"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";

import { focusReducer, type Focus } from "@/lib/book";

/**
 * What the reader is pointing at, shared by every panel on the book (V25).
 *
 * The page draws one book six ways — a holdings table, a waterfall of the day,
 * sector weights, factor betas, a correlation grid, a weight per update — and
 * until now each of them was an island. A reader who found MSFT at the top of
 * the holdings had no way to see which bar of the waterfall it was, and the
 * answer was two panels away in a chart with ten unlabelled bars.
 *
 * This is a VIEW STATE and nothing else. It holds no figure, it fetches
 * nothing, it changes no number: a panel that is not looking at what is focused
 * draws itself back, and that is the whole mechanism. The rule the page keeps —
 * a number on screen is a number a run stored — is untouched by it, which is
 * why linking is safe to do on the client while a delta is not.
 *
 * The kinds are kept apart on purpose. A sector and a ticker can share a name
 * in no book this desk holds, but a factor and a holding can (TLT and HYG are
 * both), and "the reader is pointing at the TLT holding" and "at the rates
 * factor" are different sentences about the same three letters.
 */

export type { Focus };

type FocusState = {
  focus: Focus;
  /** Point at something. Setting a new kind replaces the old one outright —
   *  two things focused at once is a state no panel knows how to draw. */
  point: (f: Focus) => void;
  clear: () => void;
  /** Whether this panel should draw `key` forward. True when nothing is
   *  focused, so an untouched page is at full strength rather than uniformly
   *  dimmed. */
  lit: (kind: "ticker" | "sector" | "factor", key: string | null | undefined) => boolean;
  /** Whether anything at all is focused — a panel dims its others only then. */
  active: boolean;
};

const Ctx = createContext<FocusState>({
  focus: null, point: () => {}, clear: () => {}, lit: () => true, active: false,
});

export function FocusProvider({ children }: { children: React.ReactNode }) {
  const [focus, setFocus] = useState<Focus>(null);
  const point = useCallback((f: Focus) => setFocus((current) => focusReducer(current, f)), []);
  const clear = useCallback(() => setFocus(null), []);
  const lit = useCallback(
    (kind: "ticker" | "sector" | "factor", key: string | null | undefined) =>
      focus == null || (focus.kind === kind && focus.key === key),
    [focus]);
  const value = useMemo(
    () => ({ focus, point, clear, lit, active: focus != null }),
    [focus, point, clear, lit]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useFocus() {
  return useContext(Ctx);
}

/** The opacity a mark draws at. One number, in one place, so six panels agree
 *  about how far back "back" is. */
export function dim(lit: boolean, active: boolean): number {
  return !active || lit ? 1 : 0.28;
}
