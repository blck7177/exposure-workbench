#!/usr/bin/env python3
"""V13-S8 — the reader's layer, checked in a browser.

The three claims this batch makes about the rendered page cannot be checked by
the offline suite, by TypeScript, or by reading the API's JSON. They are claims
about the DOM:

  1. No internal identifier reaches the reader's layer. Not "no id is prominent"
     — none is present, which is why AuditOnly is a component that renders
     nothing rather than a class that hides something. This script asserts the
     absence over the text of the rendered page.
  2. Every page renders without a JavaScript error. A chart that throws leaves a
     blank card and a 200.
  3. The audit layer, switched on, DOES show them. A page that renders no ids
     because it renders nothing would pass (1) and fail this.

Run it against anything that serves both the page and /api on one origin:

    python scripts/smoke_ui.py                       # https://desk-for-one.com
    python scripts/smoke_ui.py http://127.0.0.1:8081 # a local build behind a proxy

It needs Playwright's chromium, which is not in the runtime image and is not
meant to be — this is an acceptance tool, not a dependency of the product:

    pip install -e '.[dev]' && playwright install chromium

Exit status is 0 when every check passes, 1 otherwise, so it can gate a deploy.
"""

from __future__ import annotations

import asyncio
import re
import sys

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "https://desk-for-one.com"

# Every id prefix this system mints. Deliberately the whole family and not the
# ones a given page happens to render: a new surface leaking `rrun_…` is exactly
# what this is for.
ID = re.compile(r"\b(fact|calc|chunk|src|run|alert|pos|rrun|task|sess|brief|port|report|user)"
                r"_[0-9a-f]{8,}")

# Strings that are transport, a provider's own words, or this machine's inside.
# The failure surface must carry none of them (V13-S2).
OPERATOR_ONLY = re.compile(
    r"openai|anthropic|tavily|asyncpg|sqlalchemy|Traceback|exposure-postgres|"
    r"exposure-mcp|localhost:\d|127\.0\.0\.1|InsufficientPrivilege|row-level security",
    re.I)

VIEWS = [
    ("book", "/", []),
    ("issuer", "/issuer/AAPL", []),
    ("issuer · financials", "/issuer/AAPL", ["Financials"]),
    ("issuer · filings", "/issuer/AAPL", ["Filings"]),
    ("issuer · brief", "/issuer/AAPL", ["Brief"]),
]


async def _open(browser, path: str, tabs: list[str]):
    ctx = await browser.new_context(viewport={"width": 1600, "height": 1100})
    page = await ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    await page.goto(BASE + path, wait_until="networkidle", timeout=60_000)
    await page.wait_for_timeout(2500)
    for tab in tabs:
        await page.get_by_role("button", name=tab, exact=True).click()
        await page.wait_for_timeout(2500)
    return ctx, page, errors


async def main() -> int:
    from playwright.async_api import async_playwright

    failures: list[str] = []
    print(f"checking {BASE}\n")
    async with async_playwright() as p:
        browser = await p.chromium.launch()

        for name, path, tabs in VIEWS:
            ctx, page, errors = await _open(browser, path, tabs)
            text = await page.inner_text("body")
            ids = sorted({m.group(0) for m in ID.finditer(text)})
            leaks = sorted({m.group(0) for m in OPERATOR_ONLY.finditer(text)})
            ok = not ids and not leaks and not errors and len(text) > 300
            print(f"  {'PASS' if ok else 'FAIL'}  {name:22} "
                  f"ids={len(ids)} operator-strings={len(leaks)} js-errors={len(errors)} "
                  f"chars={len(text)}")
            if ids:
                failures.append(f"{name}: internal ids in the reader's layer: {ids[:6]}")
            if leaks:
                failures.append(f"{name}: operator-only strings on the page: {leaks[:6]}")
            if errors:
                failures.append(f"{name}: javascript error: {errors[0][:200]}")
            if len(text) <= 300:
                failures.append(f"{name}: rendered almost nothing ({len(text)} chars)")
            await ctx.close()

        # (3) the layer is a way of LOOKING, not a deletion — and it survives a
        # navigation, which is the reason it is mounted in the layout.
        ctx, page, _ = await _open(browser, "/", [])
        await page.get_by_role("button", name="Audit", exact=True).click()
        await page.wait_for_timeout(1800)
        with_audit = {m.group(0) for m in ID.finditer(await page.inner_text("body"))}
        print(f"  {'PASS' if with_audit else 'FAIL'}  audit layer shows the ids   "
              f"({len(with_audit)} on the book)")
        if not with_audit:
            failures.append("the audit layer showed no ids — a page rendering nothing "
                            "would pass the checks above")
        await page.goto(BASE + "/issuer/AAPL", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        still = await page.get_by_role("button", name="Audit", exact=True).get_attribute("aria-pressed")
        print(f"  {'PASS' if still == 'true' else 'FAIL'}  audit survives a navigation")
        if still != "true":
            failures.append("the audit switch reset on navigation — it is not hoisted "
                            "into the layout, or cacheComponents assumptions changed")
        await ctx.close()
        await browser.close()

    print()
    if failures:
        print(f"{len(failures)} failure(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
