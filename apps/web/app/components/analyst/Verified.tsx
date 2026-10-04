"use client";

import React from "react";

import type { Delivery, Verified as VerifiedRecord, VerifiedMatch } from "@/lib/issuer";

/**
 * What the observer found, made visible.
 *
 * This product's argument is that every figure in an answer was read against the
 * analyses the desk recorded before the answer was shown. The badge is a record,
 * not a claim: it counts what the observer supported, what did not hold and what
 * matched nothing, on the turn the answer was delivered — never recomputed later.
 * An answer delivered with problems says so here, in the same place.
 */
export function VerifiedBadge({ verified, delivery }: { verified?: VerifiedRecord; delivery?: Delivery }) {
  if (!verified) return null;
  const { figures, supported, contradicted, unsourced, ambiguous, completion } = verified;
  const problems = (contradicted ?? 0) + (unsourced ?? 0) + (ambiguous ?? 0);
  const clean = problems === 0 && delivery !== "answered_with_problems";
  const tone = clean
    ? "text-teal-300 border-teal-800/60 bg-teal-950/40"
    : "text-amber-400 border-amber-800/60 bg-amber-950/30";
  const title = clean
    ? "Every figure in this answer was matched against an analysis the desk recorded this turn, before the answer was shown."
    : `${problems} figure${problems === 1 ? "" : "s"} did not hold against the desk's record and could not be revised within the turn; they are marked in the record.`;
  return (
    <span title={title}
      className={`inline-flex items-center gap-1.5 font-mono text-[10.5px] tracking-wide border rounded px-2 py-0.5 whitespace-nowrap ${tone}`}>
      <span aria-hidden className="font-semibold">{clean ? "✓" : "!"}</span>
      {figures === 0
        ? "no figures to check"
        : `${supported} of ${figures} figure${figures === 1 ? "" : "s"} supported`}
      {problems > 0 && ` · ${problems} not`}
      {completion && completion !== "unknown" && ` · covers ${completion.replace("_", " ")}`}
    </span>
  );
}

/**
 * A figure with its basis attached — the prose renderer for answers stored
 * before figures became blocks. Nothing new is written in this shape.
 */
export function FiguredText({ text, matches, labels }: {
  text: string;
  matches?: VerifiedMatch[];
  labels?: Record<string, { type: string; label: string }>;
}) {
  if (!matches || matches.length === 0) return <>{text}</>;
  const ordered = matches.filter((m): m is VerifiedMatch & { span: [number, number] } => Array.isArray(m.span))
    .sort((a, b) => a.span[0] - b.span[0]);
  const out: React.ReactNode[] = [];
  let cursor = 0;
  ordered.forEach((m, i) => {
    const [start, end] = m.span;
    if (start < cursor || end > text.length || text.slice(start, end) !== m.surface) return;
    if (start > cursor) out.push(<span key={`t${i}`}>{text.slice(cursor, start)}</span>);
    const source = m.source_id ? labels?.[m.source_id]?.label ?? m.source_id : null;
    const basis = m.how === "quoted"
      ? "Quoted verbatim from a cited passage"
      : [m.label, source].filter(Boolean).join(" · ");
    out.push(
      <span key={`m${i}`} title={basis}
        className="border-b border-dotted border-teal-500/60 hover:border-solid hover:bg-teal-500/10 cursor-help">
        {m.surface}
      </span>
    );
    cursor = end;
  });
  if (cursor < text.length) out.push(<span key="tail">{text.slice(cursor)}</span>);
  return <>{out}</>;
}
