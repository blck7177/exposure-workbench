# IMPLEMENTATION PLAN V1 — 原语工具层、三位分析师、自带意义的事实（2026-09-19）

> 新系列从 V1 重新编号。旧系列 `IMPLEMENTATION_PLAN.md`、`V2`–`V38` 与 `MCP_PLAN.md` 已归档到 `docs/archive/plans/`，以后不再阅读；查某轮的数字或根因才按需去翻一份。
> 依据：Claude Doc「桌子架构 V39 设计稿」（9/17，角色与文件的正本）；9/17、9/18、9/19 三次讨论的决定（§1）；9/19 三路调研（工具设计原则、数据库与 RAG 工具模式、金融 agent 系统）与仓库数据盘点（§2.0）。
> 起点：`issuer-intelligence` 的 HEAD `6ebb886`（V38 A-R1）之上提交归档与本计划，再从那里开出执行分支 `desk-v1`。K5 五文件已 stash（9/19）。生产仍是 9/9 的 `e6c290b`。
> 读法：每步一组提交、一个机械验收。分析按「先判谁越界，再按七层讲位置」；实测轮冻结代码，按节点沟通表分析；手册与角色说明的文字改动走措辞过目。

## 0. 一句话，与不变量

**一句话**：工具层降到底层正交的动词（看有什么、从某表取某信息、按名字取度量、对数字做一步运算、去某文件找某物、动作、出口），每个输出是一行不看图例就能读的事实；问题级的知识（什么是杠杆、怎么判断波动升高）回到手册；度量的定义与读法只在登记簿一处；三位分析师按资源族切面；主分析师只做三件事：和用户说话、向分析师提要求、翻证据链。

**不变量**：
- 证据链不动：每个数是账本上的类型化事实；typed_calculator 的单位与期间规则（R1–R3、书的代数）不动；registry 四步 wrapper、按 session 记账、两道检查（按行、按句、两次机会、原样重发不算第二次）不动。
- 不加 fallback；LLM 路径上不加规则补丁；每条改动消灭一类错误。
- 模型不给度量起名；不开放自由 SQL（每个数必须是账本上的事实，SQL 逃生口与此冲突）。
- 三个过程规则：措辞过目、实测期冻结代码、按节点沟通表分析。

## 1. 已定的决定（作为前提）

| 日期 | 决定 |
|---|---|
| 9/17 | ① 领域分析师像真实桌子一样工作，不写程序；② 主分析师拿含义层；③ 读法写进事实本身；④ V38 D 轮先跑作基线；⑤ 领域分析师按资源族切三位：发行人分析师、市场分析师、组合风险经理 |
| 9/18 | 五处边界补齐：校验规则退出手册；比较要有可比性约束；意思字段只用登记簿枚举词；主分析师拿到事实行原文；分析师必须能拿到边界事实的 id |
| 9/19 | 工具是底层正交的动词，不是报表；"波动是否升高、是否已在价格里、杠杆翻转点、回报与杜邦"这类是分析师的问题，进手册不进工具；事实 8 字段最小化；主分析师三件事；领域分析师开工前知道四样（本域有哪些数据、要干嘛、有哪些 tool 各能回答什么、一章手册加风格指南），每次调用必填 why，log 由此长出，不另写报告；先单步调用，代码组合进代办；RAG 召回改进单独代办；**program_service 退役；D 轮不跑；K5 五文件 stash；归档与本计划先提交，再开 `desk-v1` 分支执行** |

本计划**替换**设计稿的 §7「报表目录」与 §10 中的「系统指南」；**保留**设计稿的角色与文件、度量登记簿、事实自带读法、简报与名册、风格指南单源、八步流转与验收思路。

## 2. 目标形状

### 2.0 调研与盘点的结论（只列影响设计的）

- 常驻工具数量与重叠伤选择，常驻面 10 个以内；治法取"少量正交原语 + 知识在 skill"（Claude Code、Vercel 实测：删八成专用工具只留两个原语翻语义层，成功率 80%→100%，步数少 42%）。
- 数据与动作分开（MCP resources 对 tools）；语义层产品一律"列出、描述、按名字要度量"，度量定义一次，不让 LLM 每次猜算法（dbt、Cube、Malloy）。
- 金融基准失败顺序：取数期间错位与单位 > 有证据仍算错 > 解读。修法：结构化接口按名字取数、算术交给代码、检索先列文档再取段。
- 可审计形状：每个操作数带概念、期间、单位、来源；参数、输出、下游动作连成依赖链。本仓库的 typed_calculator + calc_ledger + facts 表已是这个形状。
- 盘点：结构化数据三族——申报事实 `financial_facts`（XBRL 原始 tag，重述追加不覆盖，取最新申报）、价格 `market_prices`/`factor_prices`、书的 run 表（`issuer_exposures`、`sector_exposures`、`limit_checks` 自带 `status`、`factor_attributions`、`exposure_metrics` 自带 `collinear`）；回撤与对账是 calc_ledger 行；公式登记簿 30 条带出处（`analytics/formulas.py`）；语料只有 `filing_chunks`（按 Item 切段、pgvector、无关键词索引）与 `research_sources`。今天的读原语都在 `program_service` 里：fundamentals、prices、price、run、column、figure、pick、method、加减乘除、rank、sell、buy。

### 2.1 角色与面

四角色不变：主分析师、领域分析师（三位）、手册（skill）、工具；加校验。领域分析师按资源族：

| | 发行人分析师 | 市场分析师 | 组合风险经理 |
|---|---|---|---|
| 数据 | 申报数字、申报文本、网页 | 价格与成交量（持仓名字与因子 ETF） | 持仓、run、因子模型、情景引擎、限额、回撤、对账 |
| 专业 | 财务报表分析、信用、读申报 | 价格统计 | 组合风险管理 |

主分析师三件事：和用户说话；向分析师提要求（ask）；翻证据链（open）。它不碰数据源，拿不到新数。

### 2.2 事实

模型看到的一行只有 8 个字段：

```
id     f_…
kind   reading | series | passage | absence
what   读作，金融名                 "EBIT 利息覆盖率"
of     主体                         "XOM"
when   实际找到的期间，不是问的期间   "TTM 至 2025-06-30"；series 写间隔与跨度
value  值带单位                     "18.4 倍"；series 为 [期, 值] 点列；passage 为原文；absence 为空
means  意思，登记簿词表写的一句话
from   来历                         "r_51 metric ebit_interest_coverage"
```

渲染行：`[f_7d21] EBIT 利息覆盖率，XOM，TTM 至 2025-06-30：18.4 倍 — 用了非经营利息行替代利息费用 — r_51 metric`。分析师读的、账本存的、主分析师引的、读者打开的是同一行；存储行另有模型看不见的类型化列（登记簿 key、数值、单位类、点列、参数、sources），渲染行是存储行的纯函数。

`means` 词表住在登记簿：方向亏/赚/平；状态清/警戒/违约/未跑；位次第 n 共 m；变化升/降/平；依据（按 91 天、期末余额、调整收盘、书的收益、参与率 25%）；组成（用了 X 替代 Y、缺 Z）；限制（共线不可逐腿引用、扣留待验证）。没有自由文本。

缺席也是一行：`means` 写原因加出路（允许值、可行的动词、在哪个面上）。政策类缺席是常驻固定 id 的事实（不预测、不给阈值、不估算），印在每个面的角色说明里，分析师直接引。

### 2.3 工具层：12 个动词

每次调用必填 `why`（这一步为任务的哪一行、为什么）。输出永远是一个头行加若干事实行；拒绝是一条缺席行。

| tool | 动词 | 输入 | 输出 |
|---|---|---|---|
| list | 看桌上有什么 | what ∈ {metrics, fundamentals, filings, prices, book, checks}；主体 | 名字、期间、日期、计数；无数字 |
| filings_read | 取一条申报科目 | ticker；科目枚举（`SUPPORTED_METRICS`）；period ∈ {fy, quarter, ttm_to, months+end, at} | 一行：值、单位、实际期间、accession；重述取最新申报；流量配 at 拒绝 |
| prices_read | 取价格或成交量 | ticker；window 或 date；field ∈ {close, adj_close, volume} | 序列或一行 |
| book_read | 取 run 表一格或一列 | run 或 calc；table ∈ {issuer_exposures, sector_exposures, limit_checks, factor_attributions, exposure_metrics}；column；row | 行；限额行自带 status 词，回归行自带 collinear 标志；扣留列不可见 |
| metric | 按名字取一个登记簿度量 | 名字（本面名单内）；主体；期间或参数 | 一行加组成（用了哪行、替代了什么、缺什么）；读法词随行 |
| calc | 对已有事实做一步运算 | op ∈ {add, sub, mul, div, scale, rank, top, filter, yoy, qoq, pct, cagr, sum, avg, min, max}；inputs 为 f_ id；params | 一行，made_of 指回输入；单位、期间、主体不合则拒绝并说哪项不合 |
| filings_search | 在申报文本里找 | ticker；query；filters ∈ {form, item, filed_after}；k | 段落：文本、Item、accession、字符偏移 |
| filings_section | 读一整节 | ticker；filing；item；offset | 原文，分页 |
| web_search | 申报不含的事 | ticker；query；理由；天数 | 来源：标题、URL、日期、摘录 |
| scenario | 卖或买之后的书 | run；trades | 新书 calc_ id，可被 book_read 读；重跑检查，不重拟 |
| start | 后台准备 | kind ∈ {readiness, exposure_run}；主体 | task id，不是证据 |
| submit | 交简报 | lines；caveats | 通过，或按行拒绝 |

面按资源族裁剪；跨资源靠 metric 名单而不靠人或报表：

| | 发行人分析师 | 市场分析师 | 组合风险经理 |
|---|---|---|---|
| 原始读 | filings_read | prices_read | book_read |
| metric 名单 | 30 条发行人公式，加 book.position | price 系列：波动、beta、动量、回撤、成交额、区间回报 | book 系列：净 beta、回撤事件、对账；加 price 的 beta、波动、成交额 |
| 文本 | filings_search、filings_section、web_search | 无 | 无 |
| 动作 | start | start | scenario、start |
| 共有 | list、calc、submit | 同 | 同 |
| 合计 | 9 | 6 | 7 |

意义从哪来：read 的行——读作与单位来自已声明的列（`resources._DECLARED`），when 写实际期间，means 写依据词，限额行带表里的 status，回归行带 collinear；metric 的行——登记簿条目给读作、单位、组成与替代、方向词、无意义时；calc 的行——op 词加输入，rank 给第 n 共 m，变化给升降平。9/17 的根因（工具算了方向却在事实上丢掉）在这里修在行上，不靠报表也不靠图例。

### 2.4 沟通 schema

```
ask     { analyst: issuer|market|risk, subjects[], lines[]: 金融语言一行一件事, context? }
Return  { task_id, analyst, status: settled|partial|unsettled|refused,
          lines[]: { n, asked, finding + rows[] | why + boundary_row },   // rows 由 harness 按 id 从账本附
          caveats[]: { line, text }, made[]: calc_… }                       // 无 shown、无 coverage 计数、无图例
submit  { lines[]: { n, settled, finding?, facts?: [f_…], why?, boundary?: f_… }, caveats[]: { line, text } }
          // schema 强制：settled ⇒ facts 非空；¬settled ⇒ boundary 必填；两者都有或都无直接拒绝
open    (id) → f_ 一行 | r_ 一次调用的全部行 | task_ 一位分析师的全程 log | calc_ 一本书；只读
HandoffVerdict { accepted, problems[]: { line, rule: 1..8, reason, way_out } }
AnswerVerdict  { accepted, problems[]: { tag,  rule: 1..8, reason, way_out } }
log     task_… ← ask；每步 { n, tool, args, why, → r_… k 行 }；submit → 裁决
```

主分析师每轮收到的只有四样：用户的话、桌上有什么（无数字、无度量名）、分析师回来的 Return、校验退回的句子。静态知道的：角色说明、三位分析师各一行"答什么"、含义层、风格指南。

领域分析师开工前一次给齐四样：本域有哪些数据（一段话 + 任务主体的覆盖）；任务与简报规矩；tool 列表（描述写能做什么、回来什么、何时拒绝，不写问题）；一章手册加风格指南。

### 2.5 知识层

- **登记簿**（代码）：一个条目 = key、读作、定义、单位、建在什么上、读法、无意义时、意思词、出处、执行器、所在面。今天的 `formulas.py` 30 条、`skill.METHODS` 的 price/book 执行器、`READINGS` 5 条、`integration` 的方向映射、`containment`、`units`、`resources._DECLARED` 合并进来。手册第 2、3 节由它渲染；事实的 what/means 由它渲染。
- **手册**（散文，三章六节，五禁区）：§1 问题；§2 度量（渲染）；§3 读法（渲染）；§4 比较与收尾——问题级的做法写在这里，用金融语言不写调用语法，例如：波动是否升高——拉 30 日与 252 日波动，算比，比大于一读作升高，不给阈值；是否已在价格里——事件窗口的相对回报；杠杆翻转点——目标倍数乘 EBITDA 减总债务；回报与杜邦——ROE 与净利率、资产周转、权益乘数，读作乘积恒等；§5 桌子持有什么；§6 政策。概念到度量名的映射由 `list(metrics)` 现场给，所以每条知识只在一处。
- **风格指南**（校验拥有，只此一份，八条）：数字带 id 按展示写法；最高级站在排序事实上；变化同度量同主体两个日期、比较同度量同窗口两个主体；周期写实际有的；引号只引段落与缺席原话；方向、状态、位次词与事实一致；caveat 挨着数字；不估算、不冒充、不预测、不搬数。

## 3. 步骤

每步一组提交、一个验收。第 1 步单独一轮离线全量。第 3 步在第 5 步之前：先有动词，手册里的程序才能删。

### 步骤 0 · D 轮基线——不跑（9/19 决定）

9/17 决定④的 D 轮基线取消：E 轮只与 C 轮（V37，`docs/spikes/v37`）对照。`phase_d.sh` 与 battery 备份留在原处不动。

### 步骤 1 · 事实与账本（单独一轮）

- 做什么：`services/facts.py` 的 Fact 改为 §2.2 的形状（模型面 8 字段，存储面另有类型化列）；渲染函数一处；`means` 词表进登记簿模块；缺席行带出路；常驻政策缺席在启动时上账。`db/models.py` 的 facts 表加列并迁移；`services/ledger.py` 存同一行；`services/fact_adapters.py` 出行不出 digest；`services/answer_check.py` 在 G3 加方向冲突与状态冲突（拿 means 词表查）。语料测试随之改。
- 验收：六条金标准渲染行（净 beta、余地、利息覆盖、DSO、缺席、政策缺席）逐字相等；渲染行是存储行的纯函数（测试从存储行重渲染相等）；方向冲突与状态冲突各一条红得了的测试。
- 提交：一组，只改事实形状，不与其他步同提交。

**执行记录（2026-09-19，分支 `desk-v1`）**：已完成。离线套件 2673 通过（基线 2647 加本步 26 条，`tests/test_v1_fact_means.py`），11 跳过，314 未选。

- 落地形状：存储行保留原有类型化列（`measure`、`params`、`unit`、`value`…），新增一列 `means`，只存行自己推不出来的词：`direction`、`status`、`basis`、`flags`、`reason`、`way_out`；位次、变化方向、组成分别由 `params.place/of`、`params.op` 加值的符号、`params.made_of/substituted` **渲染**出来，不抄第二份。词表与措辞在新模块 `analytics/registry.py`，词表外的词在 Fact 构造时即报错。存储层的 kind 仍是 `scalar|series|passage|absence|task`，模型面的词是 `reading|series|passage|absence`；`task` 留到步骤 3 随 `start` 一起改。
- 渲染：`services/facts.py` 的 `model_row()`（8 字段）与 `line()`（一行）；六条金标准行、"同一条存储行渲染四次相等"的纯函数测试已钉住。渲染行用英文，与桌子发给模型的其他文字一致。
- 词从生产者带到事实：`integration_service` 记账时把 `direction`、`status`、`quotable_individually` 写在数字旁边；命名器 `quantities` 读行上自己的词（limit_checks 行的 `status`，`ok` 映射为 `clear`）；`program_service` 的节点按标签携带并在 rank/top/select/filter/pick 里传下去；`fact_adapters` 的上下文同样携带；`digest.boundary` 与被拒节点的缺席带 `reason`（依赖被拒的取根因），有最近名字时带 `way_out`。利息覆盖的替代科目从 `substituted_inputs` 进 `params.substituted`。
- 常驻政策缺席：`f_policy_no_forecast`、`f_policy_no_threshold`、`f_policy_no_estimate`，句子取自沿用至今的 DESK_RULES 原文；每个 Ledger 构造时即持有，抽屉在库里查不到时回登记簿；`Ledger.shown` 给出不含它们的本 session 事实。
- 两道新检查：`sense_conflict`（事实说亏而句子说赚、net short，或反之）与 `status_conflict`（句子声称的状态与所指检查的状态无一相符）；句子带否定词或两边都说则不判。
- 库：`infra/migrations/v39_fact_means.sql`（库迁移沿用 v 编号的自身序列）、`init.sql`、`FactRecord.means`，已列入 PRODUCTION.md 的部署顺序。

**本步发现，留给后面**：
1. 净 beta 与毛 beta 在 `resources.CALC_RESULTS` 里声明为 RATIO，于是 −0.86 渲染成 "-86.0%"。beta 的单位与写法归步骤 2 的登记簿条目定。
2. `pick` 直接从 run 取单个数、`figure()` 走类型计算器解析，拿不到行上的词；步骤 3 的 `book_read` 直接读行，连词一起带，不在将退役的程序语言里补。
3. 模型现在仍经旧 digest 读数，看不到 `means` 的词，只会在被新检查拒绝时从出路里读到；词随行下发在步骤 3。`registry.py` 里的措辞是发给模型的新文字，步骤 3 接线前走措辞过目。
4. 读者抽屉的 body 已含 `means` 与 `line`，前端卡片尚未显示，随步骤 4 或 7 的读者面一起做。

### 步骤 2 · 登记簿

- 做什么：新模块（`analytics/registry.py`）承载 §2.5 的条目；`formulas.py`、`skill.METHODS` 的执行器、`READINGS`、`integration` 方向映射、`containment`、`units`、`resources._DECLARED` 迁入或被它引用；`metric` 的执行路径 = 登记簿条目 → 现有 service（`formula_service`、`price_analytics_service`、`drawdown_service`、`reconcile_service`、`integration_service`）→ 一行事实带组成。16 条 `DESK_RULES` 逐条归位：定义类进登记簿（EBIT 从净利润起算、FCF 定义、金融发行人不适用、总债务覆盖、权重代数、净 beta 方向、情景不重拟、扣留）、政策类进手册 §6（不预测、不给阈值、前提先核、比较的形状）、引用类进风格指南（数字是事实、缺席如实说）；`skill.py` 里不再有 READINGS 与 DESK_RULES 文本。
- 验收：每个条目能渲染手册 §2/§3 一段与事实一行；DESK_RULES 在发给模型的文字里出现次数 = 0；每条规则的关键短语在全部模型文字里各出现一次。

**执行记录（2026-09-19，`desk-v1`）**：条目层已完成；离线套件 2681 通过（新增 `tests/test_v1_registry.py` 8 条）。

- `skill.py` 里的 `Method`、`METHODS`（46 条）、`Reading`、`READINGS`、运算名整体搬进 `analytics/registry.py`，`skill` 只转出口，所有旧读者读到的是同一批对象；没有另起第二套条目类。条目新增三个字段：`reads_as`（金融名，行上印的）、`basis`（登记簿依据词）、`faces`（哪几位分析师可按名字要）。`registry.metrics_for(face)` 给出每个面的度量名单：发行人 33、市场 7、风险 7（含 price 的 beta、波动、成交额）；卖出与买入没有面，它们是动作。
- 度量的依据词随事实走：周转天数四条带"期末余额"，价格类带"调整收盘/成交价"，净 beta 带"书的收益"；`fact_adapters.compute` 把条目的 `basis`、公式返回的 `made_of` 与 `substituted_inputs` 都放到它生出的事实上。
- 净 beta 与毛 beta 的单位从 RATIO 改为 MULTIPLE，与 `price.beta` 一致，−0.86 不再渲染成百分比。
- `metric` 的执行路径不用新建：`compute_service.compute(method=…)` 加 `fact_adapters.compute` 就是"条目 → 现有 service → 一行事实"，步骤 3 的 `metric` 动词包它。

**顺序调整（依赖决定，非计划变更）**：旧 prompt 仍在读 `READINGS` 与 14 个域的文字，直到分析师切到新面为止；所以 16 条 DESK_RULES 的归位、READINGS 的改写、旧文字的删除，放到步骤 5（手册）与退役提交里做，那时一并进措辞过目单。实际执行顺序：2 → 3a（新动词加面，旧面仍在）→ 5（手册）→ 4（分析师切换）→ 3b（退役程序语言与旧测试）。

### 步骤 3 · 原语工具层

- 做什么：`tools/definitions.py` 注册 §2.3 的 12 个动词，JSON schema 用枚举，`why` 必填，期间类型化，输出经 fact_adapters 成行，拒绝成缺席行；`tools/faces.py` 改为三个面（`FACE_ISSUER`、`FACE_MARKET`、`FACE_RISK`）加各面的 metric 名单与 `list` 的 what 枚举；`program_service` 的原语被拎出来单步调用（fundamentals→filings_read，prices/price→prices_read，run/column/figure/pick→book_read，method→metric，算术与集合与序列→calc，sell/buy→scenario）；`run`、`compile`、签名页、符号表、`digest.HOW_TO_CITE` 下面；`program_service` 退役（9/19 决定）：原语拎出后删除 `run`、`compile`、签名页、符号表与 `docs/PROGRAM_LANGUAGE.md`；日后若做代码组合，以 12 个动词为函数面另建，不复用程序语言。
- 验收：每个动词三类单元测试（正常、拒绝带出路、越面拒绝说在哪个面）；tool 描述扫描不含手册 §1 的问题句；每面 tool 数 9/6/7；结果文本里图例长度 = 0。

**执行记录 3a（2026-09-19，`desk-v1`）：新动词与三个面已加上，旧面仍在**。离线套件 2703 通过（新增 `tests/test_v1_primitives.py` 22 条）。

- `tools/primitives.py`：11 个动词注册在面上，`submit` 仍是分析师进程内的出口。每个动词是现有 service 的薄包装：`filings_read`→`_read_fundamentals`，`prices_read`→`_read_prices`，`metric`/`calc`/`scenario`→`compute_service.compute`，`filings_search`/`filings_section`→检索服务（search 多了 item、filed_after 过滤；section 按 `PASSAGE_CHARS` 分页，回 `next_offset`），`web_search`、`start` 包原函数，`book_read` 直接读命名器的行（连同行上的状态词），`list` 只回名字与日期。`why` 在每个 schema 里必填，`web_search` 与 `start` 的 reason 就是 why。
- 面是结构：`build_analyst_registry(face)` 只注册该面的动词，`metric.name`、`list.what`、`start.kind` 的枚举也按面裁剪；三个面各自一个 MCP 挂载（`/mcp/issuer|market|risk`）。别面的动词在这里不存在（`unknown_tool`）；别面的度量名被枚举拒绝，缺席行写明"这是某某分析师可以要的度量"，原因记为 `not_on_this_face`。
- 行输出：`Tool.rows=True` 时 `invoke` 返回 `{pull, head, rows}`，行就是 `facts.line`；每次调用铸一个 `r_…`，盖在该次全部事实的 `params.pull` 上（不进身份 token），行的来历以它开头。拒绝一律铸成缺席事实上账：fn 返回的错误、参数不合、预算用完都是；后两者发生在执行之前，另记一条 completed 的 boundary 步骤，因为账本只读 completed。出路取自拒绝本身带的允许值、最近名字、数据覆盖范围。
- `calc` 的 `top` 是排序后截断；`filter` 的 `level` 可以写成桌子显示的样子（"8%"、"$1.5M"）或一个 f_ id，由同一个解析器读，分析师不做单位换算；满足的个数记成一条 COUNT 事实，满足的 id 列在 `kept`。
- 跨资源度量 `book.position`（发行人面）：某个名字在每本持有它的书的最新 run 里的权重、市值、贡献，和它那条集中度检查的三档；新服务 `services/position_service.py`，登记簿与 `compute_service` 各加一条。

**与计划的出入**：`prices_read` 没有 volume 字段（窗口读调整收盘序列，日期读当日收盘与调整收盘；成交量走 `metric price.adv`）；`list` 回的是目录行不是事实，所以不含任何数字。

### 步骤 4 · 分析师与主分析师

- 做什么：`agents/sub_analyst.py` 按面实例化三位，system 由四样组成，工具列表原生下发；每次调用的 `why` 记入 `agent_steps`，log 可按 task 重建；`agents/delegation.py` 的 submit schema 做 §2.4 的强制，`for_lead` 改出 Return（附行、无 shown、无 coverage、无 how_to_cite），`made` 从账本填；`agents/meta_agent.py` 只剩 ask、open、reply（被退回时按 tag 替换），system 加含义层与三条名册，`services/briefing.py` 清掉度量名与调用提示，只留桌上有什么。
- 验收：主分析师全部文字无度量名、无 tool 名、无登记簿 key（扫描）；submit 的四种非法组合被 schema 拒绝；从 `agent_steps` 离线重建一份沟通表与 log 相等；措辞过目。

**执行记录 4（2026-09-19，`desk-v1`）：分析师与主分析师已切到新面**。离线套件 3053 通过。

- `agents/delegation.py` 重写：`ask`（analyst 三选一、subjects、lines、context、follow_up_of；没有 facts_to_derive 与 constraints）、`submit`（lines 每条 settled 真或假，两种形状写成 schema 的 oneOf，并在 `parse_submission` 里于任何检查之前拒绝第三态；caveat 必须挂行；没有 report）、`open`（f_ 一行、r_ 一次调用的全部行、任务 id 的 log、calc_ 一本建出来的书）。同一位分析师在一次 ask 里可以出现多次，只要主体不同（几个发行人各自深挖）。
- 交接检查五条：每行恰有一条；发现里的数过答案检查；id 在账本上；未解决行的 boundary 必须是账本上的缺席（常驻政策缺席算）；caveat 指向本任务的行。报告正文那道检查随报告一起取消。
- 返回（Return）：每行三种形状之一——发现加事实行原文、原因加边界行原文、或"分析师的发现没过桌子的检查"。行由 `for_lead` 按 id 从账本读出附上，分析师改不了；caveat 贴在它限定的行上；没有 shown、coverage、cost、图例。
- `agents/sub_analyst.py` 重写：每位分析师为自己的任务打开自己面的挂载（`TurnContext.open_tools`），工具列表是该面的动词加进程内的 submit；system 是角色说明加手册本章；每次调用的 why 进 `AnalystResult.log`，`delegation.log_text` 把它渲染成 log，存进 `analyst_reports.text`（页面与 `open` 读的就是它）；原样重发（不看 why）不计费；`start` 单独计数、同主体只发一次；没交简报时铸一条缺席事实记在 completed 的 boundary 步骤上，每行以它为边界。旧的 `shown` 旁路已不存在。证据调用上限 8→16、完成数 8→10，因为一个程序现在是几次单步调用。
- `agents/meta_agent.py`：主分析师不再持有工具面；三个工具 ask、open、repair_answer；system 重写（含"用户前提先核"那条旧规则，全桌只此一处）；三个块：desk（`briefing.for_lead`：无度量名、无方法名、无调用提示，检查用桌子的叫法）、roster（手册三条）、readings（含义层）。`[table: …]` 改为指一次调用的 r_ id，旧的节点名仍可解析以兼容旧 session。
- 简报：主分析师那份去掉 domains、not_held、cannot、boundaries、read_with、科目名与方法名；被问到某个名字的分析师拿到该名字的完整条目（含哪些科目线提前结束、哪些度量算不了、索引了哪些 Item）。
- 页面契约未动：`analyst_reports` 仍按 findings/not_done/caveats 的形状存，`domain` 写分析师种类，状态词仍是 verified/refused；`meta.delegations` 的键不变，status 取 settled/partial/unsettled/refused。
- 测试：`tests/test_meta_agent_gate.py` 17 条改到新形状（端到端离线一轮：ask → 分析师开自己的面 → 行 → 简报 → 交接检查 → 带行的返回 → 答案检查）；新增 `tests/test_v1_delegation.py` 19 条、`tests/test_v1_analyst.py` 13 条；`tests/test_v36_reports.py` 的读报告四条改成按 id 打开记录；删除只钉旧形状的四个文件（test_v36_sub_analyst、test_v36_delegation、test_v36_turn_offline、test_v37_context_labels）。

**未做、留给步骤 6**：风格指南单源。引用规则现在写在两份角色说明里各一次（主分析师、分析师），还没有抽成一份共同引入的文件。

### 步骤 5 · 手册重写

- 做什么：14 章并 3 章，六节五禁区；§2/§3 从登记簿渲染；§4 收下 26 个示例程序所对应的问题，改写成金融语言的做法；名册三条从 §1 与 §5 生成；含义层 = 三章 §3 与 §6，给主分析师。
- 验收：五禁区扫描绿（无花括号、美元符、键路径、调用形式；无"小于零意味着"类输出约定句；正文无数字与 ticker 作主体；每句只在一处）；能问⇔可达：§1 每一行对应 §4 一条做法，做法点名的度量都在本面 metric 名单里（机械）；措辞过目。

**执行记录 5a（2026-09-19，`desk-v1`）：手册模块与内容已写好，尚未接进分析师（接线在步骤 4）**。离线套件 3089 通过（新增 `tests/test_v1_handbook.py` 386 条，绝大多数是逐句扫描）。

- 新模块 `analytics/handbook.py`：三章（发行人、市场、组合风险经理），每章六节。第 2 节（度量）由登记簿条目渲染：金融名、定义、依据词、无意义时、出处；公式类的两条公共失败条件提到节首说一次，代码里的常量名不渲染。第 3 节（读法）由 `registry.READS` 渲染，第 6 节（政策）由三条常驻政策缺席的原句渲染，所以政策只写一处。第 1、4、5 节是人写的：每个题目（Topic）同时带"能问什么""怎么比""怎么收尾"，并用登记簿 key 记下它依靠哪些度量（不渲染），章在构造时校验这些 key 都在本面名单里。
- 问题级的做法写在第 4 节，用金融语言：波动是否升高（短窗对长窗，比值）、是否已在价格里（事件窗口相对市场的回报）、杠杆翻转点（目标倍数乘 EBITDA 减债务）、回报的杜邦三项、到某档要卖多少美元、关闭余地的价格变动、变现天数（市值除以参与率乘日成交额）。
- 登记簿新增 `READS`（10 条去掉符号约定、活数据之后的读法，含两条书的列读法）与 `INSTRUMENTS`（七个因子工具各是什么、代表哪种风险；不说系数怎么取号）。旧的五条 `READINGS` 仍被旧分析师 prompt 渲染，随它一起退役。
- 主分析师的两样：`handbook.roster()` 三条（答什么、能问什么、缺什么及原因），`handbook.meaning_layer()`（全部读法、因子工具、政策）；扫描确认其中没有度量 key、动词名。
- 五禁区各有扫描：调用语法与键名、输出约定句式、校验规则短语、数字与 ticker、同句两处；16 条旧 DESK_RULES 里归手册与登记簿的 15 条各有一个关键短语，断言在全部新文字里恰好出现一次（"用户前提先核"那条归主分析师角色说明，步骤 4 落）。

**与计划的出入**：事件扫描没有放在风险经理一章。风险面没有文本工具，持仓名字的事件由主分析师按名字派给发行人分析师（它有 `book.position`，能说这条消息碰到多大的仓位）。

### 步骤 6 · 风格指南单源与校验

- 做什么：`services/style_guide.py` 唯一承载八条，两份角色说明各引入一次；`answer_check`、`handoff_check` 的拒绝按 §2.4 的 verdict 形状带规则号与出路；其他地方的复述删除。
- 验收：八条关键短语在全部模型文字里各出现一次；A-R1 的重发规则测试仍绿。

### 步骤 7 · E 轮

- 做什么：同 fixture、同 20 题，与 D 轮（若跑）和 C 轮对照；模型分配作为变量：主分析师强模型、领域分析师弱模型各跑一遍。
- 量：每题派单次数、每任务调用次数与 why 的可读性、prompt 峰值、拒绝率、方向与状态冲突数、缺席事实里算术类占比（决定是否加动词）。
- 验收：按节点沟通表分析；实测期冻结代码。

## 4. 代办（不进本轮，单独标记）

| 代办 | 内容 | 触发条件 |
|---|---|---|
| **RAG 召回** | `filing_chunks` 加关键词索引（tsvector/BM25）做混合检索；嵌入前给每段加 50–100 token 的上下文前缀（Anthropic contextual retrieval：top-20 漏检 5.7%→1.9%）；加 rerank；评估集从 C/D/E 轮的 read_filings 调用构造 | 步骤 7 之后单独一轮；本轮只做两级检索（list → search → section） |
| **代码组合** | 先单步。若 E 轮显示调用次数或 prompt 峰值是瓶颈，评估 programmatic tool calling / code mode：12 个动词作为沙箱内可调用函数，循环与过滤在沙箱里，账本仍逐步记；以动词为函数面另建，不复用已退役的程序语言 | E 轮数据 |
| 估值倍数 | P/E、EV/EBITDA、FCF 收益率，价格乘申报，登记簿新条目 | 步骤 2 之后 |
| web_fetch | 今天只存 Tavily 摘录；取全文要新动词 | 有题目需要时 |
| 市场分析师去留 | E 轮量它单独被派的比例，决定是否并入组合风险经理 | E 轮数据 |
| docs/spikes 清理 | 二十多个测试与脚本从那里读语料 | 单独一轮 |

## 5. 拍板记录

9/19 已拍板：`program_service` 退役（步骤 3）；D 轮不跑（步骤 0）；K5 五文件 stash（`git stash list` 第一条）；归档与本计划先提交；执行分支 `desk-v1`。

仍未拍板：`metric` 作为独立动词（本计划按保留执行；若拍掉，则 §2.3 只剩 read 加 calc，登记簿的组成与替代记录改由 calc 承担）；push。

## 6. 验收总表（机械，红了就是越界）

| 边界 | 验收 |
|---|---|
| 事实自明 | 六条金标准行逐字相等；渲染是存储行的纯函数 |
| 意思在账本上 | 方向冲突、状态冲突测试红得了 |
| 每条知识只在一处 | 八条风格指南与十六条旧 DESK_RULES 的关键短语在全部模型文字里各出现一次 |
| 手册不含调用语法、输出约定、活数据 | 三条扫描 |
| 能问⇔可达 | §1 每行对应 §4 一条做法，点名的度量在本面名单里 |
| 工具只认资源不认问题 | tool 描述不含 §1 问题句；每面 9/6/7 |
| 面裁剪是结构 | 越面调用返回缺席并说在哪个面上 |
| 主分析师无词汇 | 扫描：无度量名、无 tool 名、无 key |
| 图例为零 | 工具结果与派单结果附带的读法文字长度 = 0 |
| log 由 why 长出 | 从 agent_steps 重建的 log 与实际调用序列相等 |
| 旁路已拆 | `shown` 不存在；pick 字面量路径不存在 |

## 7. 归档记录（2026-09-19）

提交 `6994b28`（issuer-intelligence，9/19），执行分支 `desk-v1` 从它开出。`git mv` 到 `docs/archive/plans/`：`IMPLEMENTATION_PLAN.md`、`IMPLEMENTATION_PLAN_V2`–`V38`（含 `V3R`）共 30 份，加 `MCP_PLAN.md`；归档目录有 README 说明"不再阅读"。README.md 的两处链接改指归档路径并指向本计划。代码与测试对旧计划只有注释级引用，无运行时读取，未改。`docs/spikes/` 未动。
