"use client";

import {
  C, ChartCard, Legend, fmtDate, fmtMonth, type TableSpec,
} from "../charts/frame";
import { LineChart } from "../charts/line";
import { CitationMap, CoverageTable, WindowLadder } from "../charts/grids";
import type {
  CitationMap as CitationMapData, Containment, CoverageRow, PanelSeries,
  PanelSeriesResponse, PriceIndex, ReportedWindows,
} from "@/lib/charts";

/**
 * The issuer's panels (V13-S6c).
 *
 * These are the views that make the difference between this desk and a chat
 * window over a filings archive visible: which windows of a measure exist and
 * which had to be derived, what this desk holds and how far back, and which
 * passages a brief actually leaned on out of the ones it could see.
 *
 * None of it is new analysis. All four read what the engine already produces,
 * and each one is a thing the Snapshot tab used to express as a row of chips.
 */

// ── price, indexed ───────────────────────────────────────────────────────────

export function PriceVsBenchmark({ index }: { index: PriceIndex }) {
  const pts = index.points;
  if (pts.length < 2) {
    return (
      <ChartCard title={`${index.ticker} against ${index.benchmark}`}>
        <p className="text-xs text-slate-500 py-6">{index.detail ?? "No price history held for this issuer."}</p>
      </ChartCard>
    );
  }
  const at = new Map(pts.map((p, i) => [p.date, i]));
  // A filing is marked at the first session on or after it was filed: the market
  // could not have read it earlier, and snapping to an exact date that fell on a
  // weekend would silently drop the mark.
  const markers = index.filings
    .map((f) => {
      const i = at.get(f.date) ?? pts.findIndex((p) => p.date >= f.date);
      return i >= 0 ? { at: i, label: f.form } : null;
    })
    .filter((m): m is { at: number; label: string } => m != null);

  const step = Math.max(1, Math.floor(pts.length / 6));
  const table: TableSpec = {
    columns: ["Date", index.ticker, index.benchmark],
    rows: pts.filter((_, i) => i % Math.max(1, Math.floor(pts.length / 60)) === 0)
      .map((p) => [fmtDate(p.date), p.value.toFixed(1), p.benchmark?.toFixed(1) ?? "—"]),
  };

  return (
    <ChartCard
      title={`${index.ticker} against ${index.benchmark}`}
      aside={index.span}
      table={table}
      note={<>{index.basis ?? "adjusted close, indexed to 100 at the first session shown"}
        {markers.length > 0 && ". Rules mark the days this desk's filings were filed"}.</>}>
      <LineChart
        x={pts.map((p) => p.date)}
        height={220}
        series={[
          { key: "t", label: index.ticker, points: pts.map((p) => p.value), colour: C.s1,
            endLabel: pts[pts.length - 1].value.toFixed(0) },
          { key: "b", label: index.benchmark, points: pts.map((p) => p.benchmark), colour: C.grey, width: 1.5 },
        ]}
        markers={markers}
        xTicks={pts.map((p, i) => ({ at: i, label: fmtMonth(p.date) }))
          .filter((_, i) => i % step === 0 && i < pts.length - step / 2)}
        yFormat={(v) => v.toFixed(0)}
        ariaLabel={`${index.ticker} indexed against ${index.benchmark}`}
        tipRows={(i) => [
          { label: index.ticker, value: pts[i].value.toFixed(1), colour: C.s1 },
          { label: index.benchmark, value: pts[i].benchmark?.toFixed(1) ?? "—", colour: C.grey },
        ]}
      />
      <Legend items={[
        { label: index.ticker, colour: C.s1, shape: "line" },
        { label: index.benchmark, colour: C.grey, shape: "line" },
      ]} />
    </ChartCard>
  );
}

// ── the windows a measure can be produced over ───────────────────────────────

export function Windows({ data, metrics, metric, onMetric, onOpen }: {
  data: ReportedWindows;
  metrics: { metric: string; label: string }[];
  metric: string;
  onMetric: (m: string) => void;
  onOpen?: (factId: string) => void;
}) {
  const money = (v: number) =>
    Math.abs(v) >= 1e9 ? `$${(v / 1e9).toFixed(2)}B`
    : Math.abs(v) >= 1e6 ? `$${(v / 1e6).toFixed(0)}M`
    : `$${v.toLocaleString()}`;

  return (
    <ChartCard
      title="Reported windows"
      aside={data.fiscal?.fiscal_year_ends ? `fiscal year ends ${String(data.fiscal.fiscal_year_ends)}` : undefined}
      controls={
        <select value={metric} onChange={(e) => onMetric(e.target.value)}
          aria-label="Measure"
          className="text-[11px] bg-[#0d1117] border border-[#30363d] rounded px-1.5 py-0.5 text-slate-300">
          {metrics.map((m) => <option key={m.metric} value={m.metric}>{m.label}</option>)}
        </select>
      }
      table={{
        columns: ["Window", "From", "To", "Value", "How"],
        rows: data.rows.flatMap((r) => r.slots.map((s) => [
          r.label, fmtDate(s.start), fmtDate(s.end),
          s.value == null ? "—" : money(s.value),
          s.value == null ? (s.unreachable ?? "no held filing reaches it")
            : (s.terms?.length ?? 1) > 1 ? `derived · ${s.derivation ?? ""}` : "as filed",
        ])),
      }}
      note={data.note}>
      {data.rows.length === 0 || data.rows.every((r) => r.slots.length === 0) ? (
        <p className="text-xs text-slate-500 py-6">
          {data.detail ?? `Nothing filed for ${data.label} that this desk holds.`}
        </p>
      ) : (
        <WindowLadder rows={data.rows} format={money} onOpen={onOpen}
          ariaLabel={`Windows of ${data.label} this desk can produce, by window length`} />
      )}
      <Legend items={[
        { label: "As filed", colour: C.s1, shape: "swatch" },
        { label: "Derived — a signed path over filed boundaries", colour: C.s1, shape: "outline" },
        { label: "No held filing reaches it", shape: "dashed" },
      ]} />
    </ChartCard>
  );
}

// ── what this desk holds ─────────────────────────────────────────────────────

export function Coverage({ rows }: { rows: CoverageRow[] }) {
  const flows = rows.filter((r) => r.kind === "flow").length;
  const stopped = rows.filter((r) => r.superseded_by?.length).length;
  return (
    <ChartCard
      title="Reported and derived measures"
      aside={`${rows.length} measures · ${flows} flows`}
      note={stopped > 0
        ? "A measure with a named successor is not absent by accident — the issuer stopped reporting it as a separate line."
        : "Periods and the date each measure runs to, so a question can be asked of what is actually here."}>
      <CoverageTable rows={rows} />
    </ChartCard>
  );
}

// ── where a brief's evidence came from ───────────────────────────────────────

export function BriefProvenance({ map }: { map: CitationMapData }) {
  const total = Object.values(map.citation_mix).reduce((a, b) => a + b, 0);
  const kind: Record<string, string> = {
    fact: "filed figures", calc: "calculations", chunk: "filing passages",
    src: "web sources", alert: "alerts", run: "runs", pos: "positions",
  };
  return (
    <ChartCard
      title="Where the brief's evidence came from"
      aside={total > 0 ? `${total} citations` : undefined}
      table={{
        columns: ["Form", "Filed", "Section", "Passages held", "Cited"],
        rows: map.sections.map((s) => [s.form, fmtDate(s.filed),
          `${s.item ?? ""} ${s.title ?? ""}`.trim(), s.passages, s.cited]),
      }}
      note="The full bar is what this desk had searchable; the filled part is what the brief leaned on. A section with many passages and none cited is not a gap — it is a section the brief did not need.">
      <CitationMap sections={map.sections} ariaLabel="Filing sections held against the ones the brief cited" />
      {total > 0 && (
        <p className="mt-3 pt-2 border-t border-[#21262d] text-[11px] text-slate-500">
          {Object.entries(map.citation_mix)
            .map(([k, v]) => `${v} ${kind[k] ?? k}`)
            .join(" · ")}
        </p>
      )}
    </ChartCard>
  );
}

// ── margins over the reported windows ────────────────────────────────────────

/**
 * The three margins as the recipe computed them — one calc row per series, so
 * the line and an answer citing net margin point at the same calculation.
 *
 * A LINE, not the dot plot first sketched for this: the recipe's series are one
 * window length marching through time, which is change-over-time, and the form
 * follows the data that exists rather than the panel that was imagined.
 */
export function Margins({ data, onOpen }: {
  data: PanelSeriesResponse;
  onOpen?: (id: string) => void;
}) {
  const margins = data.series.filter((s) => s.metric.endsWith("_margin"));
  if (margins.length === 0) return null;
  const x = margins[0].points.map((p) => p.end);
  const at = (s: PanelSeries) => {
    const by = new Map(s.points.map((p) => [p.end, p.value]));
    return x.map((d) => by.get(d) ?? null);
  };
  const colours = [C.s1, C.s2, C.s3];

  return (
    <ChartCard
      title="Margins"
      aside={data.as_of ? `computed ${fmtDate(data.as_of)}` : undefined}
      table={{
        columns: ["Quarter end", ...margins.map((s) => s.label)],
        rows: x.map((d, i) => [fmtDate(d), ...margins.map((s) => {
          const v = at(s)[i];
          return v == null ? "—" : `${(v * 100).toFixed(2)}%`;
        })]),
      }}
      note={<>Each line is one ledgered calculation over the issuer&apos;s filed quarters
        {onOpen && margins.map((s, i) => (
          <span key={s.metric}>{i === 0 ? " — " : " · "}
            <button onClick={() => onOpen(s.calc_id)}
              className="text-teal-400 hover:text-teal-300 hover:underline">{s.label.toLowerCase()}</button>
          </span>
        ))}.
      </>}>
      <LineChart
        x={x}
        height={200}
        series={margins.map((s, i) => ({
          key: s.metric, label: s.label, points: at(s), colour: colours[i % colours.length],
          endLabel: `${((s.points[s.points.length - 1]?.value ?? 0) * 100).toFixed(1)}%`,
        }))}
        xTicks={x.map((d, i) => ({ at: i, label: fmtMonth(d) }))
          .filter((_, i) => i % Math.max(1, Math.floor(x.length / 5)) === 0)}
        yFormat={(v) => `${(v * 100).toFixed(0)}%`}
        ariaLabel="Gross, operating and net margin over the issuer's filed quarters"
        tipRows={(i) => margins.map((s, k) => ({
          label: s.label, colour: colours[k % colours.length],
          value: at(s)[i] == null ? "—" : `${((at(s)[i] as number) * 100).toFixed(2)}%`,
        }))}
      />
      <Legend items={margins.map((s, i) => ({
        label: s.label, colour: colours[i % colours.length], shape: "line" as const,
      }))} />
    </ChartCard>
  );
}

// ── how a composed figure is assembled ───────────────────────────────────────

/**
 * The containment engine's own account of a composed figure (V13, planned in
 * S3 and built after the cover fix landed): which lines were summed, which
 * were SET ASIDE because part of them was already inside a taken line, and
 * which are absent — at this date, or entirely.
 *
 * The set-aside row is the whole point. Two parents sharing one child is how a
 * total debt came out a billion high through every check this desk has; the
 * fix records the candidates it refuses, and this card is where a reader sees
 * the refusal instead of taking the narrower total on faith. There is no
 * total at the bottom on purpose — a value summed here would carry no calc_id,
 * and the assembled figure belongs to the calculation that mints one.
 */
export function HowAssembled({ data, onOpen }: {
  data: Containment;
  onOpen?: (id: string) => void;
}) {
  const money = (v: number | null) =>
    v == null ? "—" : Math.abs(v) >= 1e9 ? `$${(v / 1e9).toFixed(2)}B` : `$${(v / 1e6).toFixed(0)}M`;

  const row = (t: { label: string; value?: number | null; fact_id?: string | null }, tail?: React.ReactNode) => (
    <li key={t.label} className="flex items-baseline gap-2 py-1">
      {t.fact_id && onOpen ? (
        <button onClick={() => onOpen(t.fact_id as string)}
          className="text-slate-300 hover:text-slate-100 hover:underline decoration-dotted underline-offset-2 text-left">
          {t.label}
        </button>
      ) : (
        <span className="text-slate-400">{t.label}</span>
      )}
      {t.value !== undefined && (
        <span className="ml-auto font-mono text-[11px] tabular-nums text-slate-300">{money(t.value)}</span>
      )}
      {tail}
    </li>
  );

  return (
    <ChartCard
      title={`How ${data.formula.replace(/_/g, " ")} is assembled`}
      aside={data.as_of ? `as of ${fmtDate(data.as_of)}` : undefined}
      note={data.note ?? data.detail}>
      {data.definition == null ? (
        <p className="text-xs text-slate-500 py-4">{data.detail ?? "Nothing to assemble at any held date."}</p>
      ) : (
        <div className="text-[12px] flex flex-col gap-3">
          <p className="font-mono text-[11.5px] text-slate-200">{data.definition.replace(/_/g, " ")}</p>
          <div>
            <h4 className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Summed</h4>
            <ul>{data.taken.map((t) => row(t))}</ul>
          </div>
          {data.overlapping_not_added.length > 0 && (
            <div>
              <h4 className="text-[10px] uppercase tracking-wider text-amber-500/90 mb-1">
                Reported, and set aside — part of it is already summed
              </h4>
              <ul>
                {data.overlapping_not_added.map((o) => (
                  <li key={o.metric} className="py-1">
                    <div className="flex items-baseline gap-2">
                      {o.fact_id && onOpen ? (
                        <button onClick={() => onOpen(o.fact_id as string)}
                          className="text-slate-300 hover:text-slate-100 hover:underline decoration-dotted underline-offset-2 text-left">
                          {o.label}
                        </button>
                      ) : <span className="text-slate-400">{o.label}</span>}
                      <span className="ml-auto font-mono text-[11px] tabular-nums text-slate-300">{money(o.value)}</span>
                    </div>
                    {o.because.map((b) => (
                      <p key={b.part} className="text-[11px] text-slate-500 mt-0.5">
                        its {b.part_label.toLowerCase()} is already inside {b.already_in_label.toLowerCase()},
                        so adding this line would count that part twice.
                      </p>
                    ))}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {(data.missing_at_this_date.length > 0 || data.no_facts_for_issuer.length > 0) && (
            <div>
              <h4 className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Absent</h4>
              <ul className="text-[11.5px] text-slate-500">
                {data.missing_at_this_date.map((m) => (
                  <li key={m.metric} className="py-0.5">
                    {m.label} — not reported at this date
                    {m.last_reported && <>; last seen {fmtDate(m.last_reported)}</>}
                  </li>
                ))}
                {data.no_facts_for_issuer.map((m) => (
                  <li key={m.metric} className="py-0.5">{m.label} — never filed by this issuer</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </ChartCard>
  );
}
