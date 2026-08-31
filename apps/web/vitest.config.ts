import { defineConfig } from "vitest/config";
import path from "path";

// Unit tests for the pure functions the pages lean on (V13 §9-⑧). The browser
// acceptance (scripts/smoke_ui.py) sees "renders wrong"; these see "computes
// wrong but renders fine" — the span-shift bug was the second kind.
export default defineConfig({
  resolve: { alias: { "@": path.resolve(__dirname) } },
  test: { include: ["tests/**/*.test.ts"], environment: "node" },
});
