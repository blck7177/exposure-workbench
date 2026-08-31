"use client";

import {
  C, ChartCard, Legend, fmtDate, fmtMonth, type TableSpec,
} from "../charts/frame";
import { LineChart } from "../charts/line";
import { CitationMap, CoverageTable, WindowLadder } from "../charts/grids";
import type { CitationMap as CitationMapData, CoverageRow, PriceIndex, ReportedWindows } from "@/lib/charts";

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
