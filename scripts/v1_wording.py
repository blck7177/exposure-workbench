"""Generate docs/WORDING_V1.md: every sentence V1 sends to a model, read off the
live objects, for one review before the first measured round (the V37 §5 rule).

    .venv/bin/python scripts/v1_wording.py            # writes docs/WORDING_V1.md
    .venv/bin/python scripts/v1_wording.py --check    # exits 1 when the sheet is stale

Nothing is copied by hand: the sheet is rendered from the modules the turn reads,
so a wording change shows up here as a diff.
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

from exposure_workbench.agents import delegation, meta_agent, repeats, research_session, sub_analyst
from exposure_workbench.analytics import handbook, registry
from exposure_workbench.services import answer_check, facts, style_guide
from exposure_workbench.tools import faces, primitives
from exposure_workbench.utils import json as ejson

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "WORDING_V1.md"


def _block(text: str) -> str:
    return "```text\n" + text.strip() + "\n```\n"


# ── what a loop or a check SAYS, read off its source ──────────────────────────
# A refusal is built where it is refused, so its sentence is an f-string inside a
# function and not an object to import. The sheet reads the source instead: every
# string a named function says (its docstring aside), and every `way_out` a check
# gives with the reason it goes with — unparsed, so a template shows its slots.

_SAID_KEYS = ("detail", "repeated", "way_out", "refused")


def _is_text(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_text(node.left) or _is_text(node.right)
    if isinstance(node, ast.IfExp):
        return _is_text(node.body) or _is_text(node.orelse)
    return False


def _function(module, name: str) -> ast.AST:
    tree = ast.parse(inspect.getsource(module))
    return next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def said_under_keys(module, function: str | None = None, keys: tuple[str, ...] = _SAID_KEYS) -> list[str]:
    """Every text a dict in `module` (or one function of it) carries under one of `keys`,
    each with the reason or error it goes with, in source order."""
    root = _function(module, function) if function else ast.parse(inspect.getsource(module))
    out: list[str] = []
    for d in sorted((n for n in ast.walk(root) if isinstance(n, ast.Dict)), key=lambda n: (n.lineno, n.col_offset)):
        named = {k.value: v for k, v in zip(d.keys, d.values) if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        code = next((named[k].value if isinstance(named[k], ast.Constant) else ast.unparse(named[k])
                     for k in ("reason", "error") if k in named), None)
        for key in keys:
            if key in named and _is_text(named[key]):
                out.append((f"[{code}] " if code else "") + ast.unparse(named[key]))
    return list(dict.fromkeys(out))


def said_in(module, function: str) -> list[str]:
    """Every string a function builds (its docstring aside), in source order."""
    fn = _function(module, function)
    doc = ast.get_docstring(fn, clean=False)
    import re
    out = []
    for n in sorted((n for n in ast.walk(fn) if isinstance(n, (ast.JoinedStr, ast.Constant))),
                    key=lambda n: (n.lineno, n.col_offset)):
        if isinstance(n, ast.JoinedStr):
            # a SENTENCE has four words of its own: the glue between two slots does not
            own = " ".join(v.value for v in n.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
        elif isinstance(n.value, str) and n.value != doc:
            own = n.value
        else:
            continue
        if len(re.findall(r"[A-Za-z]{2,}", own)) >= 4:
            out.append(ast.unparse(n))
    # a constant inside an f-string is that f-string's, not a sentence of its own
    sentences = list(dict.fromkeys(out))
    return [s for s in sentences if not any(s != o and s.strip("'\"") in o for o in sentences)]


def render() -> str:
    parts = ["# V1 措辞过目单（由 scripts/v1_wording.py 生成，勿手改）\n",
             "V1 发给模型的全部文字，从运行时对象与源码渲染。分九组：主分析师、分析师角色说明、工具描述、登记簿词表、"
             "登记簿读法与工具说明、手册三章、研究简报、风格指南、拒绝与提示。旧架构的文字（14 个域、程序语言说明、两份图例、READINGS、DESK_RULES）已随退役删除。\n"]

    parts += ["\n## 1. 主分析师\n", "### 1.1 角色说明 `meta_agent._ROLE`（其后引入风格指南全文，见第 8 组）\n", _block(meta_agent._ROLE),
              "### 1.2 四个块的标签（`<state>` 每次 completion 前由记录重新渲染）\n",
              _block("\n".join((meta_agent.BRIEFING_TAG, meta_agent.ROSTER_TAG, meta_agent.READINGS_TAG, meta_agent.STATE_TAG))),
              "### 1.3 三个工具的描述\n"]
    for tool in (delegation.ASK_TOOL, delegation.OPEN_TOOL, meta_agent.REPAIR_TOOL):
        f = tool["function"]
        parts += [f"**{f['name']}**\n", _block(f["description"])]
    parts += ["### 1.4 提示句\n", _block("\n".join((meta_agent._WRITE_OR_ASK, meta_agent._REPAIR_ONLY)))]
    parts += ["### 1.5 名册 `handbook.roster()`（三条）\n"]
    for r in handbook.roster():
        parts += [f"**{r['analyst']}** — {r['answers']}\n", _block("can be asked:\n- " + "\n- ".join(r["can_be_asked"])
                                                                   + "\nabsent:\n- " + "\n- ".join(f"{a['what']} ({a['why']})" for a in r["absent"]))]
    parts += ["### 1.6 含义层 `handbook.meaning_layer()`\n", _block(handbook.meaning_layer())]

    parts += ["\n## 2. 分析师角色说明 `sub_analyst._SYSTEM`（三位共用，标题与政策 id 代入；其后引入风格指南全文，再接本章手册）\n",
              _block(sub_analyst._SYSTEM.format(title="<the issuer analyst | the market analyst | the portfolio risk manager>",
                                                policies=sub_analyst._POLICIES)),
              "块标签与提示句（`<prior>` 只在 follow_up_of 指向本 session 的任务时出现）：\n",
              _block("\n".join((sub_analyst.TASK_TAG, sub_analyst.COVERAGE_TAG, sub_analyst.PRIOR_TAG, sub_analyst._WRITE_OR_ASK))),
              "`submit` 的描述：\n", _block(delegation.SUBMIT_TOOL["function"]["description"])]

    parts += ["\n## 3. 工具描述（tools/primitives，11 个动词；每面只见自己的）\n"]
    seen: set[str] = set()
    for face in primitives.FACES:
        for name, tool in primitives.build_analyst_registry(face).tools.items():
            if name in seen:
                continue
            seen.add(name)
            on = [f for f in primitives.FACES if name in faces.ANALYST_FACES[f]]
            parts += [f"**{name}**（面：{', '.join(on)}）\n", _block(tool.description)]
    parts += ["每个动词都有的 `why` 参数：\n", _block(primitives._WHY["description"])]

    parts += ["\n## 4. 登记簿词表（事实 `means` 的全部用词，analytics/registry）\n"]
    for title, table in (("方向 DIRECTION", registry.DIRECTION), ("状态 STATUS", registry.STATUS), ("依据 BASIS", registry.BASIS),
                         ("限制 FLAGS", registry.FLAGS), ("缺席原因 ABSENCE_REASONS", registry.ABSENCE_REASONS)):
        parts += [f"**{title}**\n", _block("\n".join(f"{k}: {v}" for k, v in table.items()))]
    parts += ["**渲染时拼出的词**：位次 `3rd highest of 8`；变化 `up / down / flat`；组成 `built on X in place of Y`、"
              "`missing at this date: …`、`never filed by this issuer: …`、`overlapping, not added: …`；不可单独引用 `not quotable on its own`；"
              f"序列被压缩时行尾 `({facts.SERIES_SHOWN})`。\n",
              "**三条常驻政策缺席**\n", _block("\n".join(f"{p['id']}: {p['text']}" for p in registry.POLICY_ABSENCES))]

    parts += ["\n## 5. 登记簿读法与因子工具\n", "**READS**\n",
              _block("\n".join(f"{registry.reads_as(k)}: {v}" for k, v in registry.READS.items())),
              "**INSTRUMENTS**\n", _block("\n".join(f"{t} is {what}, standing for {risk}" for t, what, risk in registry.INSTRUMENTS))]

    parts += ["\n## 6. 手册三章 `handbook.chapter_text()`\n"]
    for analyst in handbook.ANALYSTS:
        parts += [f"### {analyst}\n", _block(handbook.chapter_text(analyst))]

    parts += ["\n## 7. 研究简报 `research_session._SYSTEM`（末尾附发行人一章，此处略）\n",
              _block(research_session._SYSTEM.split("YOUR CHAPTER OF THE DESK'S HANDBOOK")[0])]

    parts += ["\n## 8. 风格指南 `style_guide.text()`（校验拥有，只此一份；两份角色说明各引入一次）\n", _block(style_guide.text()),
              "每条规则由哪些拒绝执行（`style_guide.rule_of`，拒绝里只写规则号）：\n",
              _block("\n".join(f"{r.n}. {r.name} — " + ", ".join(k for k, n in style_guide._RULE_OF.items() if n == r.n)
                               for r in style_guide.RULES))]

    parts += ["\n## 9. 拒绝、修复与提示（从源码读出；`{…}` 是运行时填入的槽）\n",
              "### 9.1 主分析师读到的\n", "答案被退回 `meta_agent._refusal_message`：\n",
              _block("\n".join(said_in(meta_agent, "_refusal_message"))),
              "循环里的其他回话 `meta_agent.handle_message`，与原样重发的提示 `repeats.nudge`：\n",
              _block("\n".join([*said_under_keys(meta_agent, "handle_message"), *said_in(repeats, "nudge")])),
              "要求声明检查 `delegation.parse_requirements`（首次 ask 不可省略）：\n",
              _block("\n".join(said_in(delegation, "parse_requirements"))),
              "回复留下未覆盖的要求时 `meta_agent._coverage_message`（V2 P3；不是句子修复，主分析师可再问再写）：\n",
              _block("\n".join(said_in(meta_agent, "_coverage_message"))),
              "读者读到的固定句 `meta_agent._PARTIAL_TEXT`（runtime 写，附在 partial 回复之后）：\n",
              _block(meta_agent._PARTIAL_TEXT),
              "### 9.2 分析师读到的\n", "简报被退回 `delegation.refusal_message`、`parse_submission` 的形状拒绝：\n",
              _block("\n".join([*said_in(delegation, "refusal_message"), *said_in(delegation, "parse_submission")])),
              "循环里的其他回话 `sub_analyst._run`，与预算用尽那一行：\n",
              _block("\n".join([sub_analyst._BUDGET_STOP, *said_under_keys(sub_analyst, "_run")])),
              "### 9.3 两道检查的出路句（方括号里是 reason；规则号见第 8 组）\n", "交接检查 `delegation.handoff_check`：\n",
              _block("\n".join(said_under_keys(delegation, "handoff_check", keys=("way_out",)))),
              "答案检查 `services/answer_check`（`_SHORT_BARE` 是其中两句共用的模板）：\n",
              _block("\n".join([f"_SHORT_BARE = {answer_check._SHORT_BARE}", *said_under_keys(answer_check, keys=("way_out",))])),
              "### 9.4 两个循环都读到的截断提示 `utils/json._CAP_DETAIL`（工具结果或回单超出读入上限时，`truncated.detail`）\n",
              _block(ejson._CAP_DETAIL)]
    return "\n".join(parts)


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        sys.exit(0 if OUT.exists() and OUT.read_text(encoding="utf-8") == text else 1)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text):,} chars)")
