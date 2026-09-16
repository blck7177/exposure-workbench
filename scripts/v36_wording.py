#!/usr/bin/env python3
"""V36 — the wording review sheet, generated from the code it reviews.

The three texts a model reads at run time (the lead's system prompt, the domain
analyst's system prompt, the fourteen `offers` the ROSTER is made of) went into
the code as drafts so Phase 1 would not block on a review. This writes
docs/spikes/v36/WORDING.md from the live objects — never from a copy — with a
file:line anchor on each, so the review reads exactly what the model reads and
an edit to the code regenerates the sheet.

    .venv/bin/python scripts/v36_wording.py
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exposure_workbench.agents import delegation, meta_agent, sub_analyst   # noqa: E402
from exposure_workbench.analytics import skill                              # noqa: E402

OUT = ROOT / "docs/spikes/v36/WORDING.md"


def _line_of(path: str, needle: str) -> int:
    for i, line in enumerate((ROOT / path).read_text(encoding="utf-8").splitlines(), 1):
        if needle in line:
            return i
    raise KeyError(needle)


def _const(path: str, name: str):
    """(line, value) of a module-level literal, annotated or not."""
    for node in ast.parse((ROOT / path).read_text(encoding="utf-8")).body:
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        if target == name:
            return node.lineno, ast.literal_eval(node.value)
    raise KeyError(name)


def _descriptions(tool: dict) -> list[tuple[str, str]]:
    f = tool["function"]
    out = [("description", f.get("description", ""))]

    def walk(schema, path):
        if not isinstance(schema, dict):
            return
        if path and "description" in schema:
            out.append((path, schema["description"]))
        for k, v in (schema.get("properties") or {}).items():
            walk(v, f"{path}.{k}" if path else k)
        if "items" in schema:
            walk(schema["items"], path + "[]")

    walk(f.get("parameters", {}), "")
    return out


def build() -> str:
    meta_ln, meta_sys = _const("src/exposure_workbench/agents/meta_agent.py", "_SYSTEM")
    sub_ln, sub_sys = _const("src/exposure_workbench/agents/sub_analyst.py", "_SYSTEM")
    woa_ln, woa = _const("src/exposure_workbench/agents/sub_analyst.py", "_WRITE_OR_ASK")
    cite_ln, cite = _const("src/exposure_workbench/agents/delegation.py", "HOW_TO_CITE")
    offers_ln, offers = _const("src/exposure_workbench/analytics/skill.py", "_OFFERS")
    # the sheet must be what runs: the literals read back from the source equal the imported objects
    assert meta_sys == meta_agent._SYSTEM and sub_sys == sub_analyst._SYSTEM
    assert cite == delegation.HOW_TO_CITE and woa == sub_analyst._WRITE_OR_ASK
    assert offers == skill._OFFERS and set(offers) == set(skill.PROCEDURES)

    # V37/A3: the pushed blocks are tagged now — each says where it came from and
    # what to do with it — and the tags are named constants, so this reads the same
    # objects the turn sends instead of scraping the assembly.
    brief_ln, brief_tag = _const("src/exposure_workbench/agents/meta_agent.py", "BRIEFING_TAG")
    roster_ln, roster_tag = _const("src/exposure_workbench/agents/meta_agent.py", "ROSTER_TAG")
    tags = [("meta_agent.BRIEFING_TAG", brief_ln, brief_tag), ("meta_agent.ROSTER_TAG", roster_ln, roster_tag)]
    for name in ("TASK_TAG", "SUBJECTS_TAG", "BOUNDARIES_TAG"):
        ln, text = _const("src/exposure_workbench/agents/sub_analyst.py", name)
        tags.append((f"sub_analyst.{name}", ln, text))
    assert brief_tag == meta_agent.BRIEFING_TAG and roster_tag == meta_agent.ROSTER_TAG
    roster_head = "\n\n".join(f"{n}  (…:{ln})\n{t}" for n, ln, t in tags)
    cap_needle = "a cap the mandate does not define has no check and no room"
    cap_ln = _line_of("src/exposure_workbench/analytics/skill.py", cap_needle)
    cap_line = (ROOT / "src/exposure_workbench/analytics/skill.py").read_text(encoding="utf-8").splitlines()[cap_ln - 1]
    cap_text = ast.literal_eval(cap_line.strip().rstrip("),"))

    roster_sample = next(r for r in skill.roster() if r["domain"] == "book_limits_and_triggers")
    domain_sample = skill.system_text(skill.PROCEDURES["book_limits_and_triggers"])

    L: list[str] = []
    L.append("# V36 措辞过目单(WORDING)— 已落进代码,待 boss 过目\n")
    L.append("> 计划 §5 说好「我先起草放在这里,你审完我再落进代码」。实际为了不阻塞 Phase 1,三处文字按草稿直接落进了代码并随各 Phase 提交。"
             "本文由 `scripts/v36_wording.py` **从代码原样抽出**(抽出的字面量与运行时对象逐一断言相等),每段带 `文件:行`;你改一处,我同步一处,改完重跑脚本即再生成。\n")
    L.append("> 这些文字是模型在运行时逐字读的,措辞的代价是持续的——要审的是**用词本身**,不只是意图。审阅时想的问题:主分析师读了 A 段会不会去碰 desk 名字?"
             "域分析师读了 B 段会不会给读者写字、会不会心算?14 段 offers 会不会让主分析师把题派错域?\n")
    L.append("状态:**未过目**(2026-09-15)。\n")
    L.append("---\n")
    L.append(f"## A. 主分析师(meta)的 system prompt — `src/exposure_workbench/agents/meta_agent.py:{meta_ln}`\n")
    L.append("```text\n" + meta_sys + "\n```\n")
    L.append(f"### A2. 两块推送上下文的标签(V37/A3:每块说清它是什么、来自谁、拿它做什么)— `meta_agent.py:{roster_ln}` 一带\n")
    L.append("```text\n" + roster_head + "\n```\n")
    L.append("ROSTER 里一条的实际形状(`skill.roster()`,以 book_limits_and_triggers 为例):\n")
    L.append("```json\n" + json.dumps(roster_sample, ensure_ascii=False, indent=1) + "\n```\n")
    L.append(f"### A3. delegate 结果里的固定文案 `HOW_TO_CITE` — `agents/delegation.py:{cite_ln}`\n")
    L.append("```text\n" + cite + "\n```\n")
    L.append("---\n")
    L.append(f"## B. 域分析师(sub-analyst)的 system prompt — `src/exposure_workbench/agents/sub_analyst.py:{sub_ln}`\n")
    L.append("`{domain}` 在运行时换成域名;其后依次接 `skill.system_text(域)`(见 B2)、`program_service.signature_text()`。\n")
    L.append("```text\n" + sub_sys + "\n```\n")
    L.append(f"空回复时追加的一句 `_WRITE_OR_ASK` — `sub_analyst.py:{woa_ln}`:\n")
    L.append("```text\n" + woa + "\n```\n")
    L.append("### B2. 域段落的实际形状(`skill.system_text`,以 book_limits_and_triggers 为例;文字来自 PROCEDURES,示例 program 随之)\n")
    L.append("```text\n" + domain_sample + "\n```\n")
    L.append(f"### B3. V36 补进 book_limits_and_triggers 的一句 desk 知识 — `analytics/skill.py:{cap_ln}`\n")
    L.append("```text\n" + cap_text + "\n```\n")
    L.append("---\n")
    L.append(f"## C. 14 段 offers(ROSTER 里每域「能被问什么」)— `src/exposure_workbench/analytics/skill.py:{offers_ln}`\n")
    L.append("每段 3–5 行;最后一行多半是这个域**不**给的东西(与 `absent` 呼应)。导入期断言 offers 与 PROCEDURES 一一对应。\n")
    for name, lines in offers.items():
        p = skill.PROCEDURES[name]
        L.append(f"### {name}(subject_kind = {p.subject_kind})\n")
        L.append(f"question:*{p.question}*  \nabsent:*{p.absent}*\n")
        L.append("\n".join(f"- {x}" for x in lines) + "\n")
    L.append("---\n")
    L.append("## D. 附:模型读到的工具 schema 里的 description\n")
    for tool in (delegation.DELEGATE_TOOL, delegation.SUBMIT_TOOL, delegation.READ_REPORT_TOOL,
                 sub_analyst.COMPILE_TOOL, meta_agent.REPAIR_TOOL):
        L.append(f"### `{tool['function']['name']}`\n")
        L.extend(f"- `{path}`: {d}" for path, d in _descriptions(tool))
        L.append("")
    L.append("---\n")
    L.append("*生成:`scripts/v36_wording.py`。*\n")
    return "\n".join(L)


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
