import { describe, expect, it } from "vitest";

import { display } from "@/lib/display";
import { levelPoints, linkedRatio, viewsOffered, windowChoices } from "@/lib/measures";
import type { FlowMeasure, RatioMeasure } from "@/lib/charts";

/**
 * The issuer's Financials picker, where the decisions are (V25).
 *
 * The panel's whole claim is that a control it renders leads somewhere: the
 * server says which views a measure supports, and the client renders exactly
 * those. These pin the three places that claim could quietly stop being true —
 * a view offered that the server did not name, a window control offering a
 * length that cannot be drawn, and a slot the engine could not reach silently
 * closing ranks with its neighbours.
 */

const revenue: FlowMeasure = {
  metric: "revenue", label: "Revenue", source: "filed", unit_class: "MONEY",
  periods: 21, through: "2026-03-31",
  windows_filed: ["3-month", "12-month"],
  windows_available: ["3-month", "12-month"],
  latest: { start: "2026-01-01", end: "2026-03-31", value: 82886000000, derived: false, fact_ids: ["fact_a"] },
  latest_12m: { start: "2024-07-01", end: "2025-06-30", value: 281724000000, derived: false, fact_ids: ["fact_b"] },
  views: ["level", "yoy", "windows"],
  yoy_metric: "revenue_yoy", share_metric: null,
};

describe("a control that is rendered is a control that leads somewhere", () => {
  it("offers only the views the server named", () => {
    expect(viewsOffered(revenue)).toEqual(["level", "yoy", "windows"]);
  });

  it("does not invent a share view for a flow with no margin", () => {
    // Revenue is what the margins are a share OF; it has no margin of its own,
    // and a `share` button on it would open an empty chart.
    expect(viewsOffered(revenue)).not.toContain("share");
  });

  it("offers share where the recipe computed the margin", () => {
    const netIncome = { ...revenue, metric: "net_income", share_metric: "net_margin",
                        views: ["level", "yoy", "share", "windows"] as FlowMeasure["views"] };
    expect(viewsOffered(netIncome)).toContain("share");
  });
});

describe("the window control offers what can be drawn", () => {
  it("offers both lengths when both derive", () => {
    expect(windowChoices(revenue)).toEqual([3, 12]);
  });

  it("offers only the year when no quarter can be derived", () => {
    // NVDA holds two annual revenue facts and no quarterly boundary near them.
    // Offering "3 months" there is a button that draws nothing — and the twelve
    // month figure must never stand in for the quarter that is missing.
    const annualOnly = { ...revenue, windows_available: ["12-month"], latest: null,
                         latest_unreachable: "this desk holds no pair of boundaries 3 months apart" };
    expect(windowChoices(annualOnly)).toEqual([12]);
  });

  it("falls back to the server's list being absent by offering both", () => {
    const noList = { ...revenue, windows_available: undefined };
    expect(windowChoices(noList)).toEqual([3, 12]);
  });
});

describe("the two doors to one margin point at each other (D2)", () => {
  const netMargin: RatioMeasure = {
    metric: "net_margin", label: "Net margin", source: "recipe", unit_class: "RATIO",
    calc_id: "calc_2f9eba710a99", operation: "calc.series.divide", points: 12,
    latest: { end: "2026-03-31", value: 0.383394 }, views: ["level"],
  };
  const grossMargin: RatioMeasure = { ...netMargin, metric: "gross_margin",
    label: "Gross margin", calc_id: "calc_dd8615785721" };
  const ratios = [grossMargin, netMargin];
  const netIncome = { group: "flow", row: { ...revenue, metric: "net_income",
    label: "Net income", share_metric: "net_margin" } };

  it("names the row the share view actually draws", () => {
    // "Net income as a share of revenue" is true and never says "Net margin",
    // so a reader arriving by each door cannot tell one calculation from two.
    expect(linkedRatio(netIncome, "share", ratios)).toEqual(netMargin);
    expect(linkedRatio(netIncome, "share", ratios)?.calc_id).toBe("calc_2f9eba710a99");
  });

  it("links nothing on any other view of the same flow", () => {
    expect(linkedRatio(netIncome, "level", ratios)).toBeNull();
    expect(linkedRatio(netIncome, "yoy", ratios)).toBeNull();
  });

  it("links nothing when the reader is already standing on the ratio", () => {
    // The other direction is noise: on Net margin, knowing you could also have
    // come from Net income does not help.
    expect(linkedRatio({ group: "ratio", row: netMargin }, "share", ratios)).toBeNull();
  });

  it("links nothing for a flow with no margin", () => {
    expect(linkedRatio({ group: "flow", row: revenue }, "share", ratios)).toBeNull();
  });

  it("links nothing when the recipe did not compute that margin for this issuer", () => {
    const orphan = { group: "flow", row: { ...revenue, share_metric: "operating_margin" } };
    expect(linkedRatio(orphan, "share", ratios)).toBeNull();
  });
});

describe("a window no filing reaches stays a gap", () => {
  const slots = [
    { start: "2025-04-01", period_end: "2025-06-30", value: 76441000000, fact_ids: ["f1"], terms: [{ fact_id: "f1", sign: 1 }, { fact_id: "f2", sign: -1 }] },
    { start: "2025-07-01", period_end: "2025-09-30", value: null, unreachable: "no held filing reaches it" },
    { start: "2025-10-01", period_end: "2025-12-31", value: 81273000000, fact_ids: ["f3"], terms: [{ fact_id: "f3", sign: 1 }] },
  ];

  it("keeps the unreachable slot in its place", () => {
    // Dropping it would let its neighbours close ranks and read as
    // consecutive quarters (V10 DP2) — the June quarter next to the December
    // one, with a quarter of growth invented between them.
    const points = levelPoints(slots);
    expect(points).toHaveLength(3);
    expect(points[1].value).toBeNull();
    expect(points[1].period).toBe("2025-09-30");
  });

  it("marks a window with several terms as derived", () => {
    const points = levelPoints(slots);
    expect(points[0].derived).toBe(true);
    expect(points[2].derived).toBe(false);
  });

  it("carries the facts a point rests on, so it can be opened", () => {
    expect(levelPoints(slots)[0].ids).toContain("f1");
    expect(levelPoints(slots)[1].ids).toEqual([]);
  });
});

describe("a figure is shown the way the rest of the desk shows it", () => {
  it("reads money at reader precision", () => {
    expect(display(82886000000, "MONEY")).toBe("$82.89B");
  });

  it("reads a ratio as a percentage", () => {
    expect(display(0.38339406, "RATIO")).toBe("38.3%");
  });

  it("reads a multiple as a multiple", () => {
    // The multiplication sign, not the letter x — the same character
    // analytics/display_conventions.py writes.
    expect(display(1.2829483, "MULTIPLE")).toBe("1.28\u00d7");
  });
});
