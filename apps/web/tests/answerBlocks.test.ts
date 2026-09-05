import { describe, expect, it } from "vitest";

import { idsInBlocks, identityOf, type Block, type FactFill } from "@/app/components/analyst/AnswerBlocks";

// V24: the ids an answer leans on include its facts and the facts its prose
// links resolved to — which is what the label endpoint is asked for, so a
// chip's hover and a chooser's rows have words on them.
const weight: FactFill = {
  id: "f_a", kind: "scalar", measure: "issuer_exposures.weight", subject: "MSFT", unit: "RATIO",
  value: 0.1625, as_of: "2026-09-03", display: "16.3%", sources: ["run_x"],
};
const mv: FactFill = { ...weight, id: "f_b", measure: "issuer_exposures.market_value", unit: "MONEY", value: 1785420, display: "$1.79M" };

describe("V24 blocks", () => {
  it("gathers facts, links, table cells, chart facts and cites", () => {
    const blocks: Block[] = [
      { type: "paragraph", runs: ["MSFT weighs ", { fact: weight }, ", worth ", { link: { to: "fact", ids: ["f_b", "f_c"], as_written: "$1.79M" } }], cites: ["f_p"] },
      { type: "table", rows: [[{ fact: weight }, { fact: mv }]], header: ["weight", "market value"], labels: ["MSFT"], explicit: [false, false] },
      { type: "chart", kind: "line", fact: { ...weight, id: "f_s", kind: "series" } },
    ];
    expect(idsInBlocks(blocks)).toEqual(["f_p", "f_a", "f_b", "f_c", "f_s"]);
  });

  it("still reads a pre-V24 answer", () => {
    const blocks: Block[] = [
      { type: "paragraph", runs: ["x ", { slot: { ref: "run_1", label: "issuer_exposures.MSFT.weight", value: 0.16, unit_class: "RATIO" } }] },
      { type: "trend", text: "climbed", series_ref: "calc_s" },
    ];
    expect(idsInBlocks(blocks)).toEqual(["run_1", "calc_s"]);
  });

  it("states a fact's identity in one line", () => {
    expect(identityOf(weight)).toBe("issuer exposures weight · MSFT · as of 2026-09-03 · RATIO");
    expect(identityOf({ ...weight, as_of: null, window: { start: "2025-04-01", end: "2026-03-31" } }))
      .toBe("issuer exposures weight · MSFT · as of 2025-04-01 – 2026-03-31 · RATIO");
  });
});
