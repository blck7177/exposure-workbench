"use client";

import React from "react";

import type { VerifiedMatch } from "@/lib/issuer";
import { useAudit } from "../audit";

/**
 * An answer, rendered with both of its annotations in one pass (V13-S6).
 *
 * There are two things to do to the stored text and they overlap:
 *
 *   - Evidence ids are replaced by numbered citations. 131 of the 234 answers in
 *     the live database carry them inside the sentence.
 *   - Figures the gate matched are underlined and carry their basis on hover.
 *
 * The first version did these in two components, stripping the ids and then
 * highlighting the figures. That is wrong, and quietly: the gate's spans are
 * offsets into the ORIGINAL string, so removing a bracketed citation at the end
 * of the first paragraph shifts every figure in the second. The check inside
 * the highlighter (does the span still hold the surface it recorded?) meant the
 * result was never mis-highlighted — it silently lost the highlighting instead,
 * which is the failure that does not look like one.
 *
 * So: one walk, over the original text, with both kinds of annotation sorted
 * into it. Nothing is removed before anything is located.
 */

type Annotation =
  | { start: number; end: number; kind: "figure"; match: VerifiedMatch }
  | { start: number; end: number; kind: "cites"; ids: string[] };

const ID_BODY = "(?:fact|calc|chunk|src|alert|run|pos)_[0-9a-f]{6,}";
const BRACKETED = new RegExp(`\\s*\\[\\s*(${ID_BODY}(?:\\s*,\\s*${ID_BODY})*)\\s*\\]`, "g");
const BARE = new RegExp(`(,\\s*)?(${ID_BODY})`, "g");

export function AnswerText({ text, citations, matches, labels, onOpen }: {
  text: string;
  citations: string[];
  matches?: VerifiedMatch[];
  labels?: Record<string, { type: string; label: string }>;
  onOpen: (id: string) => void;
}) {
  const { audit } = useAudit();
  const order = [...citations];
  const numberOf = (id: string) => {
    const i = order.indexOf(id);
    return i >= 0 ? i + 1 : order.push(id);
  };

  const spans: Annotation[] = [];

  for (const m of text.matchAll(BRACKETED)) {
    const start = m.index ?? 0;
    spans.push({
      start, end: start + m[0].length, kind: "cites",
      ids: m[1].split(",").map((s) => s.trim()),
    });
  }
  for (const m of text.matchAll(BARE)) {
    const start = m.index ?? 0;
    // A bare id inside a bracketed group is already accounted for.
    if (spans.some((s) => start >= s.start && start < s.end)) continue;
    spans.push({ start, end: start + m[0].length, kind: "cites", ids: [m[2]] });
  }
  for (const match of matches ?? []) {
    const [start, end] = match.span;
    if (end > text.length || text.slice(start, end) !== match.surface) continue;
    // A figure inside a citation group cannot happen, but a guard here costs
    // nothing and keeps the walk's non-overlap invariant true by construction.
    if (spans.some((s) => start < s.end && end > s.start)) continue;
    spans.push({ start, end, kind: "figure", match });
  }

  spans.sort((a, b) => a.start - b.start);

  const out: React.ReactNode[] = [];
  let cursor = 0;
  let key = 0;
  for (const s of spans) {
    if (s.start < cursor) continue;
    if (s.start > cursor) out.push(<span key={key++}>{text.slice(cursor, s.start)}</span>);
    if (s.kind === "cites") {
      out.push(
        <span key={key++} className="whitespace-nowrap">
          {s.ids.map((id) => (
            <sup key={id} className="align-super leading-none">
              <button onClick={() => onOpen(id)} title={labels?.[id]?.label ?? id}
                className="font-mono text-[10px] leading-none align-baseline ml-0.5 px-1 py-px rounded border border-teal-800/60 bg-teal-950/40 text-teal-300 hover:bg-teal-500 hover:text-[#0b0f14] transition-colors">
                {numberOf(id)}
              </button>
            </sup>
          ))}
        </span>
      );
    } else {
      const m = s.match;
      const source = m.source_id ? labels?.[m.source_id]?.label ?? m.source_id : null;
      const basis = m.how === "quoted"
        ? "Quoted verbatim from a cited passage"
        : [m.label, source].filter(Boolean).join(" · ") || "Matched against cited evidence";
      out.push(
        <span key={key++} title={basis} tabIndex={0}
          className="border-b border-dotted border-teal-500/60 hover:border-solid hover:bg-teal-500/10 focus:bg-teal-500/10 cursor-help outline-none">
          {m.surface}
        </span>
      );
    }
    cursor = s.end;
  }
  if (cursor < text.length) out.push(<span key={key++}>{text.slice(cursor)}</span>);

  return (
    <>
      <span className="whitespace-pre-wrap leading-relaxed">{out}</span>
      {audit && order.length > 0 && (
        <span className="block mt-1 font-mono text-[10px] text-slate-600 break-all">
          {order.map((id, i) => `[${i + 1}] ${id}`).join("  ")}
        </span>
      )}
    </>
  );
}

/** Every evidence id a piece of text refers to, in citation order — what to ask
 *  the label endpoint for. */
export function idsIn(text: string | null | undefined, citations?: string[]): string[] {
  const out = [...(citations ?? [])];
  for (const m of (text ?? "").matchAll(new RegExp(ID_BODY, "g"))) {
    if (!out.includes(m[0])) out.push(m[0]);
  }
  return out;
}
