"use client";

import React, { useEffect, useRef, useState } from "react";

import { C, fmtMonth } from "../charts/frame";
import { LineChart } from "../charts/line";
import { display as displayValue } from "@/lib/display";
import { getEvidence } from "@/lib/issuer";
import { useAudit } from "../audit";
import { AnswerText, idsIn } from "./AnswerText";

/**
 * An answer made of blocks, with every figure resolved from the ledger (V14-C).
 *
 * The prose renderer beside this one takes a string and hunts through it for
 * figures the gate matched, because in a v1 answer the numbers are IN the
 * sentence. Here they never were: the model wrote slots, the gate resolved them
 * against the rows they name, and what arrives is the ledger's own value with
 * the ledger's own name for it.
 *
 * That moves one decision out of the model's hands entirely. How many digits a
 * reader sees is a property of the unit — decided in lib/display, once, and
 * held to the server's own rule by a shared fixture — so `0.1627` is shown as
 * `16.3%` and `10866320` as `$10.87M` without anyone having asked the model to
 * round, and without a rounded figure having to be verified all over again.
 * The exact value stays on the element, which is what the reader gets on hover
 * and what the audit layer shows outright.
 *
 * V15 adds two things a block can rest on besides a row: `cites`, the passages
 * a paragraph's or table's prose was checked against, shown as numbered
 * footnotes after the block; and `action`, work this turn started, by its id.
 * The same shapes now make up an issuer brief's six sections.
 */

export type Slot = {
  ref: string;
  label: string;
  value: number;
  unit_class: string;
  /** V19: the words a table cell was derived from (subject + name), set on table cells only. */
  caption?: string;
};

/**
 * V24. A fact as the gate filled it: the record the tool showed the model,
 * plus its display string and, for a series, its own summary. The chip shows
 * `display`; hover says what the figure IS (measure · subject · as of · unit);
 * click opens the drawer on the fact, which drills to the rows it rests on.
 */
export type FactFill = {
  id: string;
  kind: "scalar" | "series" | "passage" | "absence" | "task";
  measure: string;
  subject?: string | null;
  unit?: string | null;
  value?: number | null;
  as_of?: string | null;
  window?: Record<string, unknown> | null;
  params?: Record<string, unknown> | null;
  standalone?: boolean;
  sources?: string[];
  display?: string;
  text?: string | null;
  series?: TrendSeries | null;
};

/** V24. A number the model wrote in prose that the gate resolved: the written
 *  text, linked to the fact(s) it equals or the passage that states it. */
export type Link = { to: "fact" | "passage"; ids: string[]; as_written: string };

export type Run = string | { slot: Slot } | { fact: FactFill } | { link: Link };

/** A trend's series, stating its own first and last point (V19). */
export type TrendSeries = {
  label: string;
  unit_class: string;
  n: number;
  from: { period: string; value: number };
  to: { period: string; value: number };
  direction: "up" | "down" | "flat";
};

export type Block =
  | { type: "paragraph"; runs: Run[]; cites?: string[] }
  // V24: rows are facts; header, labels and explicit are derived server-side
  // from the facts' measures and subjects (services/answer.derive_table).
  | { type: "table"; title?: string; rows: { fact: FactFill }[][]; cites?: string[];
      header?: string[]; labels?: string[]; explicit?: boolean[] }
  | { type: "chart"; kind: string; title?: string; fact?: FactFill; series_ref?: string }
  // ── pre-V24 blocks: stored answers are records and render as they were ──
  | { type: "metric_table"; title?: string; columns?: string[]; rows: Run[][]; cites?: string[];
      header?: string[]; labels?: string[]; explicit?: boolean[] }
  | { type: "trend"; text: string; series_ref: string; series?: TrendSeries }
  | { type: "absence"; text: string; absence_ref: string }
  | { type: "action"; text: string; task_ref: string };

/** The reader's form of a slot — see lib/display for the rule itself. */
export function display(slot: Slot): string {
  return displayValue(slot.value, slot.unit_class);
}

function stringRuns(b: Block): string[] {
  switch (b.type) {
    case "paragraph":
      return b.runs.filter((r): r is string => typeof r === "string");
    case "metric_table":
      return b.rows.flat().filter((r): r is string => typeof r === "string");
    default:
      return [];
  }
}

function refOf(r: Run): string[] {
  if (typeof r === "string") return [];
  if ("slot" in r) return [r.slot.ref];
  if ("fact" in r) return [r.fact.id];
  if ("link" in r) return r.link.ids;
  return [];
}

/**
 * Every id the answer's prose cites, in reading order: a block's `cites`, then
 * any bare id written inside its text. This is the numbering — computed once
 * for the whole answer so the same passage is footnote 2 in every block that
 * leans on it, rather than 1 in each.
 */
export function citedIds(blocks: Block[]): string[] {
  const out: string[] = [];
  for (const b of blocks) {
    const cites = b.type === "paragraph" || b.type === "metric_table" || b.type === "table" ? b.cites ?? [] : [];
    for (const id of idsIn(stringRuns(b).join("\n"), cites)) {
      if (!out.includes(id)) out.push(id);
    }
  }
  return out;
}

/** Every id the answer leans on — cites, slots and block-level refs alike —
 *  which is what to ask the label endpoint for. */
export function idsInBlocks(blocks: Block[]): string[] {
  const out = citedIds(blocks);
  const add = (id: string) => {
    if (!out.includes(id)) out.push(id);
  };
  for (const b of blocks) {
    switch (b.type) {
      case "paragraph":
        for (const r of b.runs) for (const id of refOf(r)) add(id);
        break;
      case "metric_table":
        for (const r of b.rows.flat()) for (const id of refOf(r)) add(id);
        break;
      case "table":
        for (const c of b.rows.flat()) add(c.fact.id);
        break;
      case "chart":
        if (b.fact) add(b.fact.id);
        else if (b.series_ref) add(b.series_ref);
        break;
      case "trend":
        add(b.series_ref);
        break;
      case "absence":
        add(b.absence_ref);
        break;
      case "action":
        add(b.task_ref);
        break;
    }
  }
  return out;
}

type Labels = Record<string, { type: string; label: string }>;

function Figure({ slot, onOpen }: { slot: Slot; onOpen: (id: string) => void }) {
  const { audit } = useAudit();
  return (
    <button
      type="button"
      onClick={() => onOpen(slot.ref)}
      title={`${slot.label} = ${slot.value}`}
      style={{
        background: "none",
        border: "none",
        padding: 0,
        font: "inherit",
        color: "inherit",
        cursor: "pointer",
        borderBottom: "1px solid var(--line-strong, #b9c2bb)",
        fontVariantNumeric: "tabular-nums",
      }}
    >
      {display(slot)}
      {audit ? (
        <span style={{ opacity: 0.6, fontSize: "0.85em" }}> ({slot.label})</span>
      ) : null}
    </button>
  );
}

/** What a fact IS, in one line: measure · subject · as of / window · unit. */
export function identityOf(f: FactFill): string {
  const when = f.as_of
    ?? (f.window && typeof f.window === "object"
      ? [f.window.start, f.window.end].filter(Boolean).join(" – ") || String(f.window.name ?? f.window.months ?? f.window.days ?? "")
      : "");
  return [f.measure.replace(/[._]/g, " ").replace(/:/g, " "), f.subject, when ? `as of ${when}` : null, f.unit]
    .filter(Boolean).join(" · ");
}

/**
 * V24. A fact, shown as what it is. A scalar is its display value; a series is
 * its last point with the V19 series line under it; an absence, a task and a
 * passage are their label. Hover states the identity; click opens the drawer.
 */
function FactChip({ fact, onOpen }: { fact: FactFill; onOpen: (id: string) => void }) {
  const { audit } = useAudit();
  const label = fact.kind === "absence" ? "not held" : fact.kind === "task" ? "started" : fact.kind === "passage" ? "passage" : null;
  return (
    <>
      <button
        type="button"
        onClick={() => onOpen(fact.id)}
        title={identityOf(fact)}
        style={{
          background: "none", border: "none", padding: 0, font: "inherit", color: "inherit", cursor: "pointer",
          borderBottom: "1px solid var(--line-strong, #b9c2bb)", fontVariantNumeric: "tabular-nums",
        }}
      >
        {label ? (
          <span style={{ opacity: 0.75, fontSize: "0.85em", fontVariant: "small-caps" }}>{label}</span>
        ) : (
          fact.display ?? String(fact.value ?? "")
        )}
        {audit ? <span style={{ opacity: 0.6, fontSize: "0.85em" }}> ({identityOf(fact)})</span> : null}
      </button>
      {fact.kind === "absence" && fact.text ? <span style={{ opacity: 0.8 }}> — {fact.text}</span> : null}
      {fact.kind === "series" && fact.series ? <SeriesLine series={fact.series} onOpen={() => onOpen(fact.id)} /> : null}
    </>
  );
}

/**
 * V24. A number the model wrote in prose, as the gate resolved it: the text as
 * written, underlined, opening the fact it equals — or, when several facts
 * share the value, a chooser naming each one's identity, so the reader picks
 * and the page never guesses.
 */
function LinkText({ link, labels, onOpen }: { link: Link; labels?: Labels; onOpen: (id: string) => void }) {
  if (link.ids.length === 1) {
    const id = link.ids[0];
    return (
      <button type="button" onClick={() => onOpen(id)}
        title={link.to === "passage" ? "Stated in a cited passage — open it" : labels?.[id]?.label ?? id}
        style={{ background: "none", border: "none", padding: 0, font: "inherit", color: "inherit", cursor: "pointer",
                 borderBottom: "1px dotted var(--line-strong, #b9c2bb)", fontVariantNumeric: "tabular-nums" }}>
        {link.as_written}
      </button>
    );
  }
  return (
    <span style={{ position: "relative", display: "inline-block" }}>
      <details style={{ display: "inline" }}>
        <summary style={{ display: "inline", cursor: "pointer", listStyle: "none",
                          borderBottom: "1px dotted var(--line-strong, #b9c2bb)", fontVariantNumeric: "tabular-nums" }}
          title={`${link.ids.length} facts share this value — choose one`}>
          {link.as_written}
        </summary>
        <span style={{ position: "absolute", left: 0, top: "1.4em", zIndex: 10, minWidth: "16rem",
                       background: "var(--panel, #171d26)", border: "1px solid var(--line, #30363d)",
                       borderRadius: 6, padding: "0.35rem 0.5rem", fontSize: "0.85em", display: "flex",
                       flexDirection: "column", gap: "0.25rem" }}>
          {link.ids.map((id) => (
            <button key={id} type="button" onClick={() => onOpen(id)}
              style={{ background: "none", border: "none", padding: 0, font: "inherit", color: "inherit",
                       cursor: "pointer", textAlign: "left" }}>
              {labels?.[id]?.label ?? id} →
            </button>
          ))}
        </span>
      </details>
    </span>
  );
}

/**
 * A text run goes through the prose renderer's annotation walk rather than
 * straight to the page, because a brief's historical text — and a model that
 * writes "as chunk_… shows" — puts evidence ids INSIDE the sentence, and those
 * should be footnotes a reader can open, not hex. The numbering is the
 * answer-wide one, so a run's footnote agrees with the block's own.
 */
function Text({
  text,
  order,
  labels,
  onOpen,
}: {
  text: string;
  order: string[];
  labels?: Labels;
  onOpen: (id: string) => void;
}) {
  return <AnswerText text={text} citations={order} labels={labels} onOpen={onOpen} inline />;
}

function Runs({
  runs,
  order,
  labels,
  onOpen,
}: {
  runs: Run[];
  order: string[];
  labels?: Labels;
  onOpen: (id: string) => void;
}) {
  return (
    <>
      {runs.map((r, i) =>
        typeof r === "string" ? (
          <Text key={i} text={r} order={order} labels={labels} onOpen={onOpen} />
        ) : "fact" in r ? (
          <FactChip key={i} fact={r.fact} onOpen={onOpen} />
        ) : "link" in r ? (
          <LinkText key={i} link={r.link} labels={labels} onOpen={onOpen} />
        ) : (
          <Figure key={i} slot={r.slot} onOpen={onOpen} />
        ),
      )}
    </>
  );
}

/**
 * The passages a block's prose was checked against, as footnotes after it —
 * the same buttons AnswerText draws for an id inside a sentence, so a reader
 * learns one visual language for "this rests on that".
 */
function Cites({
  ids,
  order,
  labels,
  onOpen,
}: {
  ids: string[];
  order: string[];
  labels?: Labels;
  onOpen: (id: string) => void;
}) {
  if (ids.length === 0) return null;
  return (
    <span className="whitespace-nowrap">
      {ids.map((id) => (
        <sup key={id} className="align-super leading-none">
          <button
            type="button"
            onClick={() => onOpen(id)}
            title={labels?.[id]?.label ?? id}
            className="font-mono text-[10px] leading-none align-baseline ml-0.5 px-1 py-px rounded border border-teal-800/60 bg-teal-950/40 text-teal-300 hover:bg-teal-500 hover:text-[#0b0f14] transition-colors"
          >
            {order.indexOf(id) + 1}
          </button>
        </sup>
      ))}
    </span>
  );
}

/**
 * The series stating its own first and last point (V19). The direction is
 * computed server-side from those two values, so "climbed" in the sentence
 * under it is the model's word and the arrow is the series'. The two can
 * disagree, and when they do the reader sees both.
 */
/**
 * A series fact, drawn (V25).
 *
 * A `chart` block used to render as the words "open the series" and a link. The
 * points were never missing — the fact's own record holds every one of them,
 * which is what the drawer draws when the link is followed — so the reader was
 * being asked to leave the answer to see the shape of the thing the sentence
 * was about.
 *
 * The points are fetched from the evidence the block already cites, when the
 * block is on screen, and cached by id: an answer citing seventeen series makes
 * seventeen small reads as they are scrolled to, and none for the ones that are
 * never looked at. Nothing here computes anything — the line is the ledger's
 * own points, and the chip beside it still opens the row.
 */
const seriesCache = new Map<string, { period: string; value: number }[]>();

function InlineSeries({ id, unit, onOpen }: {
  id: string;
  unit: string | null | undefined;
  onOpen: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [points, setPoints] = useState<{ period: string; value: number }[] | null>(
    () => seriesCache.get(id) ?? null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (points || failed) return;
    const el = host.current;
    if (!el) return;
    let cancelled = false;
    const load = () => {
      getEvidence(id).then((ev) => {
        if (cancelled) return;
        const body = ev.body as Record<string, unknown>;
        const raw = (body.points ?? (body.result as Record<string, unknown> | undefined)?.points);
        const rows = Array.isArray(raw) ? raw : [];
        const parsed = rows.flatMap((p) => {
          // A fact's points are [period, value] pairs; a calc row's are objects
          // that end on `end`, `as_of` or `period_end`. Both are the ledger's
          // own spellings and neither is normalised on the way in.
          if (Array.isArray(p) && p.length >= 2 && typeof p[1] === "number") {
            return [{ period: String(p[0]), value: p[1] }];
          }
          if (p && typeof p === "object") {
            const o = p as Record<string, unknown>;
            const period = o.end ?? o.as_of ?? o.period_end;
            if (typeof period === "string" && typeof o.value === "number") {
              return [{ period, value: o.value }];
            }
          }
          return [];
        });
        if (parsed.length < 2) { setFailed(true); return; }
        seriesCache.set(id, parsed);
        setPoints(parsed);
      }).catch(() => { if (!cancelled) setFailed(true); });
    };
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { observer.disconnect(); load(); }
    });
    observer.observe(el);
    return () => { cancelled = true; observer.disconnect(); };
  }, [id, points, failed]);

  // No frame while there is nothing to draw: an empty axis looks like a series
  // that measured zero, and the sentence above already carries the figures.
  if (failed) return null;
  return (
    <div ref={host} style={{ margin: "0.4rem 0" }}>
      {points && (
        <LineChart
          x={points.map((p) => p.period)}
          series={[{
            key: id, label: "", colour: C.s1,
            points: points.map((p) => p.value),
            endLabel: unit ? displayValue(points[points.length - 1].value, unit) : undefined,
          }]}
          height={132}
          padLeft={58}
          xTicks={points.map((p, i) => ({ at: i, label: fmtMonth(p.period) }))
            .filter((_, i) => i % Math.max(1, Math.ceil(points.length / 4)) === 0)}
          yFormat={(v) => (unit ? displayValue(v, unit) : String(v))}
          ariaLabel={`${points.length} points, ${points[0].period} to ${points[points.length - 1].period}`}
          tipRows={(i) => [{
            label: points[i].period,
            value: unit ? displayValue(points[i].value, unit) : String(points[i].value),
            colour: C.s1,
          }]}
        />
      )}
      <button type="button" onClick={onOpen}
        style={{ background: "none", border: "none", padding: 0, font: "inherit",
                 fontSize: "0.78rem", color: "var(--accent, #2dd4bf)", cursor: "pointer" }}>
        {points ? "open the series" : "open the series"}
      </button>
    </div>
  );
}

function SeriesLine({ series, onOpen }: { series: TrendSeries; onOpen: () => void }) {
  const arrow = { up: "↑", down: "↓", flat: "→" }[series.direction];
  const v = (x: number) => displayValue(x, series.unit_class);
  return (
    <p style={{ margin: "0.5rem 0 0", fontSize: "0.9em", opacity: 0.85, fontVariantNumeric: "tabular-nums" }}>
      <button
        type="button"
        onClick={onOpen}
        title={`${series.n} points`}
        style={{ background: "none", border: "none", padding: 0, font: "inherit", color: "inherit", cursor: "pointer" }}
      >
        <span style={{ opacity: 0.7 }}>{series.label}</span>{" "}
        {v(series.from.value)} <span style={{ opacity: 0.6 }}>({series.from.period})</span>{" "}
        {arrow} {v(series.to.value)} <span style={{ opacity: 0.6 }}>({series.to.period})</span>
      </button>
    </p>
  );
}

/**
 * A claim about a sequence, about something not being reported, or about work
 * this turn set going.
 *
 * All three carry the row they rest on, and the row is reachable — which is
 * the point of having made them blocks. "VaR has been climbing" used to be a
 * sentence nothing could check; now it is a sentence with a series behind it,
 * and the reader can go and look at the series. "I have started a research
 * run" likewise names the task, and the reader can go and watch it.
 */
function Claim({
  text,
  refId,
  kind,
  onOpen,
}: {
  text: string;
  refId: string;
  kind: "trend" | "absence" | "action";
  onOpen: (id: string) => void;
}) {
  const label = { trend: "trend", absence: "not reported", action: "started" }[kind];
  const link = { trend: "see the series", absence: "see the record", action: "see the task" }[kind];
  return (
    <p style={{ margin: "0.5rem 0", display: "flex", gap: "0.5rem", alignItems: "baseline" }}>
      <span
        aria-hidden
        style={{ opacity: 0.55, fontSize: "0.8em", flex: "0 0 auto" }}
      >
        {label}
      </span>
      <span>
        {text}{" "}
        <button
          type="button"
          onClick={() => onOpen(refId)}
          style={{
            background: "none",
            border: "none",
            padding: 0,
            font: "inherit",
            color: "var(--accent, #1f6f54)",
            cursor: "pointer",
          }}
        >
          {link}
        </button>
      </span>
    </p>
  );
}

export function AnswerBlocks({
  blocks,
  labels,
  onOpen,
}: {
  blocks: Block[];
  labels?: Labels;
  onOpen: (id: string) => void;
}) {
  const { audit } = useAudit();
  const order = citedIds(blocks);
  return (
    <div>
      {blocks.map((b, i) => {
        switch (b.type) {
          case "paragraph":
            return (
              <p key={i} style={{ margin: "0.5rem 0", lineHeight: 1.65 }}>
                <Runs runs={b.runs} order={order} labels={labels} onOpen={onOpen} />
                <Cites ids={b.cites ?? []} order={order} labels={labels} onOpen={onOpen} />
              </p>
            );

          case "table":
            return (
              <div key={i} style={{ margin: "0.75rem 0", overflowX: "auto" }}>
                {b.title ? <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>{b.title}</div> : null}
                <table style={{ borderCollapse: "collapse", fontSize: "0.95em", width: "100%" }}>
                  <thead>
                    <tr>
                      {["", ...(b.header ?? [])].map((c, j) => (
                        <th key={j} style={{ textAlign: j === 0 ? "left" : "right", padding: "0.3rem 0.6rem",
                                             borderBottom: "1px solid var(--line, #dfe3db)", fontWeight: 500,
                                             opacity: 0.7, whiteSpace: "nowrap" }}>
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((row, j) => (
                      <tr key={j}>
                        <td style={{ textAlign: "left", padding: "0.3rem 0.6rem",
                                     borderBottom: "1px solid var(--line-faint, #eef1ea)" }}>
                          {b.labels?.[j] ?? ""}
                        </td>
                        {row.map((cell, k) => (
                          <td key={k} style={{ textAlign: "right", padding: "0.3rem 0.6rem",
                                               borderBottom: "1px solid var(--line-faint, #eef1ea)",
                                               fontVariantNumeric: "tabular-nums" }}>
                            <FactChip fact={cell.fact} onOpen={onOpen} />
                            {b.explicit?.[k] ? (
                              <div style={{ opacity: 0.6, fontSize: "0.8em" }}>{identityOf(cell.fact)}</div>
                            ) : null}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {b.cites && b.cites.length > 0 ? (
                  <div style={{ marginTop: "0.25rem" }}>
                    <Cites ids={b.cites} order={order} labels={labels} onOpen={onOpen} />
                  </div>
                ) : null}
              </div>
            );

          case "metric_table":
            return (
              <div key={i} style={{ margin: "0.75rem 0", overflowX: "auto" }}>
                {b.title ? (
                  <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>{b.title}</div>
                ) : null}
                <table style={{ borderCollapse: "collapse", fontSize: "0.95em", width: "100%" }}>
                  <thead>
                    <tr>
                      {(b.header ? ["", ...b.header] : b.columns ?? []).map((c, j) => (
                        <th
                          key={j}
                          style={{
                            textAlign: j === 0 ? "left" : "right",
                            padding: "0.3rem 0.6rem",
                            borderBottom: "1px solid var(--line, #dfe3db)",
                            fontWeight: 500,
                            opacity: 0.7,
                            whiteSpace: "nowrap",
                          }}
                        >
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((row, j) => (
                      <tr key={j}>
                        {b.labels ? (
                          <td
                            style={{
                              textAlign: "left",
                              padding: "0.3rem 0.6rem",
                              borderBottom: "1px solid var(--line-faint, #eef1ea)",
                            }}
                          >
                            {b.labels[j]}
                          </td>
                        ) : null}
                        {row.map((cell, k) => (
                          <td
                            key={k}
                            style={{
                              textAlign: k === 0 && !b.labels ? "left" : "right",
                              padding: "0.3rem 0.6rem",
                              borderBottom: "1px solid var(--line-faint, #eef1ea)",
                              fontVariantNumeric: "tabular-nums",
                            }}
                          >
                            {typeof cell === "string" ? (
                              <Text text={cell} order={order} labels={labels} onOpen={onOpen} />
                            ) : "slot" in cell ? (
                              <>
                                <Figure slot={cell.slot} onOpen={onOpen} />
                                {b.explicit?.[k] && k > 0 ? (
                                  <div style={{ opacity: 0.6, fontSize: "0.8em" }}>
                                    {cell.slot.caption ?? cell.slot.label.replace(/[.@]/g, " ").replace(/_/g, " ")}
                                  </div>
                                ) : null}
                              </>
                            ) : "fact" in cell ? (
                              <FactChip fact={cell.fact} onOpen={onOpen} />
                            ) : (
                              <LinkText link={cell.link} labels={labels} onOpen={onOpen} />
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {b.cites && b.cites.length > 0 ? (
                  <div style={{ marginTop: "0.25rem" }}>
                    <Cites ids={b.cites} order={order} labels={labels} onOpen={onOpen} />
                  </div>
                ) : null}
              </div>
            );

          case "chart": {
            // V25: the series is drawn from the ledger's own points, fetched
            // from the evidence this block already cites. The sentence above it
            // (`SeriesLine`) stays — it states the two ends and the direction,
            // and it is what a reader with no chart still gets.
            const ref = b.fact?.id ?? b.series_ref ?? "";
            return (
              <div key={i} style={{ margin: "0.5rem 0" }}>
                {b.title ? <strong>{b.title} </strong> : null}
                {b.fact?.series ? <SeriesLine series={b.fact.series} onOpen={() => onOpen(ref)} /> : null}
                {ref ? (
                  <InlineSeries id={ref} unit={b.fact?.unit ?? b.fact?.series?.unit_class}
                    onOpen={() => onOpen(ref)} />
                ) : null}
              </div>
            );
          }

          case "trend":
            return (
              <div key={i}>
                {b.series ? <SeriesLine series={b.series} onOpen={() => onOpen(b.series_ref)} /> : null}
                <Claim text={b.text} refId={b.series_ref} kind="trend" onOpen={onOpen} />
              </div>
            );

          case "absence":
            return (
              <Claim key={i} text={b.text} refId={b.absence_ref} kind="absence" onOpen={onOpen} />
            );

          case "action":
            return <Claim key={i} text={b.text} refId={b.task_ref} kind="action" onOpen={onOpen} />;

          default:
            return null;
        }
      })}
      {audit && order.length > 0 ? (
        <span className="block mt-1 font-mono text-[10px] text-slate-600 break-all">
          {order.map((id, i) => `[${i + 1}] ${id}`).join("  ")}
        </span>
      ) : null}
    </div>
  );
}
