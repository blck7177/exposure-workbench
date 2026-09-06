"use client";

import React from "react";

import type { Evidence } from "@/lib/issuer";
import { display as displayValue } from "@/lib/display";
import { AuditOnly } from "../audit";
import { C, fmtDate, fmtMonth } from "../charts/frame";
import { LineChart } from "../charts/line";

/**
 * Evidence, rendered as what it is (V13-S3).
 *
 * The drawer used to print `Object.entries(body)` and `Object.entries(provenance)`
 * as two columns of key–value pairs, so a reader checking a number met
 * `mapping_version: v2`, `primitive_version: v2`, `invoked_by: recipe`,
 * `char_span: [14210,15090]` and `quality_flags: {"data_quality":"high"}` in the
 * same list as the value, the period and the filing it came from.
 *
 * The valuable half was already there — `raw_concept: us-gaap:GrossProfit`, the
 * accession, the period, the source URL. It was buried in the other half. So:
 * one card per kind, saying what this piece of evidence IS, with the machinery
 * behind a disclosure that the audit layer opens by default.
 */

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[96px_1fr] gap-2 text-xs py-0.5">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-200 m-0 break-words">{children}</dd>
    </div>
  );
}

function Kind({ kind }: { kind: string }) {
  const style: Record<string, string> = {
    fact: "text-sky-300 bg-sky-950/50",
    calc: "text-violet-300 bg-violet-950/50",
    chunk: "text-amber-300 bg-amber-950/40",
    source: "text-emerald-300 bg-emerald-950/40",
    exposure_run: "text-teal-300 bg-teal-950/40",
    alert: "text-red-300 bg-red-950/40",
    position: "text-slate-300 bg-slate-800/50",
    fact_record: "text-teal-200 bg-teal-950/50",
  };
  const name: Record<string, string> = {
    fact: "Fact · reported", calc: "Calculation", chunk: "Passage · filing",
    source: "Source · web", exposure_run: "Exposure run", alert: "Warning",
    position: "Holding", fact_record: "Fact · shown to the analyst",
  };
  return (
    <span className={`inline-block font-mono text-[10px] uppercase tracking-wider px-2 py-0.5 rounded ${style[kind] ?? "text-slate-300 bg-slate-800/50"}`}>
      {name[kind] ?? kind}
    </span>
  );
}

/**
 * The machinery. Open when the audit layer is on, collapsed otherwise — never
 * absent, because "how was this produced" is a question a reader is entitled to
 * follow, just not one they should have to read past to see the number.
 */
function Technical({ rows }: { rows: [string, unknown][] }) {
  const shown = rows.filter(([, v]) => v != null && v !== "" &&
    !(typeof v === "object" && Object.keys(v as object).length === 0));
  if (shown.length === 0) return null;
  return (
    <details className="border-t border-[#21262d] pt-2 mt-1">
      <summary className="cursor-pointer text-[11px] text-slate-500 list-none select-none">
        Technical details
      </summary>
      <dl className="mt-2 font-mono text-[10.5px]">
        {shown.map(([k, v]) => (
          <div key={k} className="mb-1">
            <dt className="text-slate-600">{k}</dt>
            <dd className="m-0 text-slate-400 break-all">
              {typeof v === "object" ? JSON.stringify(v) : String(v)}
            </dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function fmtValue(v: unknown, unit?: unknown): string {
  if (typeof v !== "number") return v == null ? "—" : String(v);
  const a = Math.abs(v);
  if (unit === "USD" || a >= 1e6) {
    if (a >= 1e9) return `$${(v / 1e9).toFixed(3)}B`;
    if (a >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  }
  if (a < 1 && v !== 0) return `${(v * 100).toFixed(2)}%`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

/**
 * A series, drawn where a series was described (V25).
 *
 * The drawer knew a calculation had twelve points and said so: "12 points ·
 * 2023-06-30 → 2026-03-31". Which is the shape of the answer to "how has this
 * moved" without being the answer. The points were on the row the whole time —
 * this is the ledger's own `result.points`, or a fact record's `points`, drawn
 * and not recomputed.
 *
 * The list of numbers moves under Technical details rather than away: a reader
 * checking a figure against a filing wants the figure, and a chart is not one.
 */
function seriesPoints(body: Record<string, unknown>): { period: string; value: number }[] {
  const raw = body.points ?? (body.result as Record<string, unknown> | undefined)?.points;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((p) => {
    // A fact's points are [period, value]; a calc row's are objects ending on
    // `end`, `as_of` or `period_end`. Both spellings are the ledger's own.
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
}

function SeriesChart({ points, unit, label }: {
  points: { period: string; value: number }[];
  unit: string | null;
  label: string;
}) {
  if (points.length < 2) return null;
  const format = (v: number) => (unit ? displayValue(v, unit) : String(Number(v.toPrecision(6))));
  return (
    <div className="-mx-1">
      <LineChart
        x={points.map((p) => p.period)}
        height={150}
        padLeft={62}
        series={[{
          key: "series", label, colour: C.s1,
          points: points.map((p) => p.value),
          endLabel: format(points[points.length - 1].value),
        }]}
        xTicks={points.map((p, i) => ({ at: i, label: fmtMonth(p.period) }))
          .filter((_, i) => i % Math.max(1, Math.ceil(points.length / 4)) === 0)}
        yFormat={format}
        ariaLabel={`${label}, ${points.length} points from ${points[0].period} to ${points[points.length - 1].period}`}
        tipRows={(i) => [{ label: fmtDate(points[i].period), value: format(points[i].value), colour: C.s1 }]}
      />
    </div>
  );
}

export function EvidenceCard({ evidence, onOpen }: {
  evidence: Evidence & { label?: string };
  onOpen: (id: string) => void;
}) {
  const { type, body, provenance, upstream } = evidence;
  const b = body as Record<string, unknown>;
  const p = provenance as Record<string, unknown>;

  return (
    <div className="flex flex-col gap-3">
      <Kind kind={type} />
      <h3 className="text-[15px] font-semibold leading-snug text-slate-100">
        {evidence.label ?? type}
      </h3>

      {type === "fact_record" && (
        <>
          {/* V24. What a tool put in front of the model, with the identity it
              carried; the rows it rests on are one click down. */}
          {b.kind === "scalar" && typeof b.value === "number" && (
            <div className="font-mono text-2xl text-slate-100">
              {typeof b.unit === "string" ? displayValue(b.value, b.unit) : fmtValue(b.value)}
            </div>
          )}
          {b.kind === "series" && Array.isArray(b.points) && (
            <SeriesChart points={seriesPoints(b)}
              unit={typeof b.unit === "string" ? b.unit : null}
              label={String(b.measure ?? "series").replace(/[._]/g, " ")} />
          )}
          {b.kind === "series" && Array.isArray(b.points) && (
            <div className="font-mono text-[11px] text-slate-400">
              {(b.points as [string, number][]).length} points
              {(b.points as [string, number][]).length > 0 && (
                <> · {String((b.points as [string, number][])[0][0])} → {String((b.points as [string, number][]).slice(-1)[0][0])}</>
              )}
            </div>
          )}
          {(b.kind === "passage" || b.kind === "absence" || b.kind === "task") && typeof b.text === "string" && (
            <blockquote className="m-0 pl-3 border-l-2 border-[#30363d] text-[13px] leading-relaxed text-slate-300 whitespace-pre-wrap">
              {b.text}
            </blockquote>
          )}
          <dl className="m-0">
            <Field label="What">{String(b.measure ?? "—").replace(/[._]/g, " ")}</Field>
            {b.subject != null && <Field label="Whose">{String(b.subject)}</Field>}
            {b.as_of != null && <Field label="As of">{String(b.as_of)}</Field>}
            {b.window != null && typeof b.window === "object" && (
              <Field label="Window">
                {Object.entries(b.window as Record<string, unknown>).map(([k, v]) => `${k} ${String(v)}`).join(" · ")}
              </Field>
            )}
            {typeof b.unit === "string" && <Field label="Unit">{b.unit}</Field>}
            {b.standalone === false && <Field label="Note">not determined on its own — see the figure that is</Field>}
            {upstream.length > 0 && (
              <Field label="Rests on">
                <div className="flex flex-wrap gap-1.5 mt-0.5">
                  {upstream.map((u) => (
                    <button key={u.id} onClick={() => onOpen(u.id)}
                      className="text-[11px] px-2 py-0.5 rounded border border-[#30363d] text-slate-300 hover:border-slate-500">
                      {u.type} →
                    </button>
                  ))}
                </div>
              </Field>
            )}
          </dl>
        </>
      )}

      {type === "fact" && (
        <>
          <div className="font-mono text-2xl text-slate-100">{fmtValue(b.value, b.unit)}</div>
          <dl className="m-0">
            <Field label="Period">
              {b.period_start
                ? `${b.period_start} – ${b.period_end}`
                : `as of ${b.period_end}`}
            </Field>
            <Field label="Reported as">{String(b.raw_concept ?? "—")}</Field>
            <Field label="Filing">
              {typeof p.form_type === "string"
                ? `${p.form_type} · filed ${String(p.filing_date ?? "—")} · ${String(p.source_accession ?? "—")}`
                : String(p.source_accession ?? "—")}
            </Field>
            {typeof p.source_url === "string" && (
              <Field label="Source">
                <a href={p.source_url} target="_blank" rel="noreferrer"
                  className="text-sky-400 hover:underline">
                  {p.source_url_kind === "edgar_index" ? "Open the filing's EDGAR index ↗" : "Open at SEC ↗"}
                </a>
              </Field>
            )}
          </dl>
        </>
      )}

      {type === "calc" && (
        <>
          {typeof (b.result as Record<string, unknown> | undefined)?.value === "number" && (
            <div className="font-mono text-2xl text-slate-100">
              {fmtValue((b.result as Record<string, unknown>).value)}
            </div>
          )}
          {/* V25: a calculation whose result is points is a line, not a count.
              The unit is on the row (V15-S1), so the axis reads the way the
              rest of the desk reads. */}
          <SeriesChart points={seriesPoints(b)}
            unit={typeof b.unit_class === "string" ? b.unit_class
              : typeof ((b.params as Record<string, unknown> | undefined)?.result_type as
                  Record<string, unknown> | undefined)?.unit_class === "string"
                ? String(((b.params as Record<string, unknown>).result_type as
                    Record<string, unknown>).unit_class).toUpperCase()
                : null}
            label={evidence.label ?? String(b.operation ?? "series")} />
          <dl className="m-0">
            <Field label="Operation">{String(b.operation ?? "—")}</Field>
            {upstream.length > 0 && (
              <Field label="Built from">
                <div className="flex flex-wrap gap-1.5 mt-0.5">
                  {upstream.map((u) => (
                    <button key={u.id} onClick={() => onOpen(u.id)}
                      className="text-[11px] px-2 py-0.5 rounded border border-[#30363d] text-slate-300 hover:border-slate-500">
                      {u.type} →
                    </button>
                  ))}
                </div>
              </Field>
            )}
          </dl>
        </>
      )}

      {type === "chunk" && (
        <>
          <p className="text-xs leading-relaxed text-slate-300 whitespace-pre-wrap max-h-72 overflow-y-auto bg-[#0d1117] rounded p-2.5 border border-[#21262d]">
            {String(b.text ?? "").slice(0, 4000)}
          </p>
          <dl className="m-0">
            <Field label="Filing">
              {String(p.form_type ?? "")} · filed {String(p.filing_date ?? "—")}
            </Field>
            {typeof p.source_url === "string" && (
              <Field label="Source">
                <a href={p.source_url} target="_blank" rel="noreferrer"
                  className="text-sky-400 hover:underline">Open at SEC ↗</a>
              </Field>
            )}
          </dl>
        </>
      )}

      {type === "source" && (
        <>
          {typeof b.snippet === "string" && (
            <p className="text-xs leading-relaxed text-slate-400">{b.snippet.slice(0, 700)}</p>
          )}
          <dl className="m-0">
            <Field label="Publisher">{String(p.publisher ?? "—")}</Field>
            <Field label="Gathered">{String(p.retrieved_at ?? "—").slice(0, 10)}</Field>
            {typeof p.url === "string" && (
              <Field label="Article">
                <a href={p.url} target="_blank" rel="noreferrer"
                  className="text-sky-400 hover:underline break-all">Open ↗</a>
              </Field>
            )}
          </dl>
        </>
      )}

      {type === "exposure_run" && (
        <dl className="m-0">
          <Field label="Reporting on">{String(b.as_of_date ?? "—")}</Field>
          <Field label="Market value">{fmtValue(b.market_value, "USD")}</Field>
          <Field label="Day">{fmtValue(b.daily_return)}</Field>
          <Field label="VaR 95% 1d">{fmtValue(b.var_95_1d)}</Field>
          <Field label="Max drawdown">{fmtValue(b.max_drawdown)}</Field>
          {upstream.length > 0 && (
            <Field label="Holdings">
              <div className="flex flex-wrap gap-1.5 mt-0.5">
                {upstream.map((u) => (
                  <button key={u.id} onClick={() => onOpen(u.id)}
                    className="text-[11px] px-2 py-0.5 rounded border border-[#30363d] text-slate-300 hover:border-slate-500">
                    {u.label ?? u.type} →
                  </button>
                ))}
              </div>
            </Field>
          )}
        </dl>
      )}

      {type === "alert" && (
        <dl className="m-0">
          <Field label="Reads as">{String(b.message ?? "—")}</Field>
          <Field label="Utilisation">
            {typeof b.utilization === "number"
              ? `${(b.utilization * 100).toFixed(0)}% of the breach level`
              : "—"}
          </Field>
          {upstream.map((u) => (
            <Field key={u.id} label="From">
              <button onClick={() => onOpen(u.id)} className="text-sky-400 hover:underline">
                the run that raised it →
              </button>
            </Field>
          ))}
        </dl>
      )}

      {type === "position" && (
        <dl className="m-0">
          <Field label="Ticker">{String(b.ticker ?? "—")}</Field>
          <Field label="Quantity">{fmtValue(b.quantity)}</Field>
          <Field label="Sector">{String(b.sector ?? "—")}</Field>
          <Field label="As of">{String(b.as_of_date ?? "—")}</Field>
        </dl>
      )}

      <AuditOnly>
        <div className="font-mono text-[10.5px] text-slate-600 break-all">{evidence.id}</div>
      </AuditOnly>
      <Technical rows={[["id", evidence.id], ...Object.entries(p),
                        ...(type === "calc" || type === "fact_record" ? [["params", b.params] as [string, unknown]] : [])]} />
    </div>
  );
}
