#!/usr/bin/env python3
"""Regenerate docs/spikes/v30/V30_WORDING_REVIEW.md from the code.

Every sentence V30 puts in front of the model, collected from the one place each
lives, so a review is of what the model actually reads and not of a transcription.
Run it after the tree is frozen for a measurement round, so the file matches the
code that round measured.

    scripts/v30_wording_review.py > docs/spikes/v30/V30_WORDING_REVIEW.md
"""
from __future__ import annotations
import inspect, re, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from exposure_workbench.agents import meta_agent                      # noqa: E402
from exposure_workbench.analytics import skill                        # noqa: E402
from exposure_workbench.services import claims                        # noqa: E402
from exposure_workbench.services import catalogue_service as cat      # noqa: E402
from exposure_workbench.services import fundamentals_service as fs    # noqa: E402
from exposure_workbench.services import name_table as nt              # noqa: E402
from exposure_workbench.services import program_service as ps         # noqa: E402
from exposure_workbench.tools import faces, mcp_server, registries    # noqa: E402

# A refusal sentence is usually several adjacent string literals across lines.
# Capturing only the first leaves the reviewer half a sentence — and the half that
# is dropped is the one naming the fix, which is the part worth reviewing.
_RUN = r'((?:f?"[^"]*"\s*)+)'
DETAIL = re.compile(r'"reason": "([a-z_]+)", "detail": ' + _RUN)
ERR = re.compile(r'_err\(\s*"([a-z_]+)",\s*' + _RUN)
RETURN_ERR = re.compile(r'"error": "([a-z_]+)", "detail": ' + _RUN)
_LIT = re.compile(r'f?"([^"]*)"')


def _join(run: str) -> str:
    """The adjacent literals as one sentence, f-prefixes and line breaks gone."""
    return "".join(_LIT.findall(run)).replace("\\n", " ").strip()


def uniq(pairs):
    seen = {}
    for code, text in pairs:
        seen.setdefault(code, _join(text))
    return seen


def main() -> int:
    reg = registries.build_meta_registry()
    w = print
    w(f"# V30 — model-facing wording, for review before commit\n")
    w(f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z by `scripts/v30_wording_review.py`, from the code itself.\n")
    w("Every sentence the model reads that V30 added or changed. Same discipline as V24_WORDING_REVIEW.md: "
      "nothing here is committed until it has been read.\n")

    w("## 1. The system prompt (`agents/meta_agent._SYSTEM`)\n")
    w("```\n" + meta_agent._SYSTEM + "\n```\n")

    w("## 2. The push preamble (`agents/meta_agent.handle_message`, when a domain matches the question)\n")
    w("```\nFor this question, the desk's own knowledge (its programs use <port>, <T>, <T1>/<T2> placeholders: "
      "substitute the ids and tickers from describe()):\n\n"
      "<the domain's question / this desk / compare / close / absent here / programs>\n```\n")

    w("## 3. Tool descriptions on the meta face\n")
    for name in faces.FACE_META_AGENT:
        t = reg.tools[name]
        w(f"### `{name}` — display: “{t.display}”\n\n```\n{t.description}\n```\n")

    w("## 4. The claims rule (`services/claims.PROSE_RULE`), imported verbatim by the prompt, by respond and by the MCP instructions\n")
    w("```\n" + claims.PROSE_RULE + "\n```\n")

    w("## 5. MCP instructions (`tools/mcp_server.INSTRUCTIONS`)\n")
    w("```\n" + mcp_server.INSTRUCTIONS + "\n```\n")

    w("## 6. What the gate says when it refuses (`services/claims`)\n")
    src = inspect.getsource(claims._check_relation) + inspect.getsource(claims.validate_shape) + inspect.getsource(claims.check)
    for code, text in uniq(DETAIL.findall(src)).items():
        w(f"- `{code}`: {text}")
    w("")

    w("## 7. What the executor says when it refuses (`services/program_service`)\n")
    psrc = inspect.getsource(sys.modules[ps.__name__])
    for code, text in uniq(list(ERR.findall(psrc)) + list(RETURN_ERR.findall(psrc))).items():
        w(f"- `{code}`: {text}")
    w("")

    w("## 8. What the catalogue says when it refuses (`services/catalogue_service`), and the desk's own rules\n")
    csrc = inspect.getsource(sys.modules[cat.__name__])
    for code, text in uniq(list(ERR.findall(csrc)) + list(RETURN_ERR.findall(csrc))).items():
        w(f"- `{code}`: {text}")
    w("\nThe desk's rules, published by `describe` under `cannot`:\n")
    for k, v in cat.CANNOT.items():
        w(f"- **{k}**: {v}")
    w("")

    w("## 9. The superseded-line refusal (`services/fundamentals_service._superseded_line`)\n")
    w("```\n" + inspect.getsource(fs._superseded_line) + "```\n")

    w("## 10. The domains and the titles of their programs (`analytics/skill.PROCEDURES`)\n")
    for p in skill.PROCEDURES.values():
        w(f"- **{p.name}**: " + "; ".join(t for t, _ in p.programs))
    w("")

    w("## 11. The symbol table, carried in `run`'s description (`services/name_table.symbol_table`)\n")
    w("```\n" + nt.symbol_table() + "\n```\n")

    w("## 12. The catalogue's call snippets (`services/name_table.call`), three examples\n")
    for n in ("price.adv", "revenue", "positions"):
        w(f"- {n}: `{nt.call(nt.TABLE[n], subject='MSFT', ref='port_001')}`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
