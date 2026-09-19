# IMPLEMENTATION_PLAN_V16 — 单位代数:缺的名字存在,名字带意义,不确定的量不上桌

> **状态:2026-09-01 执行完成并上线**(commits `d920276..` + build 第二收缩相修复;
> 1818 offline / 246 live 全绿;mapping v4 已重映射 2,472 行;S0/S6 电池存档
> `V16_BASELINE.json` / `V16_S6.json`,判分见 `docs/spikes/V16_COVERAGE.md`——
> **顶替 S0≥2 → S6=0**,Validation 本批零新增成立)。§7 六项当日按四条设计法律
> 裁决执行(单位代数进类型系统、EV 双 as-of、Tier 2 开放全面、最低观测数=生产者
> 参数、JPM 银行分支推 V17),唯一保留给 boss 的是**模型可见措辞过目**(清单在
> session 交付物里)。依据不是权威(V8 纪律):计划与代码不符时以实测为准——本次
> 回写两处:窗口标签豁免已在 V15 存在无需再加;build 收缩对非 run 申报无路的
> 死角是执行中实测新发现,已修并双 pin。
> 前置:V15(桌面)已上线。调研与盘点见 `dev_note/portfolio-demo/analyst-skills/14-analysis-catalog-and-the-third-asymmetry.md` 与 `research_scratch/A–E`。

---

## §1 目标

V15 之后,门那一半已经收敛(三轮实测:尝试中位 5→2→1,拒绝 79%→50%→20%,无答案 0)。
剩下的失误**全部是门按构造接受的**:模型指错名字,或者要的名字根本不存在。
分析师问题的最大一类(价 × 基本面,54 个模板里的 30 个)结构性无法回答——不是缺数据
(股数/EPS/分红/回购全在库里,十个持仓 832–894 根日线),是那一层的量没有名字。

V16 延续同一条方向:**把"模型必须记住/门必须检查"的事,改写成"结构使其不可能或使其可见"**。

- 缺的名字存在:价格进类型系统,一条单位代数让整个价 × 基本面层由组合到达(M1);
- 名字带意义:桌面条目从 `名字 → 值` 变 `名字 → (值, 组, 读者名)`(M2);
- 不确定的量不上桌:观测数不足与共线同类,在生产处投影掉,不进答案路径(M3);
- 方法与算术分两层:登记表(具名 + 出处 + 失效条件)与模型命名的临时组合(Tier 1 / Tier 2)。

**Validation 层零新增**——这是方案自洽的检验:每一条新正确性都由类型、投影或登记表承担。

## §2 诊断(实测与调研,详见 14 号笔记)

1. **第三个不对称**。发行人基本面与组合 run 各有四件套(身份/清单/具名生产者/知识);
   价 × 基本面与单名价格分析两层全无。每补齐一层,失败就从"编数字"退到"指错名字",
   再退到"名字不存在"——pass-3 仅剩的实质失误(`net_exposure_pct` 被当利率敞口、
   `limit_value` 被当 room left、金额槽进日期句)全是后两类。
2. **缺的是名字不是数据**。八家全有稀释 EPS(345 行)、稀释加权股数(281)、封面股数(157)、
   回购(319)、分红(194)、SBC(302),未映射;`market_prices` 有 close 与 adj_close。
3. **对齐规则今天靠模型记**。复权/未复权、三种股数各配什么、价格日 vs 期末日、TTM vs 单季——
   B 路九条跨切面陷阱里六条应是量的属性或类型规则,不是提示词。
4. **估计量没有确定性守卫**。C 路给了每个估计的最小观测数(波动率 20、单因子 beta 硬下限 60、
   历史 VaR95 250、ES97.5 250…),我们一条都没有;而"共线单系数不上桌"已经证明了正确的处理形态。
5. **外部确认了最难的一件已做对**:累计申报/Q4 推导即 V9 区间代数,不动。

## §3 架构

### M1 · 价格进类型系统 + 单位代数

`typed_calculator.Typed` 已有 `(value, unit_class, instant|interval, quantity, issuers, recorded_basis)`。
价格是一个 instant 上的量,进不来只因为没有产生它的原语、以及单位里没有"每股"。

**单位代数**(取代 multiply/divide 的"取左类"欠定义):

```
money_per_share × count           = money          (市值)
money           ÷ count           = money_per_share (每股账面价值、每股 FCF)
money           ÷ money_per_share = count
money_per_share ÷ money_per_share = ratio           (P/E:价 ÷ 每股盈利)
money           ÷ money           = ratio           (既有)
同类 ± 同类      = 同类;跨类 ±    = 拒绝            (既有)
```

**原语**:`get_price(ticker, at)` 与 `get_price_series(ticker, window)`,产出带 `instant` 的量;
`close` 与 `adj_close` 是**两个量**(`quantity` 不同,`do_not_combine_with` 互指):
复权序列只做收益算术,任何"价 × 股数"必须用未复权价——混用从"模型要记的规则"变成类型拒绝。
序列侧补一个 `regress(series_a, series_b)` 原语(单名 beta;组合因子模型的机器已有)。

**对齐即类型**:市值 = `calculate(multiply, price, cover_shares)`,两个 instant 不同即拒
(`different_instants` 既有);EV = 市值 + 债务 − 现金,混合价格日与资产负债表日时
**结果如实携带双 as-of**(`recorded_basis.mixed` 既有形态)——不放宽、不假装同一天,
"截至两个日期"本身就是产品。

### M2 · 意义随量上桌

桌面条目从 `名字: 值` 变 `名字: (值, 组, 读者名)`。组与读者名**已经是数据**
(`describe_run._RUN_GROUPS` 的 8 个组、`resources.Column.display`),只是没进切片。
组是 8 个键不是 235 句话,载荷代价可控(S3 判据钉上限)。
`describe_issuer`/`describe_run` 的分组顺序按 A 路的分析师阅读顺序重排:
**现金 → 收入 → 利润率 → 资产负债表 → 回报率 → 筛子**
("从比率表开始的分析师解释比率;从现金开始的分析师解释生意")。

### M3 · 不确定的估计不上桌

与 `not_alone` 同一类、同一处置:**估计量的确定性由算它的代码判定,不确定即不进桌面投影**。
波动率 n<20、单因子 beta n<60、历史 VaR95 n<250、ES97.5 n<250、Amihud n<200——
下限是**生产者的参数**(带 C 路出处,写在产生该量的模块里),不是门里的阈值,
不在答案路径上出现。被投影掉的量在清单的 `not_available` 里带原因
("42 个观测不足以确定一个 beta"),模型看不见值就写不出值。

### Tier 1 / Tier 2 · 方法与算术分两层

- **Tier 1 登记表**:`formulas.py` 是"方法定义进数据,有出处"。新增条目是知识行为:
  定义 + `authority` + `note`(陷阱)+ **失效条件**(分母为负 → 拒绝并铸缺席行;
  银行 → `_bank_refusal` 形态扩展到 EV/FCF/Merton 类)。首批 ~10 条(§4-S5),不一次塞完。
- **Tier 2 临时组合**:`calculate` 的 `as_quantity` 参数开放到面上——模型给自己算的量命名
  (V15"写名字不写值"往上挪一层:**写它算的是什么**)。行上记操作数与 basis,
  桌面与渲染标为"本会话算出",与登记表的"本台定义"可区分。量空间由此开放而非枚举。

### 边界(更新后)

| 层 | 负责 | 不许做 |
|---|---|---|
| Tool(投影) | 带四件套的量:身份、basis、意义、确定性;类型系统(含单位代数)执行全部对齐与双重计数;清单说有什么/缺什么/这个面不能做什么 | 判断;替模型决定问题需要什么 |
| Skill(知识) | 挂在对象上的选择知识:量的 note/`do_not_combine_with`、登记表 authority + 失效条件、face 能力声明;note 随关系走 | 路由器、SOP、阈值、堆提示词 |
| Agent(智能) | 取什么、组合什么、**给组合命名**、组织论证 | 产生数字;写不在桌上的名字;记数据布局 |
| Validation(解析) | 五个查找(V15 不变) | **本批零新增** |

挪动的边界:对齐规则 模型记忆→类型系统;确定性 门→投影;量的意义 manifest→桌面条目;
临时计算的命名 无处→Agent;方法权威 注释→登记表数据。

## §4 排程(单人约 7.5 人日;每步 offline 全绿 → commit;S6 前不 build 镜像)

| 步 | 交付物 | 判据 |
|---|---|---|
| **S0 · 缺口基线**(0.5 天) | 14 号笔记 §7 的 8 题缺口电池今天先跑一遍存档(`docs/spikes/V16_BASELINE.json`):记录每题今天是拒绝、顶替还是编造 | 基线在手;**中止判据先写死**(见表下) |
| **S1 · 单位代数 + 价格原语**(1.5 天) | `typed_calculator` 单位代数(表驱动,不是 if 链);`get_price`/`get_price_series` 工具(两面均可用?issuer 作用域→都可);`close`/`adj_close` 两个量;`regress` 序列原语 | 代数每条规则一测且封闭(表外组合拒);市值→EV 全链在真库上算通且 EV 带双 as-of;`adj_close × shares` 被类型拒 |
| **S2 · 股数与每股层映射**(1 天,concept_mapping v4) | 三种股数为三个量(各带用途与 `do_not_combine_with`)+ `eps_diluted`、`dividends_paid`、`buybacks`、`sbc`(先这七个,R&D/PP&E/goodwill 后批);先验语料再映射(V11 tag-drift 纪律) | `describe_issuer` 列出三股数且各说配什么;加权股数 × 价格被知识警示、期末股数配余额;八家 EPS/股数最新期 ≥2026-03 |
| **S3 · 桌面四元组 + 清单重排**(1 天) | 切片 `名字: [值, 组]` + 清单携带读者名;`describe_issuer`/`describe_run` 按阅读顺序分组 | 整 run 切片 ≤ `TABLE_CHAR_LIMIT` 仍成立;V3 问句重放:利率问题命中 `factor_exposure` 组(人工判) |
| **S4 · 确定性投影 + 单名价格量**(1.5 天) | 单名滚动波动率、beta(经 `regress`)、动量 12-1、52 周位置、ADV/可变现天数,每量携带 n;下限为生产者参数(带出处);不确定→不上桌 + `not_available` 带原因 | n 下限逐条有出处注释;n<60 的 beta 在桌面缺席且清单说明;`test_determinacy` 钉"值与 n 同行,无 n 不上桌" |
| **S5 · Tier 1 首批 + Tier 2 开放**(1.5 天) | 登记表 +10:ROE、ROA、ROIC、DuPont(3步)、asset_turnover、quick_ratio、CCC、fcf_margin、capex_intensity、net_debt_to_ebitda——各带 authority/note/失效条件(负分母拒绝);`calculate.as_quantity` 进 schema,结果标 `session_named` | 16→26 条;零阈值纪律不破(`test_v9_formulas`);负权益的 ROE 拒绝并铸缺席行;Tier 2 行在渲染与桌面上与登记表可区分 |
| **S6 · 验收与切换**(1 天) | 缺口 8 题 + 原 8 题电池对照 S0;四镜像重建 → 容器内 grep → smoke_ui;wording 三处(新工具描述、清单文案、Tier 2 标注)列表提交过目 | ① 缺口 8 题:**能算的给具名槽,不能算的给有原因拒绝,顶替 = 0**(人工判,逐题记录);② 原 8 题错误接受(指错名字)不高于 pass-3;③ `read_required_inputs` 按"量上桌且被引"重述后 ≥ pass-3;④ 拒绝率与尝试中位不劣化 |

**中止判据(先写死)**:S1 后单位代数使任何既有绿测转红且属真回归 → 停,S1 回滚,S2–S5 各自独立评估;
S6 若缺口电池"顶替"仍 >2/8 → M2 判定不足,记录并停在 S5,不追加规则补丁。

## §5 结构守卫

| 测试 | 钉住 |
|---|---|
| `test_unit_algebra.py` | 代数表驱动、封闭:每条规则一测,表外组合拒;multiply/divide 无"取左类"路径残留 |
| `test_price_quantities.py` | `close`/`adj_close` 两个量;`adj_close` 参与任何 × 股数被拒;价格量带 instant 与 issuer |
| `test_share_counts.py` | 三股数三个量;两两混用被知识/类型拦;EPS × 期末股数 ≠ 净利润(加权 vs 期末不互换) |
| `test_determinacy.py` | 不确定的估计不进桌面;下限来自生产者参数且带出处;`not_available` 带原因;门里无任何 n 检查 |
| `test_table_meaning.py` | 切片三元组;组 ∈ 声明的组集;载荷上限 |
| `test_tier2.py` | `as_quantity` 落 `result_type.quantity` 且行标 `session_named`;登记表名与 Tier 2 名冲突时拒绝命名 |
| `test_registry_conditions.py` | 每条新公式有失效条件或显式声明无;负分母 → 缺席行(不是 0,不是 NaN) |
| `scripts/gap_battery.py` | S0 vs S6 对照;逐题记录 具名槽/有因拒绝/顶替 三态 |

## §6 明确不做

- **自动补取**(模型没取的量替它取)——fallback。缺席可见 + 清单便宜是全部手段,行为归模型。
- 句子角色 vs 单位的检查——散文语义,V14-B 边界;渲染让荒谬自证。
- 历史倍数序列——每家仅 2–3 份申报,point-in-time 序列不可建;当期可建,清单如实写原因。
- PEG、reverse DCF、peer 回归、EV/IC(B 路对 10 名风险台的明确排除);TSR 分解/CAR/Merton DD
  推到 V17(依赖 S1–S2 落地后的组合,且 Merton 是带假设的方法,登记表条目需单独审校)。
- LLM judge、答案路径上的任何阈值、按问题类的路线。

## §7 待拍板

1. **单位代数进类型系统**(M1 核心)。不做则价 × 基本面要写 ~30 个工具。
2. **EV 双 as-of** 作为产品形态(替代方案"用最近资产负债表假装同一天"是 fallback,不提供)。
3. **Tier 2 开放给面**——风险:模型给组合起错名(意义错误,门不拦,读者可穿透)。可选折中:先只开研究面。
4. **Tier 1 首批清单与每条 note/失效条件的措辞**——落库前过目(S6 一并列表)。
5. **最低观测数作为生产者参数**(数值取 C 路出处)是否接受;及 beta 用 60 硬下限还是 250。
6. **银行分支扩展范围**(JPM):EV/FCF/Merton 拒绝之外,P/B、P/TBV、股息率是否本批为 JPM 开(建议否,V17)。

---

## 附录:实测依据

**三轮电池走势**(V15_COVERAGE):尝试中位 5→3→2→1;拒绝 79%→70%→50%→20%;无答案 0;
pass-3 仅剩失误全为门接受的指错名字。

**缺口量化**(14 号笔记 / research_scratch):54 模板中 F+P 占 30,今天 0 可答;
H2 17 个量输入已映射;股数/EPS/分红/回购/SBC 未映射但库中行数 157–345、八家最新期 2026-03…08;
十持仓 adj_close 完整 832–894 根;因子 8 条 × 832。

**权威对齐**:三种股数各配流量/余额/市值(B#17);复权价仅收益算术(B 陷阱#1);
稀释 EPS 本身含价格(ASC 260 库藏股法按期内平均市价,B#16);Q4 = FY − 9M(A§0,已由区间代数实现);
分母为负 ROE 无意义(A§5,Damodaran);银行无 EV/FCF/DD(B 陷阱#7);
最小观测:vol 20 / beta 60 / VaR95 250 / ES97.5 250 / Amihud 200(C 路,各带 URL)。
