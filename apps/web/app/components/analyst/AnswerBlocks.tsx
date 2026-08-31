"use client";

import React from "react";

import { useAudit } from "../audit";

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
 * reader sees is a property of the unit, decided here, once — so `0.1627` is
 * shown as `16.3%` and `10866320` as `$10.87M` without anyone having asked the
 * model to round, and without a rounded figure having to be verified all over
 * again. The exact value stays on the element, which is what the reader gets on
 * hover and what the audit layer shows outright.
 */

export type Slot = {
  ref: string;
  label: string;
  value: number;
  unit_class: string;
};

export type Run = string | { slot: Slot };

export type Block =
  | { type: "paragraph"; runs: Run[] }
  | { type: "metric_table"; title?: string; columns: string[]; rows: Run[][] }
  | { type: "chart"; kind: string; title?: string; series_ref: string }
  | { type: "trend"; text: string; series_ref: string }
  | { type: "absence"; text: string; absence_ref: string };

/**
 * The display conventions, in the one place they live.
 *
 * Reader precision, not ledger precision: a portfolio weight is read to a tenth
 * of a percent and a market value to two significant cents of a million. The
 * ledger keeps every digit and the citation drawer will show them; a sentence
 * that carries all of them reads as a machine rather than an analyst, which the
 * V14 baseline measured at 3 of 8 answers.
 */
export function display(slot: Slot): string {
  const v = slot.value;
  switch (slot.unit_class) {
    case "RATIO":
    case "PERCENT": {
      const pct = v * 100;
      const digits = Math.abs(pct) >= 10 ? 1 : 2;
      return `${pct.toFixed(digits)}%`;
    }
    case "MONEY": {
      const abs = Math.abs(v);
      const [scale, suffix] =
        abs >= 1e9 ? [1e9, "B"] : abs >= 1e6 ? [1e6, "M"] : abs >= 1e3 ? [1e3, "K"] : [1, ""];
      const scaled = v / scale;
      const digits = Math.abs(scaled) >= 100 ? 0 : 2;
      return `$${scaled.toFixed(digits)}${suffix}`;
    }
    case "MULTIPLE":
      return `${v.toFixed(2)}×`;
    case "COUNT":
      return Number.isInteger(v) ? String(v) : v.toFixed(2);
    default:
      return String(v);
  }
}

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

function Runs({ runs, onOpen }: { runs: Run[]; onOpen: (id: string) => void }) {
  return (
    <>
      {runs.map((r, i) =>
        typeof r === "string" ? (
          <React.Fragment key={i}>{r}</React.Fragment>
        ) : (
          <Figure key={i} slot={r.slot} onOpen={onOpen} />
        ),
      )}
    </>
  );
}

/**
 * A claim about a sequence, or about something not being reported.
 *
 * Both carry the row they rest on, and the row is reachable — which is the
 * point of having made them blocks. "VaR has been climbing" used to be a
 * sentence nothing could check; now it is a sentence with a series behind it,
 * and the reader can go and look at the series.
 */
function Claim({
  text,
  refId,
  kind,
  onOpen,
}: {
  text: string;
  refId: string;
  kind: "trend" | "absence";
  onOpen: (id: string) => void;
}) {
  return (
    <p style={{ margin: "0.5rem 0", display: "flex", gap: "0.5rem", alignItems: "baseline" }}>
      <span
        aria-hidden
        style={{ opacity: 0.55, fontSize: "0.8em", flex: "0 0 auto" }}
      >
        {kind === "trend" ? "trend" : "not reported"}
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
          {kind === "trend" ? "see the series" : "see the record"}
        </button>
      </span>
    </p>
  );
}

export function AnswerBlocks({
  blocks,
  onOpen,
}: {
  blocks: Block[];
  onOpen: (id: string) => void;
}) {
  return (
    <div>
      {blocks.map((b, i) => {
        switch (b.type) {
          case "paragraph":
            return (
              <p key={i} style={{ margin: "0.5rem 0", lineHeight: 1.65 }}>
                <Runs runs={b.runs} onOpen={onOpen} />
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
                      {b.columns.map((c, j) => (
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
                        {row.map((cell, k) => (
                          <td
                            key={k}
                            style={{
                              textAlign: k === 0 ? "left" : "right",
                              padding: "0.3rem 0.6rem",
                              borderBottom: "1px solid var(--line-faint, #eef1ea)",
                              fontVariantNumeric: "tabular-nums",
                            }}
                          >
                            {typeof cell === "string" ? cell : <Figure slot={cell.slot} onOpen={onOpen} />}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
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
            return <Claim key={i} text={b.text} refId={b.series_ref} kind="trend" onOpen={onOpen} />;

          case "absence":
            return (
              <Claim key={i} text={b.text} refId={b.absence_ref} kind="absence" onOpen={onOpen} />
            );

          default:
            return null;
        }
      })}
    </div>
  );
}
