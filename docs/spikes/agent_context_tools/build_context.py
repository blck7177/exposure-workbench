"""Assemble, offline, the context ONE agent would get under the simplified design:

    agent  +  the context it should get  +  the tools it can use

Everything except ROLE (a draft) and the block tags is rendered from the repo's own pure functions:
the handbook chapters (analytics/handbook), the eleven verbs of the existing `meta` mount
(tools/registries.build_meta_registry). The DESK block is a SYNTHETIC fixture in the exact shape
services/briefing.for_question returns (no database is read here); subjects are detected with the
repo's own regexes.

No database, no network, nothing written inside the repo. Output goes next to this file.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from exposure_workbench.analytics import formulas as fm
from exposure_workbench.analytics import handbook
from exposure_workbench.services import briefing as briefing_svc
from exposure_workbench.services import context_budget as cb
from exposure_workbench.tools import faces
from exposure_workbench.tools.registries import build_meta_registry

OUT = Path(__file__).parent
(OUT / "prompts").mkdir(exist_ok=True)

# ── the one piece of NEW wording: the role, organised by the four things the agent must understand ──

VERB_MAP = (
    ("see what the desk holds", ("list",)),
    ("an issuer's filed figures", ("filings_read",)),
    ("the text of its filings", ("filings_search", "filings_section")),
    ("what the filings cannot hold", ("web_search",)),
    ("a name's prices", ("prices_read",)),
    ("the book's figures", ("book_read",)),
    ("the book after a trade", ("scenario",)),
    ("a measure, by name", ("metric",)),
    ("one operation on rows you already have", ("calc",)),
    ("background preparation", ("start",)),
)

ROLE = """You are the analyst of a portfolio risk & issuer-intelligence desk, and the one the user talks to.

WHAT YOU ARE DOING
Answering the user's question from the desk's own evidence. The analysis is yours: take the question apart, decide \
what has to be known to answer it, get it with your tools, and say what it shows and what it means for the question \
asked. Keep the question in view as you work. You are done when you can answer it, or can say exactly what the desk \
does not hold.

WHAT YOU CAN DO
Your tools are verbs over the desk's resources; each says what it does and what it takes.
{verbs}
Every result is rows. A row carries its id (f_…), what it is, whose, over what period, the value, what it means and \
where it came from. A refusal is a row too, with its reason and the way out; it describes that one call and does not \
prove the question is unanswerable. Use tool arithmetic, not mental arithmetic.

HOW TO DO IT
The HANDBOOK block is the desk's method, one chapter per family of evidence: an issuer from its filings, a name from \
its prices, the book. For each it says what can be asked, which measures answer it, how each reads, what to set \
against what, and what the desk does not hold or does not say.

WHERE THE RESOURCES ARE
The DESK block is the desk's map for this question: the issuers it holds, the user's books with their runs and \
holdings, and how far each name's filings and prices reach. It carries names, dates and coverage, and no figure. \
`list` shows the rest: the measures, a name's filed lines, its filings and its price span, a book's tables, rows \
and checks.

YOUR ANSWER
Plain prose, to the user. Write a figure as its row shows it, with the row's id in brackets after it: \
16.0% [f_2592baab170e]."""

HANDBOOK_TAG = ('<handbook source="the desk\'s handbook" use="method — what a thing is, how it reads, what to set '
                'against what; it holds no figure">')
DESK_TAG = ('<desk source="the desk\'s catalogue" trust="names, dates and coverage only — no figure here" '
            'use="find the subjects and what the desk holds for them; check the question\'s premises">')

FAMILY = {"issuer": "AN ISSUER, FROM ITS FILINGS", "market": "A NAME, FROM ITS PRICES", "risk": "THE BOOK"}


def verbs_said(tool_names: list[str]) -> str:
    """The verb map, from the tools actually served: what the agent can do is never written twice."""
    have = set(tool_names)
    lines = [f"- {what}: {', '.join(n for n in names if n in have)}" for what, names in VERB_MAP
             if any(n in have for n in names)]
    return "\n".join(lines)


def role_text(tool_names: list[str]) -> str:
    return ROLE.format(verbs=verbs_said(tool_names))


def handbook_text() -> str:
    """The three chapters as the repo renders them, under family names, with the policy said once."""
    parts = []
    for i, analyst in enumerate(handbook.ANALYSTS, 1):
        chapter = handbook.chapter_text(analyst)
        body, sep, _policy = chapter.partition("\n\n6. POLICY\n")
        assert sep, f"chapter {analyst}: the policy section moved"
        _title, _, rest = body.partition("\n")
        parts.append(f"CHAPTER {i} — {FAMILY[analyst]}\n{rest}")
    return "\n\n".join(parts) + "\n\nPOLICY — WHAT THE DESK DOES NOT SAY\n" + handbook.policy_text()


def tools() -> list[dict]:
    return build_meta_registry().schemas(faces.FACE_META_AGENT)


# ── a SYNTHETIC desk, in the shape services/briefing.for_question returns ──────────────────────────

AS_OF = "2026-09-11"
HOLDINGS = [("AAPL", "Technology", "equity"), ("MSFT", "Technology", "equity"), ("NVDA", "Technology", "equity"),
            ("AMZN", "Consumer_Discretionary", "equity"), ("GOOGL", "Communication_Services", "equity"),
            ("JPM", "Financials", "equity"), ("XOM", "Energy", "equity"), ("LLY", "Healthcare", "equity"),
            ("TLT", "Fixed_Income", "etf"), ("HYG", "Fixed_Income", "etf")]
COMPANIES = {  # ticker -> (name, sector, fiscal_year_ends, latest_period_end, 10-K filed, 10-Q filed)
    "AAPL": ("Apple Inc.", "Technology", "Sep 27", "2026-06-27", "2025-10-31", "2026-08-01"),
    "MSFT": ("Microsoft Corporation", "Technology", "Jun 30", "2026-06-30", "2026-07-30", "2026-04-29"),
    "NVDA": ("NVIDIA Corporation", "Technology", "Jan 25", "2026-07-26", "2026-02-25", "2026-08-27"),
    "AMZN": ("Amazon.com, Inc.", "Consumer_Discretionary", "Dec 31", "2026-06-30", "2026-02-06", "2026-08-01"),
    "GOOGL": ("Alphabet Inc.", "Communication_Services", "Dec 31", "2026-06-30", "2026-02-04", "2026-07-24"),
    "JPM": ("JPMorgan Chase & Co.", "Financials", "Dec 31", "2026-06-30", "2026-02-13", "2026-08-04"),
    "XOM": ("Exxon Mobil Corporation", "Energy", "Dec 31", "2026-06-30", "2026-02-18", "2026-08-04"),
    "LLY": ("Eli Lilly and Company", "Healthcare", "Dec 31", "2026-06-30", "2026-02-19", "2026-08-07"),
    "KO": ("The Coca-Cola Company", "Consumer_Staples", "Dec 31", "2026-06-26", "2026-02-20", "2026-07-28"),
}
NOT_FOR_FINANCIALS = sorted(n for n, f in fm.FORMULAS.items() if f.not_for_financials is not None)
LINES_ENDING_EARLY = {
    "NVDA": {"revenue": {"ends": "2022-01-30", "continues_as": "total_revenues", "through": "2026-07-26",
                         "read_as_one_line": True,
                         "because": "the issuer moved the line to another tag; the two tags are one line"}},
    "KO": {"revenue": {"ends": "2018-12-31", "continues_as": "total_revenues", "through": "2026-06-26",
                       "read_as_one_line": True,
                       "because": "the issuer moved the line to another tag; the two tags are one line"}},
}
ITEMS = ["Item 1", "Item 1A", "Item 2", "Item 7", "Item 7A", "Item 8"]
CHECKS = sorted({"Gross exposure", "One-day loss", "Volatility, 30 sessions",
                 *(f"Issuer weight: {t}" for t, _s, _a in HOLDINGS),
                 *(f"Sector weight: {s}" for _t, s, _a in HOLDINGS)})


def _issuer(tk: str) -> dict:
    name, sector, fy_end, latest, k, q = COMPANIES[tk]
    held = [{"portfolio_id": "port_001", "as_of": AS_OF}] if tk in {t for t, _s, _a in HOLDINGS} else []
    return {"name": name, "status": "ready", "sector": sector, "fiscal_year_end": fy_end, "latest_period_end": latest,
            "filings": {"10-K": {"latest": k}, "10-Q": {"latest": q}},
            "prices": {"from": "2023-09-11", "to": AS_OF}, "held_in": held,
            "coverage": {"lines_ending_early": LINES_ENDING_EARLY.get(tk),
                         "measures_not_computable": ({n: "not for a financial issuer" for n in NOT_FOR_FINANCIALS}
                                                     if sector == "Financials" else {}),
                         "items_indexed": ITEMS}}


def _portfolio() -> dict:
    return {"name": "US Growth & Income Portfolio",
            "runs": {"latest": {"id": "run_7f3a9c21d4e8", "as_of": AS_OF},
                     "prev": {"id": "run_2b8e5d10a6c3", "as_of": "2026-09-10"}},
            "positions_as_of": AS_OF,
            "holdings": [{"ticker": t, "sector": s, "asset_class": a} for t, s, a in HOLDINGS],
            "checks": CHECKS}


def subjects_in(text: str) -> dict:
    """services/briefing.subjects_in, over the synthetic company list (same regexes, same caps)."""
    words_upper = set(briefing_svc._TICKER.findall(text or ""))
    lower = (text or "").lower()
    tickers = [t for t in COMPANIES if t in words_upper]
    for t, (name, *_rest) in COMPANIES.items():
        if t in tickers:
            continue
        for w in re.findall(r"[A-Za-z][A-Za-z']{3,}", name):
            if w.lower() not in briefing_svc._NAME_STOP and re.search(r"\b" + re.escape(w.lower()) + r"(?:'s)?\b", lower):
                tickers.append(t)
                break
    portfolios = re.findall(r"\bport_[A-Za-z0-9]+\b", text or "")
    if not portfolios and (set(re.findall(r"[a-z]+", lower)) & briefing_svc._BOOK_WORDS):
        portfolios = ["port_001"]
    runs = re.findall(r"\b(?:run|calc)_[A-Za-z0-9]+\b", text or "")
    return {"tickers": tickers[:6], "portfolios": portfolios[:3], "runs": runs[:3]}


def desk_for(question: str) -> dict:
    subs = subjects_in(question)
    return {"subjects": subs,
            "portfolios": {p: _portfolio() for p in subs["portfolios"]},
            "issuers": {t: _issuer(t) for t in subs["tickers"]},
            "desk": {"issuers_on_desk": sorted(COMPANIES), "issuers_preparing": []}}


QUESTIONS = [
    # the dock's own suggestions (apps/web/app/components/analyst/Dock.tsx)
    ("Q01", "What is my largest exposure right now?"),
    ("Q02", "Why did the book move on the last run?"),
    ("Q03", "Which limits am I closest to breaching, and how much room is left on each?"),
    ("Q04", "Put MSFT, AAPL and GOOGL 2025 full-year net income side by side in a table."),
    ("Q05", "Add up AAPL's debt — long-term, current portion, short-term — then net the cash off so I have net debt."),
    ("Q06", "How has NVDA's revenue grown over the last four quarters?"),
    ("Q07", "Search the web for the latest news on LLY from the past week and tell me what happened."),
    # the handbook's own topics (analytics/handbook: a hypothetical trade, liquidity, volatility, leverage, absent)
    ("Q08", "If I sold half of my largest position, what would the book look like and which checks would change?"),
    ("Q09", "How many days would it take to sell each of my holdings if I traded 20% of its average daily volume?"),
    ("Q10", "Has MSFT become more volatile lately, or is it just the market?"),
    ("Q11", "Is JPM more levered than it was a year ago?"),
    ("Q12", "What is the book's value at risk, and how much would it lose in a stress scenario?"),
    ("Q13", "How does TSLA's net margin compare with AAPL's over the last fiscal year?"),
    ("Q14", "Which of my holdings has the weakest 12-1 momentum, and how big is it in the book?"),
]


def prompt_for(qid: str, question: str, tool_list: list[dict]) -> str:
    names = [t["function"]["name"] for t in tool_list]
    return "\n\n".join([
        "===== SYSTEM MESSAGE 1 (role) =====\n" + role_text(names),
        "===== SYSTEM MESSAGE 2 (handbook) =====\n" + HANDBOOK_TAG + "\n" + handbook_text() + "\n</handbook>",
        "===== SYSTEM MESSAGE 3 (desk) =====\n" + DESK_TAG + "\n"
        + json.dumps(desk_for(question), ensure_ascii=False, indent=1) + "\n</desk>",
        "===== TOOLS (function schemas, exactly as the provider receives them) =====\n"
        + json.dumps(tool_list, ensure_ascii=False, indent=1),
        f"===== USER MESSAGE ({qid}) =====\n" + question,
    ])


def main() -> None:
    tool_list = tools()
    names = [t["function"]["name"] for t in tool_list]
    role, book = role_text(names), handbook_text()
    (OUT / "role.txt").write_text(role)
    (OUT / "handbook.txt").write_text(book)
    (OUT / "tools.json").write_text(json.dumps(tool_list, ensure_ascii=False, indent=1))
    rows = []
    for qid, q in QUESTIONS:
        desk = desk_for(q)
        (OUT / "prompts" / f"{qid}.txt").write_text(prompt_for(qid, q, tool_list))
        messages = [{"role": "system", "content": role},
                    {"role": "system", "content": HANDBOOK_TAG + "\n" + book + "\n</handbook>"},
                    {"role": "system", "content": DESK_TAG + "\n" + json.dumps(desk, ensure_ascii=False) + "\n</desk>"},
                    {"role": "user", "content": q}]
        rows.append((qid, cb.count_prompt(messages, tool_list), cb.count_tokens(json.dumps(desk, ensure_ascii=False)),
                     desk["subjects"]))
    (OUT / "questions.json").write_text(json.dumps([{"qid": q, "question": t} for q, t in QUESTIONS], indent=1))
    print("served verbs:", ", ".join(names))
    print(f"role            {len(role):>6} chars {cb.count_tokens(role):>6} tok")
    print(f"handbook        {len(book):>6} chars {cb.count_tokens(book):>6} tok")
    print(f"tool schemas    {len(json.dumps(tool_list)):>6} chars {cb.count_tokens(json.dumps(tool_list)):>6} tok")
    print("per question: first-completion prompt tokens (everything), desk tokens, subjects found")
    for qid, total, desk_tok, subs in rows:
        print(f"  {qid}  total {total:>6}  desk {desk_tok:>5}  {subs}")


if __name__ == "__main__":
    main()
