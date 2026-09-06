/**
 * The Financials picker's pure decisions (V25).
 *
 * The panel's claim is that a control it renders leads somewhere. The server
 * decides which views a measure supports — from the measure's kind, from
 * whether the recipe computed a year-on-year series, from the recipe's own
 * margin table — and this file only reads that decision back. Nothing here
 * infers a capability the server did not state, and nothing computes a figure.
 */

import type { FlowMeasure, MeasureView, RatioMeasure, WindowSlot } from "./charts";

/**
 * The views to offer, in reading order.
 *
 * The order is fixed rather than the server's, so the same control sits in the
 * same place whichever measure is chosen; the CONTENTS are the server's alone.
 */
const ORDER: MeasureView[] = ["level", "yoy", "share", "windows"];

export function viewsOffered(measure: { views: MeasureView[] }): MeasureView[] {
  return ORDER.filter((v) => measure.views.includes(v));
}

/**
 * The window lengths a flow can actually be drawn over.
 *
 * From `windows_available`, which is what the interval engine could produce —
 * not from `windows_filed`, which is what the issuer filed. An issuer files 3-
 * and 12-month revenue and may still have no derivable latest quarter, and a
 * "3 months" button there is a button that draws nothing.
 *
 * With no list at all (an older API), both are offered: the chart's own read
 * then refuses the one that cannot be built, and says why.
 */
export function windowChoices(measure: Pick<FlowMeasure, "windows_available">): (3 | 12)[] {
  const available = measure.windows_available;
  if (!available) return [3, 12];
  return ([3, 12] as const).filter((m) => available.includes(`${m}-month`));
}

export type LevelPoint = {
  period: string;
  value: number | null;
  ids: string[];
  derived: boolean;
};

/**
 * A flow's windows as points, with the unreachable ones kept in place.
 *
 * A slot the engine could not derive stays, with a null value, so the line
 * breaks there. Dropping it would let its neighbours close ranks and read as
 * consecutive quarters — the June quarter drawn next to the December one, with
 * a quarter of growth invented between them (V10 DP2).
 *
 * `derived` is a window assembled from more than one filed figure — Microsoft's
 * June quarter is the fiscal year less its nine months, which no filing states.
 * The legend says so; nothing here treats it as a lesser number.
 */
export function levelPoints(slots: WindowSlot[]): LevelPoint[] {
  return slots.map((s) => ({
    period: s.period_end,
    value: s.value,
    ids: s.fact_ids ?? (s.terms ?? []).map((t) => t.fact_id),
    derived: (s.terms?.length ?? 1) > 1,
  }));
}


/**
 * The ratio row a flow's "Share of revenue" view actually draws (V25, D2).
 *
 * Net margin has two doors: `Ratios → Net margin` and
 * `Flows → Net income → Share of revenue`. Both resolve to one ledger row —
 * `calc_2f9eba710a99` on Microsoft, twelve points — and until this function
 * existed the second door never said so. The chart was headed "Net income as a
 * share of revenue", four words that do not include "Net margin", so a reader
 * who arrived by each door had no way to know they were in one room and might
 * reasonably go and check whether the two agreed.
 *
 * The two doors stay. Keeping only the Ratios row would cost the flow its
 * follow-up question ("this $31.78B — how much of revenue is that?"); keeping
 * only the share view would take `net_margin` out of the list that is supposed
 * to be the inventory of what this desk holds, while briefs go on citing it.
 * What was wrong was never the second door. It was that the two names did not
 * point at each other.
 *
 * This is the pointing: the share view is titled with the margin's own name,
 * says the division it is, and lights that row in the list.
 */
export function linkedRatio(
  selected: { group: string; row: unknown } | null,
  view: MeasureView,
  ratios: RatioMeasure[],
): RatioMeasure | null {
  if (!selected || selected.group !== "flow" || view !== "share") return null;
  // Only a flow carries `share_metric`, and only the `flow` branch is reached
  // here — the cast is the narrowing the discriminant has already done.
  const metric = (selected.row as FlowMeasure).share_metric;
  return (metric && ratios.find((r) => r.metric === metric)) || null;
}
