"use client";

import {
  C, ChartCard, Legend, fmtDate, fmtMonth, type TableSpec,
} from "../charts/frame";
import { LineChart } from "../charts/line";
import { CitationMap, CoverageTable, WindowLadder } from "../charts/grids";
import type {
  CitationMap as CitationMapData, Containment, CoverageRow, PriceIndex, ReportedWindows,
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

export function PriceVsBenchmark({ index, span, onSpan, benchmark, onBenchmark, benchmarks, briefDate }: {
  index: PriceIndex;
  /** The window, from the endpoint's own list (`index.spans`). */
  span: string;
  onSpan: (span: string) => void;
  /** What to index against. Any ticker this desk prices is accepted; the page
   *  offers the market and macro factors, and the book's other holdings when
   *  the reader came from a book (V25). */
  benchmark: string;
  onBenchmark: (ticker: string) => void;
  benchmarks: { ticker: string; label: string }[];
  /** The day the desk last wrote about this name, marked as a second rule: a
   *  reader can then see what the price did after the brief they are about to
   *  read was written. */
  briefDate?: string | null;
}) {
  const pts = index.points;
  const spans = index.spans ?? [span];
  const controls = (
    <div className="flex items-center gap-2">
      <div className="flex rounded border border-[#30363d] overflow-hidden text-[11px]">
        {spans.map((s) => (
          <button key={s} onClick={() => onSpan(s)} aria-pressed={s === span}
            className={`px-2 py-0.5 ${s === span ? "bg-[#1d2530] text-slate-200" : "text-slate-500 hover:text-slate-300"}`}>
            {s}
          </button>
        ))}
      </div>
      <label className="flex items-center gap-1.5 text-[11px] text-slate-500">
        against
        <select value={benchmark} onChange={(e) => onBenchmark(e.target.value)}
          aria-label="Benchmark"
          className="bg-[#0d1117] border border-[#30363d] rounded px-1.5 py-0.5 text-slate-300">
          {benchmarks.map((b) => (
            <option key={b.ticker} value={b.ticker}>{b.label}</option>
          ))}
        </select>
      </label>
    </div>
  );

  if (pts.length < 2) {
    return (
      <ChartCard title={`${index.ticker} against ${index.benchmark}`} controls={controls}>
        <p className="text-xs text-slate-500 py-6">{index.detail ?? "No price history held for this issuer."}</p>
      </ChartCard>
    );
  }
  const at = new Map(pts.map((p, i) => [p.date, i]));
  const onOrAfter = (date: string) => {
    const exact = at.get(date);
    if (exact != null) return exact;
    const i = pts.findIndex((p) => p.date >= date);
    return i >= 0 ? i : null;
  };
  // A filing is marked at the first session on or after it was filed: the market
  // could not have read it earlier, and snapping to an exact date that fell on a
  // weekend would silently drop the mark.
  const markers = index.filings
    .map((f) => {
      const i = onOrAfter(f.date);
      return i == null ? null : { at: i, label: f.form };
    })
    .filter((m): m is { at: number; label: string } => m != null);
  const briefAt = briefDate ? onOrAfter(briefDate.slice(0, 10)) : null;

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
      controls={controls}
      table={table}
      note={<>{index.basis ?? "adjusted close, indexed to 100 at the first session shown"}
        {markers.length > 0 && ". Rules mark the days this desk's filings were filed"}
        {briefAt != null && ", and the day its brief was written"}.</>}>
      <LineChart
        x={pts.map((p) => p.date)}
        height={220}
        series={[
          { key: "t", label: index.ticker, points: pts.map((p) => p.value), colour: C.s1,
            endLabel: pts[pts.length - 1].value.toFixed(0) },
          { key: "b", label: index.benchmark, points: pts.map((p) => p.benchmark), colour: C.grey, width: 1.5 },
        ]}
        markers={[
          ...markers,
          ...(briefAt == null ? [] : [{ at: briefAt, label: "brief" }]),
        ]}
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
        ...(markers.length > 0 ? [{ label: "Filing arrived", shape: "tick" as const, colour: "#6c7887" }] : []),
        ...(briefAt != null ? [{ label: "Brief written", shape: "tick" as const, colour: "#6c7887" }] : []),
      ]} />
    </ChartCard>
  );
}

// ── the windows a measure can be produced over ───────────────────────────────

export function Windows({ data, metrics, metric, onMetric, onOpen, today }: {
  data: ReportedWindows;
  metrics: { metric: string; label: string }[];
  metric: string;
  onMetric: (m: string) => void;
  onOpen?: (factId: string) => void;
  /** The last session this desk has priced (V25). The ladder has taken this
   *  prop since V13 and nothing passed it, so the gap between the newest filed
   *  window and now — the thing a reader is judging the figures' age by — was
   *  the one interval the panel could not show. */
  today?: string | null;
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
          r.label, fmtDate(s.start), fmtDate(s.period_end),
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
        <WindowLadder rows={data.rows} format={money} onOpen={onOpen} today={today ?? undefined}
          ariaLabel={`Windows of ${data.label} this desk can produce, by window length`} />
      )}
      <Legend items={[
        { label: "As filed", colour: C.s1, shape: "swatch" },
        { label: "Derived — a signed path over filed boundaries", colour: C.s1, shape: "outline" },
        { label: "No held filing reaches it", shape: "dashed" },
        ...(today ? [{ label: "Today", shape: "tick" as const, colour: "#6c7887" }] : []),
      ]} />
    </ChartCard>
  );
}

// ── what this desk holds ─────────────────────────────────────────────────────

export function Coverage({ rows, selected, onSelect }: {
  rows: CoverageRow[];
  /** V25: the measure the ladder above is showing. A row here is the way into
   *  it — the table and the ladder are one list and one picker, not two lists
   *  that happen to be about the same issuer. */
  selected?: string;
  onSelect?: (metric: string) => void;
}) {
  const flows = rows.filter((r) => r.kind === "flow").length;
  const stopped = rows.filter((r) => r.superseded_by?.length).length;
  return (
    <ChartCard
      title="Reported and derived measures"
      aside={`${rows.length} measures · ${flows} flows`}
      note={<>
        {stopped > 0
          ? "A measure with a named successor is not absent by accident — the issuer stopped reporting it as a separate line."
          : "Periods and the date each measure runs to, so a question can be asked of what is actually here."}
        {onSelect && " Choose a flow to put it in the ladder above."}
      </>}>
      <CoverageTable rows={rows} selected={selected} onSelect={onSelect} />
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
