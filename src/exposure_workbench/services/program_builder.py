"""The program builder (V33): a decision-level evidence request, compiled.

The analyst says WHAT — subjects, the desk's names for what it wants, a window,
a comparison. This turns that into a program the executor types and runs. It
is deterministic: the same request is the same program. What it cannot say it
says so (NotExpressible, with the nearest names), and the evidence broker hands
that, with the analyst's own words, to a program writer that sees the language's
signatures. Copying and editing an example program is where the round's errors
entered (Q15 kept an example's 0.25 when the user said 20%); here nothing is
copied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from exposure_workbench.analytics import skill
from exposure_workbench.services import concept_mapping as cm
from exposure_workbench.services import name_table as nt
from exposure_workbench.services import program_service as ps


class NotExpressible(Exception):
    def __init__(self, reason: str, nearest: list | None = None):
        super().__init__(reason)
        self.reason = reason
        self.nearest = nearest or []


RUN_TABLES = {
    "issuer_exposures": ("weight", "market_value", "contribution", "daily_pnl", "daily_return", "weight_change"),
    "sector_exposures": ("weight", "market_value", "weight_change"),
    "limit_checks": ("current_value", "warning_level", "breach_level"),
    "risk_alerts": ("current_value", "limit_value", "utilization"),
    "factor_attributions": ("beta", "contribution", "factor_return", "r_squared"),
}
# the standard book read: what each name weighs and is worth, and where each check
# stands against its tiers. Sized by what the question means, never by what fits —
# the digest owns the budget (evidence_broker._fit).
BOOK_DEFAULT = ("issuer_exposures.weight", "issuer_exposures.market_value", "limit_checks.current_value",
                "limit_checks.warning_level", "limit_checks.breach_level")
_DEFAULT_KEY = {"price.adv": "dollars", "price.drawdown": "depth", "price.beta": "beta"}
_SPANS = ("1m", "3m", "6m", "1y", "3y")


@dataclass
class Window:
    months: int | None = None
    last_n: int | None = None
    at: str | None = None
    span: str | None = None
    window_days: int | None = None
    vs_prev: bool = False
    benchmark: str | None = None
    days: int | None = None


def parse_window(text: str | None) -> Window:
    w = Window()
    t = (text or "").lower().strip()
    if not t:
        return w
    if re.search(r"\bprev(ious)?\b|prior run|last run", t):
        w.vs_prev = True
    m = re.search(r"\bat\s+(\d{4}-\d{2}-\d{2})", t) or re.search(r"\bas of\s+(\d{4}-\d{2}-\d{2})", t)
    if m:
        w.at = m.group(1)
    m = re.search(r"\blast[_ ]?n?\s*(\d+)\s*(quarters?|years?|fiscal years?|periods?|windows?|annual)?", t) \
        or re.search(r"(\d+)\s*(quarters?|fiscal years?|years?)\b", t)
    if m:
        n, unit = int(m.group(1)), (m.group(2) or "")
        if "quarter" in unit:
            w.last_n, w.months = n, 3
        elif "year" in unit or "annual" in unit or "period" in unit or "window" in unit or not unit:
            if re.search(r"\b\d+\s*[my]\b", t) and not unit:
                pass
            else:
                w.last_n, w.months = n, 12
    m = re.search(r"\b(\d+)\s*m(?:onths?)?\b", t)
    if m and not w.last_n:
        w.months = int(m.group(1))
    if re.search(r"\bttm\b|trailing twelve|trailing 12", t):
        w.months = 12
    m = re.search(r"\b(1m|3m|6m|1y|3y)\b", t)
    if m:
        w.span = m.group(1)
    m = re.search(r"\b(\d+)\s*(?:d|days?|sessions?)\b", t)
    if m:
        w.window_days = int(m.group(1))
        w.days = int(m.group(1))
    if re.search(r"two weeks|fortnight", t):
        w.days = 14
    m = re.search(r"\b(?:vs\.?|versus|against|relative to)\s+([A-Za-z]{2,5})\b", text or "")
    if m and m.group(1).upper() not in ("PREV", "PRIOR", "THE", "LAST"):
        w.benchmark = m.group(1).upper()
    return w


def classify(name: str) -> tuple:
    """('method', spec, key) | ('metric', name) | ('column', table, col) | ('figure', key) | ('book',) | ('scenario', text)"""
    n = (name or "").strip()
    low = n.lower()
    if low == "book":
        return ("book",)
    if low.startswith("scenario:"):
        return ("scenario", n.split(":", 1)[1].strip())
    base, _, key = n.partition(":")
    base, key = base.strip(), key.strip()
    if base in skill.METHODS:
        return ("method", skill.METHODS[base], key or None)
    if key in skill.METHODS:
        # "issuer_profitability: roe" — the analyst wrote the domain before the name (V33C Q12)
        return ("method", skill.METHODS[key], None)
    if base in ("filings", "news", "prepare"):
        raise NotExpressible(f"{n!r} is read by the desk's tools, not computed by a program", [])
    if n in cm.SUPPORTED_METRICS:
        return ("metric", n)
    parts = n.split(".")
    if len(parts) == 2 and parts[0] in RUN_TABLES and parts[1] in RUN_TABLES[parts[0]]:
        return ("column", parts[0], parts[1])
    if len(parts) == 2 and parts[0] == "exposure_metrics":
        return ("figure", n)
    if len(parts) == 3 and parts[0] in RUN_TABLES:
        return ("figure", n)
    nearest = [r["name"] for r in nt.nearest(base, n=4) if r]
    raise NotExpressible(f"{n!r} is not a name this desk holds", nearest)


def _name(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]+", "_", s).strip("_").lower()
    if not s or s[0].isdigit():
        s = "n_" + s
    return s[:60]


_OPS = {"-": "sub", "+": "add", "*": "mul", "/": "div"}
# `room = limit_checks.warning_level - limit_checks.current_value`: an optional
# name, then one operator over two operands. Round G's Q11 wrote the name and the
# whole left side was read as an operand; Q15 needed mv / (adv × 0.2) and one
# operator per line could not say it — a named line, used by the next, can.
_DERIVE = re.compile(r"^\s*(?:([A-Za-z_][A-Za-z0-9_]*)\s*=\s*)?(.+?)\s*([-+*/])\s*(.+?)\s*$")


def build(item: dict, held_in: dict | None = None, skipped: list | None = None) -> dict:
    """The program for one request.

    `held_in` = {ticker: [port_…]} from the briefing: a book want with only a
    ticker named reads the book that holds it (V33C Q01 asked AMZN's weight and
    the compiled program said run(portfolio="AMZN")).

    `skipped` receives one entry per want (or comparison, or derivation) this
    desk cannot express. A name it does not know costs that name and nothing
    else: V33C Q15 named `issuer_exposures.ticker` beside two it does know and
    lost the whole item, `compare: rank` included, so the answer had no ordering
    to rest its superlatives on. NotExpressible is raised only when NOTHING is
    expressible.
    """
    skipped = skipped if skipped is not None else []
    subjects = [str(s).strip() for s in (item.get("subjects") or []) if str(s).strip()]
    want = [str(w).strip() for w in (item.get("want") or []) if str(w).strip()]
    if not subjects or not want:
        raise NotExpressible("a request names at least one subject and one thing wanted")
    tickers = [s.upper() for s in subjects if not s.startswith(("port_", "run_", "calc_"))]
    ports = [s for s in subjects if s.startswith("port_")]
    runs = [s for s in subjects if s.startswith(("run_", "calc_"))]
    win = parse_window(f"{item.get('window') or ''} {item.get('ask') or ''}")
    compare = (item.get("compare") or "").strip().lower()

    let: list[dict] = []
    returns: list[str] = []
    names: set[str] = set()

    def bind(name: str, expr: dict, ret: bool = True) -> str:
        n = _name(name)
        i = 2
        while n in names:
            n = f"{_name(name)}_{i}"
            i += 1
        names.add(n)
        let.append({"name": n, "expr": expr})
        if ret:
            returns.append(n)
        return n

    run_nodes: dict[str, str] = {}

    def run_of(pid: str, which: str | None = None) -> str:
        key = f"{pid}:{which or 'latest'}"
        if key not in run_nodes:
            expr = {"fn": "run", "portfolio": pid, **({"which": which} if which else {})}
            run_nodes[key] = bind(f"run_{pid}{'_' + which if which else ''}", expr, ret=False)
        return run_nodes[key]

    scenario_node: str | None = None
    vectors: list[str] = []          # vector nodes a rank/filter applies to
    series: list[str] = []           # series nodes a change applies to
    scalars_by_want: dict[str, dict[str, str]] = {}   # want -> {subject -> node}

    def skip(w: str, e: NotExpressible) -> None:
        skipped.append({"want": w, "reason": e.reason, "nearest": list(e.nearest or [])})

    expanded: list[str] = []
    for w in want:
        try:
            k = classify(w)
        except NotExpressible as e:
            skip(w, e)
            continue
        if k[0] == "book":
            expanded += list(BOOK_DEFAULT)
        elif k[0] == "scenario":
            trades = re.findall(r"(sell|buy)\s+([A-Za-z.]{1,6})\s+([0-9.]+)", k[1], flags=re.IGNORECASE)
            if not trades or not ports:
                skip(w, NotExpressible("a scenario is 'scenario:sell <T> <fraction>' / 'scenario:buy <T> <weight>' on a portfolio"))
                continue
            base = run_of(ports[0])
            cur = base
            for side, tk, amt in trades:
                if side.lower() == "sell":
                    cur = bind(f"after_sell_{tk}", {"fn": "sell", "run": f"${cur}", "sales": [{"ticker": tk.upper(), "fraction": float(amt)}]})
                else:
                    cur = bind(f"after_buy_{tk}", {"fn": "buy", "run": f"${cur}", "buys": [{"ticker": tk.upper(), "weight": float(amt)}]})
            scenario_node = cur
        else:
            expanded.append(w)

    nodes_of_want: dict[str, list[str]] = {}
    for w in expanded:
        before = len(let)
        try:
            k = classify(w)
            if k[0] == "method":
                spec, key = k[1], k[2]
                params: dict = {}
                if spec.subject_kind in ("issuer",):
                    if win.months:
                        params["months"] = win.months
                    if win.at:
                        params["at"] = win.at
                    if win.last_n:
                        params["last_n"] = win.last_n
                    subs = tickers
                elif spec.subject_kind == "price":
                    props = spec.params_schema.get("properties", {})
                    if "window_days" in props and win.window_days:
                        params["window_days"] = win.window_days
                    if "window" in props and win.span:
                        params["window"] = win.span
                    if "benchmark" in props and win.benchmark:
                        params["benchmark"] = win.benchmark
                    key = key or _DEFAULT_KEY.get(spec.name)
                    subs = tickers
                elif spec.subject_kind == "run":
                    subs = [f"${scenario_node}"] if scenario_node else (runs or [run_of(p) for p in ports])
                    subs = [s if s.startswith("$") or s.startswith(("run_", "calc_")) else f"${s}" for s in subs]
                else:   # portfolio
                    if spec.name == "book.explain_episode":
                        raise NotExpressible("book.explain_episode needs a peak and a trough: ask for the worst drawdown episode and its explanation in words (`ask`)")
                    subs = ports
                    if spec.name == "book.drawdown_episodes" and win.span:
                        params["span"] = win.span
                if not subs:
                    raise NotExpressible(f"{spec.name} is a {spec.subject_kind} method; name a {spec.subject_kind} in subjects")
                if len(subs) > 1 and spec.subject_kind in ("issuer", "price"):
                    if win.last_n and spec.subject_kind == "issuer":
                        ents = {}
                        for t in subs:
                            s_node = bind(f"{spec.name}_{t}", {"fn": "method", "name": spec.name, "subject": t, "params": params, **({"key": key} if key else {})})
                            series.append(s_node)
                            ents[t] = "$" + bind(f"{spec.name}_{t}_latest", {"fn": "latest", "of": f"${s_node}"}, ret=False)
                        vectors.append(bind(f"{spec.name}_latest", {"fn": "vector", "entries": ents}))
                    else:
                        expr = {"fn": "method", "name": spec.name, "subject": subs, **({"params": params} if params else {}), **({"key": key} if key else {})}
                        vectors.append(bind(spec.name, expr))
                else:
                    for t in subs:
                        label = t.lstrip("$")
                        expr = {"fn": "method", "name": spec.name, "subject": t, **({"params": params} if params else {}), **({"key": key} if key else {})}
                        n = bind(f"{spec.name}_{label}", expr)
                        if win.last_n and spec.subject_kind == "issuer":
                            series.append(n)
                        elif spec.subject_kind in ("issuer", "price"):
                            scalars_by_want.setdefault(spec.name, {})[t] = n
            elif k[0] == "metric":
                metric = k[1]
                if not tickers:
                    raise NotExpressible(f"{metric} is a filed line of an issuer; name a ticker in subjects")
                ents = {}
                for t in tickers:
                    expr = {"fn": "fundamentals", "ticker": t, "metric": metric}
                    if win.months:
                        expr["months"] = win.months
                    if win.at:
                        expr["at"] = win.at
                    if win.last_n:
                        expr["last_n"] = win.last_n
                    n = bind(f"{metric}_{t}", expr)
                    if win.last_n:
                        series.append(n)
                        if len(tickers) > 1:
                            ents[t] = "$" + bind(f"{metric}_{t}_latest", {"fn": "latest", "of": f"${n}"}, ret=False)
                    else:
                        scalars_by_want.setdefault(metric, {})[t] = n
                        if len(tickers) > 1:
                            ents[t] = f"${n}"
                if len(tickers) > 1:
                    vectors.append(bind(f"{metric}_across", {"fn": "vector", "entries": ents}))
            elif k[0] in ("column", "figure"):
                if scenario_node:
                    if k[0] == "column":
                        vectors.append(bind(f"{k[1]}_{k[2]}_after", {"fn": "column", "run": f"${scenario_node}", "table": k[1], "col": k[2]}))
                        base = run_of(ports[0])
                        vectors.append(bind(f"{k[1]}_{k[2]}_before", {"fn": "column", "run": f"${base}", "table": k[1], "col": k[2]}))
                    else:
                        bind(f"{k[1]}_after", {"fn": "pick", "of": f"${scenario_node}", "key": k[1]})
                        bind(f"{k[1]}_before", {"fn": "pick", "of": f"${run_of(ports[0])}", "key": k[1]})
                    continue
                targets = runs or ports
                if not targets and tickers and held_in:
                    targets = sorted({pid for t in tickers for pid in (held_in.get(t) or held_in.get(t.upper()) or [])})
                if not targets:
                    raise NotExpressible(f"{w} is a figure of a book's run; name the port_… that holds the name in subjects "
                                         f"(the briefing's held_in says which)")
                for tgt in targets:
                    r = tgt if tgt.startswith(("run_", "calc_")) else f"${run_of(tgt)}"
                    if k[0] == "column":
                        n = bind(f"{k[1]}_{k[2]}", {"fn": "column", "run": r, "table": k[1], "col": k[2]})
                        vectors.append(n)
                        if win.vs_prev and not tgt.startswith(("run_", "calc_")):
                            prev = bind(f"{k[1]}_{k[2]}_prev", {"fn": "column", "run": f"${run_of(tgt, 'prev')}", "table": k[1], "col": k[2]})
                            chg = bind(f"{k[1]}_{k[2]}_change", {"fn": "sub", "a": f"${n}", "b": f"${prev}"})
                            vectors.append(chg)
                    else:
                        n = bind(k[1].replace(".", "_"), {"fn": "pick", "of": r, "key": k[1]})
                        if win.vs_prev and not tgt.startswith(("run_", "calc_")):
                            prev = bind(k[1].replace(".", "_") + "_prev", {"fn": "pick", "of": f"${run_of(tgt, 'prev')}", "key": k[1]})
                            bind(k[1].replace(".", "_") + "_change", {"fn": "sub", "a": f"${n}", "b": f"${prev}"})

        except NotExpressible as e:
            skip(w, e)
            continue
        nodes_of_want[w] = [b["name"] for b in let[before:]]

    # comparisons
    try:
        _compare(compare, win, tickers, bind, classify, vectors, series, scalars_by_want)
    except NotExpressible as e:
        skip(f"compare:{compare}", e)

    # derivations: one line of arithmetic over the names already asked for
    for line in (item.get("derive") or []):
        try:
            _derive(str(line), bind, nodes_of_want, let)
        except NotExpressible as e:
            skip(f"derive:{line}", e)

    if not returns:
        first = skipped[0] if skipped else None
        raise NotExpressible(first["reason"] if first else "nothing in this request compiled to a program",
                             (first or {}).get("nearest") or [])
    program = {"let": let, "return": returns}
    problems = ps.typecheck(program)
    if problems:
        raise NotExpressible("the request compiled to a program the language refuses: " + (problems[0].get("fix") or problems[0].get("detail") or problems[0]["reason"]),
                             [p for p in problems[:3]])
    return program


def _operand(side: str, nodes_of_want: dict[str, list[str]], let: list[dict]):
    """One side of a derivation: a number, or the node a named want produced."""
    side = side.strip()
    try:
        return float(side)
    except ValueError:
        pass
    for w, ns in nodes_of_want.items():
        if w == side or w.split(":", 1)[0] == side:
            settled = [n for n in ns if next(b for b in let if b["name"] == n)["expr"].get("fn") != "run"]
            if settled:
                return "$" + settled[-1]
    hint = ""
    if any(op in side for op in "+-*/") and not side.replace(".", "").replace("-", "").isdigit():
        hint = " — one operator per line: name a line (`adv20 = price.adv * 0.2`) and use its name in the next"
    raise NotExpressible(f"{side!r} is not one of the names this request asked for or derived above, and is not a number{hint}",
                         sorted(nodes_of_want))


def _derive(line: str, bind, nodes_of_want: dict[str, list[str]], let: list[dict]) -> None:
    m = _DERIVE.match(line)
    if not m:
        raise NotExpressible(f"a derivation is '<name> = <name> <+-*/> <name|number>'; got {line!r}")
    given, left, op, right = m.groups()
    a, b = _operand(left, nodes_of_want, let), _operand(right, nodes_of_want, let)
    if not isinstance(a, str) and not isinstance(b, str):
        raise NotExpressible("a derivation works over the desk's figures: at least one side names a want")
    node = bind(_name(given) if given else _name(line), {"fn": _OPS[op], "a": a, "b": b})
    # the line's name is a name the next line may use
    nodes_of_want[given or line] = [node]


def _compare(compare, win, tickers, bind, classify, vectors, series, scalars_by_want) -> None:
    if compare.startswith("rank"):
        direction = "lowest" if "low" in compare or "least" in compare or "smallest" in compare else "highest"
        if not vectors:
            # several scalars across subjects gathered into one vector
            for wname, by_sub in scalars_by_want.items():
                if len(by_sub) > 1:
                    vectors.append(bind(f"{wname}_across", {"fn": "vector", "entries": {t.lstrip('$'): f"${n}" for t, n in by_sub.items()}}))
        if not vectors:
            raise NotExpressible("rank needs several figures: several subjects, a run column, or a series (last_n)")
        for vn in vectors:
            bind(f"{vn}_ranked", {"fn": "rank", "of": f"${vn}", "direction": direction})
    elif compare.startswith("change"):
        if series:
            for sn in series:
                bind(f"{sn}_yoy", {"fn": "yoy", "of": f"${sn}"})
        elif not win.vs_prev:
            raise NotExpressible("change needs a history: a window like 'last 5 years' (a series) or 'vs prev run' for the book")
    elif compare.startswith("share_of:"):
        denom_name = compare.split(":", 1)[1].strip()
        kd = classify(denom_name)
        if kd[0] not in ("metric", "method") or not tickers:
            raise NotExpressible("share_of:<name> divides each wanted figure by that issuer figure")
        for t in tickers:
            if kd[0] == "metric":
                dexpr = {"fn": "fundamentals", "ticker": t, "metric": kd[1], **({"months": win.months} if win.months else {}), **({"last_n": win.last_n} if win.last_n else {})}
            else:
                dexpr = {"fn": "method", "name": kd[1].name, "subject": t, **({"params": {"months": win.months}} if win.months else {})}
            d = bind(f"{denom_name}_{t}", dexpr, ret=False)
            for wname, by_sub in scalars_by_want.items():
                if t in by_sub:
                    bind(f"{wname}_share_{t}", {"fn": "div", "a": f"${by_sub[t]}", "b": f"${d}"})
            for sn in [s for s in series if s.endswith("_" + t.lower())]:
                bind(f"{sn}_share", {"fn": "div", "a": f"${sn}", "b": f"${d}"})
    elif compare.startswith("filter:"):
        m = re.match(r"filter:\s*(>=|<=|==|!=|>|<)\s*([0-9.]+)", compare)
        if not m or not vectors:
            raise NotExpressible("filter is 'filter:<op><level>' over a vector (several subjects or a run column)")
        for vn in vectors:
            bind(f"{vn}_where", {"fn": "filter", "of": f"${vn}", "op": m.group(1), "level": float(m.group(2))})
    elif compare and not compare.startswith("versus"):
        raise NotExpressible(f"compare {compare!r} is not one of rank | change | versus | share_of:<name> | filter:<op><level>")
