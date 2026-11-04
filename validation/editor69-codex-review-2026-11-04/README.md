# 2026-11-03 两批改动独立复核

2026-11-04，Codex。整体结论：**rework**。本地功能有通过项，但当前公网产物与请求验收的新版不一致；另有四个独立代码反例。线上首次整稿失败。真实浏览器线上操作仍未完成，不能以本地自动化或 HTTP 测试替代。

## 范围与版本

- 本地 HEAD：`7db5bf7`。检查 `a037563..HEAD` 的 9 个提交；8 项需求的主体已经在 `a037563`，也纳入复核。清单：`commits.txt`，差异：`review-diff.patch`。
- 阅读看板 §0 与 DEPLOYMENT.md 最新一节。最新发布记录是 editor-68，没有 editor-69 的发布/清单证据；历史 editor-58 一节还出现 editor-68 镜像名，存在记录不一致。本次没有自行修改发布历史。
- 公网 `app.js` 与 a037563 / b69c1f4 / d9bccf4 / 5c66635 相同，与 c16f37c 及后续前端不同。这只能定位前端版本范围，**不能据此断言服务器镜像标签**。
- 公网 `/api/me` 返回 404；新测试项目在不带 Cookie 的独立连接中可见。导出仍写 `spcPct`，Logo 去底标志为真但图片仍完全不透明。新版的空间接口、前端及两项导出行为均未与本地 HEAD 对齐。
- 证据：`online-app-version-comparison.json`、`online-app.js`、`public-probe.json`、`live-operations/export-readback.json`。
- HTTPS 固定域名所对应服务器 IP 43.153.76.85，保留 SNI 和证书校验；没有修改系统 DNS、代理或线上配置。

## 逐项结论

下表的 accepted 是**已列明的实现范围**通过，不代表整个线上批次 accepted。发布一致性和真实浏览器验收是独立未通过项。

| 项目 | 结论 | 证据及范围 |
|---|---|---|
| 缩略图增量更新、主画布交叉淡入 | accepted（实现） | 47 项 JS 含单页 revision 更新复用其他帧、选择仅切换属性、移除页清理；源码保留旧画布至新页 ready 后淡入。线上观感未测。 |
| 样式类别筛选、禁止越界滑动 | accepted（实现） | JS 分类/去重/选择保持通过；本地 Chrome 分类与移动布局通过，CSS 含横向 overscroll 限制。macOS 真实触控板返回手势未测。 |
| 主色与辅色、应用和撤销 | accepted（实现及线上 API） | palette 全量用例通过；独立线上项目应用后 scene 改变，undo 后与原 scene 完全相等。按钮操作未测。 |
| 图片/PPTX 用户模板、拒绝仅换色 | accepted（本地实现） | Python 上传/PPTX 可编辑布局/模板隔离通过；普通模板 IoU≥0.7 退回，重试仍不换布局则失败；style 重排允许同几何是显式路径。真实模型适配浏览器分支因未配置模型跳过，线上新版上传入口未验。 |
| 3 页对标解析、逐页改版、风格副本 | rework | 解析及逐页预览/确认的本地用例通过；但副本 `_copy_images` 会跳过 `image-slot*` 真图片，同一图片换普通 ID 即可复制。自动配图不能被静默排除。新版逐页入口未在线确认。 |
| “为你推荐”的历史偏好 | rework | HTTP 请求上下文内隔离正确；后台任务未绑定 owner，Alice 新任务取得仅 Bob 产生的品红色偏好。见 `owner-context-results.json`。 |
| 受众版本与原稿对照 | accepted（本地实现） | 独立项目、来源记录、受众规则、对照映射的 Python 用例通过；对照为文本相似度映射，不是事实一致性证明。本轮未重新调用模型生成受众稿；当前公网前端缺 c16f37c 的对照改动，线上交付 rework。图片继承共用上一条待修复制逻辑。 |
| Logo 去底、挪字、强制放置 | rework | 本地去底/挪字/强制放置用例通过，导出透明 alpha 保持；但处理先把长边压到 1200，违反原图质量要求。公网上传后导出的 alpha 全为 255，去底修复未体现在服务。 |
| 整稿自动放大锚点 | rework | 读取 `page.blocks` 而实际是 `page.composition.blocks`；7 字合法 metric 不进入候选，32px 原样保留，错误扁平结构对照却放大为72px。 |
| “待补充”不判失败 | accepted（规则实现） | 审稿提示将明确资料缺口与视觉/证据问题分开；未放开无依据事实和人工验收。相关测试通过。它是模型规则，不是强制清空失败状态；本次整稿未进入审稿，未取得新线上模型证据。 |
| PPTX 行距点数 | accepted（本地实现）；线上 rework | 同 scene 前后实际导出、LibreOffice 渲染及文本读回：正文从150%变36pt（32px×1.5×0.75），无文字丢失。公网导出仍用百分比。 |
| 匿名个人空间、项目/模板隔离、空间码 | rework | 本地 HTTP 隔离及空间码用例通过，但后台偏好越界；公网 `/api/me`404，无法验收空间迁移。两个真实浏览器尚未操作，不把两个 HTTP 连接称为双浏览器验收。 |

## 需要返工的具体代码问题

1. **P1：后台生成偏好跨空间。** `server.py:144–178` 的 worker 未绑定请求 owner；`studio.py:1120` 调用 context，`studio.py:794` 聚合 userTasteProfile；`taste.py:38` 依赖 `owners.owned_project_ids`，无 owner 时返回 None 并读取所有项目。`owner-context-repro.py` 用真实队列 `next_job()` 复现：Alice HTTP 无偏好，任务上下文却出现 Bob 三个项目的“品红系主色”。应按任务所属项目的持有者限定查询，不能把无请求上下文解释为全局用户。本次只证明偏好摘要越界，没有声称整份私稿文件可被另一用户下载。
2. **P1：Logo 被静默降采样。** `logo.py:34–37` 在处理前把长边压至1200。2400×1200 原图中的2000×800色标变成1000×400，再加边得到1040×440。原始 `logo-upload.png` 字节保留，但 scene/PPTX 使用已降采样版本。按原始像素处理并保留原件；去底/裁边与额外缩小像素是两回事。`reproductions.json`、`export/readback.json`。
3. **P2：锚点计划字段读错。** `quality.py:367,381` 读取错误层级。两页、充足空间、`metric='12345万元'`、32px，合法嵌套 plan 的 boosts=[]；扁平对照 boosts=1。现有 `test_priority_metric_digit_kicker_other` 也使用扁平假计划，掩盖问题。短于7字的启发式仍可能有效，不能称所有锚点均失效。`reproductions.json`。
4. **P2：风格副本丢失自动图片附件。** `derived.py:109` 只按 ID 前缀跳过 `image-slot*`，没有区分空预留与已落地真图。`export_check.py` 对实际复制函数传相同 PNG：`image-slot-hero` 复制0张，`user-picture` 复制1张。源项目未被改动；问题是新副本拿不到原图附件，可能留空或重生图，不能保证原图保留。还应显式处理10张/8MB上限，不能静默省略。`derived-image-repro.json`。

## 线上实测结果（HTTP 补充，不是浏览器验收）

### 一次输入整稿

- 项目：`project-4ce8868bd59f3af9`；deepseek-flash；沿用前轮4页 We-PPT 产品需求、默认配图。
- 一次提交；人工重试0，人工改稿0。约187.76秒观察到失败，`INVALID_PROJECT_FIELDS` / `purpose 取值不支持。`。
- 生成0/4页，无 deck、无自动配图、无完整PPTX。质量状态 not_checked，测量0/0是**没有页面**，不是 N/N 完成。
- 没有伪造具体失败的 purpose 值或归因于哪个模型输出；服务器执行日志未能读取。原始材料：`live/request.txt`、`live/submitted.json`、`live/final-state.json`、`live/summary.json`。

### 配色、白底 Logo 与导出

- 单独示例测试项目：`project-220ce249034198b5`。调用 demo 生成固定示例，仅作为 API 功能检查，不混入上面的 one-shot 记录。
- 配色实际改变 scene；undo 完整恢复（JSON 等值）。`live-operations/before.json` → `after-palette.json` → `after-undo.json`。
- 上传本次合成的白底测试图 `fixtures/white-logo-2400.png`，放置后单页导出；导出的 media 与服务端处理预览字节一致，尺寸1040×440，alpha最小/最大均255，**不透明**。本地 HEAD 同图处理 alpha范围0–255。
- 原生文本读回完整；线上单页实际 LibreOffice 渲染，图：`live-operations/rendered/slide-1.png`。页面白底会掩盖 Logo 白边，所以以嵌入图片 alpha 数据判断。示例标题有自然换行，此次不扩为无关新阻断。
- 公网导出 XML 使用 `spcPct`，没有 `spcPts`，与本地行距修改不一致。`live-operations/summary.json`、`export-readback.json`。

### 未完成的线上浏览器步骤

CUA 返回 `The browser access host is unavailable`，无浏览器 surface。已经请求恢复连接或明确允许 Playwright 双独立 Chrome，尚未收到答复。按浏览器技能要求未绕过连接限制。SSH 严格校验后返回 `Permission denied (publickey)`，未改密钥/信任设置，未重复尝试。

因此：线上 UI 输入、配色按钮/撤销、Logo 上传下载按钮、双浏览器隔离/空间码迁移、自动配图封面 N/N 测量和在线截图均待补。当前服务缺空间接口，整稿失败，也独立阻断对应验收。不把前次截图、本地 Chrome 或 API 检查冒充本次在线截图。

## 测试记录

- Python：最终 `.venv/bin/python -m unittest discover -s tests`，**527项，96.332秒，OK，零跳过**。`python-full-final.log`。
- 最初两次各527项/6错误，都是 MCP 子进程在临时目录无法 import 本包。保留 `python-full.log`、`python-full-with-path.log`；重装本地 editable package 后恢复。无构建隔离的 pip 先因缺 setuptools 失败，普通 `pip install --no-deps -e .` 成功；记录在 `editable-install*.log`。未改源码/测试来凑通过。
- `WEPPT_CHROMIUM="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" node tests/run_browser_tests.mjs`：**10组退出成功，0组失败**，但3个模型相关路径跳过：design_loop review replay、JEV smart selection、template adaptation配置模型路径。不能表述为所有模型功能全覆盖。`browser-full.log`。
- 本地测量测试3/3完成，包含测试图片；另报一个该测试场景的文字框重叠，不等于线上封面测量通过。
- `node tests/ui_logic.mjs`：47项通过。`ui-logic.log`。
- PPTX 前后实物：本地32px、1.5倍行高正文导出36pt；所有原生文字相同，Logo嵌入媒体等于处理后PNG，alpha0–255。实际渲染并查看 `export/before/slide-1.png`、`export/after/slide-1.png`。没有在 PowerPoint 桌面版打开。

## 证据和改动边界

- 前后对比：`export/before/slide-1.png` ↔ `export/after/slide-1.png`，只比较本地行距；两边都使用 HEAD 处理的同一 Logo，不冒充线上去底修复对照。
- 本地浏览器截图：`browser-local/categories.png`、`categories-mobile.png`、`right-template-recommendations.png` 等。已查看分类截图；全套测试截图保留原字节。
- 线上导出图：`live-operations/rendered/slide-1.png`，不是浏览器截图。
- 原始图片归档路径和逐字节校验见 `image-archive-manifest.json`。未压缩或覆盖原始图片。产品内部降采样造成的问题如实保留为证据。
- 本次仅写复核证据与看板 §3；没有修改任务卡正文、运行源码或测试，没有修复/部署，没有替用户人工验收。最终冻结核验见 `final-verification.json`。
- 看板没有这两批改动的独立任务卡，因此结论集中追加在 §3，没有把2026-11-01旧 T1–T8 的 accepted/rework 覆盖成新的需求结论。

返工后只需复验上述四个反例、发布一致性，以及尚未完成的真实浏览器路径；已有无关通过项不需重做一轮全面审查。
