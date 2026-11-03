# editor-57 · T3 / T7 / T8 返工独立复核

仅复验2026-11-01「Devin 返工记录」、metrics-rework.json、13份相对上次有变化的运行/测试文件及线上一套新整稿。未修改运行代码、未发布、未调整模型或服务器设置。旧评审原件保留。

## T3：验收口径可以接受，事实保护仍需返工

**结论：rework。接受新验收口径，不等于接受当前实现。**

“每页正文均下降”改为“整稿正文下降且严格多数页面下降”合理：同一需求可以重新分配信息，单页增长不必代表退步。需固定定义：正文统计composition.blocks[].body；多数为超过50%；只约束模型起草的文字；原文、原图、事实与必要限定语保护仍是硬条件，不允许为过指标删信息。≥半数页面有72px锚点的原条件保留。不能仅因一次随机结果不佳就移动阈值。

Devin记录的[75,183,198,165]等是**全页文字**，包含标题、标签，不是正文。独立从原始只读计划计算，真正的正文也满足新条件：

| 题目 | T1正文总字数 | editor-57正文总字数 | 正文下降页 | ≥72px锚点 |
|---|---:|---:|---:|---:|
| Product | 405 | 294 | 4/4 | 3/4 |
| Memory | 1077 | 601 | 5/6 | 3/6 |

`independent-results.json`保留逐页bodyOnly与全页统计。两种口径均保存，建议Devin改正原记录的名称，不覆盖原证据。

事实保护原三个反例均修复，正常“3 个”、全角“８０％”也能保留。但同一数字边界问题仍有遗漏：

- 用户原文“营收十八亿元”，模型metric“八亿元”：**实际create_deck保存为八亿元**。
- 用户原文“成本三十万元”，模型metric“十万元”：**实际保存为十万元**。

`page_design.metric_supported()`仅用isdigit检查边界，中文数词不是digit，仍会把完整金额内的子串当原文数字。不是语义相近与否的问题，而是18→8、30→10的事实变化。需识别完整数词/金额边界，补此类反例；无法可靠核对时删除可选metric，原正文仍保留。此次所有反例均通过实际保存路径验证，body未改变。范围内复现见`recheck.py`、`independent-results.json`。两份基准savedMetrics为空，只证明本次没有用metric，不能证明保护全面有效。

## T7：accepted（按返工提出的新指标）

独立重算metrics-rework.json全部对应字段，结果一致。以事先固定的T1-after为对照：Product平均相似度0.403→0.292、最大0.667→0.333；Memory平均0.383→0.275、最大0.583→0.417。两题平均均下降且最大低于0.85。去重数已饱和，改用连续相似度有实际区分度，接受这一调整。

调用链成立：design_review从已保存上一页scene计算previousPageStats，design_loop向审稿传入SIMILAR_TO_PREVIOUS（≥0.75）并提示改构图。没有为警告放松原文或原图保护。已实际查看raw57两套基准的全部contact sheet，出现封面、分栏、横向流程、纵向流程、对比等变化。

限制：Product相对editor-53的平均相似度0.139反而上升至0.292，Memory则0.425→0.275；此次接受的是**对T1基线达标**，不声称每一版都单调改善。两次单题对照不能证明few-shot单项因果收益或跨模型普遍有效。耗时730/1325秒、调用27/35次也比editor-53增加，不能宣传质量与速度同时提升。

## T8：rework（手改保护已通过，画布兜底未通过）

原缺陷的复验已经通过：

- 入队后旋转15°、改色、加阴影，均conflict，用户手改完整保留；改动其他对象仍能applied。
- 保存auto后服务器WEPPT_AUTO_IMAGES=off，返回off且imageModeLocked=true；再开启返回IMAGE_MODE_LOCKED。
- 自动落图前审稿仍当前：审稿状态保留；同页其他对象或另一页有用户编辑：落图后仍stale；humanAccepted均为false。见`review-carry-forward.json`。

检查顺延的含义仅是沿用既有布局结论，**没有让模型重新检查生成图片的像素内容**。autoImageRevisions是顺延记录，不是新的图像审稿证据；人工验收不应据此省略。

画布兜底在本次Chrome实测仍有异常：12秒后iframe已active、data-interactive=true，但无imagesReady标记，AX仍about:blank，截图仍空白。控制台工具返回空列表（不是根因已排除）。首次运行结束后和刷新一次后，结果相同：画布空白、测量0/3。直接打开同页S003的/api/preview可以正常显示。见`editor-blocked-before-reload.jpg`、`editor-blocked-after-reload.jpg`、`editor-final-dom-console.json`、`editor-final-ax.txt`和`direct-S003-preview.jpg`。该问题在本次Chrome环境明确复现，根因仍未知，不扩大为所有客户端必现。

## 验证范围与原始证据

- 新执行Python449项，75.102秒、零skip、OK；JS42项通过。`unittest.log`、`ui-logic.log`。单测通过不代替实际UI验证。
- 复验本地fixture调用真实Studio/CreateDeck/ImageJobs；仅模型提供者/截图用fixture替代，无额外收费调用。
- 独立指标和失败反例：`independent-results.json`。相对前次变动清单：`changed-files-since-last-review.json`。
- 指定证据：`../vivid-T2T8-2026-11-01/metrics-rework.json`、`raw57/product/result/`、`raw57/memory/result/`。原文件未修改。
- 前后图：`../vivid-T2T8-2026-11-01/after-product.png` / `after-memory.png` 对照 `raw57/product/result/final-render/sheet-01/candidate.png`、`raw57/memory/result/final-render/sheet-01/candidate.png`、`sheet-02/candidate.png`。数学改善的指定基线是`../vivid-T1-2026-11-01/after/`，不是editor-53。

## 线上新整稿（首次结果）

项目：<https://ppt.bbstack.date/?project=project-346f5da592b13f4b>。

现役镜像editor-57，启动时间2026-11-01T11:40:19Z（`version-initial.json`）。沿用原4页We-PPT产品需求、deepseek-flash、imageMode:auto，一次提交，不人工重试、不改稿、不点击认可。浏览器选页/刷新只用于观察UI。`live_test.py`保存首次运行与终态；`request.txt`与前次逐字一致。生成内部允许既有检查/修正循环，不等于仅调用一次模型。


T8剩余返工范围：修复实际预览加载/就绪判断。12秒计时只能触发重载、错误提示或恢复流程，不能把尚为about:blank的frame当已就绪。保留已通过的快照保护、服务器锁和用户编辑过期判断，不要求重做这些修复。此次主画布修复已列入Devin返工记录，因此明确保留为该卡未通过项。没有把本次模型字段错误归因于自动配图。

### 首次实测终态

约360.57秒后blocked，3/4页保存，第4页`INVALID_SCENE`：`title.emphasis 必须是最多 8 个、每个不超过 80 字的强调词。`。用户提交1次、人工重试0次、人工改稿0次。自动配图只在整稿完成后排队，因此本次images为空，**没有验证到线上自动落图**；不把未执行当成功或配图失败。

`live/summary.json`、`live/progress.jsonl`、`live/final-state.json`、`live/review-reports.json`保留首次错误和检查记录。服务器版本未变化；12份关键运行文件与本地哈希一致（`live-version-and-hashes.txt`）。

这是新增整稿实测的健壮性失败：模型产出不合法emphasis，当前流程未在本次自动修复，需用户手动重试才能继续。应保留结构校验，再完善有界纠错；不能靠删除校验或把失败忽略成成功。此次不执行修复，也不反复跑模型直到出现成功稿。该问题独立记录，不推翻T7已验证的基准指标。

### 部分产物实际渲染

整稿导出会被DECK_INCOMPLETE保护。使用产品明确支持的指定单页草稿导出，分别保存`live/S001-partial.pptx`、`S002-partial.pptx`、`S003-partial.pptx`，没有合成为“完整PPT”。已逐页转PDF/PNG并亲自查看；三页原生文字读回均与保存的scene一致。`live/partial-readback-and-metrics.json`只统计已保存3页，不冒充完整4页指标。

发现实际导出差异：S001浏览器标题完整，但本机LibreOffice字体替代渲染时，标题右端进入白色预留区，末尾不能完整看清；源scene与PPTX文字读回完整。这是浏览器/导出排版差异，不能用机械error=0或XML完整掩盖。对照`direct-S001-preview.jpg`与`live/rendered/S001/slide-1.png`。S002正文可读，S003长主句的断行生硬；均不标为审美验收通过。本次未使用Microsoft PowerPoint桌面版。

每页渲染原图在`live/rendered/S001/`至`S003/`，原始导出保持不变。没有生成新的模型图片；截图保留工具返回的原始JPEG字节，渲染PNG也不做降采样。

原始图归档：8张原始截图/渲染图已逐字节复制至`/Users/auntlee/Pictures/Codex生成图片/WePPT/vivid-T3T7T8-codex-recheck-20261101`，清单`image-archive-manifest.json`。范围校验`scope-verification.json`确认旧看板正文/Devin记录与运行代码均保持。
