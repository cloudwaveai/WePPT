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

### T1 · 重写提示词里的视觉规则：从"禁止清单"改为"设计工具箱"　`P0` `状态: todo`

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
> （改动文件 / 测试结果 / 对比图路径 / 偏离说明）

---

### T2 · 扩展 Design / Strategy / DesignBrief 字段，让"风格"可落地　`P0` `状态: todo`

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

- [ ] 旧格式计划仍能通过校验（加回归测试）。
- [ ] 新字段非法值被拒（加测试）。
- [ ] 基准对比：生成的计划中每页都有 `layoutArchetype`，相邻无重复。

**Codex 回写**：
>

---

### T3 · 计划阶段加"可视化锚点"文案，减少整段句子上屏　`P0` `状态: todo`

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

- [ ] 用户原文的数字/事实保护测试仍通过；新增"metric 不在原文中 → 拒绝"的测试。
- [ ] 基准对比：after 中每页正文总字数下降、至少一半页面有 ≥ 72px 的锚点元素。

**风险**：与"原文必须完整上屏"的现有规则冲突。处理：用户**粘贴的原文**仍必须完整出现在页面或备注中；模型自己起草的文案才适用 40 字规则。拿不准就在回写区提出来。

**Codex 回写**：
>

---

### T4 · 检查循环加入"视觉张力"标准　`P1` `状态: todo`

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

- [ ] 用 `outputs/weppt-content-capacity-2026-10-31/scenes.json` 第 1、4 页作为输入跑一次 `review_candidate`，期望返回 REVISE 并给出具体视觉修改（把报告放进 validation 目录）。
- [ ] 不放宽任何原文/原图保护。

**Codex 回写**：
>

---

### T5 · 机械化"视觉节奏"指标（只出 warning，不拦发布）　`P1` `状态: todo`

**目标**：给审稿模型和用户提供客观证据，也作为本项目的效果度量。

**位置**：`ppt_workbench/quality.py`（新增函数），`deck_review.py` 的 context 构造（L136-142）。

**做法**：新增 `visual_stats(scene)` 与 `deck_rhythm(scenes)`：

- 每页：`fillAreaRatio`（非背景填充 rect/图片面积 / 画布面积）、`scaleRatio`（最大字号 / 正文众数字号）、`distinctFills`、`textAreaRatio`、`isInverse`（背景亮度）、`layoutSignature`（把对象 bbox 量化到 4×3 网格后的占用指纹）。
- 整稿：相邻页 `layoutSignature` 相似度 > 0.8 → `LAYOUT_MONOTONY`（warning）；`scaleRatio < 2` → `LOW_SCALE_CONTRAST`（warning）；整稿无 inverse 页且 ≥ 5 页 → `NO_TONAL_RHYTHM`（warning）。
- severity 一律 `warning`，**不得**加入阻断发布的 error 集合。
- 把结果放进 deck_review 每页的 context（`visualStats`）和整稿 context（`deckRhythm`）。

**验收**：

- [ ] 单测：用现有 4 页死板样例应触发 `LOW_SCALE_CONTRAST` 和 `LAYOUT_MONOTONY`。
- [ ] 指标写入 §2.0 的 `metrics.json`，作为后续每张卡的统一度量。

**Codex 回写**：
>

---

### T6 · 扩充 Scene 原语（编辑器、HTML 预览、PPTX 导出三处同步）　`P1` `状态: todo`

**目标**：给模型更多可编辑的视觉词汇。

**位置**：`rendering.py`（`TYPE_FIELDS`、`validate_scene`、HTML 渲染）、`local_renderer.py`、`export-pptx.mjs`、`quality.py`（几何/遮挡判断）、`studio.py` `sceneSpec`（L742-751）、`web/app.js` 编辑器（如有类型分支）、相关测试。

**做法**（按价值排序，可拆成 T6a/T6b/T6c 分别提交）：

- T6a `ellipse` 类型（字段同 rect 去掉 radius）→ pptxgenjs `ShapeType.ellipse`。用于节点、大圆底、装饰圆。
- T6b 文本 `runs`：`[{text, color?, bold?, fontSize?}]`，与 `text` 二选一；用于标题中的关键词高亮。pptxgenjs `addText` 支持数组。注意：textRef/原文保护要能处理 runs（拼接后等于原文）。
- T6c 通用 `rotation`（-180~180）与 rect/ellipse `shadow`（`{blur, offsetY, color, opacity}` 的受限预设，如 `soft`/`none`），文本 `letterSpacing`（pptxgenjs `charSpacing`）。
- 不做：渐变（pptxgenjs 不支持）、SVG、任意路径。

**验收**：

- [ ] 每个新字段：校验测试、HTML 渲染测试、PPTX 导出后回读（参考现有 `export-readback.json` 流程）。
- [ ] 旧 scene 完全兼容。
- [ ] 浏览器预览与导出 PPTX 渲染对比无明显偏差（截图放 validation）。

**Codex 回写**：
>

---

### T7 · 生成上下文加入 few-shot 好页面示例　`P1` `状态: todo`

**目标**：模型模仿示例比遵守规则有效得多。

**位置**：`deck_design.generation_context`（L143-173），数据源 `ppt_workbench/data/design-map-scenes/*.json`（62 个现成 scene）。

**做法**：

1. 从 design-map-scenes 中挑 8-12 个视觉层级强的 scene，按 `layoutArchetype`（T2 词表）打标签，存为 `data/design-exemplars.json`（只保留几何、字号、颜色角色，文字替换为占位语义，如"<标题>""<大数字>"，避免模型抄内容）。
2. `generation_context` 根据当前页 `designBrief.layoutArchetype` 取 1-2 个示例放进 `designExemplars`，并注明"学习比例和层级，不抄文字和坐标"。
3. 控制 token：每个示例对象数 ≤ 25。

**验收**：

- [ ] 上下文大小增长可控（记录前后字节数）。
- [ ] 基准对比：版式多样性（T5 的 layoutSignature 去重数）提升。

**Codex 回写**：
>

---

### T8 · 可选：自动配图模式　`P2` `需用户确认` `状态: todo`

**目标**：封面/章节/关键论断页可自动生成无文字背景图或插画，文字仍为原生可编辑对象。

**背景**：项目已有 `image_generation.py`、`codex_image_provider.py`，但 `image_generate` 仅在用户显式要求时可用（`agent_bridge.py` L294）。

**做法（待用户拍板后细化）**：在项目 brief 增加 `imageMode: off | accents | illustrated`，默认 `off` 保持现状；开启后，Strategy 的 `imagePolicy` 允许在指定角色页自动排队生成背景图（无文字、无 logo），失败时回退到纯色块版式。

**需要用户确认**：是否接受自动生图带来的耗时与成本？默认开还是关？

**Codex 回写**：
>

---

## 3. 实施日志（Codex 追加，最新在上）

<!-- 格式：
### YYYY-MM-DD HH:MM · Tx · 状态
- 改动：
- 测试：
- 对比图：
- 问题/偏离：
-->

## 4. 评审意见（Devin 追加，最新在上）

<!-- 格式：
### YYYY-MM-DD · Tx · accepted / rework
- 结论：
- 需要返工的点：
-->
