# Implementation Plan V3-R — 对抗式 review 修复(Verify 层收口)

> 定位:V3 建成了验证层,对抗式 review(5/6 维度交付,发现均经本人独立复现)证明它
> "对看见的数字严格,但整类句式看不见"。V3-R 不加任何新功能:它决定 V3 已建的东西是真是假。
> 输入:review 发现清单(见 V3_COVERAGE §Adversarial review,R9 补写)+ 本人复现记录。
>
> 三个已复现的核心事实,本计划全部围绕它们:
> ①`-$81.615B` 抽取后 value 为 **+81,615,000,000**(符号轴整体缺失);
> ②模型经 `think`/回显工具可把**任意 id** 写进 evidence trail;
> ③`"Your holdings are AAPL 5000"` 抽取结果为**空** → 零引用放行,A0-1/A1 双双失效。

---

## 0. 执行者须知

### 0.1 全局规则(继承 V1/V2/V3 全部,新增两条本阶段专属)

1. **先红后绿**:每项修复必须先把 review 的复现脚本固化成一个**失败的**测试,看它红,再修,
   看它绿。复现探针转为回归测试是本阶段一半的交付物。
2. **改抽取器必重跑语料**:任何触碰 `numeric_verification.py` 抽取/豁免/匹配逻辑的提交,
   必须重跑 `scripts/eval_faithfulness.py` 并把数字变化写进 commit message。A1d 已经证明过
   一次:第一版修复(最小位数)被语料否决。禁止用放宽容差掩盖误拒。

### 0.2 钉死的实现常量与决策

| 项 | 值 | 依据 |
|---|---|---|
| 符号范围 | 前缀 `-`/`+` 进入 `value`;**会计括号负数 `(135,441)` 不做** | 全语料零实例;做了就要区分"括号=负"与"括号=补充说明",引入新误判轴。写进 known limits |
| harvest 收紧规则 | `_harvestable` 追加两条正交条件:**结果含 `"error"` 键不收**、**REFLECTION 类不收** | 三条已复现注入向量(think、get_task_status/get_portfolio_positions 的 unknown 分支)被这两条全覆盖;不打逐工具补丁 |
| designator 豁免新形状 | **两支**:①数字紧贴字母 `[A-Z][A-Za-z&.]*\d{2,4}`(H200/B200/GB200);②**枚举闭集**的带空格名称,初始名单:`S&P 500 / S&P 400 / S&P 600 / Nasdaq 100 / Russell 1000 / Russell 2000 / Russell 3000 / Fortune 500 / Microsoft 365 / Dow 30` | 带空格+任意大写词的旧形状是洞的根源;枚举闭集正是 §0.3 豁免表的既定哲学(加名字=改表+加测试) |
| year 豁免补丁 | 追加 `(?<!\$)` 与 scale 词负向前瞻 | `$2000`/`1950 million` 按构造不是年份 |
| `pos_` 身份 | positions 进 harvest/gate/resolver 三处 + `_VALUE_SOURCES`(quantity → COUNT);**seed 的 10 行裸 UUID id 由 migration 改写为 `pos_` 形**并修 seed 脚本 | 实测:44 行 positions 有 10 行(全部 port_001 demo seed)是裸 UUID —— V1 `alert<hex>` 同款 bug 第三次出现。positions.id 无任何外键引用,改写安全 |
| open_questions 数字策略 | 数字出现在 open_questions → 按该 brief **全部引用的并集**验证;不过 → 拒绝提交,提示"移入带引用 block 或删去" | 与全严格拍板一致;问题句里的数字仍是展示给用户的数字。★ 拍板点 1(见 §0.4) |
| MCP 会话预算 | `create_session` 加显式 `per_turn: bool = True` 参数;MCP 传 `False` → `turn_tool_budget=NULL` 维持终身 40 | 兑现 V3 文档已经声称(但代码没做)的"MCP 维持终身语义" |
| migration 幂等修补 | `tool_budget 0→NULL` 清扫加 `AND started_at < '2026-08-02'` 谓词 | 现状:每次部署重跑,把部署后写入的 kill-switch 0 抹回 NULL |
| `_LIT` 小数修补 | 允许无整数位小数:`.5%` 抽为 0.005,不再错读成 `5%` | 差十倍的错读比漏抽更糟 |
| scale 词边界 | `\b` 后追加 `(?![&-])` | `3 M&A`/`10 T-bills`/`25 K-1` 不再是数量 |
| COUNT 兼容性 | **不动**(COUNT 仍可匹配任意类) | 裸数字不声明单位是设计;收紧属语义变更,记入 known limits 供下一轮议 |
| `get_portfolio_positions` 上限 | 工具返回加 `limit=50` + 显式 `truncated: true` 标记与总数 | CSV 上限 200 行,6000 字符截断必然撑破成非法 JSON;截断必须模型可见 |

### 0.3 顺序与依赖(单人串行)

```
R1 符号 ──→ R3 豁免洞 ──→ (语料重跑 ×2)
R2 trail 收紧(独立)
R4 pos_ 身份(依赖 R3:豁免洞不修,持仓句抽不出数字,R4 验收无法表达)
R5 open_questions(独立,依赖 R1 的 verify 签名不变这一事实)
R6 MCP 预算 + migration 谓词(独立,同一提交:都是 B2 的收口)
R7 minors + 文档失真批改(依赖 R1-R6 全部落地,数字才是终值)
R8 测试完整性:RLS 测试改 app_rls 角色连接、read_issuer_brief 归属字段、截断上限
R9 收口:V3_COVERAGE 补 Adversarial review 章节 + 全量重测 + live 复验
```

R1 与 R3 之间必须重跑语料一次(R1 单独的影响可度量),R3 后再跑一次。

### 0.4 拍板点

1. **open_questions 策略**:本计划钉"按并集验证,不过即拒"。备选是"open_questions 禁止出现
   实质数字"(更简单更严,但会拒掉"capex 会维持在 $17B 以上吗?"这类合理问句)。
   如无异议按钉死值执行。
2. **designator 枚举名单**的初始内容(§0.2)。执行中语料若再暴露合法名称,按"改表+加测试"
   流程追加,不需要重新拍板。

---

## R1 — 符号(blocker)

**改动点**:`numeric_verification.py`
- 抽取(~L208-243):`magnitude` 解析后,若 `surface.lstrip()` 以 `-` 开头(或 `($` 前的 `-`),
  `value`、`atol` 不变符号但 `value` 取负;`+` 显式为正。`key` 保持无符号(引文路线按数字串
  匹配,符号由结构化路线判)。
- `verify()`:比较本就是 `abs(v.value - n.value) <= atol`,值带符号后自动正确,**不改判据**。
- 死代码 `key=literal.lstrip("+-")` 的注释改为说明 key 无符号是引文路线的刻意选择。

**测试(先红后绿)**:
- offline 新组 E(符号轴):`-$81.615B` 对正证据**拒**、对负证据**过**;`-1.1%` 同;
  `+85.2%` 仍过;`daily_pnl -16450` 类真实值样例。
- live:D2 回放集补 3 条含负值的问答样例(用真实 run 的负 daily_return 构造),
  `test_numeric_verification_live.py` 加"负值证据可被正确引用"。

**验收**:复现脚本红→绿;语料重跑,brief 14 条拒绝的构成变化逐条解释(负号修复理论上不改变
现有 14 条——它们全是正数——若有变化必须查明)。

## R2 — Trail 收紧(blocker)

**改动点**:`registry.py`
- `_harvestable(tool, status, result)`(签名加 `result`):
  `status == "completed" and tool.tool_class not in (GATE, REFLECTION) and "error" not in result`。
- docstring 同步:harvest 的语义收紧为"**成功检索的返回值**才是证据;错误载荷与模型自述不是"。
- `test_tool_registry.py:107` 那条把洞钉住的断言(`_harvestable(read,"completed") is True`)
  反转为按新签名的三组断言(error 载荷 False / REFLECTION False / 干净 READ True)。

**测试**:
- offline:三条已复现注入向量各一条回归(think 回显、`unknown_job` 回显、`unknown_portfolio`
  回显 → harvest 结果为空)。
- live:重演投毒序列(fresh session → 只调 think/get_task_status → `_respond` 引用该 id)
  → 必须被 `not_in_evidence_trail` 拒。

**验收**:投毒复现脚本红→绿;既有 89 live 全绿(delegation 工具的 run_id harvest 不受影响——
它们的成功载荷不含 error 键)。

## R3 — 豁免洞(major,连带 A0-1)

**改动点**:`numeric_verification.py` `_EXEMPTION_PATTERNS`
- designator 拆为两支(§0.2 钉死形状);枚举名单为模块级 tuple(数据,不是正则片段),
  加名字 = 改 tuple + 测试。
- year 加 `(?<!\$)` 与 `(?!\s*(?:{_SCALE_ALT})\b)`。

**测试**:
- offline:`AAPL 5000`/`Backlog 2500`/`A 500 basis point`/`USD 5000`/`$2000`/`1950 million`
  全部**抽得出来**;`H200`/`S&P 500`/`Microsoft 365`/`Russell 2000` 仍豁免;
  gate 集成:`"Your holdings are AAPL 5000, MSFT 3500."` 零引用 → `citations_required`。
- live:语料重跑;新增误拒逐条读并分类,超出 §0.1 规则 2 的解释义务即回退方案重议。

**验收**:A0-1 绕过复现红→绿;语料数字进 commit message。

## R4 — `pos_` 身份(major,C3 收口)

**改动点**(三方相等测试会强制同步,漏一处直接红):
- `evidence_trail_service._RESOLVERS` + `registry._ID_PREFIXES` + evidence_resolver 加 `pos_`;
- `numeric_verification._VALUE_SOURCES` 加 positions 路线(quantity → COUNT;market_value 不给
  ——它属于 run,position 行上的价格快照正是 V2-E5 清理过的三套约定之一,不得复活);
- `portfolio_service.positions_with_weights` 每行带 `pos_id`;
- `infra/migrations/v3_harness.sql` 追加(幂等):demo 10 行裸 UUID id 改写为
  `'pos_' || replace(id,'-','')` 形;`scripts/seed_demo_db.py`(或 `_generate_seed_data.py`)
  修铸造;init.sql 若含字面 id 同步。
- RLS:positions 已有 `tenant` 策略(实测确认),`pos_` 的 `_exists_in_db` 在 RLS 下天然
  只见可见行——**这正是要的行为**(引用不可见持仓 = unresolved)。

**测试**:
- offline:三方相等测试自动覆盖;抽取器对 `5,000 shares` 的 COUNT 匹配 positions 值。
- live:`"You hold 5,000 shares of AAPL"` 引 `pos_` → **过**(现状:必拒);demo 组合的
  10 行改写后 `read` 回的 id 全部 `pos_` 形且可 resolve;UI 证据抽屉能钻取 `pos_`。

**验收**:C3 的验收查询(quantity 类问答)端到端过 gate;三方相等测试绿。

## R5 — open_questions(major)

**改动点**:`research_tools.py` `_submit_brief` 数字循环后追加 open_questions 特例
(按 §0.2 钉死策略);`scripts/eval_faithfulness.py` 的 `BLOCKS` 补上 open_questions
(按同规则度量);`brief_service._BLOCKS` 不变(渲染面本就包含)。

**测试**:offline——含编造数字的 open_questions 被拒、含"并集可验证"数字的过、纯文字问句过;
live——D2 重跑,3 份存量 brief 的 open_questions 若新增拒绝,逐条分类进天花板注释。

## R6 — MCP 预算 + migration 谓词(major/hygiene,一个提交)

**改动点**:`agent_session_service.create_session(per_turn: bool = True)`;
`apps/mcp/server.py:67` 传 `per_turn=False`;`v3_harness.sql` 清扫加 `started_at` 谓词;
PRODUCTION/V3_COVERAGE 两处"MCP 维持终身"表述从**谎言改为事实陈述**(不改文字,改代码使其为真,
并注明 R6 兑现)。

**测试**:live——MCP 建的 session `turn_tool_budget IS NULL` 且第 16 次 reserve 仍成功;
migration 重跑后,一个部署后手工置 0 的 tool_budget 保持为 0。

## R7 — Minors + 文档失真批改(一个提交)

- `_LIT` 允许 `.5` 形;scale 边界 `(?![&-])`;各一条测试。
- **docstring 头牌例子更换**:单位类的论证例子换成真实成立的(money↔ratio 混淆:
  `$0.16` 不得匹配 alert 的 0.158 ratio——现测试已断言);alert 同行三列的例子移到
  "A1 是存在性检查"的 known limit 下,如实说明单位类**分不开同类混淆**;
  `test_a_percent_may_not_be_matched_against_an_unrelated_scale` 改名并改断言语义,
  使测试名、docstring、V3_COVERAGE 三方一致。
- 文档陈旧批改:PRODUCTION §4 "40 tool calls/conversation"→15/turn 双轨表述;
  MODULE_NOTES:388 同;MODULE_NOTES:528 的 check_limits 失真句(S1 漏改的那条);
  MCP_BOUNDARY_PLAN §1 现状基线 12→16/裁剪 8→4;README "identical face" 改为如实
  (差 4 个工具,face 守卫钉着);V3_COVERAGE totals 表更新至终值。

## R8 — 测试完整性(major,证明力修复)

- `tests/test_memory_tools_live.py` 与 C 相关 RLS 断言改用 **`app_rls` 角色 + 显式租户**连接
  (bypassrls 超级用户测 RLS = 测了个寂寞);补两条:匿名只见 public brief、
  B 租户查 A 的 rrun_ 得 `unknown_job`。
- `read_issuer_brief` 返回加 `is_own` 与 `research_run_id`(归属可见;字段名沿用 snapshot 的
  `is_own` 先例);ChatPanel 不改(信息已在 payload,UI 呈现属后续)。
- `positions_with_weights` 加 `limit=50` + `truncated` 标记 + `total`;工具 schema 文档化。

## R9 — 收口

- V3_COVERAGE 补 **Adversarial review** 章节(V2 先例):维度数、发现数、复现数、修复数、
  驳回数(带理由)、未验证遗留(第 6 维度未跑 + 判为 known limit 的),终值数字表全部更新。
- 全量:offline + live 全绿;语料终跑;真栈 rebuild + 三条 live 抽查
  (负值问答、持仓 quantity 问答、投毒序列被拒)。
- MODULE_NOTES M15 追加 V3-R 小节:两条新踩坑写入(**豁免正则的每一支都要有对抗测试**、
  **"测 RLS 必须用非特权角色"**)。

---

## 附:非目标(本阶段明确不做)

- 会计括号负数、拼写体百分数("74.93 percent")的抽取——各记 known limit,语料零/一实例;
- COUNT 兼容性收紧(§0.2);
- `think` 改为不回显——harvest 层已正交关闭,工具行为不动;
- 第 6 维度(并发/预算)review 的补跑——其覆盖面(reserve 竞态、租约互动)已有 V2/V3 live
  测试基础,遗留风险记入 V3_COVERAGE,不在本阶段展开;
- MCP face 显式化(仍属 MCP_BOUNDARY_PLAN)。

## 附:工作量与提交切分

| 提交 | 内容 | 估量 |
|---|---|---|
| V3R-1 | R1 符号 + 语料重跑 | 0.5d |
| V3R-2 | R2 trail 收紧 | 0.5d |
| V3R-3 | R3 豁免洞 + 语料重跑 | 0.5d |
| V3R-4 | R4 pos_ 身份 + seed/migration | 1d |
| V3R-5 | R5 open_questions + R6 MCP/migration | 0.5d |
| V3R-6 | R7 minors/文档 + R8 测试完整性 | 1d |
| V3R-7 | R9 收口(coverage/M15/live 复验) | 0.5d |

总计约 4.5 人日当量;每步全量跑 offline,R2/R4/R8 各带 live。
