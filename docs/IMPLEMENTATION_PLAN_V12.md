# Implementation Plan V12 — 知识层:让模型看见这套系统已经知道的事

> **状态(2026-08-27)**:起草,未开工。**上游** `dev_note/portfolio-demo/analyst-skills/13-skill-as-knowledge.md`(四路联网研究)与 `dev_note/portfolio-demo/agent-battery/`(43 次真实会话 + `GAPS.md`)。
> **性质**:加法,但**只加已经存在的知识的投递管道**,不加分析能力、不加规则、不加阈值。四条公理、门、工具面一律不动。
> **一句话**:`concept_mapping.py` 的注释和 `formulas.py` 的 `note` 里写着这套系统对数据的全部理解,**而模型一个字都看不到**。把它们发到模型手上,然后让它自己决定。
> **与 G2 的关系**:G2(投影契约,`GAPS.md`)改的是 `describe_issuer` **数据的准确性**;本批加的是**数据的语义**。**建议合批**,理由见 §7。

---

## 0. 诊断:V11 之后剩下的是"选择",不是"计算"

V11 把门能消灭的类别消灭了(1068 offline / 225 live)。电池重跑显示**剩余失败全部在选择上**,而且外部证据说这正是加了工具之后普遍剩下的东西:

| 我们的实测 | 外部同类测量 |
|---|---|
| 总债务 24 次 **11/24**;调 `evaluate_formula` → **9/9 对**,没调 → 2/15 | FinRetrieval:有目录工具后剩余失败中**选错相近序列 19.6%** |
| 问 drawdowns 答单日 **3/5** | FinRetrieval:**期间搞错 63.0%**,归因 *"undocumented tool conventions"* |
| NVDA 选了止于 2022 的 `revenue` 而非 `total_revenues` | 同上;Bloomberg ContDa:**选择混淆 27.3%** > 检索失败 8.4% |
| 问杠杆答绝对额 | BigFinanceBench:*"most remaining between-model separation appears **before a clean setup is reached**"*,条件化后模型间差 5.1pp vs 题间差 49.7pp |

**干预的量级**(全部有出处,见上游 note §2):

```
目录工具 vs 纯检索        +71 pp   (FinRetrieval, Claude Opus 19.8→90.8)
策展的接口库 vs 直接写码   +41.7 pp (Data-Copilot, gpt-3.5 28.5→70.2;GPT-4o 仅 +4.3)
语义文档 vs 仅 schema     +17~23 pp(Cube 配对,三个模型齐升,p≤0.0015)
示例查询                  +24 pp   (LinkedIn);Databricks 称 "single largest improvement"
人写的分步计划            +8.2 pp  (DA-Code) ← 最小的一个,也是 note 12 走的那条路
```

**两条结论**:①**描述数据 > 规定流程**;②**弱模型受益更大**(Data-Copilot 在 gpt-3.5 上 +41.7 而 GPT-4o 上 +4.3;Agentics Qwen3-8B +14.32 而 405B +1.64)。生产用 **gpt-5.4-mini**,BigFinanceBench 上 GPT-5.4 Mini 是 22.3/6.6,榜尾。

**一条硬约束**(DABstep):手册放在磁盘上、提示两次要求先读,Claude 3.7 **第 1 步读了、第 6 步漏了**。*"agents perform well at following instructions **explicitly stated** … considerably more prone to fail … **implicitly mentioned** … or **composite rules linked together implicitly**"*。
→ **每条知识必须:贴在它约束的那个对象上 · 说出后果而不只说事实 · 不要求模型组合两条才得结论。**

---

## 1. 已定决策

| # | 决策 | 依据 |
|---|---|---|
| D1 | **不建 SKILL.md 文件、不加 `activate_skill` 工具**。知识挂在**定位工具的返回值**上 | 电池实测 `describe_issuer` / `get_portfolio_snapshot` 首调率 **100%**;Cube 的教训是 `ai_context` 必须在模型实际看到的那一层 |
| D2 | **知识是数据,不是代码**。全部落在 `analytics/` 的字面量里,evaluator 只做拼装 | 与 `formulas.py`/`containment.py` 同构;"adding one is an edit to data" |
| D3 | **只发有话可说的条目**,空的不发 | LinkedIn:*"adding domain knowledge **decreases** …"*;Snowflake:同义词无价值 |
| D4 | **不发流程卡、不发阈值、不发判决** | FinAgent 的 T 消融(不匹配资产 −21%)、AutoGuide vs ExpeL、DV8、判断禁令是不变量 |
| D5 | **每条 note 要写成"事实 + 后果"**,并且**结论字段与图字段一起发** | DABstep 的复合规则失败 |
| D6 | **先基线后写**,开关对照,**n ≥ 8** | Anthropic:*"Create evaluations BEFORE writing extensive documentation"*;V11 的方差纪律 |

---

## 2. 现状基线(2026-08-27,全部实读)

**模型今天从 `describe_issuer(NVDA)` 拿到的**(6,170 字节):

```
company            8 字段(id/ticker/name/cik/exchange/sector/industry/is_investigable)
available_metrics  34 × {metric, periods, latest_period_end}
formulas           16 × {name, definition, basis, source, computable[, missing_inputs]}
```

**没有**:一行是什么、谁包含谁、谁取代谁、什么不能加到什么头上、任何 caveat、任何示例、任何期间口径。

**知识实际所在**(`grep` 实数):

| 位置 | 数量 | 形态 |
|---|---|---|
| `concept_mapping.py` 的行内注释 | **约 12 条带测量的 gotcha** | Python 注释,不进任何返回值 |
| `formulas.py` 的 `Formula.note` | **16 条** | 字段存在,`describe_issuer` **不发**(V11-T 从面板拿掉了,定位工具本来就没发过) |
| `containment.EDGES` | 11 条边 + 共现次数 | 只有 `cover()` 和 `calculate()` 读 |
| `FORMULAS[*].alternatives` | 4 条 | `evaluate_formula` / `_common_window` / V11 的 `absence_service.superseded_by` 读 |

**常驻上下文**:系统提示 1,051 + 29 个工具 schema 4,652 = **5,707 tokens**,软上限 80,000。`TOOL_RESULT_LIMIT` = 12,000 字节。**预算不是约束。**

**旁证**:近两天 ~480 次工具调用里 `think` **0 次**。

---

## 3. 起草时对着数据核出的两处纠正

**① 「累计申报」是指标属性,不是发行人属性。** 上游 note 的 K0 草稿把 `reporting_style` 放在发行人层。实测(去重后统计"同一 `period_start` 有几个不同 `period_end`"):

```
NVDA operating_cash_flow  4      NVDA revenue          1
NVDA capex                4      MSFT 全部指标          2
```

发行人层聚合是 23–36%,毫无区分度;**指标层是干净的**。→ `reporting_style` 从 K0 移到 K1。

**② 不要用 `fiscal_year` 列。** 同一条 NVDA 的 `2025-01-27..2025-04-27` 同时以 `fiscal_year=2026` 和 `2027` 各存一行。财年末改从**年度事实的 `period_end`** 推(`period_end - period_start BETWEEN 330 AND 400`,取最新):

```
AAPL Sep 27 · MSFT Jun 30 · NVDA Jan 25 · 其余 Dec 31
日历季对齐:NVDA = false,其余 true
```

**这两条都是结构事实,不是阈值。**

---

## 4. 目标形状

### K0 — 期间语义(`describe_issuer` 顶层,每家一份)

```json
"period_semantics": {
  "fiscal_year_ends": "Jan 25",
  "latest_period_end": "2026-04-26",
  "fiscal_quarters_align_with_calendar": false,
  "note": "A window ending 2026-04-26 is this issuer's fiscal Q1, not calendar Q1. State the window dates, not a quarter label.",
  "how_to_ask": "A flow is over an interval and a balance is at an instant; they are different kinds of number and cannot be added. Ask get_flow for the window you want (months=3 for a quarter, 12 for a year) — it derives exactly that window from what the issuer filed, or refuses. It never returns a shorter period than you asked for."
}
```

`note` 仅当 `align == false` 时出现(D3)。

### K1 — 指标语义(`available_metrics` 每条)

```json
{"metric": "cash_and_restricted_cash", "periods": 22, "latest_period_end": "2026-04-26",
 "kind": "instant",
 "note": "Includes restricted cash, so this is NOT the cash available to repay debt — up to 9.9% apart from cash_and_equivalents on AAPL.",
 "do_not_combine_with": ["cash_and_equivalents"]}

{"metric": "long_term_debt_total", "periods": 19, "latest_period_end": "2026-03-28",
 "kind": "instant",
 "note": "All term debt, current maturities INCLUDED. It is a component of total debt, not the measure: adding it to a component it already contains double-counts — 8.31bn on AAPL.",
 "contains": ["long_term_debt_noncurrent", "current_portion_long_term_debt"],
 "do_not_add_to": ["long_term_debt_noncurrent", "current_portion_long_term_debt"],
 "for_a_total_call": "evaluate_formula(name='total_debt')"}

{"metric": "revenue", "periods": 3, "latest_period_end": "2022-01-30",
 "kind": "flow", "windows_filed": ["3-month"],
 "superseded_by": ["total_revenues"],
 "note": "This issuer stopped filing under this tag; total_revenues runs to 2026-04-26. Ask for that one."}

{"metric": "operating_cash_flow", "periods": 22, "latest_period_end": "2026-04-26",
 "kind": "flow", "windows_filed": ["3-month", "6-month", "9-month", "12-month"],
 "note": "Filed cumulatively from the fiscal year start. get_flow(months=3) derives a single quarter by subtracting the shorter cumulative period from the longer one, and returns the terms and signs it used."}
```

`contains` **与** `do_not_add_to` 同时发(D5:不让模型自己从图推结论)。

### K2 — 公式语义(`formulas` 每条)

```json
{"name": "net_debt", "definition": "total debt − cash and equivalents", "basis": "instant",
 "family": "leverage", "unit_class": "money", "computable": true,
 "note": "NOT an agency net debt. S&P nets only surplus cash, with haircuts that need inputs this desk does not have, so a number carrying that name here would be a defined term it is not."}
```

`family` 是**新字段**(leverage / coverage / liquidity / margin / turnover / cash / earnings)。`note` 来自已有的 `Formula.note`,**但要先去掉里面的测量数字**——见 §8 风险 4:16 条里已有 2 条带 `138.753bn` / `8.31bn` 这类数,发出去就是"看起来可引、实际引不了"。

### K3 — 已验证示例(`describe_issuer` 与 `get_portfolio_snapshot` 各 3–5 条)

```json
"worked_examples": [
 {"question": "What is <TICKER>'s total debt?",
  "calls": ["evaluate_formula(name='total_debt')"],
  "why": "Total debt is a composed measure: which components an issuer files varies, and adding a reported total to one of its own components double-counts. The formula path composes a non-overlapping set and carries the definition and a calc_id."},
 {"question": "How has revenue grown over the last four quarters?",
  "calls": ["get_flow(metric=..., months=3, last_n=4)", "series_stat(series_id, op='yoy')"],
  "why": "Pick the metric whose latest_period_end reaches the present — a metric with superseded_by has stopped being filed under that tag."}
]
```

组合面的两条:

```json
 {"question": "Why are there large drawdowns?",
  "calls": ["get_drawdown_episodes()", "explain_episode(peak, trough)"],
  "why": "A drawdown is a peak-to-trough episode over many sessions. reconcile_move explains ONE session. If the question is about episodes, measure the episodes first."},
 {"question": "Was the loss market-driven or company-specific?",
  "calls": ["reconcile_move(run_id)"],
  "why": "It returns factor_share and unexplained_share; the larger one is the answer. Position contributions and factor contributions are two decompositions of the same number and must not be added across."}
```

---

## 5. 排程(单 lane,每步 offline 全绿 + live 增量 → commit)

| 步 | 内容 | 触及 | 量 |
|---|---|---|---|
| **S1** | `analytics/semantics.py`:知识表(数据) | 新文件 + 单测 | 中 |
| **S2** | K0 期间语义:`services/period_semantics.py` + 接进 `_describe_issuer` | 新文件、`definitions.py` | 小 |
| **S3** | K1 指标语义:`available_metrics` 逐条增补 | `calc_service.list_available_metrics` 或 `definitions.py` | 小 |
| **S4** | K2 公式语义:`Formula.family` + `note` 上线 | `formulas.py`、`definitions.py` | 小 |
| **S5** | K3 示例 + `_SYSTEM` 第 56/62 段迁出 | `analytics/semantics.py`、`meta_agent.py` | 小 |
| **S6** | 评测:开关 + 电池重跑 n≥8 | `scripts/agent_battery.py`、settings | 中 |

### S1 · `analytics/semantics.py`

与 `formulas.py` / `containment.py` 同构:**字面量 + 一个查询函数,没有逻辑**。

```python
@dataclass(frozen=True)
class MetricSemantics:
    note: str = ""                                   # 事实 + 后果,一句
    do_not_combine_with: tuple[str, ...] = ()        # 结论,与 containment 图并存
    for_a_total_call: str = ""                       # 指向唯一正确的生产者

METRICS: dict[str, MetricSemantics] = { ... }        # 约 12 条,逐字来自 concept_mapping 注释

WORKED_EXAMPLES: dict[str, tuple[Example, ...]] = {"issuer": (...), "portfolio": (...)}
```

**测试**(`tests/test_v12_semantics.py`):
- 每个 `METRICS` 的键必须在 `concept_mapping` 的映射表里(拼错就红)
- 每个 `do_not_combine_with` / `contains` 的目标必须是真实指标名
- 每条 `note` ≤ 240 字符,且**必须含一个后果连接词**(`so` / `NOT` / `rather than`)——D5 的机械化形式
- **零阈值**:`note` 里不得出现数字比较词(`above` / `below` / `high` / `low` / `healthy` / `risky`),沿用 `test_no_formula_carries_a_threshold` 的写法
- 每个 `WORKED_EXAMPLES` 里点名的工具必须在 `FACE_META_AGENT` 上(仿 `faces.resolve` 的 strict 语义)

### S2 · K0 期间语义

新 `services/period_semantics.py`,一个函数:

```python
async def describe_periods(db, ticker) -> dict:
    """Fiscal calendar and how to ask for a window, derived from the facts themselves."""
```

- `fiscal_year_ends`:最新的年度事实(`period_end - period_start BETWEEN 330 AND 400`)的 `period_end`,格式化成 `"Jan 25"`。**不读 `fiscal_year` 列**(§3②)。
- `fiscal_quarters_align_with_calendar`:该 `period_end` 是否落在 3/6/9/12 月的月末附近。
- `how_to_ask`:常量串(K0 里那段),来自 `get_flow` 的既有契约。

**测试**(`tests/test_v12_period_semantics_live.py`):8 家的 `fiscal_year_ends` 与签入的期望值比对(AAPL Sep 27 / MSFT Jun 30 / NVDA Jan 25 / 其余 Dec 31);NVDA `align == False` 且其余为 True。**同 `test_v11_tag_drift_live` 的棘轮形状**:新出现的不一致变红,不是静默漂移。

### S3 · K1 指标语义

`_describe_issuer` 里逐条增补,数据来源全部已有:

| 字段 | 来源 | 备注 |
|---|---|---|
| `kind` | `period_start IS NULL` → instant,否则 flow | 一句 SQL,可与 `list_available_metrics` 合并 |
| `windows_filed` | 去重后 `period_end - period_start` 的天数桶(3/6/9/12 月) | 仅 flow |
| `note`(累计申报那句) | `windows_filed` 含 6 或 9 月 → 常量串 | **结构判据,非阈值** |
| `contains` / `contained_by` | `containment.EDGES` | 已验证,带共现次数 |
| `do_not_add_to` | = `contains` ∪ `contained_by` | **结论字段**(D5) |
| `for_a_total_call` | 该指标所属 `FAMILIES` 有对应公式时 | 只有 debt/equity/leases 三族 |
| `superseded_by` | `absence_service.superseded_by(metric)` | V11 已实现,直接调 |
| `note`(gotcha) | `semantics.METRICS[metric].note` | S1 的表 |

**注意**:`list_available_metrics` 现在只查 `normalized_metric` 与 `period_end`,要多取 `period_start`。这是它唯一的改动。

### S4 · K2 公式语义

- `Formula` 加 `family: str = ""`,16 条各填一个;**测试断言每条非空且在闭集内**。
- `_describe_issuer` 的 formula 条目加 `note` 与 `family`,**保留** `definition`。

> **与 G2 的冲突,已解**:G2 要删 `describe_issuer` 的 `definition`(T01:未经计算的承诺被贴到自己挑的数上)。**冲突是表面的**——G2 删的是"这个数是怎么算出来的"(只有算过才该拥有),K2 加的是"这个度量是什么、不是什么"(选之前就该知道)。合批时的处置:`definition` **改名为 `measures`** 并重写成不含运算过程的一句(如 `total_debt` 从 *"the widest non-overlapping set of reported debt components"* 改为 *"what this issuer owes, composed from its reported components"*),`note` 照发。**这一条要 boss 单独确认。**

### S5 · K3 与提示迁出

- `describe_issuer` / `get_portfolio_snapshot` 各带对应面的 `worked_examples`。
- `_SYSTEM` **删第 56 段**(发行人流程:describe → 各原语的用法)与**第 62 段**("why moved" 的顺序),二者是 task content,由 K3 承担。
- 保留六条不变量:引用 · 期间 · 定义 · 缺席 · 无判决 · respond。
- **`_SYSTEM` 措辞过目**(既有惯例)。

### S6 · 评测

`settings` 加 `semantics_enabled: bool = True`(**唯一目的**是开关对照,不是 fallback;上线后可删)。
`scripts/agent_battery.py` 已有 `--repeat`。跑:

| 题 | n | V11 基线 | 判据 |
|---|---|---|---|
| 4 家 total debt | 6 ×4 = 24 | **11/24** | 答对率;`evaluate_formula` 调用率 |
| why large drawdowns | 8 | **3/5** 未测回撤 | `get_drawdown_episodes` 调用率;导语方向 vs `factor_share` |
| NVDA 四季度增长 | 8 | 假 "not available" | 最终答案含 `total_revenues` |
| AAPL vs MSFT 杠杆 | 8 | 绝对额 | 答案含 ratio 族度量 |

**开/关各跑一遍,新鲜会话。** 按 agentskills.io:两种配置下都通过的断言要剔除。

---

## 6. 验收(本批的定义性判据)

1. **offline / live 全绿**,新增测试见各步。
2. **`describe_issuer` 载荷 ≤ 11KB**(现 6.2KB + 约 4.9KB),不触发 `dumps_capped` 的截断——**live 测试断言**,同 `test_the_panel_fits_the_context_cap_for_every_issuer`。
3. **零新增规则**:`semantics.py` 无阈值、无判决(机械测试)。
4. **知识不重复**:`METRICS` 的 note 与 `Formula.note` 不得互相复制(测试断言无 ≥60 字符的公共子串)。
5. **对照有数**:S6 的四题开/关各 n≥8,数字进 `docs/spikes/V12_COVERAGE.md`,**改善与否都如实记**。
6. **`_SYSTEM` 变短**(字符数断言)。

---

## 7. 与 G2 的合批建议

G2 的六项里,**四项与本批改同一个函数**(`_describe_issuer`):

| G2 项 | 与本批的关系 |
|---|---|
| 删 `definition` | **冲突,已定处置**(S4 的引注) |
| 拆 `computable` → `inputs_present` + `latest_derivable_window` | **互补**:K1 说"这个指标被谁取代",G2 说"这个公式能算到哪天" |
| 加 `superseded_by` | **同一件事**,K1 已含 |
| `get_balance_sheet` 加 `contains` | **同一份图**,与 K1 共用 |
| `_resolve_company` 删 `id` | 独立,可顺手 |
| `evaluate_formula` 加 `window_bound_by` | 独立 |

**建议**:S3 与 G2 的前四项合成一步做,避免两次改同一个返回值、两次重跑电池。

---

## 8. 风险与退路

| 风险 | 迹象 | 退路 |
|---|---|---|
| **知识没被用上**(DABstep 的失败形态) | 开/关对照无差异 | 不是加更多字,是**把 note 挪到更靠近决策的地方**(如 `get_flow` 的返回也带该指标的 note),或缩短到只剩后果句 |
| **无关知识降分**(LinkedIn) | 某一题开着反而更差 | D3 收紧:只留该题触及的条目;逐条剔除 |
| 载荷变大挤掉别的 | `truncated` 字段出现 | 验收判据 2 会先红 |
| `note` 被模型当成可引用事实写进答案 | 门拒 `unverified_numbers`(note 里的 9.9% 无 id) | **note 里不放可被当作答案的数字**——测试断言 note 不含 `%` 与货币量级词;测量数字放在 `docs/spikes/V9_FORMULA_BASIS.md` 里给人读 |

> 最后一条是起草时才想到的,而且**已经在现有代码里存在**。扫 16 条 `Formula.note`,**2 条带可被抄进答案的数字**:
>
> ```
> ebit        "GOOGL's June 2026 quarter, pretax income of 138.753bn against operating income of 40.770bn"
> total_debt  "adding a total to its own component double-counts — 8.31bn on AAPL"
> ```
>
> 这些数字今天是安全的——因为 `note` **谁也没发给模型**(V11-T 把它从面板拿掉,定位工具本来就没发过)。K2 一上线它们就变成"看起来可引、实际引不了"的数,模型抄进答案会被门拒,而拒因是 `unverified_numbers`——**看起来像模型的错,实际是我们发了不该发的东西**。这正是 V11-T 修 `days_*` 时的同一形状(系统发布了任何证据行都支撑不了的数)。
>
> **处置**:`note` 上线前逐条去掉具体数字,只留后果句;测试断言 `note` 不含 `%` 与货币量级词(`bn`/`billion`/`m`/`million`)。被删掉的测量数字留在 `docs/spikes/V9_FORMULA_BASIS.md` 给人读——它们本来就是写给写代码的人的证据,不是写给答案的。**待拍板:同意去掉,还是给这两句各配一个 fact id。**

---

## 9. 本批不动、登记待议

- 换模型实验(Cube 的结论说文档效应 > 同档模型选择,先做本批再看)
- 判决禁令、引号外的方法句、叙事拉力——`GAPS.md` 右列,不可机械化
- LLY capex 映射(`test_v11_tag_drift_live` 的唯一 `unmapped_candidate`,需先验证语料)
- G6 范围绑定的 skill 层厚度(本批的 K3 是最薄的一版,按 S6 的数字决定要不要加厚)
