# editor-58 · T3 / T8 第二轮返工独立复核

复核日期：2026-11-02（Asia/Shanghai）。范围限于第二轮返工、原失败场景和用户要求的一次新整稿。没有修改或部署运行代码，没有人工重试生成，没有人工验收页面。

| 卡片 | 结论 | 依据 |
|---|---|---|
| T3 | **accepted** | 中文数词反例已修复；真实 `Studio.create_deck` 保存路径 15 例全部符合预期，正文不变。指标字段更名正确。 |
| T8 | **rework** | 主画布与配图封面恢复，后台浏览器测量仍未完成。新整稿另有 `num.fontSize` 校验失败，未实现本次一次输入完成。 |

## T3：已解决的问题

`check_t3.py` 实际创建隔离项目并读回计划，结果在 `t3-results.json`：

- “营收十八亿元”→“八亿元”、“成本三十万元”→“十万元”、“第三十名”→“第三”均删除可选 metric。
- 之前的 `180→80`、`3个模块→3亿元`、无来源“八成”仍被拒绝。
- 大写金额、两千金额截取也被拒绝；完整引用、全半角/空白规范化及原文第二处独立出现均正常保留。
- 每例 `bodyUnchanged=true`。这是指定反例及相邻场景的验证，不宣称覆盖所有自然语言事实核验。
- `perPageAllTextCharacters` 更名成立，六组序列与上轮独立重算完全一致（`metrics-rename-check.json`）。沿用上轮已接受的正文口径：模型撰写正文总量下降且严格多数页下降；正文按 `composition.blocks[].body`；用户原文/事实/限定语保护与至少半数页 ≥72px 锚点保持。Product 405→294 字、4/4 页下降；Memory 1077→601 字、5/6 页下降。无需再跑随机基准。

## T8：真实浏览器结果

线上镜像 `weppt-dev:20261101-editor-58`，镜像 ID `sha256:6ccc2e1db4858eb322d1f94f92bf43a935876344d3f7dcddf765691a03ed0896`，启动于 `2026-11-01T16:22:50.919924143Z`。七份直接相关线上文件与本地一致，见 `live-version-projects.txt`、`live-hashes.txt`、`live-hash-check.json`。

**网络条件**：公网域名在 Chrome 和不经代理的 curl 中均报证书域名不匹配，用户确认 DNS 污染。首次 SSH 转发/已有 HTTPS 代理路径也出现超时。最终使用 `verified_proxy.py`：仅监听本机 `127.0.0.1:8766`，上游连接已核实服务器 IP `43.153.76.85:443`，SNI 与证书主机名仍为 `ppt.bbstack.date`，使用系统默认 CA 验证。未关闭 TLS 校验、未跳过浏览器警告、未改系统 DNS、浏览器设置或线上配置。`curl --resolve` 证书验证成功、HTTP 200，耗时约 1.25 秒。以下结论来自这个稳定入口下的真实桌面 Chrome，不是本地复制品或无头浏览器；不代表普通 DNS 入口已恢复。

实测已有自动配图项目 `project-90b780a7be9936e3`，选择 S001 封面：

- 主画布 `active`，`ready=true`，`interactive=true`，`imagesReady=true`；实际走 `srcdoc` 回退。
- 亲看主画布，封面文字与配图可见。图片 `complete=true`，原始尺寸 **1106×1422**。原始 PNG 2,581,675 字节，SHA256 `f2d0bbba5d141a8c71ee77b9a438d50d9506ff47f292f32901667768bd2bcf23`，见 `cover-original.png`。封面图片来自既有自动批次 `applied`，不是本轮新生图。
- 测量队列按产品现有自动重试逻辑跑完，最终 **0/4 页**；测量 iframe 已撤除，UI 显示“4 页尚未完成浏览器测量：未收到当前页面的真实测量”。封面及无图片页都未完成。预览 HTML 与图片均 HTTP 200；稳定链路日志中没有 `POST /api/quality/report`。
- 当前选中的真实 Chrome 标签页就是此测试页；后台测量帧可读到页面文字。控制台工具返回空的错误/警告列表。无法据此确定根因；`rendering.py` 的测量依赖双层 `requestAnimationFrame`，`style.css` 的测量帧处于屏幕外，是后续定位线索，不作为已证明根因。
- 原项目各页版本未改变；没有点击“重新检查”（该操作会 autoFix），没有认可或修改页面。本轮只选择页面、触发产品自动测量并读取状态。

**结论边界**：主画布恢复已通过，不再要求返工此项；后台测量仍阻断 T8 本轮收口。上轮已通过的手改保护/服务器总开关无需重开；相关自动配图测试本轮仍通过。不能用“图片看得到”代替测量完成，也不能将模型检查顺延解释为图像像素审稿或人工验收。

截图/原始记录：

- 前：`../vivid-T3T7T8-codex-recheck-2026-11-01/editor-blocked-after-reload.jpg`（另一份旧项目，机制前后对照，不是同一页像素对比）。
- 后：`cover-loaded.jpg`、`cover-measurement-failed.jpg`。
- `cover-measurement-final.json`、`cover-final-dom.txt`、`cover-state-before.json`、`cover-state-after.json`、`proxy-pinned-tls.log`。

## 新建整稿：首次结果保留

[线上项目](https://ppt.bbstack.date/?project=project-d80df9b095106c48)。通过现有 HTTP API 新建项目、选择 `deepseek-flash`，发送与上一轮完全相同的 `request.txt`；默认自动配图开启。创建/发送发生在服务器现有回环 API，终态另用真实 Chrome 打开核对。没有声称本次输入是浏览器手工键入。

- **1 次用户输入，人工重试 0 次，人工改稿 0 次**。
- **190.19 秒，blocked，0/4 页**。第 1 页 `INVALID_SCENE`：`num.fontSize 必须是 10 到 160 之间的有限数值。`
- 旧 `title.emphasis` 失败类型的归一化单测通过；本次失败是仍严格校验的字号字段。这个结果证明本次 one-shot 没完成，不证明旧强调字段修复无效，不归因于 DNS 或自动配图。
- 自动配图未排队，不能作为新图生成成功/失败证据；没有成稿可导出，因此没有本轮 PPTX/渲染交付。
- 证据：`live/summary.json`、`live/progress.jsonl`、`live/submitted.json`、`live/final-state.json`、`one-shot-final-dom.txt`、`one-shot-blocked.jpg`；完整执行脚本 `live_test.py`。

## 定向测试与范围

- Python `test_vivid_design.py`：**27 项通过，零跳过**，2.306 秒；包括锚点、装饰字段归一化、自动配图保护及检查顺延等直接相关测试。
- `node tests/ui_logic.mjs`：**43 项通过**；新增 ready 判断用例在内。JS 单测本身不是真实浏览器证据。
- T3 独立真实保存路径 **15/15**。本轮没有重跑全仓 449 项，也不把上轮全量结果当本轮结果。
- 五份源码/测试文件相对上轮变化（`changed-files.json`），其余历史问题不扩为本轮门槛。
- 协作看板只在 T3/T8「Codex 回写」顶部及 §3 追加，不修改任务卡正文、标题状态或 Devin 记录。源码冻结与写回范围核验见 `scope-verification.json`。

原图和工具原生截图均未压缩、降采样或重新编码；归档清单见 `image-archive-manifest.json`。

临时浏览器测试页、代理和SSH隧道已关闭，未留下常驻服务；见 `cleanup.json`。
