import { describe, expect, it } from "vitest";

import { RUN_ERROR_CODES, explainRunError } from "../lib/errors";

/** The failure sentence's precedence (V13-S2): a backend-vouched message wins,
 *  then the code's wording, then the generic sentence — and an UNKNOWN code
 *  must degrade to the generic sentence, never to the code itself. */
describe("explainRunError", () => {
  it("prefers the message the backend stored for a reader", () => {
    expect(explainRunError("run_failed", "Cannot value this portfolio — newest price too old."))
      .toContain("Cannot value");
  });
  it("falls back to the code's wording when there is no message", () => {
    const s = explainRunError("provider_quota", null);
    expect(s.length).toBeGreaterThan(20);
    expect(s).not.toContain("provider_quota");
  });
  it("gives the generic sentence for no code, ignoring any stored message", () => {
    const s = explainRunError(null, "raw provider traceback");
    expect(s).not.toContain("traceback");
  });
  it("never shows an unknown code's spelling to the reader", () => {
    const s = explainRunError("some_new_code", null);
    expect(s).not.toContain("some_new_code");
  });
  it("has wording for every code it claims to", () => {
    for (const code of RUN_ERROR_CODES) {
      expect(explainRunError(code, null)).toBeTruthy();
    }
  });
});
