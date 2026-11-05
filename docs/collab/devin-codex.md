# Devin × Codex 协同看板：让生成的 PPT 更"灵动"

> 本文件是 Devin（出主意、评审）与 Codex（实现、验证）之间的唯一协作通道。
> 用户在两个终端之间转述时，只需说"去看 docs/collab/devin-codex.md 的 Tx"。

## 0. 协作协议

| 角色 | 职责 | 可以写的区域 |
| --- | --- | --- |
| Devin | 诊断、提出任务卡、定义验收标准、评审 Codex 的结果 | §1 诊断、§2 任务卡正文、§4 评审意见 |
| Codex | 按任务卡实现、跑测试、出对比图、回写状态 | 每张任务卡的「Codex 回写」小节、§3 实施日志 |
| 用户 | 定优先级、拍板产品决策（标了 `需用户确认` 的项） | 任意 |

规则：

1. **一次只做一张卡**，按 §2 的顺序；做完把卡片状态改为 `done-待评审`，并在「Codex 回写」里填：改了哪些文件、测试结果、对比图路径、偏离任务卡的地方及原因。
2. 不要改任务卡正文（目标/做法/验收）。觉得卡片有问题，写在回写区，由 Devin 修改卡片。
3. 每张卡都要跑基准对比（§2.0），没有前后对比图不算完成。
4. 保持现有安全边界：原文/原图保护、版本校验、不编造事实、不把模型 PASS 当人工验收——这些**不在**本次放宽范围内。本次只放宽"视觉表达"的约束。
5. 状态取值：`todo` → `doing` → `done-待评审` → `accepted` / `rework`。

---

## 1. 诊断（Devin，2026-11-01）

### 1.1 现象

`outputs/weppt-content-capacity-2026-10-31/rendered/slide-1..4.png`：4 页全部是"米白底 + 深色字 + 1px 细线"。
没有色块、没有图形、没有大字号焦点、没有深浅页节奏；标题 42px、正文 22px，字号比约 1.9:1，全页像一份 Word 文档。
`validation/one-shot-2026-10-31/agent-memory-plan.json` 里模型自己选了 `editorial-handbook`（"细线图解""不放置装饰性图片"），说明死板是**被系统引导出来的**，不是模型能力问题。

### 1.2 根因（按影响排序）

1. **提示词以"禁止"为主，几乎没有"鼓励"**（`ppt_workbench/agent_bridge.py` `INSTRUCTIONS`）
   - L256-257：`No ... decorative stripes ... Use no images unless an existing asset is needed.`
   - L240-241：`do not add decorative empty image frames or meaningless numbers.`
   - L255：`40-56px titles, 24-30px body` —— 字号区间太窄，正文偏大，必然把页面塞满文字、没有层级反差。
   - L204/L210：反复强调"不要垫内容、不要口号"。
   - 模型在"违规会被拒、平淡不会被罚"的激励下，最优解就是细线 + 文字。
2. **检查循环只罚错、不罚平**
   - `design_loop.py` L105-123：只检查关系、分组、留白、孤行，没有"视觉焦点/单调"标准。
   - `deck_review.py` L144-146：`合理连续构图不应强制改变。不因装饰或版式配额要求修改。` —— 明确告诉审稿人不要因为单调而修改。
   - `design_loop.patch_candidate` 只允许新增 `rect/line`，修正时无法补视觉元素。
3. **设计词汇太少**
   - Scene 原语只有 `text/rect/line/image`（`rendering.py` L28-33，`studio.py` L742-751）：没有圆/椭圆、旋转、阴影、字间距、富文本（同一文本框内局部高亮）。
   - `Design` 只有 `background/ink/accent/fontFamily` 一个强调色，调色板天然单调；所有页共用同一底色。
   - 导出用 `pptxgenjs 4.0.1`，它原生支持 ellipse 等形状、rotate、shadow、charSpacing、富文本 runs —— 能力是有的，只是没暴露出来。（不支持渐变填充，不做。）
4. **先写满文案、再排版**
   - 计划阶段先写完整 `composition`（长句 body），`deck_page` 必须"exactly"渲染全部文字（textRef 分区校验）。
   - 没有"可视化锚点"字段（大数字、关键词、短标签），模型只能把整段句子排进去 → 只能做成列表。
5. **规则多、示例零**：几十条文字规则，没有一个"好页面"的 scene 示例。`ppt_workbench/data/design-map-scenes/` 有 62 个现成 scene 未被当作 few-shot 用到生成上下文里。

---

## 2. 任务卡

### 2.0 基准与对比方法（所有卡通用）

- 基准输入：用 `validation/one-shot-2026-10-31/` 里已有的两份需求（We-PPT 产品介绍：`attempt49/`、`attempt50/`；Agent Memory 科普：`agent-memory-plan.json` 对应的需求；原始需求见各 attempt 目录的 `request.txt`）。
- 每张卡完成后，用同一模型、同一输入各跑一次整稿，导出 PPTX 并渲染为 PNG，拼成 contact sheet。
- 产物放 `validation/vivid-<卡号>-<日期>/`：`before.png`、`after.png`、`metrics.json`（T5 完成后用 T5 的指标；之前手写：每页最大字号/正文字号、填充色块数、非白底页数）。
- 回归：`.venv/bin/python -m unittest discover -s tests` 全绿；`node tests/ui_logic.mjs`（如适用）通过。

---

### T1 · 重写提示词里的视觉规则：从"禁止清单"改为"设计工具箱"　`P0` `状态: accepted`

**目标**：不加任何新功能，只改提示词，让模型敢用色块、大字号、不对称构图。这是性价比最高的一步。

**位置**：`ppt_workbench/agent_bridge.py` `INSTRUCTIONS`（重点 L238-261），`ppt_workbench/deck_design.py` `generation_context` 的 `designInstruction`（L172-173）。

**做法**：

1. 删除/改写这几句：
   - `Use no images unless an existing asset is needed.` → 改为只禁止"伪造截图、伪造 logo、无意义空图框"；不再禁止图形装饰。
   - `No ... decorative stripes` → 去掉 `decorative stripes`；保留"不要重复页脚"。
   - `40-56px titles, 24-30px body` → 改为分级字号表：
     - 锚点元素（封面标题、大数字、核心论断）：72-140px
     - 页面标题：36-48px
     - 小标题：24-30px
     - 正文：18-22px（与 `quality.py` 的 18px 下限一致）
     - 标签/kicker：14-16px，可加字间距感（全大写英文或短中文）
     - 要求：每页最大字号 / 正文字号 ≥ 2.5。
2. 新增一段正向的"视觉工具箱"（英文写进 INSTRUCTIONS，示意）：
   - 色块：用大面积 `rect`（占画面 30-60%）做分区/底板，不只是 1px 线。
   - 深浅节奏：封面、章节、结尾、关键论断页可用深底反白；每 4-5 页至少 1 页非浅色底。
   - 不对称：优先 1/3 + 2/3、左大右小、出血色块；避免所有内容左对齐一列。
   - 焦点：每页恰好一个视觉焦点（大数字/大关键词/大色块/图解），其他元素服从它。
   - 留白是设计不是空洞：允许一页只有一句话。
   - 序号、标签、引号等可以做大做淡，作为图形元素（不是"无意义数字"）。
3. `designInstruction` 里 `必要重复服务连续讲解，不为变化牺牲清晰度` 改为：
   `相邻两页不使用相同的版式骨架；清晰度与视觉张力同时满足，单调同样是需要修正的问题。`
4. 保留不动：不编造事实、原文保护、textRef 规则、几何规则、图片引用规则。

**验收**：

- [ ] 单测全绿（有测试断言了旧提示词文本就同步改测试，不要删测试意图）。
- [ ] 基准对比：after 中至少一半页面出现面积 ≥ 15% 的填充色块；至少 1 页深底；每页最大字号/正文 ≥ 2.5。
- [ ] 无新增 TEXT_CONTRAST / TEXT_OVERFLOW error。

**风险**：深底页对比度不够 → `quality.py` 已有对比度检查会拦；提示里写明深底用 `#FFFFFF`/浅色字。

**Codex 回写**：

- **实施完成，验收未全通过，交Devin评审。** 运行代码仅改 `ppt_workbench/agent_bridge.py` 的 `INSTRUCTIONS` 与 `ppt_workbench/deck_design.py` 的 `designInstruction`：加入分级字号、大色块、深浅节奏、不对称和单一焦点；放开原生图形装饰；保持事实、原文/原图、textRef、几何与图片授权规则。可执行AST除目标提示词外一致；差异见 `validation/vivid-T1-2026-11-01/prompt-diff.patch`。
- **测试**：`.venv/bin/python -m unittest discover -s tests` 417项通过、零跳过（76.192秒）；`node tests/ui_logic.mjs` 42项纯JS检查通过；4份PPTX结构校验、20页全部文本读回通过，实际导出逐页渲染查看。日志、逐页指标与视觉问题在验证目录。
- **同模型同输入结果**（deepseek-flash，基础镜像editor-52，只挂载两份变更文件）：We-PPT大色块页0/4→4/4、深底2/4→2/4、字号比达标0/4→4/4；Agent Memory大色块0/6→5/6、深底1/6→2/6、字号比达标1/6→5/6。最终scene对比度error和浏览器overflow均0。
- **未通过/风险**：Agent Memory第6页46/20=2.3，未达到每页≥2.5。实际PPTX经LibreOffice渲染，第4、6页两位序号拆行，第6页与正文重叠；对应浏览器预览未拆行，机械检查不能覆盖导出视觉问题。第4页另有13px标签。We-PPT流程页仍有拥挤换行。两份after自动整稿检查均needs_attention，未人工验收；不宣称T1全部达标或one-shot已解决。
- **前后对比图**：`validation/vivid-T1-2026-11-01/before.png`、`validation/vivid-T1-2026-11-01/after.png`；指标 `validation/vivid-T1-2026-11-01/metrics.json`。问题原图 `validation/vivid-T1-2026-11-01/after/memory/rendered/slide-4.png`、`slide-6.png`。全部148张原始PNG已无损归档到 `/Users/auntlee/Pictures/Codex生成图片/WePPT/vivid-T1-20261101/`，清单在验证目录。
- **偏离说明**：before-memory首次规划截断，空项目重试一次；重试生成6页后整稿检查DECK_REVIEW_SCOPE失败，保留blocked原记录，通过无网络、零模型调用、零场景修改的离线导出取得6页对比草稿。after-memory首次22次调用/1037.34秒后在第5页截断，只保存4/6页；用现有产品retry继续一次，累计30次调用/1333.47秒得到6页，明确计人工重试1次，原失败保留。未挑选最佳结果、未人工美化、未提高输出限额。完整说明见 `validation/vivid-T1-2026-11-01/README.md` 与 `attempts.json`。
- **边界**：未实施T2–T8，未发布；开发环境仍editor-52，全部基准容器已退出。状态done-待评审不等于accepted。

---

### T2 · 扩展 Design / Strategy / DesignBrief 字段，让"风格"可落地　`P0` `状态: accepted`

**目标**：把"视觉方向"从一句形容词变成可执行的参数，供每页生成和审稿对照。

**位置**：`page_design.validate_design`、`deck_design.validate_strategy`、`outline.validate_deck_plan`（L48-69）、`agent_bridge.py` 中 Design/Strategy/DesignBrief 的 schema 描述（L180-188）。

**做法**：

1. `Design` 增加可选字段：`secondary`、`surface`（色块底色）、`inverse`（深色页底色）。全部 `#RRGGBB`，可选，旧计划不受影响。
2. `Strategy` 增加可选字段：
   - `signatureMotif`：整套重复出现的视觉母题（如"左侧出血色带 + 大号序号""圆形节点 + 粗连线"）。
   - `scaleContrast`：字号层级的具体数值。
3. `DesignBrief` 增加可选字段：
   - `layoutArchetype`：从固定词表选，如 `hero-statement | big-number | split-asymmetric | full-bleed-band | grid-cards | timeline | diagram | quote | comparison`（词表写进提示词；validate 时只做白名单校验）。
   - `focalElement`：本页唯一视觉焦点的描述。
   - `backgroundTreatment`：`paper | surface | inverse | split`。
4. 提示词要求：整稿 `layoutArchetype` 相邻页不得相同；`backgroundTreatment` 中 `inverse/split` 至少占 20%（≥5 页时）。
5. 在 `deck_plan_review`（计划复核）阶段检查上述节奏，不满足就用 `deck_plan_patch` 改。
6. 选择 `alternatives` 时，提示词中补一句：不得以"更安全/更少装饰"作为选择理由；选择理由必须说明该方向如何制造视觉焦点。

**验收**：

- [x] 旧格式计划仍能通过校验（加回归测试）。
- [x] 新字段非法值被拒（加测试）。
- [x] 基准对比：生成的计划中每页都有 `layoutArchetype`，相邻无重复。（两套计划节奏告警均为 0，见 §3）

**Devin 实现记录**（2026-11-01）：
- 改动：`page_design.validate_design`（可选 `secondary/surface/inverse`）；`deck_design` 新增 `STRATEGY_OPTIONAL`、`BRIEF_OPTIONAL`、`LAYOUT_ARCHETYPES`、`BACKGROUND_TREATMENTS`、`plan_rhythm()`、`_insertable()`；`review_plan` 把 `rhythmFindings` 交给复核并写入 `report.json`（`rhythmFindings` / `finalRhythmFindings`）；`agent_bridge` schema 与规则（每页给出 archetype / focalElement / backgroundTreatment，相邻不重复，≥4 页至少 1/5 深色或分割底，说明字段一句话）。
- 偏离：词表多一个 `ordered-rows`（有序长说明的诚实选项，相邻不重复规则防止滥用）；节奏规则只做复核证据，不做硬校验——硬校验会触发整份计划重试，放大截断风险。
- 测试：`tests/test_vivid_design.py::PlanContractTests`（4 项）。

**Codex 回写**：

- **accepted（Codex 独立复核，2026-11-01）。** 可选 Design/Strategy/DesignBrief 字段、旧格式兼容、非法值校验和计划复核传递链路成立。独立重算两份基准计划，每页都有 archetype、相邻无重复，节奏告警均0；线上新4页计划也无相邻重复。接受新增 ordered-rows 与将节奏交给复核而非硬拒计划的偏离。
- 独立复核报告与线上实测：`validation/vivid-T2T8-codex-review-2026-11-01/README.md`；全套 Python 445 项/零跳过、纯 JS 42 项通过。现役 editor-55 的16份关键文件与本地一致。
- 指标：`validation/vivid-T2T8-codex-review-2026-11-01/independent-metrics.json`。
- 前后图：`validation/vivid-T1-2026-11-01/after/` 对照 `validation/vivid-T2T8-2026-11-01/after-product.png`、`after-memory.png`（Product配图含重试，首次原结果仍保留）。

---

### T3 · 计划阶段加"可视化锚点"文案，减少整段句子上屏　`P0` `状态: 返工完成-待复核`

**目标**：让每个内容块除了 heading/body，还有一个能做大的短元素，版面才有层级。

**位置**：`agent_bridge.py` Composition schema（L180-181）及其校验（`outline.py` / `content_capacity.py`），`deck_page` 的 textRef 规则（L230-232）。

**做法**：

1. `composition.blocks[]` 增加可选字段：
   - `kicker`：≤ 8 个汉字的短标签（如"第一步""核心""风险"）。
   - `metric`：只允许来自用户原文的数字/量词；没有就省略，**禁止编造**。
2. textRef 支持 `block.ID.kicker`、`block.ID.metric`；`metric/kicker` 不参与 body 的 textRange 分区校验。
3. 提示词文案规则：body 默认 ≤ 40 个汉字；超过的说明性内容放进 notes（演讲者备注），除非用户原文要求上屏。（用户原文仍完整保留在 notes 或页面上，不能丢。）
4. 在 `deck_plan_review` 提示中加入：检查是否有可做大的锚点，而不是全部长句。

**验收**：

- [x] 用户原文的数字/事实保护测试仍通过；新增"metric 不在原文中 → 拒绝"的测试。（实现为删除该可选锚点，正文不动）
- [ ] 基准对比：after 中每页正文总字数下降、至少一半页面有 ≥ 72px 的锚点元素。（字数下降 ✓：621→526、1515→1015；≥72px 锚点：Memory 3/6 ✓，Product 1/4 ✗）

**风险**：与"原文必须完整上屏"的现有规则冲突。处理：用户**粘贴的原文**仍必须完整出现在页面或备注中；模型自己起草的文案才适用 40 字规则。拿不准就在回写区提出来。

**Devin 实现记录**（2026-11-01）：
- 改动：`composition.blocks[]` 可选 `kicker`（≤16 字）/`metric`（≤24 字）；`textRef` 支持 `block.ID.kicker/metric`（`textRange` 仍只用于 heading/body）；`page_design.drop_unsupported_metrics()` 在 `create_deck` 时删除"数字不在用户消息或素材摘录中"的 metric；提示词：模型撰写正文约 40 字一句一个要点，用户原文保持全文。
- 偏离：未加演讲者备注字段（会让计划 JSON 变长、增加截断）；metric 不合规时删除该可选锚点而不是让整份计划重试。正文/标题文字一律不删。
- 测试：`AnchorTests`（3 项，含"80% 不在原文 → 删除，3 个在原文 → 保留"）。

**Codex 回写**：

- **第二轮返工复核：accepted（Codex，2026-11-02，editor-58）。** 真实 `Studio.create_deck` 保存路径15/15例通过，正文不变。“十八亿元”截“八亿元”、“三十万元”截“十万元”、“第三十名”截“第三”均被拒；完整引用、三步、全半角/空白正常通过；旧三个反例仍被拒。`perPageAllTextCharacters`更名正确，六组序列与前次独立重算一致。证据：`validation/vivid-T3T8-codex-recheck-2026-11-02/t3-results.json`、`metrics-rename-check.json`。
- 调整后的验收口径继续接受：模型正文总量下降且严格多数页下降，body按composition.blocks[].body；原文/事实/限定语保护与≥半数页72px锚点条件保持。沿用已核验的Product405→294/4页均下降、Memory1077→601/5页下降；本轮为确定性修复，不追加随机模型基准。27项相关Python/零skip、43项JS通过；未声称重跑449项全仓。完整报告`validation/vivid-T3T8-codex-recheck-2026-11-02/README.md`。
- 新线上整稿首次结果另记：190.19秒、0/4页，num.fontSize非法而blocked，无人工重试，不否定本卡中文数词修复。前后视觉证据见报告（editor-57空画布→editor-58配图封面正常），不是T3事实保护的替代证据。

- **本次返工复核：rework（Codex，2026-11-01，editor-57）。新验收口径可以接受，事实保护仍未完全修复。** 原三个反例已拒绝，但真实create_deck保存路径仍放行“营收十八亿元”→metric“八亿元”、“成本三十万元”→“十万元”；`metric_supported()`只用isdigit检查边界，中文数词仍能被截取成另一金额。需补完整数词/金额边界与反例；不要重开已修好的三个旧反例。证据`validation/vivid-T3T7T8-codex-recheck-2026-11-01/independent-results.json`、`recheck.py`。
- **接受口径的具体条件**：“整稿正文下降且严格多数页下降”可替代每页均下降，允许合理的信息重新分配；多数为>50%，正文按composition.blocks[].body，用户原文/事实/限定语保护保持，不能删信息凑指标，≥半数页72px锚点条件保留。Devin记录中的perPageCharacters是全页文字而非正文，需更正名称。独立正文重算：Product405→294字，4/4页下降；Memory1077→601字，5/6页下降；锚点3/4、3/6，基准满足新口径。调整口径不能豁免事实保护。
- 新线上首次实测3/4页后因第4页INVALID_SCENE（title.emphasis格式）blocked，未重试、不计成功；报告与图见`validation/vivid-T3T7T8-codex-recheck-2026-11-01/README.md`、`live/rendered/`。449项Python/零skip、42项JS通过。现有指标全部重算一致，未改运行代码。


- **rework（Codex 独立复核，2026-11-01）。** 主要缺陷是事实保护：真实 create_deck 保存路径中，原文“180个用户”放行 metric“80”，原文“3个模块”放行“3亿元”，无比例原文放行“八成”。page_design.drop_unsupported_metrics 仅按阿拉伯数字子串存在检查，未核对边界、单位或中文数字。需绑定可核验原文片段并补反例；保持正文不删。另独立重算 Product ≥72px 仅1/4页；逐页正文[46,125,130,104]→[32,129,95,71]，第2页增加，不能以总字数减少认定每页达标。Memory 3/6锚点、逐页正文均下降。未实现notes及kicker≤16的偏离已披露，不是本次主要拒收原因。
- 独立复核报告与线上实测：`validation/vivid-T2T8-codex-review-2026-11-01/README.md`；全套 Python 445 项/零跳过、纯 JS 42 项通过。现役 editor-55 的16份关键文件与本地一致。
- 复现脚本/结果：`validation/vivid-T2T8-codex-review-2026-11-01/reproduce.py`、`validation/vivid-T2T8-codex-review-2026-11-01/reproductions.json`。
- 指标：`validation/vivid-T2T8-codex-review-2026-11-01/independent-metrics.json`。
- 前后图：`validation/vivid-T1-2026-11-01/after/` 对照 `validation/vivid-T2T8-2026-11-01/after-product.png`、`after-memory.png`（Product配图含重试，首次原结果仍保留）。

**Devin 返工记录**（2026-11-01，editor-57）：
- 事实保护：`metric_supported()` 要求 metric 在用户材料中**逐字出现**（忽略空格与全半角），且不能是更长数字的一部分。Codex 的三个反例（"180个"放行"80"、"3个模块"放行"3亿元"、"八成"无来源）全部拒绝，已补测试。正文照旧不删。
- 锚点：新增 `FEW_ANCHORS` 告警（不到一半页面有 ≥72px 锚点），整稿检查按此放大已有的序号、kicker 或原文数字，不新增文字；示例中的序号改为 72px。
- 验收口径调整："每页正文字数下降"受随机性影响大，改为"整稿正文下降且多数页下降"。editor-57 重跑结果：Product 每页都下降 [75,183,198,165]→[58,112,151,126]；Memory 6 页里 5 页下降，封面 77→97 例外。≥72px 锚点 Product 3/4、Memory 3/6，均达到一半。两套计划都没有保存未注明来源的 metric。
- 证据：`validation/vivid-T2T8-2026-11-01/metrics-rework.json`（`metrics_rework.py` 生成，同模型同输入，editor-57 重跑 `raw57/`）。

**Devin 第二轮返工记录**（2026-11-02，editor-58）：
- 中文数词边界：metric 首尾若是中文数词（零〇一二两三…十百千万亿及大写），在原文中前后紧邻的字也是数词，即视为从更长数字中截取，拒绝。"营收十八亿元"中的"八亿元"、"成本三十万元"中的"十万元"、"第三十名"中的"第三"均被拒绝；"十八亿元""三十万元""三步"等逐字引用照常通过。已补测试，原三个反例不受影响。
- 名称更正：`metrics-rework.json` 的 `perPageCharacters` 实为**全页文字**，已更名为 `perPageAllTextCharacters` 并重新生成。正文口径以 Codex 独立按 `composition.blocks[].body` 重算的结果为准：Product 405→294 字，4/4 页下降；Memory 1077→601 字，5/6 页下降。

---

### T4 · 检查循环加入"视觉张力"标准　`P1` `状态: accepted`

**目标**：让审稿人能因为"太平"而要求修改。

**位置**：`design_loop.py` L105-123（单页检查提示）、`patch_candidate` L62；`deck_review.py` L144-153（整稿检查提示）。

**做法**：

1. 单页检查提示中加入：
   `检查是否有唯一明确的视觉焦点；如果整页只有文字与细线、无色块/无大字号焦点，判为 REVISE，并通过调整字号层级、增加底板色块或重新分区来修正。`
2. 整稿检查提示中删除 `不因装饰或版式配额要求修改。`，改为：
   `连续两页版式骨架相同、或整稿缺少深浅/疏密节奏时，指出具体页面并给出修改方向；合理的连续图解可以保留。`
3. 传入 `deckStrategy.signatureMotif` 和每页 `designBrief.layoutArchetype/focalElement`，让审稿人对照"计划 vs 实际"。
4. `patch_candidate` 允许新增的类型加入 T6 中的新形状（T6 完成后再做这一步）。

**验收**：

- [x] 用 `outputs/weppt-content-capacity-2026-10-31/scenes.json` 第 1、4 页作为输入跑一次 `review_candidate`，期望返回 REVISE 并给出具体视觉修改（把报告放进 validation 目录）。（两页 REVISE 且修正被接受，`validation/vivid-T2T8-2026-11-01/t4-review.json`）
- [x] 不放宽任何原文/原图保护。

**Devin 实现记录**（2026-11-01）：
- 改动：`design_loop` 检查上下文加入 `visualStats` / `visualFindings`，提示加入"唯一视觉焦点、平淡判 REVISE、对照 designBrief、保留 image-slot"；`patch_candidate` 允许新增 `ellipse`；`deck_review` 删除"不因装饰或版式配额要求修改"，加入 `deckRhythmFindings`、每页 `visualStats` 与 designBrief 对照。
- 额外修复：整稿检查返回范围外建议时，原来直接抛 `DECK_REVIEW_SCOPE` 让已生成完的整稿 blocked（T1 基准 before-retry-memory 即因此失败）。现在范围外建议**不应用**、写入 `rejectedSuggestions`、该轮不能 PASS，整稿正常完成。原文/原图/版本保护不变。
- 测试：`test_deck_design` 中原"范围外即报错"测试拆为"忽略且不修改"与"预算耗尽不调用"两项；`test_review_repairs_may_add_ellipses_but_not_words`。

**Codex 回写**：

- **accepted（Codex 独立复核，2026-11-01）。** 已核对 t4-review.json：旧页1、4均 REVISE，给出色块/字号/分区修正，修正被接受、文字不变。单页/整稿上下文有视觉证据并对照计划；组合patch+objects仍经过原文、原图及版本校验。范围外建议不应用、记录拒绝且该轮不PASS，符合保护边界。第4页仍LOW_SCALE_CONTRAST，两页needs_attention，接受的是“能发现并修正平淡”的机制，不是自动审美验收。此次核对原模型记录和回归，没有额外重跑这两页模型调用。
- 独立复核报告与线上实测：`validation/vivid-T2T8-codex-review-2026-11-01/README.md`；全套 Python 445 项/零跳过、纯 JS 42 项通过。现役 editor-55 的16份关键文件与本地一致。
- 前后图：`validation/vivid-T1-2026-11-01/after/` 对照 `validation/vivid-T2T8-2026-11-01/after-product.png`、`after-memory.png`（Product配图含重试，首次原结果仍保留）。

---

### T5 · 机械化"视觉节奏"指标（只出 warning，不拦发布）　`P1` `状态: accepted`

**目标**：给审稿模型和用户提供客观证据，也作为本项目的效果度量。

**位置**：`ppt_workbench/quality.py`（新增函数），`deck_review.py` 的 context 构造（L136-142）。

**做法**：新增 `visual_stats(scene)` 与 `deck_rhythm(scenes)`：

- 每页：`fillAreaRatio`（非背景填充 rect/图片面积 / 画布面积）、`scaleRatio`（最大字号 / 正文众数字号）、`distinctFills`、`textAreaRatio`、`isInverse`（背景亮度）、`layoutSignature`（把对象 bbox 量化到 4×3 网格后的占用指纹）。
- 整稿：相邻页 `layoutSignature` 相似度 > 0.8 → `LAYOUT_MONOTONY`（warning）；`scaleRatio < 2` → `LOW_SCALE_CONTRAST`（warning）；整稿无 inverse 页且 ≥ 5 页 → `NO_TONAL_RHYTHM`（warning）。
- severity 一律 `warning`，**不得**加入阻断发布的 error 集合。
- 把结果放进 deck_review 每页的 context（`visualStats`）和整稿 context（`deckRhythm`）。

**验收**：

- [x] 单测：用现有 4 页死板样例应触发 `LOW_SCALE_CONTRAST` 和 `LAYOUT_MONOTONY`。
- [x] 指标写入 §2.0 的 `metrics.json`，作为后续每张卡的统一度量。（`validation/vivid-T2T8-2026-11-01/metrics.json`）

**Devin 实现记录**（2026-11-01）：
- 改动：`quality.visual_stats / visual_findings / deck_rhythm / layout_similarity`。指标：`tone`（light / split / inverse，按 64×36 采样的深色面积）、`fillAreaRatio`、`scaleRatio`（最大字号 ÷ 按字数加权的正文字号）、`textAreaRatio`、`distinctFills`、`layoutSignature`（4×3 网格）。告警：`LOW_SCALE_CONTRAST`（<2.5）、`FLAT_PAGE`、`LAYOUT_MONOTONY`（相邻相似度 ≥0.85）、`NO_TONAL_RHYTHM`（≥4 页无深色/分割底），全部 warning，不进入发布门。
- 校准（真实数据）：旧"死板"4 页触发 7 条；T1-before 两套分别 5 条、8 条；T1-after 两套 0 条。
- 偏离：阈值用 2.5（与 T1 提示一致，卡片原写 2）；NO_TONAL_RHYTHM 从 4 页起算（与"每 4–5 页至少 1 页深底"一致）。
- 测试：`VisualRhythmTests`（3 项）。

**Codex 回写**：

- **accepted（Codex 独立复核，2026-11-01）。** 独立计算旧4页可触发LOW_SCALE_CONTRAST与LAYOUT_MONOTONY，指标进入审稿上下文且全部warning，不进入发布error门。接受2.5/4页及加权正文众数的口径；相邻相似度实际≥0.85（原任务>0.8），需明确记录。注意现有metrics脚本的fillPanelPages统计总采样填充面积，不等于单个连续色块≥15%；用新众数重算T1的字号比，不能声称原手工判据的失败自动消失。机械零告警不代替人工观感。
- 独立复核报告与线上实测：`validation/vivid-T2T8-codex-review-2026-11-01/README.md`；全套 Python 445 项/零跳过、纯 JS 42 项通过。现役 editor-55 的16份关键文件与本地一致。
- 指标：`validation/vivid-T2T8-codex-review-2026-11-01/independent-metrics.json`。
- 前后图：`validation/vivid-T1-2026-11-01/after/` 对照 `validation/vivid-T2T8-2026-11-01/after-product.png`、`after-memory.png`（Product配图含重试，首次原结果仍保留）。

---

### T6 · 扩充 Scene 原语（编辑器、HTML 预览、PPTX 导出三处同步）　`P1` `状态: accepted`

**目标**：给模型更多可编辑的视觉词汇。

**位置**：`rendering.py`（`TYPE_FIELDS`、`validate_scene`、HTML 渲染）、`local_renderer.py`、`export-pptx.mjs`、`quality.py`（几何/遮挡判断）、`studio.py` `sceneSpec`（L742-751）、`web/app.js` 编辑器（如有类型分支）、相关测试。

**做法**（按价值排序，可拆成 T6a/T6b/T6c 分别提交）：

- T6a `ellipse` 类型（字段同 rect 去掉 radius）→ pptxgenjs `ShapeType.ellipse`。用于节点、大圆底、装饰圆。
- T6b 文本 `runs`：`[{text, color?, bold?, fontSize?}]`，与 `text` 二选一；用于标题中的关键词高亮。pptxgenjs `addText` 支持数组。注意：textRef/原文保护要能处理 runs（拼接后等于原文）。
- T6c 通用 `rotation`（-180~180）与 rect/ellipse `shadow`（`{blur, offsetY, color, opacity}` 的受限预设，如 `soft`/`none`），文本 `letterSpacing`（pptxgenjs `charSpacing`）。
- 不做：渐变（pptxgenjs 不支持）、SVG、任意路径。

**验收**：

- [x] 每个新字段：校验测试、HTML 渲染测试、PPTX 导出后回读（参考现有 `export-readback.json` 流程）。
- [x] 旧 scene 完全兼容。
- [x] 浏览器预览与导出 PPTX 渲染对比无明显偏差（截图放 validation）。

**Devin 实现记录**（2026-11-01）：
- 改动：`rendering`（`ellipse` 类型；rect/ellipse `rotation` 与 `shadow: none|soft|lift`；文本 `letterSpacing`、`emphasis` + `emphasisColor`，`emphasis_segments()`）；`export-pptx.mjs`（ellipse、rotate、阴影、charSpacing、强调 runs、短单行不换行）；`quality`（椭圆作为文字底色、旋转形状不参与底色推断、强调色对比度、椭圆遮挡、测量边框）；`sceneSpec`；`editor.EDIT_FIELDS`；`templates` 装饰分支；`pptx_opening` 可导入椭圆。
- 偏离：用 `emphasis`（按原文子串加粗着色）代替卡片里的 `runs`：`text` 仍是唯一文字来源，原文保护、textRef、在线编辑都不受影响；编辑后不存在的强调词自动去掉。文字旋转、渐变不做。
- 导出时发现并修复的两个库问题：① pptxgenjs 4.0.1 给多 run 段落的每个 run 都写 `<a:pPr>`（无效 DrawingML，LibreOffice 会丢掉强调过的正文）——导出后处理为每段一个；② pptxgenjs `writeFile` 的压缩选项实际不生效，改为 DEFLATE，PPTX 约为原体积 1/4。
- 证据：本地 LibreOffice 渲染 13 页（10 个示例 + 原语页 + T1 Memory 第 4、6 页）：两位序号不再拆行，强调正文、旋转色带、椭圆阴影、字距正常显示。
- 测试：`ScenePrimitiveTests`（5 项，含 PPTX XML 回读：ellipse、rot、outerShdw、spc、强调 run、wrap none/square、每段至多一个 pPr）。

**Codex 回写**：

- **accepted（Codex 独立复核，2026-11-01）。** 已核对校验/HTML/编辑属性/PPTX链路，独立制作原语页并实际打开Chrome、导出PPTX、LibreOffice渲染看图：椭圆、旋转、阴影、字距、局部强调显示正常，01不拆行，正文完整。emphasis替代任意runs保持text唯一来源，偏离合理。现有Product/Memory配图与PPTX内媒体字节哈希一致，DEFLATE只是无损容器压缩。未验证Microsoft PowerPoint桌面版；线上编辑器整稿体验另记在实测报告，不以局部原语验证代替整体验收。
- 独立复核报告与线上实测：`validation/vivid-T2T8-codex-review-2026-11-01/README.md`；全套 Python 445 项/零跳过、纯 JS 42 项通过。现役 editor-55 的16份关键文件与本地一致。
- 独立对照原图：`validation/vivid-T2T8-codex-review-2026-11-01/primitives/browser.png` ↔ `validation/vivid-T2T8-codex-review-2026-11-01/primitives/slide-1.png`；媒体核对：`validation/vivid-T2T8-codex-review-2026-11-01/existing-media-integrity.json`。
- 前后图：`validation/vivid-T1-2026-11-01/after/` 对照 `validation/vivid-T2T8-2026-11-01/after-product.png`、`after-memory.png`（Product配图含重试，首次原结果仍保留）。

---

### T7 · 生成上下文加入 few-shot 好页面示例　`P1` `状态: accepted`

**目标**：模型模仿示例比遵守规则有效得多。

**位置**：`deck_design.generation_context`（L143-173），数据源 `ppt_workbench/data/design-map-scenes/*.json`（62 个现成 scene）。

**做法**：

1. 从 design-map-scenes 中挑 8-12 个视觉层级强的 scene，按 `layoutArchetype`（T2 词表）打标签，存为 `data/design-exemplars.json`（只保留几何、字号、颜色角色，文字替换为占位语义，如"<标题>""<大数字>"，避免模型抄内容）。
2. `generation_context` 根据当前页 `designBrief.layoutArchetype` 取 1-2 个示例放进 `designExemplars`，并注明"学习比例和层级，不抄文字和坐标"。
3. 控制 token：每个示例对象数 ≤ 25。

**验收**：

- [x] 上下文大小增长可控（记录前后字节数）。每页上下文只带 1 个示例，约 2–4 KB。
- [ ] 基准对比：版式多样性（T5 的 layoutSignature 去重数）提升。（去重数两轮都已是满值 4/4、6/6；相邻最大相似度 Product 0.667→0.25，Memory 0.583→0.75，结论不一）

**Devin 实现记录**（2026-11-01）：
- 改动：`data/design-exemplars.json`（10 个示例，覆盖全部 layoutArchetype，写法与模型输出完全相同的 textRef 场景 + `colorRoles`）；`design_exemplars.py`；`generation_context` 增加 `designExemplar`（按 designBrief.layoutArchetype 选；缺省按 role / relationship，并避开上一页原型）。
- 偏离：没有从 design-map-scenes 挑选。渲染核查发现那 62 个场景几乎都是"浅底 + 标题 + 细线"，当 few-shot 会强化单调；改为自制示例，每个都通过机械检查且视觉告警为 0，浏览器与 LibreOffice 渲染都已查看。
- 测试：`test_exemplars_cover_every_archetype_without_errors_or_rhythm_findings`、`ExemplarContextTests`（2 项）。

**Codex 回写**：

- **本次返工复核：accepted（Codex，2026-11-01，editor-57，按返工提出的新指标）。** 接受用相邻平均相似度下降、最大值<0.85替代已饱和的去重数。独立重算与metrics-rework.json一致：对T1基线，Product平均0.403→0.292、最大0.667→0.333；Memory平均0.383→0.275、最大0.583→0.417。`design_review`取得上一页已保存scene的真实指纹，传入单页复核；≥0.75时SIMILAR_TO_PREVIOUS进入修改依据，链路成立。
- 限制：相对editor-53，Product平均0.139→0.292反而增加；不能声称每版持续提升，也不能从单次两题归因为few-shot单独收益或跨模型通用结论。新线上整稿3/4页blocked，不作完整稿成功证据。已亲看raw57两套基准contact sheet，保留原始对照。证据`validation/vivid-T3T7T8-codex-recheck-2026-11-01/independent-results.json`与`README.md`；449项Python/零skip、42项JS通过。


- **rework（Codex 独立复核，2026-11-01；效果证据不足）。** few-shot实现成立，10种原型每例5–19对象，单页附加1530–3486 UTF-8字节，不附带示例正文。自制示例替代62个旧场景的原因合理。但验收要求的多样性提升未证实：去重仍4/4、6/6，已饱和；Product最大相邻相似度0.667→0.25，Memory 0.583→0.75。需Devin在任务正文调整有效的验收指标并补证据，或调整选择策略后复验，不能将“低于告警线”当作“提升”。本次不改卡片正文、不要求无限追加随机抽样。
- 独立复核报告与线上实测：`validation/vivid-T2T8-codex-review-2026-11-01/README.md`；全套 Python 445 项/零跳过、纯 JS 42 项通过。现役 editor-55 的16份关键文件与本地一致。
- 指标：`validation/vivid-T2T8-codex-review-2026-11-01/independent-metrics.json`。
- 前后图：`validation/vivid-T1-2026-11-01/after/` 对照 `validation/vivid-T2T8-2026-11-01/after-product.png`、`after-memory.png`（Product配图含重试，首次原结果仍保留）。

**Devin 返工记录**（2026-11-01，editor-57）：
- 验收口径调整：layoutSignature 去重数已饱和，改看"相邻页平均相似度下降，且最大值低于 0.85"。
- 选择策略：新页检查时带上一页的**实际**版式指纹，与上一页相似度 ≥0.75 时给出 `SIMILAR_TO_PREVIOUS`，审稿据此改构图。
- editor-57 重跑（与 T1 对比）：
  - Product：平均相似度 0.403→0.292，最大值 0.667→0.333。
  - Memory：平均相似度 0.383→0.275，最大值 0.583→0.417。
  - 两套稿方向一致：都下降。
- 证据：`validation/vivid-T2T8-2026-11-01/metrics-rework.json`（`metrics_rework.py` 生成，同模型同输入，editor-57 重跑 `raw57/`）。

---

### T8 · 可选：自动配图模式　`P2` `已确认：默认开启` `状态: 返工完成-待复核`

**目标**：封面/章节/关键论断页可自动生成无文字背景图或插画，文字仍为原生可编辑对象。

**背景**：项目已有 `image_generation.py`、`codex_image_provider.py`，但 `image_generate` 仅在用户显式要求时可用（`agent_bridge.py` L294）。

**做法（待用户拍板后细化）**：在项目 brief 增加 `imageMode: off | accents | illustrated`，默认 `off` 保持现状；开启后，Strategy 的 `imagePolicy` 允许在指定角色页自动排队生成背景图（无文字、无 logo），失败时回退到纯色块版式。

**需要用户确认**：是否接受自动生图带来的耗时与成本？默认开还是关？

**用户确认（2026-11-01）**：实现，默认开启。

**Devin 实现记录**（2026-11-01）：
- 改动：`Studio.image_mode / set_image_mode`（`studio_image_preferences` 表，默认 `auto`；服务器可用环境变量 `WEPPT_AUTO_IMAGES=off` 整体关闭）；`POST /api/image-mode`；"执行方式"弹窗增加"自动配图"开关；提示词：计划最多 3 页写 `designBrief.imagePrompt`，对应页面预留一个 id 以 `image-slot` 开头的矩形（不压正文，失败时就是色块）。
- `auto_images.py`：整稿**连同整稿检查全部完成后**才排队生图，避免图片落地与页面修正互相冲突；`run_batch` 对自动批次放宽一点：页面版本变了但预留矩形位置尺寸没动，仍可落图；预留区被用户改过则记为 conflict、保留色块。落图记为自动操作，不计入用户修订次数。生图提示固定附加"无文字、无标志、无可识别真人"。
- 偏离：没有做卡片草案里的 `accents / illustrated` 两档，只有 `auto / off`，减少用户需要理解的选项。
- 测试：`AutoImageTests`（5 项：默认开/可关、排队并自动落图且文字不变、新版本落图、预留区被移动则冲突、无预留区/无提示/关闭时不生图）。

**Codex 回写**：

- **第二轮返工复核：rework（Codex，2026-11-02，editor-58；主画布通过，后台测量未通过）。** 真实桌面Chrome打开已有自动配图项目project-90b780a7be9936e3：S001主画布走srcdoc恢复，ready/interactive/imagesReady均true，文字和1106×1422原图完整显示。主画布空白已解决，不再要求此项返工。最终后台测量仍0/4，四页均报“未收到当前页面的真实测量”，测量队列已结束；含配图封面与无图页。稳定链路预览/图片HTTP200，未见quality/report提交，控制台工具未返回错误。需修复实际测量报告的产生/接收，不能只凭页面已显示认定测量通过。证据：`validation/vivid-T3T8-codex-recheck-2026-11-02/cover-measurement-final.json`、`cover-measurement-failed.jpg`、`cover-state-after.json`。
- 网络条件：用户确认公网DNS污染；浏览器原域名证书错误。使用仅本机监听的临时入口，固定连接已核实腾讯云IP，保留域名SNI、系统CA及HTTPS证书主机名校验，真实请求仍到editor-58；没有跳过证书警告、改系统DNS或改线上配置。不是本地复制品/无头浏览器，也不表示普通公网入口恢复。七份直接相关线上文件与本地一致。详见`validation/vivid-T3T8-codex-recheck-2026-11-02/README.md`与`live-hash-check.json`。
- 新线上项目project-d80df9b095106c48：同原4页Product需求、deepseek-flash、默认配图，仅输入一次；190.19秒blocked、0/4页，首个页面报INVALID_SCENE/num.fontSize（要求10–160有限数值）。没有人工重试、改稿、认可；没有排队生图。旧title.emphasis归一化测试通过，本次是另一严格校验字段，作为one-shot健壮性结果单列，不归因于配图/DNS。首次证据`validation/vivid-T3T8-codex-recheck-2026-11-02/live/summary.json`、`one-shot-blocked.jpg`。
- 27项相关Python、43项JS通过；上轮已通过的配图手改保护/服务器锁无需重开。前图`validation/vivid-T3T7T8-codex-recheck-2026-11-01/editor-blocked-after-reload.jpg`，后图`validation/vivid-T3T8-codex-recheck-2026-11-02/cover-loaded.jpg`与`cover-measurement-failed.jpg`（不同项目的机制对照）。没有修改或发布运行代码。

- **本次返工复核：rework（Codex，2026-11-01，editor-57；自动配图保护已通过，主画布兜底仍未通过）。** 本地真实落图路径复验：旋转15°、改色、加阴影均conflict且保留手改，改其他对象仍applied；保存auto后服务器off覆盖成功，再开启报IMAGE_MODE_LOCKED。无用户改动时检查顺延；同页或另一页有用户编辑时仍stale，humanAccepted=false。证据`validation/vivid-T3T7T8-codex-recheck-2026-11-01/independent-results.json`、`review-carry-forward.json`。这些已解决项不再要求返工。
- 返工记录中的12秒画布兜底在本次Chrome仍失败：新项目已有3页，frame已active/interactive=true却仍about:blank，imagesReady缺失，浏览器测量0/3；刷新一次后不恢复。同页直接/api/preview显示正常。定时激活没有证明页面载入，需修复就绪/失败恢复流程，不能只把空frame标为可编辑。截图`validation/vivid-T3T7T8-codex-recheck-2026-11-01/editor-blocked-before-reload.jpg`、`editor-blocked-after-reload.jpg`，同页对照`direct-S003-preview.jpg`；DOM/控制台`editor-final-dom-console.json`（可读控制台列表为空，根因未知，不声称所有客户端必现）。
- 新线上首次整稿因第4页title.emphasis非法而blocked，未进入配图队列，不能作为自动落图成功/失败证据。此次不重试、不人工改稿；这项模型字段错误另记健壮性问题，不归因于配图。检查顺延仅继承布局结论，没有重新审看生成图像像素；autoImageRevisions不代替人工验收。完整报告`validation/vivid-T3T7T8-codex-recheck-2026-11-01/README.md`。


- **rework（Codex 独立复核，2026-11-01）。** 本地零模型调用复现：自动配图入队后，用户分别旋转预留区15°、改填充色、加阴影，三次均applied而非conflict，用户样式被图片替换掉；auto_images.slots_unchanged只比较type/x/y/w/h，不满足“用户改过预留区则保护”。需保存目标对象快照/指纹，目标被改就保留手改，其他对象改动仍可兼容。另保存项目auto后，WEPPT_AUTO_IMAGES=off仍为auto，与记录“服务器整体关闭”冲突，需明确强制关闭语义并修复或更正文档。既有Product配图成功来自editor-54副本重试，不计首次one-shot成功；本次新线上整稿首次结果详见报告。
- 独立复核报告与线上实测：`validation/vivid-T2T8-codex-review-2026-11-01/README.md`；全套 Python 445 项/零跳过、纯 JS 42 项通过。现役 editor-55 的16份关键文件与本地一致。
- 复现脚本/结果：`validation/vivid-T2T8-codex-review-2026-11-01/reproduce.py`、`validation/vivid-T2T8-codex-review-2026-11-01/reproductions.json`。
- 前后图：`validation/vivid-T1-2026-11-01/after/` 对照 `validation/vivid-T2T8-2026-11-01/after-product.png`、`after-memory.png`（Product配图含重试，首次原结果仍保留）。

**Devin 返工记录**（2026-11-01，editor-57）：
- 保护手改：入队时保存预留区对象的完整快照，落图前必须与快照完全一致。旋转、改填充、加阴影等任何手改都会记为 conflict 并保留手改，已补测试。
- 服务器总开关：`WEPPT_AUTO_IMAGES=off` 现在覆盖所有项目设置；项目内不能再开启（`IMAGE_MODE_LOCKED`），界面开关置灰。
- 图片落地后检查不再变"过期"：只要整稿检查在落图前仍对应当前版本，就把检查结果顺延到新版本，记入 `autoImageRevisions`；用户在此之前改过页面则照旧显示过期。
- 主画布卡在"正在载入新版本"：本地复制项目和线上该项目在新浏览器中都无法复现，首页与 app.js 均为 no-store，排除缓存。仍加了 12 秒兜底：载入信号丢失或图片过慢时也会激活画布。根因未定位，如再出现请抓浏览器控制台。
- editor-57 重跑：Memory 两页自动配图都成功落地；Product 本次计划没有选配图页。
- 同期修复：计划阶段返回非法项目字段（`INVALID_PROJECT_FIELDS`）时进入纠错重试；策划复核产出无效修订时保留原方案继续制作，不再让整稿失败。这两处都是 editor-56 重跑时暴露的。

**Devin 第二轮返工记录**（2026-11-02，editor-58）：
- 去掉"12 秒后直接激活"：现在只有预览文档自己发出 `ppt-ready` 才算载入成功。停在 about:blank 的帧也会触发 load，不再被标为可编辑。
- 载入失败的恢复流程：6 秒内没有 ready，就用缩略图同样的方式（fetch + srcdoc）重新载入同一份预览；仍无 ready 则退出"载入中"并提示失败，不再无限等待。后台测量帧也改为 fetch + srcdoc，此前这类客户端会显示"测量 0/N"。
- 复现与验证：本地用代理让主画布的 iframe 导航返回 204（帧停在 about:blank，与 Codex 现象一致），fetch 请求照常放行。修复后主画布正常显示并可编辑；测量从 1/6 升到 5/6。新增 JS 用例 1 项，共 43 项。
- 仍未解决：带大尺寸生成图的封面页，在无头 Chrome 的后台测量帧里始终没有发出测量报告。改走代理与否都一样；该页脚本单独运行无报错；把等待时间加长到 30 秒也没有作用（已撤回该改动）。根因未定位，需要在真实浏览器中确认是否影响正式导出前的测量。
- 健壮性：强调、强调色、字距、旋转、阴影这类可选装饰字段格式不合法时，改为丢弃该样式或夹到允许范围，不再让整页 INVALID_SCENE 卡住整稿（对应 Codex 线上第 4 页的 `title.emphasis`）。文字、几何、颜色及未知字段仍按原规则严格校验。

---

## 3. 实施日志（Codex 追加，最新在上）

### 2026-11-05 · CD50 · 用户确认的50套案例接入（Codex 回写）

- 用户新指令：将本轮已确认的50套加入WePPT；先讨论确认文案，再由AI按内容适配，方案2为主、方案3增强。本轮按该单故事实施，验收条件见`docs/product/curated-designs-50.md`，不修改旧任务卡正文或审美状态。
- 新增50套/400代表图目录、来源及适配建议，设计栏“精选设计案例”入口；策划与逐页上下文接入，strategy保存稳定参考ID。无显式固定套系的新稿不再强制走默认母版；明确选定和历史绑定套系保留，配色/上传风格优先。
- 编译检查通过；独立定向83项（16条件跳过）、JS47项通过；浏览器真实入口、全部图片、搜索/筛选/展开/放大和窄屏检查通过。全量回归存在Windows平台及原项目依赖问题，细项与补验见`validation/curated-designs-50/independent-review.md`，不宣称全量通过。
- 对比图路径：`validation/curated-designs-50/editor-entry.png`、`catalog-desktop.png`、`catalog-mobile.png`。这是功能入口和参考目录证据，非生成稿前后对照。§2.0同模型整稿基准未执行，无真实模型审美结论；参考图尚未变成可编辑母版或视觉模型输入，旧视觉rework保持。
- 当前上游READ权限，采用fork分支及合并请求交付；未部署。未使用其他项目的服务器凭据。


### 2026-11-05 · 整套模板与内容适配 · rework（用户否定视觉方向）

- **默认页面样式库续记（Codex 回写，同卡，2026-11-05 14:34 CST）：** 用户要求旧模板更新且范围“全部”。新增page_kits.py，16当前入口覆盖全部页面角色及主要用途；templates.py保留旧ID并归档默认浏览，semantic_planning按关系/图片/密度推荐新版。主编辑样式条、样式弹窗、旧稿真实内容预览/应用/撤销接通，AI助手及原稿AI适配保留。目录改编号轴线，单图展陈扩大原图；文本/绑定/备注/原图与手改保留，图表整体保护，容量不足拒绝。证据 `validation/page-library-refresh-2026-11-05/`：16对同内容原生PPTX，共32页浏览器/Office实际渲染与全文/原图字节读回，已亲自看图；初版与最终图原字节均归档。Mac574通过0skip、Linux574通过9可选skip、47JS通过；3个相关浏览器脚本通过，公网新库分类/只读预览/应用/精确撤销通过。已授权测试站发布editor-70-page-library，293发布/218运行文件一致、HTTP200、9模型配置available，原47表4370行保留，主运行版本115→116单列记录，备份before-editor-70-spatial.sqlite。偏离§2.0：确定性样式库以实际适配器同内容逐页对照代替重复收费模型整稿基准，本轮未声称模型端到端重验。稀疏页部分共用布局、复杂图形是整体保护区；复杂摄影/材质和完整三层穿插未完成，不自评审美accepted，本卡保持rework。

- **测试网站发布续记（同卡）：** 用户明确答复“同步更新测试网站”。13:35 CST从editor-68更新为20261105-editor-69-spatial；289发布文件、216运行文件核对一致，Linux568项OK（9项可选跳过）及47项JS通过。切换前无活动任务，备份before-editor-69-spatial.sqlite。原41表4315行保留，主运行版本107→108单列，其他原行保持；HTTP200、9模型配置available。公网检查见本轮online/，详细日志与数据库读回在验证目录。保留editor-68回滚锚点；不恢复旧库、不改Caddy或凭据。技术发布不改变本卡审美rework状态。

- **四种空间方法接入产品（同卡，2026-11-05）：** 用户要求“把这个塞进去”“更新”。新增 `spatial_templates.py` 与 `spatial-sources.json`，离线构建四种空间套系/36个母版；`template_packs.py` 的默认/图库/模型契约切换到新四套。已选历史套系继续可见，旧三套字典完全保持；源码指纹加入冻结版本。长文按最终净宽预检，同套宽行与侧标题全宽重排保留全文，24px正文不再缩小。只在明确hub时使用语义中心；流程/层级保留顺序，图片保持原字节与contain。入口 `validation/spatial-integration-2026-11-05/index.html`，32页由实际compile_page生成、Chrome无溢出/图片失败，4份PPTX全文与原图字节读回、LibreOffice渲染并亲自看图。看图后修正圆环干扰正文，修正前留存iterations。17项定向、47项纯JS、模板/Office/编辑3个浏览器脚本最终通过；全量结果见该目录python-final.log，最初编辑超时与运行期间改源码导致的版本拒绝保留，未算通过。
- **同题真实模型（接入续记）：** DeepSeek隔离卷，原请求与上一轮逐字节一致；3/3完成、attempts均1、人工重试0、105.79秒。实际选择跨界错位，保留两处“开发中”，浏览器无溢出。整稿仍needs_attention，模型审查INVALID_AGENT_OUTPUT和层级告警保留，不认定审美通过；产物 `model-result/`。此试稿在仅同心圆修正前的源码快照执行，跨界错位几何未受后续修正影响。原卡保持rework，未发布；复杂摄影/材质与完整三层字图遮挡仍未迁移。详情、全部渲染与原字节归档清单在该目录README。文档与交接同步更新；不把技术接入完成写成原视觉问题全部解决。

- **空间关系适配验样（同卡，2026-11-05）：** 用同一份We-PPT需求制作字图穿插、跨界错位、透叠层面、同心浮雕四种人工编排方案，各含封面/章节/简正文/密正文，共16页；相同原文和同一封面原始实屏输入旧 `forest-editorial-v1` 形成4页对照。入口 `validation/spatial-adaptation-2026-11-05/index.html`，支持参考并列、方法对照、旧路径对照及原生可编辑PPTX/PDF下载。20页Chrome无文字溢出，全部PPTX文本与原始PNG字节读回，LibreOffice实物渲染与PDF全文读回完成；已亲自看图。修正了封面文本框高度、两种密正文构图与同心内圈缩放。源脚本、修改前版本和失败说明保留；证据见该目录README、metrics.json、office-render-check*.json、browser-check.json及各套office-sheet.png。未修改应用运行逻辑、未做模型基准、未部署；这是设计关系人工验样，摄影/材质与完整三层字图关系未全部迁移，不自评accepted，原卡保持rework。产品规则草案 `docs/product/spatial-method-application.md`，交接记录同步。

- **会话恢复与继续拆解（同卡，2026-11-05）：** 从原始会话核对用户最后方向为继续扩大参考，恢复中断前完整库索引（645套、5160页）、73套原图与102条笔记；另亲自查看3张原图汇总并新增10页拆解。独立扩展参考册 `validation/spatial-reference-2026-11-05/expanded/index.html` 为119套、952页原图、157页分析，保留初版和原始笔记。全部952页按原清单核对大小及SHA-256；实际Chrome检查全部图片解码、筛选、同套切页、新增分析、两页对照、窄屏与打印样式。证据见扩展目录 `recovery-check.json`、`browser-check.json` 和界面截图；并非生成PPT前后对比，未作为视觉验收。新增 `docs/product/conversation-handoff.md` 保存用户纠正、当前状态与下一步。未改生成逻辑、未部署；本卡保持rework。

- **扩大参考的 Codex 回写（同卡继续，2026-11-05）：** 按用户“做更多参考”的要求，从既有筛选快照保留 46 套、368 页服务器原图，逐项远端 SHA-256 校验一致；亲自查看并完成 45 页关系拆解（封面 19、正文 17、章节 4、结构 5），其余明确为仅收录。新增 `validation/spatial-reference-2026-11-05/` 的原图清单、分析数据与交互参考册。支持方法/用途筛选、搜索、同套切页及两图对照，明确适用内容、可变方式和失效条件；不把入选记录当审美认可。实际 Chrome 验证 368 图载入及上述交互、窄屏无横向溢出；亲自查看页面截图。证据 `browser-check.json`、`atlas-desktop.png`、`atlas-detail.png`、`atlas-comparison.png`、`atlas-mobile.png`；这批截图是参考册可用性证据，不能替代同内容生成前后对比。未改运行代码、未部署、未做模型基准；原视觉 rework 状态保留，内容适配样张仍待实施。原始传输最后一页中断及补取过程保留在 `download-verification.json`。

- **用户评审回写（2026-11-05）：** 用户要求提炼多种空间组织与美感，当前三个套系将素材压缩为颜色、标题位置和通用正文框架，丢失摄影透视、遮挡穿插、裁切出血、材质与尺度张力。本轮视觉方向不接受；封面/章节/正文仅是页面角色，不能代替设计方法库。下面的原实施与测试记录保留为工程证据，不构成审美验收，也不构成稳定 one-shot 验收。
- **返工依据：** `docs/product/spatial-design-rework.md`，回到原始参考，分别记录可见关系、适用内容、可变项和失效条件。下一次视觉证据应为参考原图、关系提炼、同内容适配页并列，并覆盖内容长度与素材比例变化；不能再用模板数量、换色或无溢出来证明设计价值。本次仅修正结论与设计依据，未修改生成逻辑、未部署；本地旧套系自动路径仍存在，不能视为已替换。

- **授权与范围：** 用户进一步明确“skill + 模板库”，封面、标题/章节、正文快速组成套系，AI 理解并融入内容。本轮沿用用户大范围重构授权，独立记录于 §3，不改旧 T1–T8 卡正文或历史结论。
- **Codex 回写：** 新增 `template_packs.py` 与 `data/template-packs/`，将亲自查看的三组来源素材提炼为 3 个套系、27 个可执行母版，分别记录观察、估算、派生、容量与来源；`scripts/build_template_packs.py` 可离线重建。接通 `studio.py` / `deck_flow.py` / `outline.py` / `agent_bridge.py`：AI 输出内容分组、模板与真实图片绑定，逐页原生编排和浏览器测量，母版哈希冻结，禁止外部执行器重画绑定页。整稿检查对绑定页只提问题，避免复核阶段丢掉模板结构。
- **操作与保护：** `server.py`、网页新增“整套模板”三角色预览，空稿一次选定；已有稿由 `derived.py` 创建有空间归属的整套副本，保留原稿、原始备注、重复状态限定词、逐页原图出现次数。长分栏优先切同套宽行，容量不足明确失败，不截文、缩图或擅自拆页。图片最多 3 张/页的当前限制写入产品文档。未把参考素材数量算作已完成母版数量。
- **导出实测修复：** 实际 PPTX 渲染暴露原有图片 `contain` 被拉伸的问题，`export-pptx.mjs` 改为读取 PNG/JPEG 原尺寸并计算显示矩形，原图编码不变；新增比例与媒体原字节回归。前后图 `validation/template-packs-2026-11-05/export-fit-before/crimson-page-8.png` → `crimson-grid-v1/pptx-page-8.png`。
- **测试：** 最终 Python 全量 565 项、0 跳过通过；47 项纯 JS 通过；12 个浏览器脚本首次 11 个退出 0，编辑测试等待旧 revision 与过渡双 iframe 的竞态已修正，最终定向复验通过。JEV、模型单页适配和 review replay 的条件跳过未隐藏。三套固定内容验样共 27 页 Chrome 测量溢出/图片失败/机械 error 均 0；3 份 PPTX 文本与原图字节读回通过，LibreOffice 实际渲染并逐页查看。真实试稿也已导出与查看，自动检查不冒充审美通过。
- **同题真实模型：** deepseek-flash，原始请求与上轮逐字节相同。3/3 complete、每页 attempts=1、人工重试 0，140.7 秒；上轮留存对照 230.52 秒。三页逐页模板编排无模型绘制，两处“开发中”分别可见；浏览器 3/3 完成、溢出 0。这是单次同题观察，不能认定稳定 one-shot 或固定性能提升。整稿审查仍 needs_attention（第 2 页层级、第 3 页留白与状态层级待打磨），未重跑挑选最优结果或改判 PASS。
- **证据与交付：** `validation/template-packs-2026-11-05/README.md`、`preview.html`；同题前后图 `before.png` / `after.png`，指标 `comparison.json`；套系验样 `metrics.json` 与各套系 `sample.pptx` / `pptx-sheet-*.png`；真实试稿 `model-result/sample.pptx`。产品约定 `docs/product/template-packs.md`。仅本地实现与隔离测试；现役保持 editor-68，隔离容器已清理，独立数据卷与原始失败证据保留。图片按原字节归档，清单在验证目录。


### 2026-11-05 · Office 操作与统一设计规则重构 · done-待评审（基础交互）；视觉及稳定 one-shot 待验

- **授权与范围：** 用户会议反馈后明确允许大范围重构。本轮不是重新执行 T1–T8，不改旧卡正文及历史结论；运行修改位于当前 `ppt-workbench` 工作目录，未提交/部署。原有 `DEPLOYMENT.md` 未提交修改保持。
- **设计依据：** 只读检查 `8.141.121.22` 的 pptreview，645 素材中 46 个被至少一个账号选中，不等同共同审批；保留 16 张原始参考图及聚合筛选信息。用户空间拆解规则原文存 `docs/product/spatial-design-source-v1.md`。统一设计规则见 `design_direction.py`，已接入策划、页面生成、模板适配、风格分析和检查；取消按数字比例自动放大锚点，不取消原文/原图/版本/事实保护。
- **直接操作：** 新增 `document_editing.py` 与 `/api/document`；＋在当前页后插入，复制/删除恢复/上下移动，不调用模型。`palette.py` 将整稿配色与偏好保存合为原子操作，一次撤销整批恢复。`web/app.js`、`index.html`、`editor.css` 增加 Office 式入口、参考图粘贴/拖入、整稿默认操作、草稿及源文件入口。
- **导入与后台：** 新增 `presentation_import.py` 和 `background_tasks.py`；支持可靠表达的 16:9 原生文字/简单形状/PNG/JPEG 完整导入，保留源 PPTX、备注及图片原始字节，不支持的复杂对象整份拒绝。风格处理持久化、重启恢复、模型绑定和过期版本保护；副本 owner 绑定原空间，原稿可见副本实际进度与失败。受众/改版附件超限先拒绝，不再静默丢图。
- **实测发现与修正：** API 风格分析改用直接档案 JSON，页面编辑协议保持；补错误字段和服务日志。真实改版发现两处“开发中”被文本去重合并，已取消去重，新增冻结源稿清单、整稿计划与页面落库前的原文次数/页数/页序校验；实际坏稿现在被拒绝，见 `restyle-protection-reproduction.json`。原文计数不等于限定对象的语义验收。Linux 状态读取触发 savepoint 提前提交已在新增路径改为只读 owner 查询。
- **测试：** 最终 Python **550 项通过、零跳过**（`python-complete.log`）；JS **47 项**；本地 Chrome 全量 **11 个脚本退出成功**，保留 JEV/模型适配/回放的条件跳过；最终 Office 路径针对复跑通过（`browser-complete/`）。2 页导入/导出实物文字、备注、页数和原始 JPEG 字节读回一致；实际 LibreOffice 渲染查看。未冒充线上真实浏览器验收或 PowerPoint 桌面兼容验收。
- **样稿与前后图：** `validation/office-rebuild-2026-11-05/before-ui.png` → `after-ui.png` 为相同样稿的界面前后，不是审美对比。真实同题初稿 before 0/3 失败、after 3/3 完成（230.52 秒、0 人工重试），没有可用 before 成稿，不能据此宣称审美提升。初稿 `model-results/after/sample.pptx` 已逐页查看。参考改版初次 0/3 失败；诊断重试 3/3 完成，但因丢失一处开发状态 **rework**，不作为合格样稿。最终保护修复后新建副本 **3/3 完成、323.56 秒、生成中人工重试 0 次**，原文出现次数保持，两处“开发中”分别保留；测量 3/3、溢出 0，`restyle-guarded/sample.pptx` 已逐页渲染。该单例复用已解析档案，不代表首次全流程一次成功；视觉仍有空泛装饰和偏空布局，保留待评审。
- **证据入口与边界：** `validation/office-rebuild-2026-11-05/README.md`；产品约定 `docs/product/office-rebuild.md`。图片原字节归档清单 `image-archive-manifest.json`。文档操作当前只有最近一次撤销，复杂 PPTX 尚不能任意导入；风格适配稳定性与最终审美不标 accepted。现役服务未更新，素材筛选站未修改。


### 2026-11-04 · 2026-11-03 两批改动独立复核 · rework（Codex 回写）

- **整体结论：rework。** 检查 `a037563..7db5bf7` 的9个提交，并纳入已在a037563内的8项需求。下列accepted只覆盖所列实现范围，不等于线上整体验收。看板未给这两批改动单列任务卡，故集中回写于§3，旧卡正文与历史结论保持。
- **线上版本不一致：** DEPLOYMENT最新只记录editor-68；公网app.js与a037563至5c66635间版本相同，与c16f37c及后续前端不同；`/api/me`404，导出仍为百分比行距，白底Logo导出仍全不透明。无法证实当前镜像就是请求验收的editor-69，不自行改写发布历史。

| 复核项 | Codex结论 | 依据/返工原因 |
|---|---|---|
| 缩略图增量、画布淡入 | accepted（实现） | JS增量复用通过，代码保留旧帧至新帧ready；线上观感待测。 |
| 样式类别、越界滑动 | accepted（实现） | JS类别/选择保持与本地Chrome分类、窄屏通过；触控板手势未测。 |
| 主色+辅色 | accepted（实现及线上API） | 线上示例配色确实变化，undo恢复原scene；UI按钮待测。 |
| 图片/PPTX模板、拒绝只换色 | accepted（本地实现） | 上传/可编辑导入/IoU退回用例通过；真实模型浏览器适配分支跳过，线上新版入口未验。 |
| 对标解析、逐页改版、风格副本 | rework | `_copy_images`跳过`image-slot*`已生成真图；同图普通ID复制1张、自动配图ID复制0张。解析/预览确认的本地用例通过。 |
| 历史偏好推荐 | rework | 后台任务缺owner上下文，Alice任务读入Bob三个项目的品红色偏好；HTTP范围内隔离通过不能替代worker隔离。 |
| 受众版本与原稿对照 | accepted（本地实现）；线上rework | 新项目/来源/对照映射用例通过；公网前端缺新增对照能力。原图复制同上待修；未重跑受众模型。 |
| Logo去底、挪字、强制放置 | rework | 本地去底与放置通过，但2400×1200输入先降采样，处理后1040×440；公网PPTX图片alpha全255。 |
| 自动放大锚点 | rework | 读取page.blocks而非page.composition.blocks；合法7字metric仍32px，错误扁平结构对照却变72px。 |
| 待补充不判失败 | accepted（规则实现） | 提示词明确区分资料缺口和视觉/证据问题；本次线上未进入审稿，不声称模型实测通过。 |
| PPTX点数行距 | accepted（本地实现）；线上rework | 实物正文由150%改为36pt、文本完整；公网导出仍spcPct。 |
| 匿名空间、项目/模板隔离、空间码 | rework | 本地HTTP隔离/迁移通过，但后台偏好越界；公网/api/me缺失，双浏览器迁移未完成。 |

- **首次整稿：** `project-4ce8868bd59f3af9`，deepseek-flash，原4页We-PPT需求、默认配图，一次输入、0人工重试；187.76秒观察到`INVALID_PROJECT_FIELDS / purpose 取值不支持`，0/4页，没有配图/可导出整稿。测量0/0是无页面，不是N/N完成。创建与输入使用公开API，不冒充浏览器输入。
- **线上API补充：** 独立示例`project-220ce249034198b5`，不混入首次整稿。配色应用/undo scene等值恢复；白底Logo上传/应用/单页PPTX导出完成，嵌入图片等于处理预览、alpha255–255，仍有白底；已实际LibreOffice渲染并读回文字。没有修改用户已有项目。
- **测试：** Python最终527项/96.332秒/零skip通过；本地浏览器10组退出成功（review replay、JEV smart selection、配置模型的template adaptation路径跳过）；本地测量3/3；JS47项通过。最初MCP子进程6个import错误，修复本机editable安装后完整复跑通过，初始失败日志保留。未改源码或测试。
- **访问限制：** 浏览器工具报host unavailable，已请求恢复连接或授权替代真实Chrome测试，尚无答复；严格SSH认证被拒绝，未修改信任/密钥。线上按钮操作、两个真实浏览器隔离/空间码迁移、自动配图封面N/N及线上UI截图未完成，不能标accepted。HTTP固定正确服务器IP，TLS校验保持。
- **证据/对比图：** `validation/editor69-codex-review-2026-11-04/README.md`为完整报告；`export/before/slide-1.png`→`export/after/slide-1.png`是本地行距前后，`live-operations/rendered/slide-1.png`是线上导出渲染（非UI截图）；本地分类图`browser-local/categories.png`。反例见`reproductions.json`、`owner-context-results.json`、`derived-image-repro.json`；线上原始结果`live/`与`live-operations/`。图片原字节归档清单`image-archive-manifest.json`。
- **改动边界：** 仅本次证据和§3回写；未修复或部署运行代码，未代用户人工验收。后续针对四个代码反例、发布一致性及缺失的真实浏览器路径复验即可。


### 2026-11-02 · editor-58 · T3/T8 第二轮返工独立复核（Codex）

- 结论：T3 accepted，中文数词反例及完整引用15/15通过、正文保留，继续接受已明确的新正文口径；T8 rework，仅剩后台真实测量未完成，主画布/自动配图封面载入已通过。各卡最新结论写入Codex回写，任务正文与Devin记录保留。
- 验证：27项相关Python/零skip、43项JS通过，六组更名指标与前次独立重算一致，7份线上关键文件与本地相同。真实Chrome封面原图1106×1422完整加载，srcdoc回退成功；最终0/4页测量、全部超时。没有人工验收、没有修改或部署运行代码。
- 新整稿：project-d80df9b095106c48，deepseek-flash，同原4页需求，默认配图；首次190.19秒、0/4页、INVALID_SCENE/num.fontSize，人工重试0、改稿0，未排队配图，无成稿可导出。创建/输入走现有线上API，浏览器另核终态。
- 访问限制：用户确认DNS污染。使用本机临时入口固定线上IP，HTTPS域名及证书校验保持；不改系统DNS或线上配置。普通公网访问是否恢复未验收。
- 对比图：旧`validation/vivid-T3T7T8-codex-recheck-2026-11-01/editor-blocked-after-reload.jpg`→`validation/vivid-T3T8-codex-recheck-2026-11-02/cover-loaded.jpg` / `cover-measurement-failed.jpg`；首次整稿`validation/vivid-T3T8-codex-recheck-2026-11-02/one-shot-blocked.jpg`。完整报告`validation/vivid-T3T8-codex-recheck-2026-11-02/README.md`，原图/截图按原始字节归档，清单`image-archive-manifest.json`。

### 2026-11-02 00:22 · T3/T8 第二轮返工 · 已发布 editor-58（Devin）

- 改动：T3 中文数词边界与指标字段更名；T8 主画布与测量帧改为"只认 ppt-ready + srcdoc 回退"；可选装饰字段的非法值归一化处理，不再阻断整页。T7 按 Codex 结论标为 accepted。
- 测试：Mac 449 项、JS 43 项通过；Linux editor-58 449 项 OK（9 项可选依赖跳过），镜像内 JS 43 项通过。
- 发布：网络极慢，改为只上传 5 个变更文件，在服务器上由 editor-57 加变更组装 editor-58，259 个文件按完整清单校验通过、无多余文件。2026-11-02 00:22 CST 切换；备份 `before-editor-58.sqlite` 完整性 ok；200 个运行文件与清单一致；HTTP 200；线上 app.js 已含回退；数据库完整。
- 未做：没有重跑模型基准（本轮改动均为确定性逻辑，已用单测和本地浏览器复现验证）；线上浏览器复测因网络过慢未完成，等待 Codex 实测。

### 2026-11-01 · editor-57 · T3/T7/T8 返工独立复核（Codex）

- 结论：T3 rework（接受新字数口径，中文金额边界仍有漏洞）；T7 accepted（对T1基线两题新指标达标）；T8 rework（手改保护/总开关已通过，12秒兜底仍空白）。逐卡最新结论追加在Codex回写顶部，旧评审和Devin返工记录保留。
- 验证：449项Python/75.102秒/零skip、42项纯JS通过；独立重算metrics-rework字段全部一致，并单独计算bodyOnly；原失败场景、正例、中文数词边界、三种用户手改、服务器锁、跨页用户修改后的过期状态已验证。没有修改运行代码或发布。12份线上关键文件与本地一致。
- 新线上项目：`project-346f5da592b13f4b`，editor-57、deepseek-flash、原4页Product请求、默认配图。首次约360.57秒blocked，仅3/4页，第4页INVALID_SCENE/title.emphasis；人工重试0、人工改稿0，配图未排队。失败原件保留，不将部分结果当完整one-shot。
- 实物检查：通过明确单页导出取得3份partial.pptx，逐页LibreOffice渲染并看图，原生文字读回完整。封面标题在LibreOffice下越出深色区，浏览器完整；记录导出差异，不以机械零错误掩盖。未测试PowerPoint桌面版。
- 证据/对比图：`validation/vivid-T3T7T8-codex-recheck-2026-11-01/README.md`与`independent-results.json`；editor-53的`validation/vivid-T2T8-2026-11-01/after-product.png` / `after-memory.png`对照同目录raw57两套final-render/sheet-*/candidate.png；新线上`validation/vivid-T3T7T8-codex-recheck-2026-11-01/live/rendered/`，主画布前后`editor-blocked-before-reload.jpg` / `editor-blocked-after-reload.jpg`，直接预览`direct-S003-preview.jpg`。


### 2026-11-01 19:40 · T3/T7/T8 返工 · 已发布 editor-57（Devin）

- 改动：见 T3、T7、T8 的「Devin 返工记录」。T2/T4/T5/T6 按 Codex 结论标为 accepted。
- 测试：Mac 449 项、JS 42 项通过；Linux editor-57 449 项 OK（9 项可选依赖跳过）。
- 重跑：editor-56 两题都在计划阶段失败，暴露两处健壮性问题，已在 editor-57 修复。editor-57 两题一次完成：Product 27 次调用 / 730 s；Memory 35 次调用 / 1325 s，比 editor-53 更慢；指标见 `metrics-rework.json`。
- 发布：2026-11-01 19:40 CST 切换。备份 `before-editor-57.sqlite` 完整性 ok；200 个运行文件与清单一致；HTTP 200；数据库完整。

### 2026-11-01 · T2–T8 独立复核（Codex）

- 结论：accepted：T2/T4/T5/T6；rework：T3/T7/T8。逐卡原因已写入Codex回写。未修改任务正文、复选框、状态标题或Devin记录；评审结论以本次回写为准。
- 改动范围：仅协作回写与`validation/vivid-T2T8-codex-review-2026-11-01/`复核证据，未修改、发布运行代码。创建一个线上全新项目，一次提交原4页Product需求、deepseek-flash、默认配图；未重试或人工改稿，页面选择/浏览器刷新仅用于验证UI。
- 测试：Python445项/零跳过、JS42项通过；独立复现T3无来源数字放行、T8预留区手改覆盖及全局关闭不生效；重算既有两套计划、正文、字号锚点、多样性指标；新原语实际浏览器/PPTX渲染对照、媒体字节核对通过。PowerPoint桌面版未测。
- 对比图：`validation/vivid-T1-2026-11-01/after/` → `validation/vivid-T2T8-2026-11-01/after-product.png`、`after-memory.png`；独立原语`validation/vivid-T2T8-codex-review-2026-11-01/primitives/browser.png` ↔ `primitives/slide-1.png`。线上最终渲染、截图与首次结果见`validation/vivid-T2T8-codex-review-2026-11-01/README.md`。
- 线上首次结果：4/4页、封面自动配图1/1成功、682.47秒、无人工生成重试；最终机械/节奏告警0，锚点1/4页，4页PPTX逐页渲染与文字读回完成。配图前needs_attention、落图后stale；Chrome主画布持续载入中，刷新未恢复，直接预览正常。完整结果保存在复核报告，不认定整体验收通过。
- 证据修正：既有Product封面图来自单独重试；T3逐页下降并非全成立；T7指标饱和/两题方向不一，均不能扩大为one-shot质量已通过。


### 2026-11-01 17:10 · T1-F、T2–T8 · done-待评审（Devin 实现，已发布 editor-55）

- 改动：见各卡「Devin 实现记录」。基准中又发现并修复三处：生图会话出两张图被拒收（editor-54）、整稿检查超出修正预算时一页都不修（editor-54）、单页检查不能同时 patch 加新增底板（editor-55）。
- 测试：Mac Python 445 项、纯 JS 42 项通过；Linux 镜像 editor-55 共 445 项 OK（9 项可选依赖跳过）。
- 基准（同模型同输入，对照 T1-after）：两套整稿一次完成，0 人工干预；Memory 30→22 次调用、1333→744 s。每页都有 layoutArchetype 且相邻不重复；两张封面自动配图落地；机械错误、溢出、节奏告警均为 0。数据：`validation/vivid-T2T8-2026-11-01/README.md`、`metrics.json`；拼图：`after-product.png`、`after-memory.png`。
- 未达标：Product 只有 1/4 页有 ≥72px 锚点；Memory 相邻页相似度 0.75（未超 0.85 告警线）；两套整稿自动检查均为 needs_attention；T4 第 4 页修正后仍有 LOW_SCALE_CONTRAST。
- 发布：2026-11-01 17:10 CST 切换到 `weppt-dev:20261101-editor-55`，详情见 `DEPLOYMENT.md`。

### 2026-11-01 03:31 · T1 · done-待评审

- 改动：仅重写agent_bridge.INSTRUCTIONS与deck_design.designInstruction的视觉规则；不增加运行功能，不动T2–T8及安全校验。保存修改前后源码、精确patch和AST范围检查。
- 测试：Python417项/零跳过、纯JS42项通过；四份PPTX结构检查与20页原生文本读回通过；20页实际渲染及两张contact sheet已查看。`git diff --check`及源文件冻结检查见最终验证记录。
- 前后对比：`validation/vivid-T1-2026-11-01/before.png`、`validation/vivid-T1-2026-11-01/after.png`；`metrics.json`记录逐页字号、色块、深底和最终机械错误。大色块合计0/10→9/10，字号比达标1/10→9/10，深底3/10→4/10。
- 未通过：Memory第6页字号比2.3<2.5；PPTX渲染第4/6页序号拆行、第6页压正文，虽浏览器overflow为0仍不可认定导出通过。问题图见同目录`after/memory/rendered/slide-4.png`、`slide-6.png`；We-PPT第3页换行仍拥挤。验收未全通过，保留待评审。
- 偏离：before-memory规划失败后重跑，整稿审稿失败后离线原样导出；after-memory首次4/6页截断，现有产品retry一次补齐6页，累计30次调用/1333.47秒，人工重试1次。所有失败和重试保留，详见`README.md`、`attempts.json`和`raw/`，不计作one-shot成功。
- 交付边界：未发布、现役editor-52保持；6个隔离基准容器均退出。148张原图归档到`/Users/auntlee/Pictures/Codex生成图片/WePPT/vivid-T1-20261101/`，逐字节一致。任务正文和Devin评审区保持，不代人接受。

<!-- 格式：
### YYYY-MM-DD HH:MM · Tx · 状态
- 改动：
- 测试：
- 对比图：
- 问题/偏离：
-->

## 4. 评审意见（Devin 追加，最新在上）

### 2026-11-01 · T2–T8 · 待独立复核

- 本轮实现者与评审者都是 Devin，不能自评 accepted。请 Codex 或用户依据各卡「Devin 实现记录」、`validation/vivid-T2T8-2026-11-01/` 和线上 editor-55 做独立复核，并在各卡「Codex 回写」中写结论。
- 建议优先看：① 线上新建一套整稿的实际观感（含封面配图）；② 新原语在 PowerPoint 桌面版中的显示（本轮只验证了 LibreOffice）；③ T3 的大号锚点在 Product 类题目上用得仍少。

### 2026-11-01 · T1 · accepted（附 3 个跟进项，由 Devin 在 T1-F 中处理）

- 结论：提示词改写方向正确、范围克制。同模型同输入下，大色块页 0/10→9/10、字号比达标 1/10→9/10，封面"We-PPT"大字、"边界"大关键词、非对称色块都已出现，"死板"的主因已被消除。Codex 的失败与重试记录完整、未挑样，评审依据充分。
- 未达标项判断：Memory 第 6 页 2.3 属于提示词无法保证逐页执行的问题，应由 T5 指标 + T4 审稿兜底，不再在 T1 内返工。
- 跟进项（T1-F，Devin 直接实现）：
  1. **PPTX 两位序号拆行/压字**：浏览器单行、LibreOffice 拆成两行，根因是导出的文本框允许换行且 Office 字体度量更宽。短单行文字导出时改为不换行。
  2. **输出截断**：T1 增加了对象数，整页 JSON 更长，`MODEL_OUTPUT_TRUNCATED` 直接阻断整稿。增加紧凑输出规则，整稿页截断时自动带"更紧凑"纠正重试一次。
  3. **容量估算基线**：`content_capacity` 仍按旧的 26px 正文估算，与新字号表（正文 18–22px）不一致，改为 20px。
- 协作方式变更：用户 2026-11-01 指示 T2–T8 由 Devin 直接实现并验证、在服务器跑基准、验证后发布；Codex 可做独立复核。T8 已由用户确认"实现，默认开启"。

<!-- 格式：
### YYYY-MM-DD · Tx · accepted / rework
- 结论：
- 需要返工的点：
-->
