# T1 提示词视觉工具箱验证

日期：2026-11-01。任务来源：docs/collab/devin-codex.md §0、§2.0、T1。

## 范围

运行代码仅修改agent_bridge.INSTRUCTIONS与deck_design.generation_context.designInstruction。未执行T2–T8，未改变校验、检查循环、原文／原图保护、图片引用或自动生图授权。原有未提交修改保持。本次产物供Devin评审，未切换开发环境版本。

## 对比协议

- 同一运行镜像：weppt-dev:20261031-editor-52；两组分别只读挂载baseline-source或after-source下的两个文件。
- 同一服务器已配置模型：deepseek-flash，官方API；密钥只由既有服务器env文件注入，不进入本地、产物或源码。
- We-PPT输入逐字复制attempt50/request.txt；Agent Memory输入逐字复制attempt47/request.txt。两组均从空白独立项目开始。
- before与after各对两个题目生成整稿（首次无页面的协议失败允许一次原配置重试并完整留档），保留全部原始结果，不挑选多次生成中的最佳结果，不人工润色，不将模型检查当用户验收。
- 同时最多两个隔离容器，独立数据卷，配置卷只读；不写现有项目或替换开发服务。
- 每份PPTX均读回并实际用LibreOffice渲染为PNG；contact sheet只原尺寸拼接，不压缩或重采样原图。
- 模型随机性仍存在；单次同题对比不能证明普遍因果或所有模型有效。

## 指标口径（仅验证脚本，不实现T5）

逐页记录实际字号、正文对象ID、最大字号／正文基准字号、可见非背景rect色块面积和背景色。正文基准按实际文本用途人工确认；有不同正文级别时记录全部级别并使用最大正文级别，防止只选择较小字号抬高比例。大色块阈值为画布15%，填充与背景相同或完全透明者不计；前景遮盖情况结合渲染检查。背景相对亮度低于0.2记为深底。

TEXT_CONTRAST以现有quality.audit_scene为准，TEXT_OVERFLOW以最终实际浏览器测量为准；实际PPTX另做逐页视觉检查。完整日志及未通过项保留。


## 运行记录

- 全量Python回归417项通过（76.192秒，零跳过）；前端42项纯JavaScript回归通过。
- before-memory首次规划响应达到16384输出上限，返回MODEL_OUTPUT_TRUNCATED，未生成页面。保留失败容器／卷／日志，使用完全相同的模型、输入和代码在独立空白项目重试一次。未改变provider输出限额。

- before-memory重试完成6/6页，但整稿检查返回范围外操作（DECK_REVIEW_SCOPE），最终状态blocked。为完成视觉对比，在无网络容器中离线导出完整6页；未再调用模型，未改场景，原summary保留，另写artifact-summary.json。首次离线导出因缺少PYTHONPATH失败；补环境变量后成功，两个日志均留存。
- after-product完成4/4页，17次模型调用、586.43秒；自动审稿为needs_attention。两次流程页修正均遭MODEL_OUTPUT_TRUNCATED，未应用修正。不把该状态改写为人工通过。

## 已观察到的视觉问题

- before-memory封面最后一个“住”单独换行；正文页面主要是细线与文本；已有一页深底。
- after-product封面和尾页增加大字号焦点，正文使用非对称色块，流程用分组色块。流程页仍拥挤，浏览器记录到孤行，连线高低不一；这是可读性缺陷，即使未触发TEXT_OVERFLOW，也不能称为最终高质量成稿。
- 只评估此次同模型同输入样本；输入相同不等于生成文案完全相同。基准保留模型原输出，未人工改成漂亮样板。

## after-memory 的补充重试（协议偏离）

初次 after-memory 在第五页输出截断后 blocked，只保存4/6页；22次调用、1037.34秒，人工干预0。原始结果保存在 `raw/after-memory/`。为了取得完整六页视觉对比，使用现有 `control_deck('retry')` 一次，不改输入、模型、提示词或已保存页面。重试容器继续使用原独立测试数据卷，生成后续页并运行原有整稿检查。累计调用和耗时、人工重试1次会写入最终结果；不将其标为one-shot成功。

初次运行中的单页报告保留了4次DESIGN_OVERFLOW、1次DESIGN_REVIEW_SCOPE（修正改变原文字或原图）、1次审稿MODEL_OUTPUT_TRUNCATED；随后第五页生成也遇到MODEL_OUTPUT_TRUNCATED。单凭slide_add动作名不能判断是否违规：新页审稿允许以完整slide_add替换隔离候选，是否接受取决于内容与范围校验。

## 最终结果：提示词实施完成，验收未全通过

| 样例 | ≥15%色块页 | 深底页 | 字号比≥2.5页 | 最终机械对比度/浏览器溢出错误 |
| --- | --- | --- | --- | --- |
| before / product | 0/4 | 2/4 | 0/4 | 0 / 0 |
| before / memory | 0/6 | 1/6 | 1/6 | 0 / 0 |
| after / product | 4/4 | 2/4 | 4/4 | 0 / 0 |
| after / memory | 5/6 | 2/6 | 5/6 | 0 / 0 |

- after-product四页达到T1的色块、深底和字号比指标。after-memory色块5/6、深底2/6；字号比依次4.667、2.667、2.600、2.632、3.000、**2.300**，第6页未达标。T1“每页≥2.5”验收未通过。
- 最终20页scene对比度error与浏览器overflow均为0，但**不能据此判定PPTX没有视觉错误**：after-memory第4、6页在LibreOffice实际导出渲染中序号拆行，第6页压到正文；对应浏览器原图未拆行。第4页还存在13px小标签。问题原图：`after/memory/rendered/slide-4.png`、`slide-6.png`，浏览器原图：`raw/after-memory-retry/final-render/page-04/candidate.png`、`page-06/candidate.png`。未做PowerPoint客户端实测。
- after-memory一次人工重试后完成6页，累计30次模型调用、1333.47秒（不含人工等待时间）；自动审稿needs_attention。after-product同为needs_attention。没有人工质量验收，不宣称one-shot成功。
- 四份原始PPTX的Office结构校验通过；20页全部可编辑文本逐项读回与scene一致；20页LibreOffice渲染和两张contact sheet已亲自查看。结构/文本通过不抹掉上述视觉缺陷。
- 全量Python回归417项通过、零跳过；42项纯JavaScript回归通过（非交互浏览器测试）；两个目标提示词以外的可执行AST一致。测试输出见`unittest.log`、`ui-logic.log`、`scope-check.json`。仅文档和验证辅助脚本在测试后继续更新，产品代码冻结未再改动。
- 对比图：`before.png`、`after.png`（原尺寸无损拼接）；逐页数据：`metrics.json`；失败/重试：`attempts.json`及`raw/`；人工视觉问题：`visual-review.json`。
- 148张原始PNG（含中间检查图与最终对比图）已逐字节归档到 `/Users/auntlee/Pictures/Codex生成图片/WePPT/vivid-T1-20261101/`，合计23587119字节，未压缩或覆盖。清单见`image-archive-manifest.json`。
- 未部署；现役仍`weppt-dev:20261031-editor-52`，启动时间2026-10-31T03:16:37Z。本轮6个基准容器均已退出，原数据卷保留。见`final-server-state.log`。

## 提请Devin评审

本次只完成T1范围内的提示词重写和验证，不改T2–T8。请依据原始对比图判断是否rework：大字号/色块确有增加，但提示词不能保证每页执行，导出排版与one-shot稳定性仍有实测缺口。未修改任务卡验收标准、未勾选Devin验收，也未靠手改样例、放宽检查或提高模型输出上限达标。
