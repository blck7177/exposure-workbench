import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { ReportChips, ReportPanelView, panelFor } from "../app/components/analyst/Reports";
import type { AnalystReport, ReportRef } from "../lib/api";

// Each answer carries a chip per specialist, and opening one shows that
// specialist's reading drawn like the answer, with the observer's verification.
// Rendered with react-dom/server — no DOM in this suite — so what is checked is
// what each state PUTS ON THE PAGE.

const returned: ReportRef = { domain: "issuer", report_id: "rep_1", status: "returned" };
const stopped: ReportRef = { domain: "risk", report_id: "rep_2", status: "stopped" };
const noop = () => {};

const report = (over: Partial<AnalystReport> = {}): AnalystReport => ({
  id: "rep_1",
  domain: "issuer",
  status: "returned",
  title: "the issuer analyst on AAPL, MSFT, NVDA",
  brief: { analyses: ["calc_view1"], stop_reason: "finished", rows_read: [] },
  text: "NVDA converts least of the three at 69.7% and fell 19.3 percentage points.",
  blocks: [{ type: "paragraph", runs: ["NVDA converts least of the three at ", { fact: { id: "f_1", kind: "scalar", measure: "cash_conversion", subject: "NVDA", unit: "RATIO", value: 0.6966, display: "69.7%" } }, "."] }],
  citations: ["f_1"],
  verified: { figures: 2, supported: 2, contradicted: 0, unsourced: 0, ambiguous: 0 },
  problems: [],
  created_at: null,
  ...over,
});

describe("ReportChips", () => {
  it("draws one chip per specialist, named by its family, marked by how the task ended", () => {
    const html = renderToStaticMarkup(<ReportChips reports={[returned, stopped]} onOpen={noop} />);
    expect(html.match(/<button/g)?.length).toBe(2);
    expect(html).toContain("issuer");
    expect(html).toContain("risk");
    expect(html).toContain("✓");
    expect(html).toContain("—");
  });
  it("says in the title what the mark means — a stopped task is on the record, not a finding", () => {
    const html = renderToStaticMarkup(<ReportChips reports={[stopped]} onOpen={noop} />);
    expect(html).toContain("stopped before the specialist wrote its reading");
  });
  it("draws nothing for an answer with no specialists behind it", () => {
    expect(renderToStaticMarkup(<ReportChips reports={[]} onOpen={noop} />)).toBe("");
    expect(renderToStaticMarkup(<ReportChips onOpen={noop} />)).toBe("");
  });
});

describe("panelFor — whose panel opens", () => {
  it("opens under the message whose chips include the report, and under no other", () => {
    expect(panelFor(returned, [returned, stopped])).toBe(returned);
    expect(panelFor(returned, [stopped])).toBeNull();
    expect(panelFor(null, [returned])).toBeNull();
    expect(panelFor(returned, undefined)).toBeNull();
  });
});

describe("ReportPanelView", () => {
  it("a returned reading shows its blocks and the observer's count, never a completion claim", () => {
    const html = renderToStaticMarkup(
      <ReportPanelView report={returned} full={report()} error={null} onClose={noop} onOpenFact={noop} />);
    expect(html).toContain(">returned</span>");
    expect(html).toContain("69.7%");
    expect(html).toContain("2 of 2 figures supported");
    expect(html).toContain("1 analysis recorded");
    expect(html).not.toContain("complete");
  });

  it("a reading with figures that did not hold says how many", () => {
    const full = report({ verified: { figures: 3, supported: 2, contradicted: 1, unsourced: 0, ambiguous: 0 } });
    const html = renderToStaticMarkup(
      <ReportPanelView report={returned} full={full} error={null} onClose={noop} onOpenFact={noop} />);
    expect(html).toContain("2 of 3 figures supported");
    expect(html).toContain("; 1 did not hold");
  });

  it("a stopped task shows why it stopped and what it analysed, and no prose", () => {
    const full = report({ id: "rep_2", domain: "risk", status: "stopped", text: "half a sentence", blocks: [],
      brief: { analyses: ["calc_view2"], stop_reason: "turn_limit" } });
    const html = renderToStaticMarkup(
      <ReportPanelView report={stopped} full={full} error={null} onClose={noop} onOpenFact={noop} />);
    expect(html).toContain(">stopped</span>");
    expect(html).toContain("turn limit");
    expect(html).toContain("1 analysis");
    expect(html).not.toContain("half a sentence");
  });

  it("says it is opening until the report arrives, and names the family from the chip meanwhile", () => {
    const html = renderToStaticMarkup(
      <ReportPanelView report={returned} full={null} error={null} onClose={noop} onOpenFact={noop} />);
    expect(html).toContain("Opening…");
    expect(html).toContain("issuer");
  });

  it("shows the failure when the report cannot be opened", () => {
    const html = renderToStaticMarkup(
      <ReportPanelView report={returned} full={null} error="This report could not be opened."
        onClose={noop} onOpenFact={noop} />);
    expect(html).toContain("This report could not be opened.");
    expect(html).not.toContain("Opening…");
  });
});
