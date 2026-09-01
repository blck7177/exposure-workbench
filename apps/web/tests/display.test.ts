import { readFileSync } from "fs";
import path from "path";

import { describe, expect, it } from "vitest";

import { display } from "../lib/display";

/**
 * The two-way lock with analytics/display_conventions.py (V15-S6).
 *
 * The cases are not written here: they are read from the fixture the Python
 * suite reads, so neither side can drift from the other without one of the two
 * suites going red. A case added to the fixture binds both at once.
 */

type Case = { value: number; unit_class: string; display: string };

const fixture = path.resolve(__dirname, "../../../tests/fixtures/display_cases.json");
const cases: Case[] = JSON.parse(readFileSync(fixture, "utf8")).cases;

describe("display mirrors the Python conventions", () => {
  it("has cases to hold it to", () => {
    expect(cases.length).toBeGreaterThan(0);
  });
  for (const c of cases) {
    it(`${c.value} ${c.unit_class} → ${c.display}`, () => {
      expect(display(c.value, c.unit_class)).toBe(c.display);
    });
  }
});

describe("display resolves an exact tie the way Python does", () => {
  // Python's format is round-half-even on the binary value; toFixed is
  // round-half-up. These only differ at an exact binary tie.
  it("to even, not up", () => {
    expect(display(512.5, "MONEY")).toBe("$512");
    expect(display(513.5, "MONEY")).toBe("$514");
    expect(display(0.125, "MULTIPLE")).toBe("0.12×");
    expect(display(0.375, "MULTIPLE")).toBe("0.38×");
    expect(display(-512.5, "MONEY")).toBe("$-512");
  });
});
