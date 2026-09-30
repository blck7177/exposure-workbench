import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { ReportChips, ReportPanelView, panelFor } from "../app/components/analyst/Reports";
import type { AnalystReport, ReportRef } from "../lib/api";

// V36: each answer carries a chip per domain analyst, and opening one shows that
// analyst's report drawn like the answer. Rendered here with react-dom/server —
// no DOM in this suite — so what is checked is what each state PUTS ON THE
// PAGE: the chip's name and mark, which message's panel opens, and that a
// refused report shows its problems and never its prose. The click itself is
// the browser smoke's (scripts/smoke_ui.py).

const verified: ReportRef = { domain: "book_limits_and_triggers", report_id: "rep_1", status: "verified" };
const refused: ReportRef = { domain: "issuer_earnings_quality", report_id: "rep_2", status: "refused" };
const noop = () => {};

const report = (over: Partial<AnalystReport> = {}): AnalystReport => ({
  id: "rep_1",
  domain: "book_limits_and_triggers",
  status: "verified",
  title: "Issuer-concentration room, run of 2026-09-10",
  brief: {
    findings: [{ want: 1, finding: "MSFT is nearest: its check reads 16.0% [f_1] against a 15.0% [f_2] warning tier." }],
    not_done: [{ want: 2, why: "the desk holds no prior run for this book" }],
    caveats: ["room is in weight points; dollar room was not requested"],
  },
  text: "MSFT is nearest.",
  blocks: [],
  citations: ["f_1", "f_2"],
  verified: {},
  problems: [],
  created_at: null,
  ...over,
});

describe("ReportChips", () => {
  it("draws one chip per analyst, named by its domain in words, marked by whether the check passed", () => {
    const html = renderToStaticMarkup(<ReportChips reports={[verified, refused]} onOpen={noop} />);
    expect(html.match(/<button/g)?.length).toBe(2);
    expect(html).toContain("book limits and triggers");
    expect(html).toContain("issuer earnings quality");
    expect(html).toContain("✓");
    expect(html).toContain("—");
  });
  it("says in the title what the mark means — 'not checked' is a report on the record, not a missing one", () => {
    const html = renderToStaticMarkup(<ReportChips reports={[refused]} onOpen={noop} />);
    expect(html).toContain("did not pass the check");
    expect(html).toContain("its figures are not quotable");
  });
  it("draws nothing for an answer with no analysts behind it", () => {
    expect(renderToStaticMarkup(<ReportChips reports={[]} onOpen={noop} />)).toBe("");
    expect(renderToStaticMarkup(<ReportChips onOpen={noop} />)).toBe("");
  });
});

describe("panelFor — whose panel opens", () => {
  it("opens under the message whose chips include the report, and under no other", () => {
    expect(panelFor(verified, [verified, refused])).toBe(verified);
    expect(panelFor(verified, [refused])).toBeNull();
    expect(panelFor(null, [verified])).toBeNull();
    expect(panelFor(verified, undefined)).toBeNull();
  });
});

describe("ReportPanelView", () => {
  it("shows evidence-only handoffs without claiming an analysis was completed", () => {
    const full = report({ status: "returned", brief: { protocol: "evidence-v2", stop_reason: "submitted",
      evidence: [{ id: "f_weight1234", row: "[f_weight1234] MSFT weight: 16.0%, latest run" }], notes: [] }, blocks: [] });
    const html = renderToStaticMarkup(<ReportPanelView report={{ ...verified, status: "returned" }} full={full}
      error={null} onClose={noop} onOpenFact={noop} />);
    expect(html).toContain(">returned</span>");
    expect(html).toContain("MSFT weight: 16.0%, latest run");
    expect(html).toContain("may still need further analysis");
    expect(html).not.toContain("not checked");
    expect(html).not.toContain("did not accept this reading");
  });

  it("keeps checked notes and evidence visible after another item failed", () => {
    const full = report({ status: "stopped", brief: { protocol: "evidence-v2", stop_reason: "submission_rejected",
      evidence: [{ id: "f_weight1234", row: "[f_weight1234] MSFT weight: 16.0%" }],
      notes: [{ id: "nte_bad", text: "untrusted raw text is never a rendering source" }] },
      blocks: [{ type: "paragraph", runs: ["A checked observation with its qualification."] }],
      problems: [{ item: "nte_bad", reasons: ["unsourced_figure"] }] });
    const html = renderToStaticMarkup(<ReportPanelView report={{ ...verified, status: "stopped" }} full={full}
      error={null} onClose={noop} onOpenFact={noop} />);
    expect(html).toContain("A checked observation with its qualification.");
    expect(html).toContain("MSFT weight: 16.0%");
    expect(html).toContain("Some submitted items did not pass checks");
    expect(html).not.toContain("untrusted raw text");
    expect(html).not.toContain(">checked</span>");
  });

  it("says it is opening until the report arrives, and names the domain from the chip meanwhile", () => {
    const html = renderToStaticMarkup(
      <ReportPanelView report={verified} full={null} error={null} onClose={noop} onOpenFact={noop} />);
    expect(html).toContain("Opening…");
    expect(html).toContain("book limits and triggers");
    expect(html).not.toContain("checked");
  });

  it("shows the failure when the report cannot be opened", () => {
    const html = renderToStaticMarkup(
      <ReportPanelView report={verified} full={null} error="This report could not be opened."
        onClose={noop} onOpenFact={noop} />);
    expect(html).toContain("This report could not be opened.");
    expect(html).not.toContain("Opening…");
  });

  it("a checked report reads like the answer: title, findings by line, what was not settled, caveats, blocks", () => {
    const full = report({ blocks: [{ type: "paragraph", runs: ["Room to warning is the smallest of the ten checks."] }] });
    const html = renderToStaticMarkup(
      <ReportPanelView report={verified} full={full} error={null} onClose={noop} onOpenFact={noop} />);
    expect(html).toContain(">checked</span>");
    expect(html).not.toContain("not checked");
    expect(html).toContain("Issuer-concentration room, run of 2026-09-10");
    expect(html).toContain("MSFT is nearest: its check reads 16.0% [f_1]");
    expect(html).toContain("Not settled");
    expect(html).toContain("the desk holds no prior run for this book");
    expect(html).toContain("room is in weight points");
    expect(html).toContain("Room to warning is the smallest of the ten checks.");
    expect(html).not.toContain("did not accept");
  });

  it("a refused report shows its problems and never its prose or its blocks", () => {
    const full = report({
      id: "rep_2", domain: "issuer_earnings_quality", status: "refused",
      text: "Amazon's accruals ratio is 4.1% and the highest of the three.",
      blocks: [{ type: "paragraph", runs: ["Amazon's accruals ratio is 4.1% and the highest of the three."] }],
      problems: [{ reason: "superlative_without_rank" }, { reason: "unsourced_figure" }],
    });
    const html = renderToStaticMarkup(
      <ReportPanelView report={refused} full={full} error={null} onClose={noop} onOpenFact={noop} />);
    expect(html).toContain("not checked");
    expect(html).toContain("The desk did not accept this reading, so its text is not shown.");
    expect(html).toContain("superlative_without_rank");
    expect(html).toContain("unsourced_figure");
    expect(html).not.toContain("accruals ratio is 4.1%");
  });

  it("lists at most five problems, the way the drawer is sized", () => {
    const full = report({ status: "refused", problems: Array.from({ length: 8 }, (_, i) => ({ reason: `reason_${i}` })) });
    const html = renderToStaticMarkup(
      <ReportPanelView report={refused} full={full} error={null} onClose={noop} onOpenFact={noop} />);
    expect(html).toContain("reason_4");
    expect(html).not.toContain("reason_5");
  });
});
