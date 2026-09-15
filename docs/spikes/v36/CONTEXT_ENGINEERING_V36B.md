# 报告：code error 还是 LLM error；上下文是谁给错的；分节渲染能救哪些（2026-09-15）

> 承接 `SOURCE_OF_ERROR_V36B.md`（十五条缺陷里十四条不是模型能力上限）。本文回答三问：
> ① 每一条到底是代码错还是模型错——"给错上下文"是**哪段代码**给的；
> ② "信息在上下文里、没检查"的六条，是不是 prompt / context engineering 的问题——尤其是**没帮模型分清它拿到的每块上下文是什么、该拿来干什么**（boss 用过 Jinja 逐 section 渲染的做法）；
> ③ 联网看 prompt engineering 与 context engineering 的现状，对着本桌两个 loop **实际拼出来的上下文**（本文 §2 重建实测）判差距。
> 材料：B 轮 trace 与 `analyst_reports`、两个 loop 的拼装代码、对 fixture 库重建的真实上下文（含 token 计量）、十二篇来源（§4 末）。代码未动。

## 0. 结论

**责任落点**：十五条里 **8 条纯代码**（记录/读取不一致、方法元数据、事实身份、拒绝信、域知识、读法）、**3 条是模型写对了而代码把对的丢掉**（caveat 没人读）、**3 条是模型写错且本该核对的代码没核**、**1 条纯模型**（Q19 读错散文）。"给错上下文"的是 `agents/sub_analyst.py` 的兜底路径把边界事实挂在 `status=rejected` 的步上，而 `services/ledger.load` 只读 `completed`——两处对"什么算账本上的事实"各持一个定义，我在 T1 把这条事实的 id 交给主分析师时把分歧暴露成了假话。

**六条"在上下文里没检查"分三种**，处方不同：
- 3 条（Q04 / Q06 / Q12）模型**已察觉并写进了 caveat**，主分析师的提示词从未提过 caveat → **纯组装问题**，Jinja 分节法直接命中；
- 3 条（Q02 / Q09 / Q11）模型没察觉 → 一半是 context engineering（**派生量没预先算好**，六个日期让它自己数；三条同值事实没标记），一半是 validation（可查表而没查）；
- 但"察觉了也不改"（Q07 五次被拒仍写最高级）与"写了 twelve quarters"这类，文献与本架构的共识一致：**模型自我核对不可靠，要外部验证器**——即门。

**Jinja 分节的假设对了一半。**两个 loop 已有分节的雏形（system 三块、`DOMAIN`、`THE LANGUAGE`），弱在六处（§2）：一行头 + 生 JSON；字段语义只靠字段名、读者没被告知；726 字的 `how_to_cite` 在每个工具结果里重复；派生量（周期、跨度）不算好；同值不同身份无标记；拒绝信说"做什么"不说"怎么做才过"。这六处都是 context engineering 的范畴，文献里都有对应原则，而且**都是代码改动，不是提示词措辞**。

## 1. 十五条缺陷的责任落点

| # | 缺陷 | 代码路径（谁给的） | 模型 | 判 |
|---|---|---|---|---|
| Q10 / Q18 | 引了不在账本上的 id | `sub_analyst.run_sub_analyst` 兜底 → `_record(..., status="rejected", facts=[fact])`；`ledger.load` 的 `where status == "completed"`；`_fill` / `for_lead` 把 `said` + `boundary` 交出去（T1） | 照规则引用 | **纯代码**（我引入） |
| Q02 9209.8% | `fcf_to_debt` 的 unit_class 登记为 RATIO（`analytics` 方法登记）→ `display_conventions` ×100 | 照抄显示值 | **纯代码/数据** |
| Q08 | `program_service` 每节点铸事实：`capex.divide.revenue`、`capex_intensity`(rank)、`vector(capex_intensity)` 同值三身份；`digest.tell_apart` 只在一次 digest 内按 (subject, measure, as_of, value) 合并，measure 不同不合，跨派单更不合 | 在三个同值里挑了没位次的 | **代码制造歧义 + 模型挑错** |
| Q03 | `gate._MIN_QUOTED_WORDS = 4` 执行而不告知；`answer_check` 的 `mark_mismatch` / `unsourced_figure` 两条修法文字互指 | 照两条修法各做了一遍；之后编了数与 id | **代码（拒绝信）+ 模型（编造）** |
| Q07 | `analytics/skill.py` `issuer_earnings_quality.compare` 三条全是同一发行人对自己过去比；跨发行人排序程序只在 `issuer_profitability` | 五次被拒仍写最高级 | **代码/知识指反方向 + 模型不改** |
| Q14 / Q15 | 域知识里没有 `reconcile.factor_share` 与 `divide(market_value, adv)` 的读法 | 按字面读 | **知识缺席** |
| Q04 / Q06 / Q12 | `delegation.for_lead` 带 `caveats`；`meta_agent._SYSTEM` 与 `HOW_TO_CITE` 一字不提 caveat；`sub_analyst._SYSTEM` 却承诺 "the lead states those to the reader" | finding 写错、caveat 写对 | **模型不一致 + 代码丢掉对的** |
| Q02 期 / Q09 / Q11 | `answer_check` 无周期词对 `window` 的规则；`superlative_without_rank` 只问"有一个 place"不问"哪个排序的" | 写了假周期词 / 假最高级 | **模型错 + 本该核的代码没核** |
| Q19 | — | "increased 20%" 读成 "is 20%" | **纯模型** |

"给错上下文"具体到行：`sub_analyst.py` 里 `await _record(ctx, actor, "brief", "submit", {"task_id": …}, text, facts=[fact], status="rejected")`，紧接着 `result.not_done = [{…, "boundary": fact.id, "said": fact.text}]`；`ledger.py` 里 `select(AgentStep.evidence_refs).where(…, AgentStep.status == "completed")`。记录方和读取方对"事实何时算数"各执一词；其余 48 条边界事实走的是 `boundary` 步（completed），只有这一条兜底走 `brief` 步（rejected）。

## 2. 模型实际拿到的上下文（重建实测）

按两个 loop 的拼装代码，对 fixture 库重建了 B 轮 Q09（域分析师）与 Q12（主分析师）读到的真实上下文，逐段计量：

| loop | 段 | 形式 | chars | tokens |
|---|---|---|---|---|
| 主分析师 | system · 角色与规则 `_SYSTEM` | 三段散文，无标题 | 2,600 | 597 |
| 主分析师 | system · BRIEFING | **一行头 + 生 JSON** | 7,460 | 2,148 |
| 主分析师 | system · ROSTER | **一行头 + 生 JSON**（14 条） | 8,957 | 2,112 |
| 主分析师 | tools · delegate schema | JSON schema，字段带 description | 2,408 | 648 |
| 主分析师 | tool · delegate 返回（E10） | **生 JSON；`how_to_cite` 是最后一个键** | 2,662 | 783 |
| 域分析师 | system · 角色与规则 | 四段散文 | 2,351 | 549 |
| 域分析师 | system · `DOMAIN` 块 | `DOMAIN <name> — question` + this desk / compare / close / absent + 示例程序 | 2,221 | 614 |
| 域分析师 | system · `THE LANGUAGE` | 签名表 | 7,769 | 2,121 |
| 域分析师 | user · `{task, subjects, boundaries}` | **生 JSON，无头** | 3,927 | 1,205 |
| 域分析师 | tool · run 结果（digest） | **生 JSON；序列是 `[[date, "v [id@date]"], …]`；每个结果都带 726 字的 `how_to_cite`** | 3,730 | 1,764 |

六处观察，每处对应一条缺陷：

**(a) 分节存在但很薄。**主分析师读到的三块 system 各有一行头（"BRIEFING — the desk's map for this question (names, dates and coverage; …)""ROSTER — …"），之后是生 JSON；域分析师的 `DOMAIN` / `THE LANGUAGE` 有标题；user 消息和所有 tool 结果**没有任何头**。没有一段说"这块来自谁、可不可引、你要拿它干什么"。

**(b) 字段语义只靠字段名承载，读者没被教过。**E10 每个 analyst 的键：`domain, task_id, status, report_id, coverage, findings, not_done, caveats, follow_ups, cost`（Q12 实测）。主分析师从哪里知道 `caveats` 是什么？——**没有地方**。`_SYSTEM` 讲了 `said` / `desk_said` / `made`，`HOW_TO_CITE` 讲了括号与 `read_report`，`caveats` 一字未提。而 Q12 的 E10 里 `caveats[0]` 正是 "JPM's equity-multiplier series came back on quarter-end dates rather than three year-end dates"。**真话在，标签不在。**

**(c) 派生量不预先算好。**Q09 的序列条目是 `{"n": 6, "first": ["2020-09-26", …], "last": ["2025-09-27", …], "points": [六个]}`——没有 `spacing` / `span` / `window` 键。模型要自己从六个日期推出"年度、五年跨度"，然后对着任务里的"twelve quarters"下判断。`place / of` 正是 V36 为最高级预先算好放进 figure 的派生量（设计稿 §3 E7b 的理由就是"分析师写 nearest 时知道依据在哪"）；周期没有同等待遇。

**(d) 同值不同身份没有标记。**Q08 的三条事实 `0.22912850875324786`，一条带 `place=1`，两条不带；它们经两次派单到主分析师面前，没有一个字说"这是同一个读数"。digest 的 `tell_apart` 只在**一份** digest 里、按 measure 合并；它管不到跨派单。

**(e) 每个工具结果重复 726 字的 `how_to_cite`。**域分析师每读一个结果就重读一遍同一段话；Q10 的 `book_market_risk` 读了 9 个结果，就是 9 遍。这既稀释注意力，也打散了缓存前缀（§4 Manus）。规则该在 system 里说一次。

**(f) 拒绝信说"做什么"不说"怎么做才过"。**Q03 复现：`mark_mismatch` 说 "quote the passage's own words"，`unsourced_figure` 说 "quote the passage that states it"；能过的那句（≥4 词逐字原话）从未出现。文献（§4 Claude 指南）的原则是"给指令附上理由与例子"；这里连规则都没给。

顺带：仓库里唯一分节写法的提示词是 `agents/prompts/daily_exposure_report.md`——Markdown 标题、每条规则带"为什么"（"Every number you write is checked … a report that breaks either is discarded"）。两个 loop 的提示词是 Python 内联字符串，没有沿用这个形。

## 3. 六条"在上下文里、没检查"的判：是不是 prompt engineering

先把问题拆准。"prompt engineering"管的是**指令怎么写**；"context engineering"管的是**每一步塞进窗口的是什么、以什么形状、标了什么**（Anthropic 2025-09 的定义：curating and maintaining the optimal set of tokens during inference）。这六条里没有一条是"指令措辞不够好"，有五条是后者。

| 条 | 上下文里有什么 | prompt engineering 能救吗 | context engineering 能救吗 | 还差什么 |
|---|---|---|---|---|
| Q04 | finding 同句 "twelve quarters" + "annual points" | 不能——指令再多，模型已经两种都写了 | **能**：E10 的 caveat 与 finding 并排呈现、主分析师被告知 caveat 是什么 | 无 |
| Q06 | 两条 caveat 写明两个窗口 | 不能 | **能**（同上） | 无 |
| Q12 | caveat 写对、finding 写错 | 不能 | **能**（同上）；再加：finding 旁自动带 `dates` | V4 查表兜底 |
| Q02 期 | 两条序列的 `window` 在 | 弱（"核对周期"的指令模型不一定执行） | **半能**：digest 给 `spacing: annual`，模型不必数 | **V4 查表** |
| Q09 | 六个年度日期在同一句 | 弱 | **半能**（同上） | **V4 查表** |
| Q11 | `place=8 of=20`；答案自己说没档位 | 指令已经在（"a superlative rests on an ordering the desk computed"） | 弱：位次已经预算好了，模型仍写 | **V1 查表**（位次须属所问的排序） |

两点判断：

**第一，三条 caveat 的失守是组装层的事，与模型无关，与措辞无关。**E10 已经带了 caveats（代码 `for_lead` 明写），主分析师的提示词与 `HOW_TO_CITE` 没有一个字讲它；域分析师却被告知 "the lead states those to the reader"。这就是 boss 说的"没告诉模型它拿到的 context 是什么、该拿来干什么"——最字面的一例。

**第二，剩下三条不该指望 prompt。**文献一致：Huang 等（ICLR 2024）"Large Language Models Cannot Self-Correct Reasoning Yet"——没有外部反馈时模型自我核对不改善、常变差；后续工作（ProgCo 2025、S²R 2025）的出路都是**程序或外部验证器**。本架构 V33 起的契约恰是这条："正确性是代码里的一次查表"。周期词对 `window`、最高级对"哪个排序的位次"，都是账本已有字段上的查表。context engineering 在这里能做的是**把派生量算好给它**（`spacing` / `span`），让模型少犯；能兜底的只有验证。

一个反例作对照：**Q07 五次被拒仍写最高级**。指令在（"a superlative rests on an ordering"）、修法在（"request compare: rank over it, or drop the word"）、原语在（签名表有 `rank(`、`vector(`）。模型不改，是因为域知识把"比较"定义成了"对自己的过去比"（§1）。这不是提示词的问题，是**知识指了反方向**——分节渲染不会改变它读到的那三条 compare。

## 4. 联网研究：现状与对本桌的映射

按来源列要点，右栏是本桌现状。

| 来源 | 要点 | 本桌 |
|---|---|---|
| Anthropic《Effective context engineering for AI agents》（2025-09） | 提示词找"合适的高度"；**用 XML 或 Markdown 标题分节**（`<background_information>` `<instructions>` `## Tool guidance`）；context rot——token 越多回忆越差；子 agent "explore extensively… returns only a condensed, distilled summary"；**tool result clearing** 是最轻的压缩 | 高度对；分节薄（§2a）；子 agent 返回浓缩 brief ✓；tool result 从不清理，域分析师 8 轮全留 |
| Claude 提示词指南（platform.claude.com，当前版） | "XML tags help Claude parse complex prompts unambiguously, **especially when your prompt mixes instructions, context, examples, and variable inputs**"；标签名前后一致；长文档 `<document index><source><document_content>`；**"Providing context or motivation behind your instructions … can help"**；状态用结构化格式 | 混合了四类内容却只有一行头；`how_to_cite` 说规则不说理由；E10/BRIEFING 是无标签 JSON |
| Anthropic《How we built our multi-agent research system》（2025-06） | **"Each subagent needs an objective, an output format, guidance on the tools and sources to use, and clear task boundaries"**；用 artifact 持久化、传轻量引用；工具描述决定成败；模型能自诊断失败 | E4 有 objective / boundaries，无"output format"之外的来源指引；报告落库 = artifact ✓；`made` = 轻量引用 ✓ |
| Manus《Context Engineering for AI Agents》（2025-07） | 前缀稳定护 KV-cache；**"keep the wrong stuff in"**（错误留在上下文里模型才会改）；recitation 把目标拉回近端；别被自己的输出 few-shot 进沟里 | 错误留着 ✓（类型报告、退回信都在）——但 Q08 四次同一程序说明"留着"不等于"读了"；`how_to_cite` 每结果重复破坏前缀 |
| Chroma《Context Rot》（2025-07） | 18 个前沿模型都随长度退化，连复制任务都退；**干扰项**的影响非线性；问题与答案的语义相似度越低退化越快 | 域分析师中位 11 次 completion、峰值 2 万 token；Q08 三条同值事实正是"干扰项" |
| LangChain《Context Engineering for Agents》（2025） | write / select / compress / **isolate**；agent 边界处压缩 | digest = compress ✓；域分析师 = isolate ✓ |
| Cognition《Don't Build Multi-Agents》（2025-06） | "Share context, and share full agent traces"；"Actions carry implicit decisions" | Q13 的 after-book、Q08 的两次派单：决定隐含在动作里，没传到 |
| Breunig《How Long Contexts Fail》（2025-06） | poisoning / distraction / **confusion** / clash | T10 = 毒化（假 id 进上下文）；Q08 = 混淆（同值三身份） |
| 12-Factor Agents | own your prompts；**own your context window**；tools are structured outputs | 提示词内联在代码里、无模板；上下文靠 JSON dump |
| Huang 等，ICLR 2024 | 模型无外部反馈不能自我纠错，可能变差 | 门与交接核对 = 外部反馈 ✓；周期词/排序归属两处漏 |
| 交接协议文献（dev.to 2026；substack 2026） | 结构化载荷：settled / open questions / constraints / artifacts，**每条 finding 带 provenance 与 confidence**；"summary-induced false certainty"——摘要抹掉了"什么确定、什么不确定" | E10 已是结构化载荷 ✓；`caveats` 正是 "uncertain" 那一栏——**存在但没人读** |
| 2026 论文（arXiv 2606.29718《Diagnosing and Mitigating Context Rot in Long-horizon Search》） | 新失败模式 **premature termination**：远未用尽上下文就放弃或给不确定的错答 | Q10 `book_market_risk` 16 次 completion 一条没交、Q18 8 次没交——同形 |

## 5. 处方：分清哪条腿救哪条

### 5.1 组装层（context engineering）——都是代码，不是措辞

- **C1 分节渲染。**两个 loop 的提示词改为模板（Jinja 或等价），每一块带三件事：**这是什么、来自谁、你拿它做什么**。最小形：
  ```
  <briefing source="desk catalogue" trust="names and dates only, no figures" use="pick subjects; check premises">…</briefing>
  <roster source="skill" use="pick the analyst by what you need to know">…</roster>
  <analysts source="handoff check, passed" use="copy figures as shown">
    <finding want="2" …>…</finding>
    <not_done want="3" said="…desk's words…" boundary="f_…"/>
    <caveat>JPM's equity-multiplier series came back on quarter-end dates rather than three year-end dates</caveat>
  </analysts>
  ```
  `caveats` 进主分析师的提示词与 `HOW_TO_CITE`；`how_to_cite` 只在 system 说一次，工具结果不再重复。直接对应 Q04 / Q06 / Q12。
- **C2 派生量预计算进 digest。**序列条目加 `spacing`（annual / quarterly / daily）与 `span`；E10 的 finding 旁自动带它引用的序列的 `dates: annual ×6, 2020–2025`。对应 Q02 / Q09 的一半。
- **C3 跨派单的同值标记。**E10 里同值不同身份的事实并排时标 `same_reading_as` 与 `carries_place`。对应 Q08。
- **C4 拒绝信带可照抄的修法。**`mark_mismatch` / `unsourced_figure` 命中 passage 时直接给出那段里含该数的 ≥4 词原话。对应 Q03（= 前文 V5）。
- **C5 用尽轮数的分析师交出它取到的东西。**兜底不该只留一句 "did not file"；它取的事实在账本上，E10 至少列出它们的 id 与 measure。对应 Q10 / Q18 的第二层损失（第一层是 T10）。

### 5.2 验证层——prompt 救不了的

- **V4** 周期词对事实的 `window` 与点间距；**V1** 最高级的位次须属句子所问的排序。交接核对与门共用同一个 `check`，改一处两处收。

### 5.3 知识层

- **S3** 按发行人算的域补跨发行人排序程序；两处读法（factor_share、days-to-liquidate）进域知识。

### 5.4 不该指望的

- 让模型"核对自己刚写的两样东西是否一致"（Q09 的六个日期）——文献与本架构都说不靠它。
- 让模型在知识指反方向时自己纠偏（Q07）。
- Q19 那种散文误读——处方仍是"只在正文里的数必须引、不许转述"，即 C4。

## 6. 与既定顺序合并

T10（别说假话）→ **C1 caveats 上行并教读**（组装）→ V4 / V1（查表）→ C4=V5、S3、读法 → T12=C3 → C2 / C5 与 T11。
C1–C3 是 `for_lead` / `digest` / 两段 `_SYSTEM` 的改动，改的时候把两段提示词从内联字符串改成分节模板，`WORDING.md` 的生成脚本随之读模板。

---

来源：
- Anthropic, *Effective context engineering for AI agents* — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic, *Prompting best practices*（当前版，含 Fable 5.1）— https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
- Anthropic, *How we built our multi-agent research system* — https://www.anthropic.com/engineering/built-multi-agent-research-system
- Manus, *Context Engineering for AI Agents: Lessons from Building Manus* — https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus
- Chroma, *Context Rot* — https://www.trychroma.com/research/context-rot
- LangChain, *Context Engineering for Agents* — https://www.langchain.com/blog/context-engineering-for-agents
- Cognition, *Don't Build Multi-Agents* — https://cognition.com/blog/dont-build-multi-agents
- D. Breunig, *How Long Contexts Fail* — https://www.dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html
- HumanLayer, *12-Factor Agents* — https://github.com/humanlayer/12-factor-agents
- Huang et al., *Large Language Models Cannot Self-Correct Reasoning Yet*, ICLR 2024 — https://arxiv.org/abs/2310.01798
- *Diagnosing and Mitigating Context Rot in Long-horizon Search*, 2026 — https://arxiv.org/abs/2606.29718
- *Multi-Agent Handoffs: The Protocol That Stops Context Loss* — https://dev.to/gabrielanhaia/multi-agent-handoffs-the-protocol-that-stops-context-loss-3ea1 ；*What the Orchestrator Forgot to Tell Its Workers* — https://claudecodefornoncoders.substack.com/p/what-the-orchestrator-forgot-to-tell
