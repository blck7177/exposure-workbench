import { describe, expect, it } from "vitest";

import { collapseSteps, stepPhrase } from "../app/components/steps";
import { fmtMoney, fmtPct, titleFromKey } from "../app/components/charts/frame";

describe("collapseSteps", () => {
  const e = (step_name: string, status: string) =>
    ({ step_name, status, message: null, duration_ms: null });
  it("keeps the LAST row per step — a failed step stays the step that happened", () => {
    const out = collapseSteps([e("a", "running"), e("a", "failed"), e("b", "running"), e("b", "completed")]);
    expect(out.map((s) => [s.step_name, s.status])).toEqual([["a", "failed"], ["b", "completed"]]);
  });
  it("phrases from the step's own message, falling back to the name in words", () => {
    expect(stepPhrase({ step_name: "check_limits", status: "completed", message: null, duration_ms: null }))
      .toBe("check limits");
  });
});

describe("fmtMoney", () => {
  it("puts the sign OUTSIDE the symbol — the Day P&L tile bug", () => {
    expect(fmtMoney(-141972.82)).toBe("−$141,973");
    expect(fmtMoney(-1_250_000)).toBe("−$1.25M");
  });
  it("scales magnitudes and survives null", () => {
    expect(fmtMoney(10_845_260)).toBe("$10.85M");
    expect(fmtMoney(null)).toBe("—");
  });
});

describe("titleFromKey", () => {
  it("reads a stored key as words", () => {
    expect(titleFromKey("Communication_Services")).toBe("Communication Services");
    expect(titleFromKey("small_cap")).toBe("Small cap");
    expect(titleFromKey(null)).toBe("—");
  });
});

describe("fmtPct", () => {
  it("is a display of a fraction, not of a percent", () => {
    expect(fmtPct(0.135581, 2)).toBe("13.56%");
  });
});
