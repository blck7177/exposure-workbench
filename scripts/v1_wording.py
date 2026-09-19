"""Generate docs/WORDING_V1.md: every sentence V1 sends to a model, read off the
live objects, for one review before the first measured round (the V37 §5 rule).

    .venv/bin/python scripts/v1_wording.py            # writes docs/WORDING_V1.md
    .venv/bin/python scripts/v1_wording.py --check    # exits 1 when the sheet is stale

Nothing is copied by hand: the sheet is rendered from the modules the turn reads,
so a wording change shows up here as a diff.
"""

from __future__ import annotations

import sys
from pathlib import Path

from exposure_workbench.agents import delegation, meta_agent, research_session, sub_analyst
from exposure_workbench.analytics import handbook, registry
from exposure_workbench.tools import faces, primitives

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "WORDING_V1.md"


def _block(text: str) -> str:
    return "```text\n" + text.strip() + "\n```\n"


def render() -> str:
    parts = ["# V1 措辞过目单（由 scripts/v1_wording.py 生成，勿手改）\n",
             "V1 发给模型的全部文字，从运行时对象渲染。分七组：主分析师、分析师角色说明、工具描述、登记簿词表、"
             "登记簿读法与工具说明、手册三章、研究简报。旧架构的文字（14 个域、程序语言说明、两份图例、READINGS、DESK_RULES）已随退役删除。\n"]

    parts += ["\n## 1. 主分析师\n", "### 1.1 角色说明 `meta_agent._SYSTEM`\n", _block(meta_agent._SYSTEM),
              "### 1.2 三个块的标签\n", _block("\n".join((meta_agent.BRIEFING_TAG, meta_agent.ROSTER_TAG, meta_agent.READINGS_TAG))),
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

    parts += ["\n## 2. 分析师角色说明 `sub_analyst._SYSTEM`（三位共用，标题与政策 id 代入）\n",
              _block(sub_analyst._SYSTEM.format(title="<the issuer analyst | the market analyst | the portfolio risk manager>",
                                                policies=sub_analyst._POLICIES)),
              "块标签与提示句：\n", _block("\n".join((sub_analyst.TASK_TAG, sub_analyst.COVERAGE_TAG, sub_analyst._WRITE_OR_ASK))),
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
              "`missing at this date: …`、`never filed by this issuer: …`、`overlapping, not added: …`；不可单独引用 `not quotable on its own`。\n",
              "**三条常驻政策缺席**\n", _block("\n".join(f"{p['id']}: {p['text']}" for p in registry.POLICY_ABSENCES))]

    parts += ["\n## 5. 登记簿读法与因子工具\n", "**READS**\n",
              _block("\n".join(f"{registry.reads_as(k)}: {v}" for k, v in registry.READS.items())),
              "**INSTRUMENTS**\n", _block("\n".join(f"{t} is {what}, standing for {risk}" for t, what, risk in registry.INSTRUMENTS))]

    parts += ["\n## 6. 手册三章 `handbook.chapter_text()`\n"]
    for analyst in handbook.ANALYSTS:
        parts += [f"### {analyst}\n", _block(handbook.chapter_text(analyst))]

    parts += ["\n## 7. 研究简报 `research_session._SYSTEM`（末尾附发行人一章，此处略）\n",
              _block(research_session._SYSTEM.split("YOUR CHAPTER OF THE DESK'S HANDBOOK")[0])]
    return "\n".join(parts)


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        sys.exit(0 if OUT.exists() and OUT.read_text(encoding="utf-8") == text else 1)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text):,} chars)")
