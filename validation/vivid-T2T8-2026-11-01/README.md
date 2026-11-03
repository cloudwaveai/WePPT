# T2–T8 视觉升级验证（2026-11-01）

任务来源：`docs/collab/devin-codex.md` T2–T8 与 T1-F。实现与验证：Devin。用户确认：T8 默认开启；在服务器跑基准；验证通过后发布。

## 对比协议

- 与 T1 相同：同一模型 deepseek-flash、同一输入（`product-request.txt`、`memory-request.txt`，逐字复制自 T1 目录）、空白独立项目、一次用户输入、不挑样、不人工改稿。
- 对照组直接使用 Codex 的 T1-after 结果（`../vivid-T1-2026-11-01/after/`），本轮未重跑 T1。
- 服务器隔离容器：每个题目一个新数据卷，配置卷只读，生产同款安全参数。生图使用独立的 Codex 目录，只复制 `config.toml`，密钥仍在 `model.env` 中。脚本：`benchmark.py`、`launch-benchmarks.sh`。
- PPTX 在 Mac 上用 LibreOffice 渲染：`FONTCONFIG_FILE` 把 Noto Sans SC、Microsoft YaHei 映射到 Noto Sans CJK SC，否则中文显示为方框。拼图：`after-product.png`、`after-memory.png`。

## 结果（`metrics.json`，由 `metrics.py` 生成）

| 指标 | Product T1 → 本轮 | Memory T1 → 本轮 |
| --- | --- | --- |
| 完成情况 | 4/4 → 4/4 | 6/6（含 1 次人工重试）→ 6/6（0 次人工干预） |
| 模型调用 / 耗时 | 17 次 / 586 s → 20 次 / 506 s | 30 次 / 1333 s → 22 次 / 744 s |
| ≥15% 色块页 | 4/4 → 3/4 | 6/6 → 6/6 |
| 深色或分割底页 | 2 → 3 | 4 → 3 |
| 字号比 ≥2.5 | 4/4 → 4/4（最低 2.53 → 2.84） | 6/6 → 6/6（最低 2.56 → 3.09） |
| 相邻页最大相似度 | 0.667 → 0.25 | 0.583 → 0.75 |
| 椭圆 / 自动配图 | 0 / 0 → 0 / 1（封面，editor-54 重试成功） | 0 / 0 → 6 / 1（封面） |
| 上屏总字数 | 621 → 526 | 1515 → 1015 |
| ≥72px 锚点页 | 2/4 → 1/4 | 1/6 → 3/6 |
| 计划：每页 archetype、相邻不重复 | — → 是（计划节奏告警 0） | — → 是（计划节奏告警 0） |
| 机械错误 / 浏览器溢出 / 节奏告警 | 0 / 0 / 0 → 0 / 0 / 0 | 0 / 0 / 0 → 0 / 0 / 0 |
| 整稿自动检查 | needs_attention → needs_attention | needs_attention → needs_attention |

不足：Product 只有 1 页有 ≥72px 锚点。Memory 相邻页相似度升到 0.75，仍低于 0.85 的告警线。两套稿的自动检查都没有判 PASS，模型 PASS 本来也不代表人工验收。单次同题对比不能证明对所有题目、所有模型都有效。

## 基准中发现并修复的问题

1. **生图会话出了两张图**：Product 封面由 editor-53 生成时，Codex 会话写出了两张图，旧适配器以"不唯一"为由拒收（`IMAGE_INVALID_RESPONSE`），预留区保持色块。editor-54 的处理：两张图都来自本次新会话时，优先用会话最终报告的那张，否则用最新一张；跨会话路径和符号链接照旧拒绝。在完成数据的**副本**上只重跑生图一步，34 s 成功落图，页面和文字不变（`image_retry.py`）。
2. **整稿检查全有或全无**：Memory 的检查意见超过 3 页修正上限，旧逻辑一页都不修。editor-54 改为在预算内按页序修正，其余写入 `deferredEdits`。
3. **单页检查只允许一个动作**：T4 验收中，第 4 页被正确判为 REVISE，但模型同时返回了 `scene_patch` 和 `scene_objects`，被旧的单动作规则拒绝。editor-55 允许这一种组合按顺序作用于候选页；每个校验器仍按原页面核对文字。

## T4 验收（`t4_review_check.py`，`t4-review.json`）

输入：`outputs/weppt-content-capacity-2026-10-31/scenes.json` 第 1、4 页，deepseek-flash 读图与结构。editor-55 结果：

- 两页都判 REVISE，修正被接受，文字不变。
- 第 4 页的 `FLAT_PAGE` 消除；`LOW_SCALE_CONTRAST` 仍在，复核仍为 REVISE，状态 needs_attention。

第一次运行失败是检查脚本自身的问题：截图不在项目目录内，已修正后重跑。

## 测试与发布

- Mac：Python 445 项通过，纯 JS 42 项通过。
- Linux 镜像内全量测试：editor-53 442 项、editor-54 444 项、editor-55 445 项，均 OK（9 项为可选依赖跳过）。
- 现役版本 `weppt-dev:20261101-editor-55`，于 2026-11-01 17:10 CST 切换。镜像 ID、备份、运行文件核对与健康检查见 `DEPLOYMENT.md`。
- editor-53、editor-54 只用于基准，没有上线。

## 文件

- `raw/`：原始结果（scenes / plan / summary / model-metrics / 渲染图 / PPTX 导出）。
- `after/`：LibreOffice 渲染图与 PDF。
- `local-primitives-check.png`：本地对新图元与 T1 两位序号拆行问题的 PPTX 渲染核对。
- 服务器保留数据卷：`weppt-vivid53-20261101-{product,memory}`、`weppt-vivid54-20261101-*`、`weppt-vivid55-20261101-t4`。
