import { describe, expect, it } from "vitest";

import { idsIn, planAnnotations } from "../app/components/analyst/AnswerText";

/**
 * The invariants the single-pass renderer exists for (V13-S6/S7).
 *
 * The bug this guards against: citations and figure highlights were applied in
 * two passes, the first pass REMOVED bracketed ids, and the gate's spans —
 * offsets into the ORIGINAL text — stopped lining up. The guard inside the
 * highlighter meant the result was never mis-highlighted; it silently lost the
 * highlighting, which no browser check and no TypeScript error reports.
 */

const fig = (start: number, end: number, surface: string) => ({
  span: [start, end] as [number, number], surface,
  value: 1, unit_class: "MONEY", how: "value" as const,
  label: undefined, source_id: undefined,
});

describe("planAnnotations", () => {
  it("locates figures against the original text even after an earlier citation", () => {
    const text = "Revenue was $10 [fact_abc123] and margin was 40% after that.";
    const pct = text.indexOf("40%");
    const spans = planAnnotations(text, [fig(pct, pct + 3, "40%")]);
    expect(spans.map((s) => s.kind)).toEqual(["cites", "figure"]);
    expect(spans[1].start).toBe(pct);
  });

  it("drops a match whose span no longer holds its surface, rather than mis-highlighting", () => {
    const text = "Margin was 40% in the quarter.";
    const spans = planAnnotations(text, [fig(0, 3, "40%")]);
    expect(spans).toEqual([]);
  });

  it("drops a match that runs past the end of the text", () => {
    const spans = planAnnotations("short", [fig(2, 99, "ort…")]);
    expect(spans).toEqual([]);
  });

  it("does not double-count a bare id inside a bracketed group", () => {
    const text = "As filed [fact_abc123, calc_def456] shows.";
    const spans = planAnnotations(text);
    expect(spans).toHaveLength(1);
    expect(spans[0].kind === "cites" && spans[0].ids).toEqual(["fact_abc123", "calc_def456"]);
  });

  it("returns non-overlapping spans in text order — the walk's whole contract", () => {
    const text = "A $5 rise [calc_aaaa11] then 12% [fact_bbbb22] and 7% more.";
    const p12 = text.indexOf("12%");
    const p7 = text.indexOf("7%");
    const spans = planAnnotations(text, [fig(p12, p12 + 3, "12%"), fig(p7, p7 + 2, "7%")]);
    for (let i = 1; i < spans.length; i++) {
      expect(spans[i].start).toBeGreaterThanOrEqual(spans[i - 1].end);
    }
  });

  it("refuses a figure that overlaps a citation group instead of nesting it", () => {
    const text = "See [fact_abc123] now.";
    const inside = text.indexOf("fact");
    const spans = planAnnotations(text, [fig(inside, inside + 4, "fact")]);
    expect(spans.filter((s) => s.kind === "figure")).toHaveLength(0);
  });
});

describe("idsIn", () => {
  it("keeps citation order first and appends inline ids once", () => {
    expect(idsIn("uses calc_def456 and calc_def456 again", ["fact_abc123"]))
      .toEqual(["fact_abc123", "calc_def456"]);
  });
  it("is empty-safe", () => {
    expect(idsIn(null)).toEqual([]);
  });
});
