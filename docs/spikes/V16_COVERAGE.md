# V16 coverage — the gap battery, before and after

Date: 2026-09-01. Branch `issuer-intelligence`, commits `d920276..55e3c22` (+ the
build-narrowing fix). Suites: **1818 offline** (V15: ~1700; the delta is the new
guards) / **246 live**, both green against the deployed containers. Data: mapping
v4 remapped 2,472 fact rows (backup `ew-2026-09-01.sql.gz` first). Deployed to
desk-for-one.com same day.

The acceptance criterion is not a refusal rate. Three buckets per question:
**named-slot answer** (computable → answered with slots), **reasoned refusal**
(not computable → says why), **substitution** (a nearby name wearing the asked-for
meaning). The target: substitution = 0. Baseline S0 = the 8 gap questions against
pre-V16 HEAD (`docs/spikes/V16_BASELINE.json`); S6 = the same 8 against deployed
V16 (`V16_S6.json`).

## §1 Question by question

| # | question | S0 (pre-V16) | S6 (V16) |
|---|---|---|---|
| G1 | MSFT 贵不贵 | half-substitution: fundamentals mush, no multiple existed to compute | evidence laid out, **no invented multiple**; 2 accepted errors (below); did NOT compose market cap though close × shares_outstanding is now reachable — behavioral, re-measure next battery |
| G2 | NVDA TSR 分解 | **substitution**: revenue growth passed off for TSR decomposition | **reasoned refusal** ✔ — names the missing piece (a valuation-multiple series), which is exactly V16's declared not-doing (2–3 filings/issuer) |
| G3 | AAPL 回购减股数? | partial (share counts unmapped) | **named slots** ✔ — weighted share count series + buybacks flow, decline shown |
| G4 | LLY ROE DuPont | ad-hoc composition, names uncheckable | **named slots** ✔ — roe 81.0% with net_margin × asset_turnover × equity_multiplier, all registry names |
| G5 | JPM EV/EBITDA | reasoned refusal ✔ (already correct) | **reasoned refusal** ✔ — bank sentence + latest price beside it |
| G6 | 应计比率最高 | off-target (answered about MSFT EBITDA) | **named slots** for 5 holdings + honest budget refusal for the rest; 1 accepted error (below) |
| G7 | XOM beta + 观测数 | **substitution**: debt/EBITDA 22.9% offered for a beta | refusal traced to an infrastructure defect (§2), fixed same day; **rerun: named slots ✔** — 1 call, 0 refusals, beta with its 250 aligned observations (`V16_S6_G7_RERUN.json`). One display residual: a beta is a ratio and rendered "-54.3%" — the value is true (-0.543), the percent dress is the known multiple-vs-percent display class (#33), still open |
| G8 | 现金流与净利背离 | budget exhausted, nothing | **named slots** ✔ — OCF/NI table across 5 issuers, honest about the missing half |

**Substitution: S0 ≥ 2 of 8 → S6 = 0 of 8.** The S6 residuals are a different
class — sentences whose slots are all true:

1. G1: "trades at $507.29 as of $507.29" — the as-of DATE is not a slottable
   quantity, so the model slotted the price twice; and a metric_table Value cell
   carries the NAME as text (`MSFT.close`, no digits, passes) instead of a slot.
2. G6: "3.40% on JPM was the highest, above 4.11%" — all four accruals values
   true (two positive, two negative), the ORDERING claim false. Comparative
   prose is content the five lookups do not judge, by design.

No invented numbers, no wrong-provenance citations, no id written into text
survived to acceptance across all 8.

## §2 The defect the battery found (and the suite did not)

G7's three gate refusals were real: `get_beta` computed beta/alpha/r2 and the
model slotted `XOM.beta.SPY` correctly — but the result declared two ~250-point
returns series beside the scalars, the series alone overflow the 16k table
slice, and `build()`'s narrowing had no move for non-run entries: the dead-end
declared **everything** empty. The beta died for the size of its inputs, and the
model, told its own result was not on the table, refused honestly.

Fix: a second narrowing phase — whole entries drop off, series first, recorded
on the payload (`truncated.dropped`) and in the stored declaration; a scalar
never dies for the size of its inputs. The first draft of that phase carried a
NameError that a full green suite never touched — the path had zero coverage —
so it is pinned by two tests now. That is the session's two meta-rules
demonstrating themselves on the session's own fix.

## §3 Residuals and leads (registered, not patched)

- **As-of dates are not quantities** → G1's slot misuse. Lead for V17: either a
  date rides the table as a named point or the convention "dates are text" gets
  said once in the slot description. Not a gate rule.
- **Comparative/ordering prose is unjudged** — by design; the gate guarantees
  provenance, not sentences. The battery measures it; a non-blocking critic
  (LLM outside the gate) remains the V17 candidate.
- **Composition initiative**: market cap / P/E are now one `calculate` away
  (unit algebra defines money_per_share × count = money) and G1 did not reach
  for them. Behavioral, not structural; re-measure.
- G8 covered 5 of 10 under the tool budget, and said so.

## §4 The self-check the plan wrote down

Validation gained **zero** new members: the five error strings are unchanged and
the source-pin test still passes. Everything V16 changed lives in tools (values
born complete), skill data (methods with authority), and the table (meaning +
reasons travel). `_NOT_A_FIGURE` is frozen at nine with a pin; LEGACY_RATIO_OPS
still may not grow. The 20-item tool-author checklist's worst silent item —
`evidence` — is now a registration-time refusal.
