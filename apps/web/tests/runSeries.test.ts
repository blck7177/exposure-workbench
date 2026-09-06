import { describe, expect, it } from "vitest";

import { compareBy, deltaLabel, focusReducer, sortRows } from "@/lib/book";
import type { Focus } from "@/lib/book";

/**
 * The book page's pure decisions (V25).
 *
 * The browser acceptance sees "renders wrong"; these see "computes wrong but
 * renders fine", which is the kind that survives a screenshot. Three of them
 * here, each a rule that is invisible in review:
 *
 *  - a delta names the update it is against, and says nothing when there is
 *    none — the difference between "unchanged" and "not compared";
 *  - a null sorts last in BOTH directions, because a name with no comparison
 *    is not the smallest move;
 *  - focusing one thing releases whatever was focused before, since no panel
 *    knows how to draw two.
 */

describe("what a delta is against", () => {
  it("names the previous dated update", () => {
    expect(deltaLabel("2026-09-02")).toBe("Δ vs Sep 2");
  });

  it("says nothing about a comparison that was never made", () => {
    // The first update of a book, and a name it did not hold last time, are the
    // same answer for a reader: there is no move to state. "Δ vs —" would be a
    // column header promising a figure that is never there.
    expect(deltaLabel(null)).toBe("Δ");
  });

  it("keeps the year off a date the page has already dated", () => {
    expect(deltaLabel("2026-01-07")).toBe("Δ vs Jan 7");
  });
});

describe("sorting is a view over the rows a run wrote", () => {
  const rows = [
    { ticker: "AAPL", weight: 0.149, delta: -0.0002 },
    { ticker: "MSFT", weight: 0.163, delta: 0.0024 },
    { ticker: "NVDA", weight: 0.042, delta: null },
    { ticker: "XOM", weight: 0.044, delta: -0.001 },
  ];

  it("orders by a number, descending", () => {
    expect(sortRows(rows, (r) => r.weight, true).map((r) => r.ticker))
      .toEqual(["MSFT", "AAPL", "XOM", "NVDA"]);
  });

  it("puts a row with no comparison last, ascending as well as descending", () => {
    expect(sortRows(rows, (r) => r.delta, true).map((r) => r.ticker))
      .toEqual(["MSFT", "AAPL", "XOM", "NVDA"]);
    expect(sortRows(rows, (r) => r.delta, false).map((r) => r.ticker))
      .toEqual(["XOM", "AAPL", "MSFT", "NVDA"]);
  });

  it("orders a string by its letters, not by its code points alone", () => {
    expect(sortRows(rows, (r) => r.ticker, false).map((r) => r.ticker))
      .toEqual(["AAPL", "MSFT", "NVDA", "XOM"]);
  });

  it("leaves the rows it was given alone", () => {
    const before = rows.map((r) => r.ticker);
    sortRows(rows, (r) => r.weight, true);
    expect(rows.map((r) => r.ticker)).toEqual(before);
  });

  it("compares nulls as equal rather than as a number", () => {
    expect(compareBy(null, null)).toBe(0);
    expect(compareBy(null, 1)).toBeGreaterThan(0);
    expect(compareBy(1, null)).toBeLessThan(0);
  });
});

describe("pointing at one thing releases the last", () => {
  const ticker: Focus = { kind: "ticker", key: "MSFT" };
  const factor: Focus = { kind: "factor", key: "Growth" };

  it("replaces a focus of another kind outright", () => {
    // TLT is both a holding and a factor on this desk, so "the reader is
    // pointing at the TLT holding" and "at the rates factor" are two different
    // sentences about the same three letters — and two panels lit at once is a
    // state none of them knows how to draw.
    expect(focusReducer(ticker, factor)).toEqual(factor);
  });

  it("clears on null", () => {
    expect(focusReducer(ticker, null)).toBeNull();
  });

  it("pointing at what is already focused changes nothing", () => {
    expect(focusReducer(ticker, { kind: "ticker", key: "MSFT" })).toEqual(ticker);
  });
});
