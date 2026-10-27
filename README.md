# WePPT · 聊天、逐页制作与即时预览

**版本 0.4.0。** 用聊天提交自己的思想和材料，在浏览器里查看实际页面，通过 Claude Code、Codex 或本地大纲排版完成制作。项目、原话、页面对象、版本和交互轮次由程序保存，不依赖模型一直记得整段上下文。

这一版围绕**最多三次完整用户输入和对应结果**组织流程：第一轮提供思想与逐页大纲，第二轮集中反馈，第三轮明确确认整稿。系统内部依然一次处理一页，支持精确修改指定对象。三轮是可验证的交付目标，不是对任意材料和任意设计要求的质量保证。

快速启动见 [QUICK_START_ZH.md](QUICK_START_ZH.md)；Coding Agent 操作约定见 [CLIENT_GUIDE.md](CLIENT_GUIDE.md)。

## 独立内容引导与经验库

工作台顶部「内容引导」进入 `/guide.html`。按用途、表达任务和材料情况显示后续问题，填写一页后加入大纲；支持页面排序、移除恢复、载入修改，并整理为含封面、目录、正文和结束页的整稿简报。未填写的结构页明确标为待补，不推断业务事实。简报经手动检查后，可交接到工作台输入框，再由用户发送。

「个人经验」保存原始问答、提炼规则、来源与关联模板；精选模板保存选择理由，可按精选或来源／风格筛选。内置经验、本次产品反馈和个人输入分别标明来源。经验库支持预览后追加导入 JSON 与导出，便于跨项目复用。草稿和经验按项目存储到工作区数据库，同时保留浏览器备份；多窗口版本冲突时停止覆盖，提供备份下载和显式重新加载。

## 1. 三轮怎样工作

| 轮次 | 用户的一次输入 | 工作台的对应结果 |
| --- | --- | --- |
| 第一轮 | 用途、听众、目标、逐页观点、真实材料与需要协助的部分 | 保存需求和整稿计划，自动逐页制作，汇总初稿与待补项 |
| 第二轮 | 看完整稿后，一次给出跨页修改与必要补充 | 将反馈分派为逐页任务，汇总修订稿、检查结果和剩余问题 |
| 第三轮 | 查看当前整稿后，明确确认内容表达与视觉呈现 | 记录整套当前版本的操作者认可，给出正式交付状态或仍缺的条件 |

每轮只显示一条完整结果；自动页任务和检测信息放在可展开的工作进度里。旧轮结果保留当时快照，后续页面变化后会标记为旧版本，不能被当成当前已完成稿。

**首次需求也计入轮次。** 补充答案、修改反馈、撤销、单页认可和整稿确认都属于用户输入。点击多个选择题选项只会汇入输入框，同组改选替换整组内容，最后一起发送才计一轮。自动续页、原轮失败重试、机械检查和浏览器补测不另计。

第 4 次输入仍允许继续，界面会如实提示未在三轮内完成。重启、换执行方式、撤销不会归零。既有轮次后绕过交互队列直接使用 CLI / MCP 改页，会留下外部变更记录，使交互计量链不完整；系统不会猜测这些修改相当于几次人类输入，也不会据此宣称三轮达标。

## 2. 第一轮先提供什么

主流程是聊天，无需先填一套表单。请尽量一次给出：

- 这份稿件的用途、听众、希望促成的理解或行动，以及现场讲述、独立阅读或两者兼用。
- 每页的观点和大纲；哪些内容已经确定，哪些需要协助组织表达或另行提供。
- 是否使用公司或联合品牌 Logo；需要使用时提供准确素材。
- 真实数据、截图、照片、案例及出处；哪些页面需要核验外部事实依据。
- 想采用的参考风格、需要保留的内容和局部修改范围。

缺少决定时，工作台会将缺项汇总为少量选择题。选项是可以修改的候选，不会自动成为用户立场。未知项保持待定；选择“无需外部资料”也不会自动替每页取消事实依据要求。

### 已有完整文案：按大纲本地排版

本地模式不调用模型，按提供的文字生成 2–30 页。下面展示可识别的前言与逐页格式；请用本次真实内容替换示例。

```markdown
按大纲排版
# 我的项目介绍
用途：介绍方案
听众：项目体验者
目标：理解项目并讨论下一步
展示方式：现场讲述
Logo策略：不使用
数据策略：无需外部资料
本稿各页依据要求：无需外部依据

## 封面｜我的项目
结论：这一份演示最希望传达的观点
署名与日期等真实信息。

## 内容｜项目解决的问题
结论：本页的一条主要结论
这里放用户已经提供的正文。

## 结束｜接下来一起做什么
结论：希望读者采取的行动
具体安排或待补信息。
```

明确的前言会保存为项目设置，完整原话仍保留。展示方式支持 `现场讲述 / 独立阅读 / 两者兼用`；Logo 策略支持 `不使用 / 使用公司Logo / 使用联合品牌Logo`；数据策略可写 `用户提供真实资料 / 协助查找并提交核验 / 用户资料与补充研究 / 无需外部资料`。选择研究策略不会自动完成检索或核验。

需要外部依据的页可单独写 `依据要求：需要核验`；明确整稿不含这类主张时才使用 `本稿各页依据要求：无需外部依据`。这些是要求声明，不是证据通过记录。元信息补充可直接作为一条由这些字段组成的聊天消息提交；本地模式不会将夹杂的其他修改句静默丢弃。

基础页面类型是封面、目录、章节、内容、对比、并列、流程、结束。应显示在页上的文字放在该页正文中。十页项目介绍输入起点见 [examples/project-introduction-outline.md](examples/project-introduction-outline.md)。

### 第二轮集中反馈

在输入框上方选择“整稿”，一次提交明确页码的修改，例如：

```text
整稿修改
第1页：标题改为：PPT 工作台
第2页：标题改为：项目解决的核心问题
```

后台逐页执行并合并为同一轮结果。上述标题修改可由本地规则处理；复杂改写、信息设计与新内容组织需要真实模型或人工制作。

需要精确调整时，先在预览中点选文字或图形，输入框会显示该对象范围。本次任务只能修改选中对象。开始输入后，页码、对象与原问题 ID 固定，后台自动续页不会改变草稿目标。未选对象时可在“整稿”和“当前页”之间选择。

## 3. 安装与启动

需要 **Python 3.11+**。导出可编辑 PPTX 还需要 **Node.js 18+** 和本项目 npm 依赖；仅使用 HTML 预览可暂不安装 Node 依赖。

解压进入 `ppt-workbench` 目录，启动新项目：

```bash
bash start-studio.sh --project project-intro --agent outline
```

Windows 命令提示符：

```bat
start-studio.cmd --project project-intro --agent outline
```

启动器在当前目录创建虚拟环境、安装依赖并打开本机浏览器。项目保存在本目录的 `work` 中。第一次安装需要网络，不会自动修改 Coding Agent 的设置。保留终端运行；若没有自动打开浏览器，使用终端打印的完整 `url`，包括首次进入使用的 token。

希望手动安装时：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[mcp]'
npm install
.venv/bin/pptctl --root ./work studio --project project-intro --agent outline --open
```

Windows PowerShell：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[mcp]"
npm install
.\.venv\Scripts\pptctl.exe --root .\work studio --project project-intro --agent outline --open
```

也可以使用 `--project demo --demo` 打开明确标注的三页示例，体验预览、对象选择和有限本地命令。示例不代表用户真实业务，也不是本版整稿 UI 验收结果。自己的整稿使用新项目 ID。

安装和运行发生在本机，本包不含云端托管或模型账号。项目状态不因关闭工作台而清空，建议备份整个 `work` 目录。

## 4. 两种 Coding Agent 接法

### 在 Claude Code / Codex 中聊，在浏览器里看

两端必须使用**相同的绝对 `--root` 路径和项目 ID**。先生成配置：

```bash
.venv/bin/pptctl --root /ABS/ppt-workbench/work config --client claude
.venv/bin/pptctl --root /ABS/ppt-workbench/work config --client codex
```

将 `/ABS/ppt-workbench` 换成实际解压路径。命令只打印配置和注册参数，不修改客户端设置。按实际路径注册，例如：

```bash
claude mcp add --transport stdio --scope project ppt -- /ABS/ppt-workbench/.venv/bin/python -m ppt_workbench.mcp_server --root /ABS/ppt-workbench/work
claude mcp get ppt
```

```bash
codex mcp add ppt -- /ABS/ppt-workbench/.venv/bin/python -m ppt_workbench.mcp_server --root /ABS/ppt-workbench/work
codex mcp list
```

Codex 等价配置：

```toml
[mcp_servers.ppt]
command = "/ABS/ppt-workbench/.venv/bin/python"
args = ["-m", "ppt_workbench.mcp_server", "--root", "/ABS/ppt-workbench/work"]
```

可以对 Agent 说：

> 使用已连接的 PPT 工作台，继续项目 main。先读交付轮次、页面和待处理任务。我的每次新需求通过 delivery_submit 保存一次原话，再逐页处理任务；整稿反馈一次汇总。不要把后台页任务当成新的用户输入，也不要替我确认整稿。

0.4 提供 **33 个 MCP 工具**。新增 `ppt_delivery_submit/status/control` 与 `ppt_quality_check/status`。外部会话的新用户要求先通过 `ppt_delivery_submit` 入队一次；已有网页消息不要再次提交。然后循环 `ppt_chat_next` → 读取实际任务 → `ppt_chat_respond`。所有内部页任务都归属原轮。

`manual` 模式需要外部 Agent 主动读取队列，不会唤醒一个已经结束的客户端会话。Agent 保存页面后，浏览器自动载入新版预览。

### 直接在网页里聊

本机已经安装并登录相应客户端时，可启动：

```bash
.venv/bin/pptctl --root ./work studio --project main --agent claude --open
```

或将 `claude` 换成 `codex`。界面也可以切换执行方式，设置会持久保存。

后台调用本机 CLI，读取结构化动作计划，由共享核心检查版本、范围和内容来源后执行。“可调用”表示找到了可执行文件；是否登录、参数是否兼容、模型是否成功返回，要由真实调用确认。失败会保留任务与错误，不伪造模型回复。

**本版尚未使用真实 Claude Code / Codex 账号完成端到端实测。** 同一项目仅允许一个工作台服务持有运行锁；重启后恢复中断任务，不重复应用已完成操作。具体已验证范围见 [VALIDATION.md](VALIDATION.md)。

## 5. 三种检查分别意味着什么

| 条件 | 检查或记录的内容 | 不代表什么 |
| --- | --- | --- |
| 机械与浏览器检查 | 对象边界、实际文字溢出、字体与图片状态、当前场景版本 | 不判断审美、故事是否有说服力或数据真假 |
| 操作者认可 | 用户查看实际稿件后认可当前整套内容表达与视觉呈现 | 不自动核验资料，也不替用户批准后续新版本 |
| 正式资料与交付检查 | 已声明的逐页依据要求、必要资料和相关审阅是否齐备，产物是否为当前版本 | 不因轮数少或文件能打开而自动通过 |

每轮生成后，网页使用隔离的测量预览逐页检查当前版本，不改变正在查看的页面、选中对象或输入草稿。没有浏览器报告、字体/图片未就绪或测量超时，会明确保留待处理状态。

自动修正目前只有一个范围：**容量估算或浏览器测量提示高度不足，且几何上有足够空间时，向下扩展文字框**。它不自动缩字、删减观点、补造数据或完成任意美术优化。估算不等于实测，修正后的新版本仍需浏览器测量。精确对象任务不会借检查之名重排其他对象。

### 第三轮确认与下载

当整稿完成、当前预览没有过期、机械检查可审阅且没有运行中的内容任务时，界面允许“确认整稿”。确认前会显示固定原话、绑定版本及计入的轮次。页面在对话框打开后变化，必须重新检查再确认，不能把旧认可移给新版本。

整稿确认也计一轮，所以无需逐页点击十次认可。资料仍需核验时，确认后继续显示交付待办。

网页区分**草稿下载**与**正式下载**。正式下载要求当前快照、检查、操作者认可和资料条件均满足；调用的是严格导出。条件未满足时，只提供带 `draft-` 前缀的草稿。CLI 中对应：

```bash
.venv/bin/pptctl --root ./work gate main
.venv/bin/pptctl --root ./work export main --format pptx --strict
```

MCP 没有用户审核通过工具。用户确认是本地操作者的陈述；资料核验与该确认分别记录。正式可交付和三轮达标也是两个状态：第 4 轮之后可以产出正式稿，但不能因此改写为三轮完成。

## 6. 当前页面与素材能力

模板选择器提供 **78 项**：设计地图原版的 54 个基础版式、7 个并列变体、14 个本地新增版式，以及本地案例提炼的“深蓝科技”系列（封面、目录、章节页）。同风格的重复封面合并为一个入口，旧 ID 兼容保留。预览使用主标题、公司、汇报人、章节等占位文字和 LOGO 占位，不携带案例主题、署名、域名或品牌图片。设计地图按原始 HTML 绘图坐标转换为声明式场景；部分曲线和箭头以独立透明图片保留，文字、矩形、圆形和支持的线条为原生对象。原始案例的完整提取记录仍保存在来源清单中。

| 能力 | 当前实现 |
| --- | --- |
| 实时预览 | 实际 16:9 HTML 页面，版本更新后加载新预览；过期预览不接受对象选择 |
| 精确编辑 | 稳定页 ID 和对象 ID，文字、位置、尺寸、颜色等属性补丁 |
| 可编辑 PPTX | 原生文本框、矩形、线条、图片，来自同一 Scene |
| 自定义页面 | 可提交声明式 Scene，仍受类型、边界、作用域和版本检查 |
| 图片与 Logo | 真实 PNG/JPEG，保留比例；缺少素材时明确待补 |
| 图表与复杂图形 | 可用基础对象表达；暂无原生数据图表、复杂 SVG 或任意图形导入 |
| 既有演示稿 | 支持原工作区 JSON；已从本地案例前三页中提取 5 个封面、1 个目录、1 个章节页，保留原图和可编辑文字；暂不支持任意 PPTX 无损导入 |
| 字体与查看器 | 浏览器与 PowerPoint 可能存在排版差异，最终需在目标查看器确认 |

本地命令包含 `标题改为：...`、`文字改为：...`（选中文字时）、`标题放大一点`、`背景换成深蓝色`、`背景换成白色` 和撤销。它们是有限规则，不是通用模型能力。

每条消息最多附 10 个文件：PNG/JPEG 单文件不超过 8 MiB；TXT/Markdown 为 UTF-8、50,000 字以内；PDF 不超过 20 MiB。文本附件仍受 20 MiB 上限。PDF 当前仅保存登记，未自动解析；图片在执行器尚未实际读取时也不能被描述为已经理解。

## 7. 常用 CLI

命令与网页共用状态目录。创建真实用户轮次优先使用 `chat send`；`scene`、`slide` 等低层入口是开发与维护能力，不能冒充完整的用户交互记录。

| 操作 | 命令 |
| --- | --- |
| 启动工作台 | `pptctl --root PATH studio --project main --open` |
| 提交一次整稿输入 | `pptctl --root PATH chat send main --scope deck --client-message-id USER_INPUT_ID --message '用户的完整原话'` |
| 读取待处理任务 | `pptctl --root PATH chat next main` |
| 提交任务动作 | `pptctl --root PATH chat respond main JOB_ID --plan reply.json` |
| 总轮次与完整结果 | `pptctl --root PATH delivery status main` |
| 重试原轮 | `pptctl --root PATH delivery control main --action retry --round-id ROUND_ID` |
| 取消当前轮 | `pptctl --root PATH delivery control main --action cancel --round-id ROUND_ID` |
| 查看机械与测量状态 | `pptctl --root PATH quality status main` |
| 检查并尝试受限修正 | `pptctl --root PATH quality check main --auto-fix` |
| 整稿逐页进度 | `pptctl --root PATH deck status main` |
| 读取实际场景 | `pptctl --root PATH scene get main S001` |
| 导出草稿 | `pptctl --root PATH export main --format html` 或 `--format pptx` |
| 严格正式导出 | `pptctl --root PATH export main --format pptx --strict` |
| 检查环境 | `pptctl doctor` |

同一次提交网络重试应复用相同 `--client-message-id`，新的用户输入应使用新 ID。直接补答指定待生成页时，可使用 `chat send` 的 `--reply-to-message QUESTION_ID --reply-to-deck-page --auto-resume`；保留原问题 ID，回答本身计一轮。

`quality check --auto-fix` 只在原轮授权范围内尝试已实现的安全修正，无真实浏览器测量时仍会等待报告，不会生成虚假的通过状态。

## 8. 验证与进一步阅读

本版的代码、状态、文件、CLI/MCP 契约与前端逻辑验证，以 [VALIDATION.md](VALIDATION.md) 的本轮记录为准。**整套新流程的真实 UI 验收仍未完成，需要连接可访问本机实例的浏览器；真实模型调用也尚未实测。** 不把程序测试、本地排版或历史样例当成本版验收完成。

本地检查命令：

```bash
.venv/bin/python -m unittest discover -s tests -v
node --check ppt_workbench/web/app.js
node tests/ui_logic.mjs
```

最后一项使用 JavaScript VM 测试界面状态与提交逻辑，不会启动浏览器。

- [CLIENT_GUIDE.md](CLIENT_GUIDE.md)：Coding Agent 的队列、作用域与工具使用。
- [ARCHITECTURE.md](ARCHITECTURE.md)：状态、版本、轮次、检查与导出设计。
- [UI_ACCEPTANCE.md](UI_ACCEPTANCE.md)：需要实际界面完成的验收流程。
- [CHANGELOG.md](CHANGELOG.md)：版本变更。

旧设计地图需要的准备材料可用 `project export` 导出 JSON；实际 HTML / PPTX 使用 `export`。两者不是同一产物。
