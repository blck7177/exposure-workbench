"use client";

import React from "react";

import type { Verified as VerifiedRecord, VerifiedMatch } from "@/lib/issuer";

/**
 * What the gate found, made visible (V13-S3/S6).
 *
 * This product's argument is that every figure in an answer was matched against
 * evidence before the answer was allowed out. The check has been running since
 * V3 and the page never said so, which left the strongest thing here as
 * something to be believed rather than seen. Meanwhile the market sells this
 * loudly and with less behind it: "No Hallucination Guarantee", an accuracy
 * benchmark, an LLM-as-judge score.
 *
 * The badge is a record, not a claim. It counts what the gate matched on the
 * turn it accepted the answer — never recomputed later, because a second
 * judgement of a stored answer is free to disagree with the one that let it
 * through.
 */

export function VerifiedBadge({ verified }: { verified?: VerifiedRecord }) {
  if (!verified) return null;
  const { figures, sources } = verified;
  return (
    <span
      title="Every figure in this answer was matched against a value held by the evidence cited for it, before the answer was shown."
      className="inline-flex items-center gap-1.5 font-mono text-[10.5px] tracking-wide text-teal-300 border border-teal-800/60 bg-teal-950/40 rounded px-2 py-0.5 whitespace-nowrap">
      <span aria-hidden className="font-semibold">✓</span>
      {figures === 0
        ? "no figures to check"
        : `${figures} figure${figures === 1 ? "" : "s"} checked`}
      {sources > 0 && ` · ${sources} source${sources === 1 ? "" : "s"}`}
    </span>
  );
}

/**
 * A figure with its basis attached.
 *
 * The gate knows which cited row supports each number and where in the text it
 * sits, so the reader can hover the number itself rather than hunt for the
 * matching citation. A figure with no match gets no underline: it is either a
 * date, a period label or one of the closed exemptions, and dressing it up as
 * verified would be the badge lying about its own scope.
 */
export function FiguredText({ text, matches, labels }: {
  text: string;
  matches?: VerifiedMatch[];
  labels?: Record<string, { type: string; label: string }>;
}) {
  if (!matches || matches.length === 0) return <>{text}</>;

  // Spans index into this exact string and cannot overlap; sorting makes the
  // walk linear. A match whose span no longer lines up (a text edited after the
  // fact — which cannot happen here, since the record is written with the
  // answer) is skipped rather than mis-highlighted.
  const ordered = [...matches].sort((a, b) => a.span[0] - b.span[0]);
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
