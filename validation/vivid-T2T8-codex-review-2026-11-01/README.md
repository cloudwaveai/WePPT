# T2–T8 独立复核（Codex，2026-11-01）

范围：核对各卡 Devin 实现记录、现有基准产物、当前代码；线上创建一个全新项目提交原来的 4 页 We-PPT 产品介绍需求一次。没有修复或发布运行代码，没有人工改稿、重试或挑选结果。只回写各卡 Codex 区和 §3；保留任务正文、复选框、Devin 记录与 §4。

## 逐卡结论

| 卡 | 结论 | 判断依据 |
|---|---|---|
| T2 | accepted | 可选设计字段兼容旧计划、非法值被拒；计划复核获得节奏证据。独立重算两套计划均无相邻原型重复、节奏告警 0；线上新计划也有四种不同原型。接受 ordered-rows 扩展及 warning/复核式约束。 |
| T3 | rework | **事实保护漏洞**：create_deck 实际保存了“180个用户”→“80”、“3个模块”→“3亿元”、无比例原文→“八成”的无来源锚点。正则仅检查数字子串，既不检查边界与单位，又放过无阿拉伯数字的锚点。另 Product ≥72px 仅 1/4 页，正文第2页125→129字，不满足“每页下降”。 |
| T4 | accepted | 旧死板页1、4均 REVISE、有具体色块/字号/分区修正，repairAccepted=true、文字不变。当前代码加入视觉证据及椭圆，组合修正仍有原文、原图及版本检查；范围外建议不应用且该轮不能 PASS。两页 needs_attention 是诚实保留，不能写成审美验收完成。 |
| T5 | accepted | 旧样例触发 LOW_SCALE_CONTRAST / LAYOUT_MONOTONY；指标进入检查上下文，均 warning。接受按字数加权正文众数及2.5/4页阈值；相似度实际阈值≥0.85（任务原>0.8），仅作诊断。此接受不代表指标可替代人工观感判断。 |
| T6 | accepted | 新图元、emphasis、字距在校验、HTML、编辑属性及PPTX链路可用；独立原语页实际浏览器截图与 LibreOffice 渲染无明显结构偏差；445项中相关XML/原文/编辑回归通过。emphasis替代任意runs可保持text为唯一来源。没有验证Microsoft PowerPoint桌面版，不能作该兼容性承诺。 |
| T7 | rework | 实现和token控制成立：10种示例、每例5–19对象，每页附加约1530–3486 UTF-8字节，不携带示例正文。但验收效果未证实：去重仍4/4、6/6；Product最大相邻相似度0.667→0.25，Memory 0.583→0.75。应由Devin调整已饱和的验收指标并补相应证据，不能靠阈值下无告警宣布提升。 |
| T8 | rework | **用户手改被覆盖**：待落图时把预留矩形旋转15°、改色或加阴影，三次均自动applied，矩形变图片且手改消失；slots_unchanged只比较类型和x/y/w/h。另项目保存auto后设置WEPPT_AUTO_IMAGES=off仍返回auto，与“服务器整体关闭”描述不符。 |

T3 建议返工范围：给 metric 明确原文引用/来源片段，核对完整数字与单位，覆盖中文数字和比例；不能把数字在其他事实上出现当作授权。补本报告三种反例测试，重新验证产品题目的锚点与逐页正文目标。未实现 notes、kicker 限16字等已披露偏离不是本次主要拒收原因。

T8 建议返工范围：入队时保留预留对象快照或指纹；目标对象有用户修改就冲突保留，其他对象的无关改动仍可允许落图。明确服务器开关是强制关闭还是仅默认值，实现与文档保持一致，补持久化auto场景测试。

## 独立验证及证据口径

- Python全套：445项、74.155秒、零跳过、OK（`unittest.log`）。JS纯逻辑：42项通过（`ui-logic.log`），不冒充浏览器回归。
- 本地复现：`reproduce.py` → `reproductions.json`，调用真实 Studio.create_deck/change_scene/ImageJobs；生图提供者和渲染是本地fixture，无模型调用/付费请求。缺陷是实际保存/落图结果，不仅是孤立helper结果。
- 指标：`recompute.py`、`independent-metrics.json`；旧正文从原始只读SQLite中提取。Product逐页正文 `[46,125,130,104] → [32,129,95,71]`；Memory `[43,171,203,215,244,201] → [26,119,92,145,105,134]`。页序对应但内容组织改变，不能将总量下降当作逐页下降。全部上屏字数Product第2页同样183→188。
- 现有T4模型运行记录：`../vivid-T2T8-2026-11-01/t4-review.json`。本次核对代码、报告、原文检查及回归，不额外调用模型重跑这两页。第4页修正后仍 LOW_SCALE_CONTRAST，与记录一致。
- T5口径限制：`fillPanelPages(>=15%)` 现有脚本实际统计采样总填充面积，不等于“一个连续色块面积≥15%”；旧T1数据用新正文众数重算，与T1原手工字号判据不能混用。64×36采样、4×3指纹是近似值，不保证看得好。
- 现有基准Product首次配图失败，editor-54副本上单独重试成功；Memory首次配图成功。README已披露，但§3“两套0人工干预+两张封面落图”需拆开解释，不能将重试后的Product图计为完整one-shot。
- 已查看两套现有contact sheet及Memory第2、4页/Product流程页原图。Memory第2页标题“记忆”断为末行单独“忆”，仍可见；没有机械error不代表视觉无问题。
- 原语独立产物：`primitives/scene.json`、`primitives/index.html`、`primitives/primitives.pptx`、`primitives/primitives.pdf`、`primitives/browser.png`、`primitives/slide-1.png`。实际打开浏览器、渲染PPTX并看图，序号01完整单行、文字未缺失。用户机器未提供PowerPoint桌面验证，使用Chrome+LibreOffice，渲染字体配置保存在同目录。
- `existing-media-integrity.json`：Product重试图片与Memory原图在PPTX媒体内逐字节SHA256一致（约2.12MB、2.58MB）。ZIP DEFLATE为无损容器压缩，没有重新编码图片，不作为违反原图保护的缺陷。

## 前后对照路径

- before：`../vivid-T1-2026-11-01/after/product/rendered/`、`../vivid-T1-2026-11-01/after/memory/rendered/`。
- after：`../vivid-T2T8-2026-11-01/after-product.png`、`../vivid-T2T8-2026-11-01/after-memory.png`及其`after/`逐页原图。Product拼图包含重试配图，原首次失败保存在`raw/product/`。
- 新原语浏览器/导出对照：`primitives/browser.png` ↔ `primitives/slide-1.png`。保持原始像素与编码，不重采样拼图。

## 线上新整稿实测

- 项目：<https://ppt.bbstack.date/?project=project-90b780a7be9936e3>。
- `deepseek-flash`，默认 `imageMode:auto`，原4页产品请求见`request.txt`，一次提交；观察脚本`live_test.py`。
- 线上 editor-55：`weppt-dev:20261101-editor-55`，镜像 `sha256:1ecce733d77858c84afa243094fe3cd02a2985119725e7ce74ca7f2c0379e6ac`。核对16份核心文件与本地逐一一致（`live-code-hashes.txt`与`source-hashes.json`），未改服务配置。
- 首次结果：4/4页complete，封面1张自动图片applied；总耗时682.47秒（含导出），用户提交1次、人工生成干预0次。各页attempts=1，系统内部检查/修正仍有多轮，不将它称作“只调用模型一次”。
- 自动检查：配图前整稿needs_attention，已自动修正S002；报告仍指出流程图缺少第4步节点、连接关系未收尾。配图后场景版本更新，整稿designReview变为stale，humanAccepted=false、qualityAccepted=false。该保守失效判断是正确的，但自动配图后尚未闭合最终检查，不能宣布最终版质量通过。
- 在线浏览器：Chrome看到4页缩略图与生成完成消息，封面缩略图已经落图；但主画布持续“正在载入新版本”，停留空白引导页，浏览器测量0/4。选择封面、刷新一次后仍未恢复。直接打开同一项目的/api/preview/S001则正常显示封面（含图）。因此确认服务器产物存在，编辑器集成体验未通过；根因尚未定位，不将其直接归因于T6新增原语，也不在本复核中擅自修改。证据`live-editor-before-reload.png`、`live-editor-after-reload.png`、`live-cover-browser.png`。
- 测试操作边界：浏览器选页与刷新没有提交内容、点击认可或发起重试；保留第一次自动生成结果，未将UI刷新计作模型生成干预。
- 完整证据：`live/summary.json`、`live/progress.jsonl`、`live/final-state.json`、`live/review-reports.json`、`live-plan.json`、`live/scenes.json`、`live/deck.pptx`。实际PPTX渲染与逐页读回见`live/deck.pdf`、`live/rendered/slide-1.png`至`slide-4.png`、`live/readback-and-metrics.json`。


### 最终产物人工看图

4页PPTX均经LibreOffice实际渲染后逐页查看，4页原生文本读回与scene完全一致，未见新增文字截断或遮挡。封面图与深底统一，内容页有浅底流程、左右分栏、深底重点带的变化；仍是较规整的列表/分区表达。第2页前三步在线上，第四步在独立卡片中，缺少一致节点，视觉更像“3+1”；这与自动检查提出的流程收尾疑点一致，应由后续修改或人工接受解决。

最终机械error=0、计划节奏告警=0、视觉节奏告警=0，≥72px页仍仅封面1/4。自动配图原始PNG为2,581,675字节，与PPTX内媒体哈希相同；没有压缩或重编码原图。完整PPTX与PDF保留为草稿，不标为已认可的正式交付。

归档：本次生成/截图的10张原始PNG已逐字节复制至`/Users/auntlee/Pictures/Codex生成图片/WePPT/vivid-T2T8-codex-review-20261101`；清单`image-archive-manifest.json`。范围校验`scope-verification.json`确认任务正文/Devin记录完整、运行代码及测试未修改。
