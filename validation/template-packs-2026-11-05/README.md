# 整套模板适配验证 · 2026-11-05

当前为本地实现与隔离测试，未发布。用户最新授权要求“skill + 模板库 + 内容适配”；本轮没有再次执行旧 T1–T8 卡。

## 结果入口

- `preview.html`：切换三个套系，查看同一份九页验样；每套均可下载可编辑 PPTX。
- `model-result/sample.pptx`：现有 DeepSeek 配置真实生成的三页产品稿，一次输入，无人工重试。不是手工排好内容的九页验样。
- `before.png` / `after.png`：同模型同输入对比。前件复用上一轮 `office-rebuild-2026-11-05/model-results/after/`；不是重新跑一次旧代码。输入字节相同，见 `comparison.json`。

## 实现

模板注册表与编排器 `ppt_workbench/template_packs.py`；3 个套系、每套 9 个母版，共 27 个。来源与估算边界写入 `data/template-packs/`。不声称 645 份素材或既有 44 个原页参考已全部转换。

规划阶段输出内容分组与母版选择；逐页原生布局不调用模型重画。按容量尝试同套变体，保留每组标题、正文、状态与数字。母版哈希冻结；页级提交不能自由替换模板几何。实际渲染检查字体、图片和溢出，选版理由保存在项目 `template-layouts/N/selection.json`。

“设计 → 整套模板”显示封面、章节和正文预览。空稿选择偏好；已有稿件生成拥有相同空间归属的改版副本。源稿、重复限定词、原始备注、原图字节及逐页图片出现次数保留。超出每页 3 图容量时明确拒绝，不生成缺图稿。

PPTX 实测发现既有 `contain` 导出误把容器宽高当成图片原比例，导致图像拉伸。`export-pptx.mjs` 现在只读取 PNG/JPEG 尺寸，按原比例计算显示矩形，原编码不变。`test_rendering` 新增宽图放入方框的比例与原始字节检查。修复前图在 `export-fit-before/`；修复后为各套系 `pptx-page-8.png`。

## 验证

- `python-final.log`：Python 全量 **565 项通过、0 跳过**（106.109 秒），包含最终图片比例修复。

- `unit-final.log`：14 项模板路径测试，包括角色/关系、长文切宽行、重复状态、超容量不改原文、同套一致、零逐页模型调用、外部重画拦截、母版变更拦截、原图/原备注/空间归属。
- `export-fit-tests.log`：24 项渲染与模板相关检查通过。
- `js-logic.log`：47 项纯 JS 检查通过。
- `browser-complete.log`：12 个脚本中首次 11 个退出 0；编辑测试误等旧 revision、过渡双 iframe 产生竞态。改为持续读取实际版本并定位唯一可交互帧，`browser-editor-final.log` 复验通过。旧失败日志保留。
- 浏览器条件跳过仍保留：未配 JEV、未配模型的单页适配、未给 review replay fixture。它们没有被这次测试覆盖。
- `metrics.json` / `render-browser-final.log`：三套共 27 页真实 Chrome 载入，全部字体就绪、图片失败 0、文字溢出 0，机械 error 0。三份 PPTX 逐页文本读回完整、原图媒体字节相同。
- 三份 PPTX 经 LibreOffice 实际转 PDF，并生成各套系 `pptx-page-*.png` / `pptx-sheet-*.png`，亲自查看；不是只查文件存在。中文字体映射沿用上一轮 `artifacts/fonts.conf`。

首次命令行 Chrome 在本机 contact sheet 截图完成后的退出阶段触发 teardown watchdog，原记录在 `render.log` 和 `crimson-grid-v1/browser/sheet-01/`。没有把异常退出算通过；固定验样改用正常退出的持久 Playwright 浏览器测量和截图。产品渲染代码未因此绕过退出检查，隔离 Linux 真实模型流程正常。

## 真实模型试稿

模型：deepseek-flash；隔离容器，新数据卷，现有配置只读。图片模式 off。请求沿用上一轮三页产品介绍。

| 项目 | 上轮 | 本轮 |
| --- | --- | --- |
| 完成页数 | 3/3 | 3/3 |
| 生成及检查耗时 | 230.52 秒 | 140.7 秒 |
| 本轮人工重试 | — | 0 |
| 浏览器溢出/图片失败 | — | 0 / 0 |
| 本轮逐页执行 | 模型绘制 | 模板编排 |

这是一次同题观察，不能据此推断稳定成功率或固定性能提升。三页的 attempts 均为 1。两项“开发中”分别保留。真实试稿的整稿模型审查仍为 **needs_attention**：第 2 页层级偏弱，第 3 页留白与状态层级待打磨；其中还包含原规划 designBrief 与固定母版之间的风格差异。原审查意见保留，未为了得到 PASS 重画或改判。独立视觉结论也只接受功能可审阅，不宣称最终审美达标。

原始报告：`model-result/work/projects/office-product/deck-reviews/*/report.json`；源请求、结果、所有场景、浏览器测量、数据库与原始日志均在 `model-result/`。

## 边界

基础套系支持常见分组，不等于任意拓扑、任意复杂图表、任意 PPTX 导入。容量不足会阻止当前稿完成，不自动删减或拆页。模型仍可能把内容分组不当，原文保护与人的复核仍需保留。

现役线上镜像保持 `weppt-dev:20261103-editor-68`。本轮只运行了一个完成的隔离模型测试容器，产物收回后删除容器；保留独立测试数据卷。未写素材筛选站或生产项目数据。
