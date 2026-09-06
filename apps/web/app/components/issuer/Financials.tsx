"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { C, ChartCard, fmtDate, fmtMonth, Legend } from "../charts/frame";
import { LineChart } from "../charts/line";
import { display as displayValue } from "@/lib/display";
import {
  getBalanceSeries, getPanelSeries, getWindows,
  type BalanceMeasure, type FlowMeasure, type Measures, type MeasureView, type RatioMeasure,
} from "@/lib/charts";
import { levelPoints, linkedRatio, viewsOffered, windowChoices } from "@/lib/measures";

/**
 * The issuer's financials: a measure chosen from a list, drawn as a line (V25).
 *
 * WHAT THIS REPLACES. The Overview drew three numbers — gross, operating and
 * net margin — out of the thirty-seven measures this desk holds for Microsoft
 * and the sixteen its recipe computed. Everything else was a table row with a
 * period count beside it, or a ladder of window rectangles for whichever metric
 * a dropdown was left on. The reader's question is "show me revenue", and it
 * took two tabs and a dropdown to half-answer.
 *
 * ONE CHART, and it is a LINE. Every measure here is the same shape of thing —
 * one number per period, in period order — and a line is what change over time
 * looks like. Bars would say each window is an independent quantity to compare
 * side by side, which is true of a ladder of derivations and not of a series a
 * reader is asking about the trend of.
 *
 * WHAT THE VIEWS ARE, AND WHO DECIDES. The server does (`/measures`): each row
 * arrives carrying the views it supports, derived from the measure's kind, from
 * whether the recipe computed a year-on-year series for it, and from the
 * recipe's own margin table. A client deciding for itself whether revenue has a
 * y/y series would be guessing about the recipe's contents; here a control that
 * is rendered is a control that leads somewhere.
 *
 *   Level             the figure itself. A flow: its 3- or 12-month windows,
 *                     from the interval engine, with derived windows marked and
 *                     unreachable ones left as gaps. A ratio: the recipe's
 *                     ledgered series. A balance: the reading at each instant.
 *   Year on year      the recipe's `<metric>_yoy` row.
 *   Share of revenue  the margin this flow is the numerator of.
 *   Windows           the ladder, in the Financials tab — the one view that is
 *                     about how a figure was DERIVED rather than what it is.
 *
 * NOTHING IS COMPUTED HERE. Every point is a filed figure, a signed path over
 * filed figures, or a ledgered calculation, and every one of them opens the row
 * it rests on.
 */

type Selected =
  | { group: "flow"; row: FlowMeasure }
  | { group: "ratio"; row: RatioMeasure }
  | { group: "balance"; row: BalanceMeasure };

type Point = { period: string; value: number | null; ids: string[]; derived?: boolean };

const KINDS = ["All", "Flows", "Ratios", "Balances"] as const;
type Kind = (typeof KINDS)[number];

const VIEW_LABEL: Record<MeasureView, string> = {
  level: "Level",
  yoy: "Year on year",
  share: "Share of revenue",
  windows: "Windows",
};

export function Financials({ ticker, measures, onOpen, onWindows }: {
  ticker: string;
  measures: Measures;
  onOpen: (id: string) => void;
  /** The Windows view is the ladder, which lives in the Financials tab: this
   *  hands it the metric and lets the page take the reader there. */
  onWindows: (metric: string) => void;
}) {
  const [kind, setKind] = useState<Kind>("All");
  const [chosen, setChosen] = useState<string>(
    () => measures.flows.find((f) => f.metric === "revenue")?.metric
      ?? measures.flows[0]?.metric ?? measures.ratios[0]?.metric ?? measures.balances[0]?.metric ?? "");
  const [view, setView] = useState<MeasureView>("level");
  const [months, setMonths] = useState<3 | 12>(3);

  const selected: Selected | null = useMemo(() => {
    const flow = measures.flows.find((f) => f.metric === chosen);
    if (flow) return { group: "flow", row: flow };
    const ratio = measures.ratios.find((r) => r.metric === chosen);
    if (ratio) return { group: "ratio", row: ratio };
    const balance = measures.balances.find((b) => b.metric === chosen);
    return balance ? { group: "balance", row: balance } : null;
  }, [chosen, measures]);

  // A view that the newly chosen measure does not support is not carried over:
  // the reader asked for a different measure, not for a control state.
  useEffect(() => {
    if (selected && !selected.row.views.includes(view)) setView("level");
  }, [selected, view]);

  // Which window lengths this flow can actually be drawn over — an issuer may
  // file quarters and still have no derivable latest one.
  // The ratio row this view is actually drawing, when the reader came in through
  // the flow's door (D2). Null everywhere else.
  const linked = linkedRatio(selected, view, measures.ratios);
  const lengths = selected?.group === "flow" ? windowChoices(selected.row) : [];
  const offered = lengths.join(",");
  useEffect(() => {
    const choices = offered ? offered.split(",").map(Number) : [];
    if (choices.length && !choices.includes(months)) setMonths(choices[0] as 3 | 12);
  }, [offered, months]);

  return (
    <ChartCard
      title="Financials"
      aside={measures.as_of
        ? `${measures.flows.length + measures.ratios.length + measures.balances.length} measures · ratios computed ${fmtDate(measures.as_of)}`
        : `${measures.flows.length + measures.ratios.length + measures.balances.length} measures`}
      controls={
        <div className="flex items-center gap-2 flex-wrap justify-end">
          {selected && selected.row.views.length > 1 && (
            <div className="flex rounded border border-[#30363d] overflow-hidden text-[11px]">
              {viewsOffered(selected.row).map((v) => (
                  <button key={v} aria-pressed={v === view}
                    onClick={() => (v === "windows" ? onWindows(selected.row.metric) : setView(v))}
                    className={`px-2 py-0.5 ${v === view ? "bg-[#1d2530] text-slate-200" : "text-slate-500 hover:text-slate-300"}`}>
                    {VIEW_LABEL[v]}
                  </button>
              ))}
            </div>
          )}
          {selected?.group === "flow" && view === "level" && lengths.length > 1 && (
            <div className="flex rounded border border-[#30363d] overflow-hidden text-[11px]">
              {lengths.map((m) => (
                <button key={m} onClick={() => setMonths(m)} aria-pressed={m === months}
                  className={`px-2 py-0.5 ${m === months ? "bg-[#1d2530] text-slate-200" : "text-slate-500 hover:text-slate-300"}`}>
                  {m === 3 ? "3 months" : "12 months"}
                </button>
              ))}
            </div>
          )}
        </div>
      }
      note={<>A flow is measured over an interval and a balance is read at an instant; the list
        keeps them apart, and a measure offers only the views it can support. Every point is a
        filed figure, a signed path over filed figures, or one ledgered calculation — and opens
        the row it rests on.</>}>
      <div className="grid grid-cols-1 md:grid-cols-[248px_minmax(0,1fr)] gap-4">
        <MeasureList
          measures={measures} kind={kind} onKind={setKind} echo={linked?.metric ?? null}
          chosen={chosen} onChoose={(m) => { setChosen(m); setView("level"); }} />
        {selected
          ? <Chart key={`${ticker}-${chosen}-${view}-${months}`}
              ticker={ticker} selected={selected} view={view} months={months}
              linked={linked} onOpen={onOpen} />
          : <p className="text-xs text-slate-500 py-8">Choose a measure on the left.</p>}
      </div>
    </ChartCard>
  );
}

// ── the list ─────────────────────────────────────────────────────────────────

function MeasureList({ measures, kind, onKind, chosen, onChoose, echo }: {
  measures: Measures;
  kind: Kind;
  onKind: (k: Kind) => void;
  chosen: string;
  onChoose: (metric: string) => void;
  /** The ratio row the chart is drawing from the other door (D2). Lit, so the
   *  reader can see that the view they are on and this row are one thing. */
  echo?: string | null;
}) {
  const showFlows = kind === "All" || kind === "Flows";
  const showRatios = kind === "All" || kind === "Ratios";
  const showBalances = kind === "All" || kind === "Balances";
  return (
    <div className="min-w-0">
      <div className="flex rounded border border-[#30363d] overflow-hidden text-[11px] mb-2">
        {KINDS.map((k) => (
          <button key={k} onClick={() => onKind(k)} aria-pressed={k === kind}
            className={`flex-1 px-2 py-0.5 ${k === kind ? "bg-[#1d2530] text-slate-200" : "text-slate-500 hover:text-slate-300"}`}>
            {k}
          </button>
        ))}
      </div>
      <div className="max-h-[380px] overflow-y-auto -mx-1 px-1">
        {showFlows && measures.flows.length > 0 && (
          <Group title="Flows · over a window" right="latest">
            {measures.flows.map((f) => (
              <Row key={f.metric} metric={f.metric} label={f.label} chosen={chosen === f.metric}
                onChoose={onChoose}
                value={f.latest ? displayValue(f.latest.value, f.unit_class) : null}
                caption={f.source === "recipe"
                  ? `the recipe · ${f.points ?? 0} windows`
                  : `${f.periods ?? "—"} periods · ${(f.windows_filed ?? []).join(" and ") || "one length"} · to ${fmtDate(f.through)}`}
                warn={f.latest ? null : f.latest_unreachable ?? null} />
            ))}
          </Group>
        )}
        {showRatios && measures.ratios.length > 0 && (
          <Group title="Ratios · the recipe" right="latest">
            {measures.ratios.map((r) => (
              <Row key={r.metric} metric={r.metric} label={r.label} chosen={chosen === r.metric}
                onChoose={onChoose} echoed={r.metric === echo}
                value={r.latest ? displayValue(r.latest.value, r.unit_class) : null}
                caption={r.metric === echo
                  ? "the row the chart is drawing — you are looking at it from Flows"
                  : `${r.points} periods · to ${fmtDate(r.latest?.end)}`} />
            ))}
          </Group>
        )}
        {showBalances && measures.balances.length > 0 && (
          <Group title="Balances · at an instant" right="latest">
            {measures.balances.map((b) => (
              <Row key={b.metric} metric={b.metric} label={b.label} chosen={chosen === b.metric}
                onChoose={onChoose}
                value={b.latest ? displayValue(b.latest.value, b.unit_class) : null}
                caption={`${b.readings ?? "—"} readings · to ${fmtDate(b.through)}`}
                warn={b.superseded_by?.length
                  ? `no longer reported — see ${b.superseded_by.join(", ")}`
                  : null} />
            ))}
          </Group>
        )}
        {measures.unavailable.length > 0 && (
          <Group title="Held, and not drawable" right="">
            {measures.unavailable.map((u) => (
              <div key={u.metric} className="px-2 py-1">
                <div className="text-[11.5px] text-slate-500">{u.label ?? u.metric}</div>
                <div className="text-[10px] text-slate-600 leading-snug">{u.detail}</div>
              </div>
            ))}
          </Group>
        )}
      </div>
    </div>
  );
}

function Group({ title, right, children }: {
  title: string; right: string; children: React.ReactNode;
}) {
  return (
    <div className="mb-1">
      <div className="flex justify-between font-mono text-[9.5px] uppercase tracking-[0.08em]
                      text-slate-600 px-2 pt-2 pb-1">
        <span>{title}</span><span>{right}</span>
      </div>
      {children}
    </div>
  );
}

function Row({ metric, label, chosen, onChoose, value, caption, warn, echoed }: {
  metric: string; label: string; chosen: boolean;
  onChoose: (metric: string) => void;
  value: string | null; caption: string; warn?: string | null;
  /** This row IS what the chart is drawing, reached through another row's view. */
  echoed?: boolean;
}) {
  // Forty-three measures in a scrolling column, and the one being drawn is
  // alphabetically wherever it falls: on MSFT the chart says Revenue while the
  // list opens on Amortisation of intangibles, with the selected row well below
  // the fold. The chosen row brings itself into view, once, on mount.
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (chosen || echoed) ref.current?.scrollIntoView({ block: "nearest" });
    // Only when WHICH row is chosen changes — not on every render, which would
    // fight a reader scrolling the list by hand.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chosen, echoed]);
  return (
    <button ref={ref} onClick={() => onChoose(metric)} aria-pressed={chosen}
      className={`w-full text-left px-2 py-1 rounded border-l-2 ${
        chosen ? "border-blue-500 bg-[#161b22]"
        : echoed ? "border-transparent bg-[#161b22] ring-1 ring-inset ring-teal-500/50"
        : "border-transparent hover:bg-[#161b22]"}`}>
      <span className="flex items-baseline gap-2">
        <span className={`text-[12px] truncate ${
          chosen || echoed ? "text-slate-100 font-medium" : "text-slate-300"}`}>
          {label}
        </span>
        <span className="ml-auto font-mono text-[11px] tabular-nums text-slate-200 shrink-0">
          {value ?? "—"}
        </span>
      </span>
      <span className={`block text-[10px] truncate ${
        warn ? "text-amber-500/80" : echoed ? "text-teal-400/90" : "text-slate-600"}`}>
        {warn ?? caption}
      </span>
    </button>
  );
}

// ── the chart ────────────────────────────────────────────────────────────────

function Chart({ ticker, selected, view, months, linked, onOpen }: {
  ticker: string;
  selected: Selected;
  view: MeasureView;
  months: 3 | 12;
  /** The ratio row this chart is actually drawing, when the reader arrived
   *  through a flow's `Share of revenue` (D2). It supplies the heading: the
   *  view is titled with the margin's own name and says which row it is, so
   *  the two doors point at each other instead of at nothing. */
  linked: RatioMeasure | null;
  onOpen: (id: string) => void;
}) {
  const [points, setPoints] = useState<Point[] | null>(null);
  const [unit, setUnit] = useState<string>(selected.row.unit_class);
  const [calcId, setCalcId] = useState<string | null>(null);
  const [caption, setCaption] = useState<string>("");
  const [refused, setRefused] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    setPoints(null); setRefused(null); setCalcId(null);

    const asSeries = (metric: string, label: string) =>
      getPanelSeries(ticker, [metric]).then((got) => {
        if (ignore) return;
        const series = got.series[0];
        if (!series) { setRefused(`${label} is not a series this issuer's recipe produced.`); return; }
        setPoints(series.points.map((p) => ({
          period: p.end, value: p.value, ids: p.fact_ids ?? [],
        })));
        setUnit("RATIO");
        setCalcId(series.calc_id);
        setCaption(`${series.points.length} periods · one ledgered calculation`);
      }).catch(() => { if (!ignore) setRefused("That series could not be read just now."); });

    if (view === "yoy" && selected.group === "flow" && selected.row.yoy_metric) {
      void asSeries(selected.row.yoy_metric, "Year on year");
    } else if (view === "share" && selected.group === "flow" && selected.row.share_metric) {
      void asSeries(selected.row.share_metric, "Share of revenue");
    } else if (selected.group === "ratio") {
      void asSeries(selected.row.metric, selected.row.label);
    } else if (selected.group === "balance") {
      getBalanceSeries(ticker, selected.row.metric).then((got) => {
        if (ignore) return;
        setPoints(got.points.map((p) => ({
          period: p.period_end, value: p.value, ids: p.fact_ids ?? [],
        })));
        setUnit(got.unit_class);
        setCalcId(got.calc_id);
        setCaption(`${got.points.length} readings · nothing is carried across dates`);
      }).catch(() => { if (!ignore) setRefused("That balance could not be read just now."); });
    } else if (selected.group === "flow" && selected.row.source === "recipe") {
      // A recipe flow (free cash flow) is a ledgered series like a ratio; its
      // unit is money, which the row already states.
      getPanelSeries(ticker, [selected.row.metric]).then((got) => {
        if (ignore) return;
        const series = got.series[0];
        if (!series) { setRefused(`${selected.row.label} is not a series this recipe produced.`); return; }
        setPoints(series.points.map((p) => ({ period: p.end, value: p.value, ids: p.fact_ids ?? [] })));
        setUnit(selected.row.unit_class);
        setCalcId(series.calc_id);
        setCaption(`${series.points.length} windows · one ledgered calculation`);
      }).catch(() => { if (!ignore) setRefused("That series could not be read just now."); });
    } else if (selected.group === "flow") {
      getWindows(ticker, selected.row.metric).then((got) => {
        if (ignore) return;
        const row = got.rows.find((r) => r.months === months);
        if (!row) {
          setRefused(got.detail
            ?? `No ${months}-month window of ${got.label.toLowerCase()} can be derived from what this desk holds.`);
          return;
        }
        // An unreachable slot keeps its place as a gap: dropping it would let
        // its neighbours close ranks and read as consecutive (V10 DP2).
        setPoints(levelPoints(row.slots) as Point[]);
        setUnit("MONEY");
        setCalcId(null);
        const derived = row.slots.filter((s) => s.value != null && (s.terms?.length ?? 1) > 1).length;
        const missing = row.slots.filter((s) => s.value == null).length;
        setCaption(`${row.label} windows · ${row.slots.length} periods`
          + (derived ? ` · ${derived} derived` : "")
          + (missing ? ` · ${missing} no held filing reaches` : ""));
      }).catch(() => { if (!ignore) setRefused("Those windows could not be read just now."); });
    }
    return () => { ignore = true; };
  }, [ticker, selected, view, months]);

  if (refused) return <p className="text-xs text-slate-500 py-8">{refused}</p>;
  if (!points) return <p className="text-xs text-slate-600 py-8">Reading…</p>;
  const drawable = points.filter((p): p is Point & { value: number } => p.value != null);
  if (drawable.length < 2) {
    return <p className="text-xs text-slate-500 py-8">
      This desk holds fewer than two periods of {selected.row.label.toLowerCase()}, so there is
      no line to draw.
    </p>;
  }

  const derivedAt = new Set(points.filter((p) => p.derived).map((p) => p.period));
  // The margin's own name, when that is what is being drawn. "Net income as a
  // share of revenue" was a true sentence that never said "Net margin", so the
  // reader could not tell this view and the Ratios row apart from two different
  // calculations (D2).
  const title = linked ? linked.label
    : view === "yoy" ? `${selected.row.label}, year on year`
    : selected.row.label;
  const derivation = linked
    ? `${selected.row.label.toLowerCase()} ÷ revenue`
    : null;

  return (
    <div className="min-w-0">
      <div className="flex items-baseline gap-2 flex-wrap mb-1">
        <span className="text-[13px] font-medium text-slate-200">{title}</span>
        {derivation && <span className="text-[11px] text-slate-400">{derivation}</span>}
        <span className="text-[11px] text-slate-500">{caption}</span>
        {calcId && (
          <button onClick={() => onOpen(calcId)}
            className="ml-auto text-[11px] text-teal-400 hover:text-teal-300 hover:underline">
            how this was worked out
          </button>
        )}
      </div>
      {linked && (
        <p className="mb-1.5 text-[11px] text-teal-400/90">
          The same row as <span className="text-teal-300">Ratios → {linked.label}</span> —
          one calculation, reached from either side.
        </p>
      )}
      <LineChart
        x={points.map((p) => p.period)}
        height={240}
        padLeft={62}
        series={[{
          key: selected.row.metric,
          label: title,
          colour: C.s1,
          points: points.map((p) => (p.value == null ? null : p.value)),
          endLabel: displayValue(drawable[drawable.length - 1].value, unit),
        }]}
        markers={[]}
        xTicks={points.map((p, i) => ({ at: i, label: fmtMonth(p.period) }))
          .filter((_, i) => i % Math.max(1, Math.ceil(points.length / 6)) === 0)}
        yFormat={(v) => displayValue(v, unit)}
        ariaLabel={`${title}, ${points.length} periods`}
        tipRows={(i) => {
          const p = points[i];
          return [
            { label: fmtDate(p.period), value: p.value == null ? "no held filing reaches it"
                : displayValue(p.value, unit), colour: C.s1 },
            ...(p.derived ? [{ label: "How", value: "derived — a signed path over filed windows" }] : []),
          ];
        }}
      />
      {/* Every point opens what it stands on. A row of buttons rather than
          clickable marks: a 4px circle is not a click target, and the period is
          what a reader names when they want the filing behind one. */}
      {points.some((p) => p.ids.length > 0) && (
        <div className="mt-1.5 flex flex-wrap items-baseline gap-x-2.5 gap-y-1 text-[10.5px]">
          <span className="text-slate-600">Open a period&apos;s evidence:</span>
          {points.filter((p) => p.ids.length > 0).slice(-8).map((p) => (
            <button key={p.period} onClick={() => onOpen(p.ids[0])}
              className={`hover:text-slate-200 hover:underline decoration-dotted underline-offset-2 ${
                derivedAt.has(p.period) ? "text-blue-300" : "text-slate-500"}`}
              title={derivedAt.has(p.period)
                ? "Derived from several filed windows — opens the first of them"
                : "Opens the figure as it was filed"}>
              {fmtMonth(p.period)}
            </button>
          ))}
        </div>
      )}
      <Legend items={[
        { label: "As filed", colour: C.s1, shape: "line" },
        ...(derivedAt.size > 0
          ? [{ label: "Derived — a signed path over filed windows", colour: C.s1, shape: "outline" as const }]
          : []),
        ...(points.some((p) => p.value == null)
          ? [{ label: "No held filing reaches it — a gap, not a zero", shape: "dashed" as const }]
          : []),
      ]} />
    </div>
  );
}
