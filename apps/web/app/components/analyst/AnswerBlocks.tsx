"use client";

import React from "react";

import { display as displayValue } from "@/lib/display";
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

export type Run = string | { slot: Slot };

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
  // V19: `header`, `labels` and `explicit` are derived server-side from the
  // slots' names (services/answer_blocks.derive_table) and the cells are slots
  // only. `columns` and string cells are what answers stored before V19 carry,
  // and they render as they did — the grammar changed, the record did not.
  | { type: "metric_table"; title?: string; columns?: string[]; rows: Run[][]; cites?: string[];
      header?: string[]; labels?: string[]; explicit?: boolean[] }
  | { type: "chart"; kind: string; title?: string; series_ref: string }
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

/**
 * Every id the answer's prose cites, in reading order: a block's `cites`, then
 * any bare id written inside its text. This is the numbering — computed once
 * for the whole answer so the same passage is footnote 2 in every block that
 * leans on it, rather than 1 in each.
 */
export function citedIds(blocks: Block[]): string[] {
  const out: string[] = [];
  for (const b of blocks) {
    const cites = b.type === "paragraph" || b.type === "metric_table" ? b.cites ?? [] : [];
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
        for (const r of b.runs) if (typeof r !== "string") add(r.slot.ref);
        break;
      case "metric_table":
        for (const r of b.rows.flat()) if (typeof r !== "string") add(r.slot.ref);
        break;
      case "chart":
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
                            ) : (
                              <>
                                <Figure slot={cell.slot} onOpen={onOpen} />
                                {b.explicit?.[k] && k > 0 ? (
                                  <div style={{ opacity: 0.6, fontSize: "0.8em" }}>
                                    {cell.slot.caption ?? cell.slot.label.replace(/[.@]/g, " ").replace(/_/g, " ")}
                                  </div>
                                ) : null}
                              </>
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

          case "chart":
            // The series itself lives in the ledger, and the drawer already
            // knows how to show a calc row. Until the inline drawing lands, the
            // honest thing is to name what would be drawn and let the reader
            // open it — not to render an empty frame that looks like a chart
            // with no data.
            return (
              <p key={i} style={{ margin: "0.5rem 0" }}>
                {b.title ? <strong>{b.title} </strong> : null}
                <button
                  type="button"
                  onClick={() => onOpen(b.series_ref)}
                  style={{
                    background: "none",
                    border: "none",
                    padding: 0,
                    font: "inherit",
                    color: "var(--accent, #1f6f54)",
                    cursor: "pointer",
                  }}
                >
                  open the series
                </button>
              </p>
            );

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
