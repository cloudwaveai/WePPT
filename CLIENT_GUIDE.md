# 给 Claude Code / Codex 的操作说明

适用于 **PPT Workbench 0.4.0**。用户通过聊天给出思想和材料，你读取持久状态、整理表达、逐页制作；浏览器负责实际页面预览、对象选择、浏览器测量和操作者确认。

项目 ID 与数据目录必须固定。例如项目 `main`，所有操作使用同一个绝对 `--root`。启动器默认使用解压目录中的 `work`，MCP 必须指向同一位置。安装和注册命令见 [README.md](README.md)。

## 1. 主流程：三次用户输入，内部逐页执行

目标是第一轮需求与材料、第二轮集中反馈、第三轮明确整稿确认。首轮、补答、修改、撤销和认可都计入总用户输入。后台页面任务、原轮重试和检查不另计，不要求用户每页说一次“继续”。

本版共有 **33 个 MCP 工具**。三轮流程新增入口如下：

| 工具 | 用途 |
| --- | --- |
| `ppt_delivery_submit(project_id, text, scope="deck", slide_id?, object_id?, client_message_id?)` | 保存一次真实用户输入并入队；同一次重试复用请求 ID |
| `ppt_delivery_status(project_id)` | 总输入/输出轮次、当前轮、完整结果快照、质量状态与正式交付缺口 |
| `ppt_delivery_control(project_id, action, round_id?)` | `retry` 或 `cancel` 原轮，不伪造新的用户输入 |
| `ppt_quality_status(project_id)` | 机械检查、当前版本浏览器测量与剩余问题 |
| `ppt_quality_check(project_id, auto_fix=false)` | 检查整稿，可选原轮授权范围内的受限修正 |

用户在 **Coding Agent 会话中**提出新要求时，用 `ppt_delivery_submit` 保存完整原话一次。整稿用 `scope="deck"`；明确页/对象用 `scope="page"` 并传真实 ID。随后读取队列处理内部任务，不为每次工具调用重复 submit。

用户已经在**网页中**发送的消息已入队，直接调用 `ppt_chat_next`，不要再次 submit。同一次提交因网络异常重试时复用 `client_message_id`；真实的新输入使用新 ID。

逐页执行的基本循环：

1. 调用 `ppt_delivery_status` 与 `ppt_studio_context`，了解当前状态和实际页面。
2. 调用 `ppt_chat_next(project_id)`，获得具体任务、原话、目标对象、基准版本及页上下文。
3. 根据任务提交 `ppt_chat_respond(project_id, job_id, plan)`。
4. 继续处理同轮自动产生的页任务。无待处理任务时停止，说明当前状态。
5. 读取交付与质量状态，汇总这一轮已经完成的版本和仍需用户决定的事项。

`manual` 模式不会唤醒一个已结束的会话；需要外部 Agent 主动读取队列。发现 CLI 不等于模型已经成功调用，本版真实 Claude Code / Codex 账号调用仍未完成端到端实测。

## 2. 先读用户的思想与明确输入

读取原始消息、`intakeInputs`、逐页 `userIntent`、后续原话和真实材料。不要从空白字段猜测用户立场，也不要把模型整理的文案登记成用户原话。

首轮可通过普通对话提供用途、听众、目标、逐页大纲、展示方式、Logo 策略、资料策略、哪些页需要另外提供内容。已有完整逐页文字时，可明确使用本地 `按大纲排版`。可识别的前言例如：

```text
用途：介绍方案
听众：目标客户
目标：理解方案并讨论下一步
展示方式：两者兼用
Logo策略：不使用
数据策略：用户提供真实资料
本稿各页依据要求：需要核验
```

展示方式接受现场讲述、独立阅读或两者兼用。Logo 和资料策略由用户明确决定，品牌素材仍须实际提供。“无需外部资料”和“无需外部依据”是不同声明，不相互推导。可以在某页大纲内写 `依据要求：需要核验`，或补充 `第3页依据要求：需要核验`。只有用户明确选择时才记录 `无需外部依据`。

未知项保持待定，冲突或不明确的元信息不能被默认为通过。所有选择保留原话；设置数据策略不等于已完成研究，设置依据要求不等于事实已核验。

缺少决定时，将真正缺失的信息合并成至多三个问题，给有区别的候选并允许自由回答。网页选项先加入输入框：多行 intake 选择按 `groupId` 替换同组完整内容，不同组可以一次发送。不要诱导用户每点一个选项就消耗一轮。补充资料、问题回答本身仍是下一轮用户输入。

## 3. 整稿任务与整稿反馈

### 首轮建立计划

用户要求一整套时，保存 2–30 页的计划，再逐页生成。网页任务可返回 `deck_start` 动作，由服务端绑定本次用户原话。模型计划中的拟用措辞是候选，不能伪装为新的原始需求。

`execution="agent"` 用于模型制作。`execution="outline"` 只用于用户明确要求按已提供完整文字本地排版的情况；不能把模型自行补写的稿件称作用户原文排版。

空项目也保留 `ppt_deck_start(project_id, plan, source_message, execution="agent")` 等低层兼容入口。但要保留从首轮开始的完整交互记录，优先通过 delivery submit 和聊天任务创建计划，不绕过队列。已开始计划的页序固定，本版不支持进行中任意扩充页数。

当 `generationTask.kind="deck_page"` 时，读取 `currentDeckPage`，只提交对应页的一个 `slide_add`，保留计划中的标题与角色。不启动新整稿、不修改已完成页。当前页确实缺关键内容时提出问题，不能造数据凑齐。

### 第二轮分派跨页反馈

当真实用户提交 `scope="deck"` 的整稿反馈时，使用单一 `deck_feedback` 动作，将反馈按已有页 ID 分派。示例 ID 仅说明格式，实际以读取结果为准：

```json
{
  "reply": "将按这条反馈依次调整第 1 页和第 4 页。",
  "actions": [
    {
      "type": "deck_feedback",
      "edits": [
        {"slide_id": "S001", "instruction": "标题改为用户明确提供的新标题"},
        {"slide_id": "S004", "instruction": "背景换成深蓝色"}
      ]
    }
  ],
  "questions": []
}
```

`deck_feedback` 只能独立出现，包含 1–30 个不同的已有页 ID。同一页的要求合并为一项；可携带用户明确指定的 `object_id`。不能夹带审核状态、核验结论或无关的“统一优化”。

动作只建立逐页任务。当 `generationTask.kind="feedback_page"` 时，读取 `currentFeedback`，只用普通 `slide_patch / scene_replace / scene_patch` 修改其 `slideId`，保留可选对象限制。不得再次返回 `deck_feedback`、创建新页或修改项目简报。程序自动执行后续页并合并为同一轮输出。

本地批次也支持明确格式：

```text
整稿修改
第1页：标题改为：PPT 工作台
第4页：背景换成深蓝色
```

本地处理器只支持标题/文字替换、标题字号、背景等已实现指令。复杂重写、复杂信息图和任意美术调整需要模型或人工，不能宣称这些规则具有通用设计能力。无法确定页码时提问，不能猜页或只处理能识别的半条要求。

### 待生成页补答与恢复

`ppt_deck_status` 返回逐页进度。`ppt_deck_control` 保留 pause/resume/retry/cancel，`ppt_deck_step` 可推进可运行任务。任务或轮次失败时，优先读取错误后用对应控制入口重试，避免重新提交同一输入。

页面问题的回答必须绑定**原提问消息 ID**。可使用 `ppt_deck_answer`，传入 `project_id`、真实 `text`、`question_message_id`、本次 `client_message_id`，并明确设置 `auto_resume=true`；也可使用 CLI 的补答参数。网页从汇总结果中点击选项时，使用选项自己的 `questionMessageId / deckPageIndex / deckId`，不能把本轮汇总输出 ID 当作原问题。回答作为当前待生成页的新材料保存，自动续做不另计轮次。

## 4. 精确修改保持原有范围

`ppt_next_action` 返回当前页、版本、缺口和相关模板；`ppt_studio_context` 提供场景、素材和上下文。普通内容补丁不能覆盖 `userIntent`；后续真实原话通过追加输入记录保存，AI 候选使用 `candidateText`，当前采用表达使用 `title / takeaway / keyPoints` 等内容字段。

单页任务最多修改一页。选中对象后只允许该对象的 `scene_patch`，不能顺便重排其他对象或页面。已有自定义排版的细节修改优先使用对象补丁；`scene_generate` 会重新安排本页基础布局，仅用于首次生成或明确要求重排。

对象补丁示例：

```json
{
  "reply": "已调整当前页标题字号。",
  "actions": [
    {
      "type": "scene_patch",
      "slide_id": "S001",
      "base_scene_revision": 3,
      "changes": [
        {"objectId": "title", "properties": {"fontSize": 48}}
      ]
    }
  ],
  "questions": []
}
```

ID 和版本必须来自实际任务。内容版本 `base_revision` 与场景版本 `base_scene_revision` 分开管理。收到 `STALE_REVISION` 后重新读取并评估，不得简单改成新版本号照抄旧操作。内容变化但预览尚未更新时，旧预览不能被当作当前结果。

支持的动作是 `project_update`、`slide_add`、`slide_patch`、`scene_replace`、`scene_patch`、`deck_start`、`deck_feedback`。`deck_start` 可伴随项目更新，但不与页面变更混用；每个内部页任务仍受更严格的类型和单页约束。动作计划不执行任意 shell，不代替用户认可或核验来源。

直接调用 `ppt_scene_patch`、`ppt_slide_patch` 等低层工具，虽仍受页面和版本规则约束，但不会天然关联一次用户交互。已有轮次后的未关联变更进入 `externalChanges`，`interactionAccountingComplete` 变为 false，不能再用该计数宣称完整三轮达标。推荐把用户输入交给 delivery submit，再经 chat respond 执行。

## 5. 检查、确认与正式交付

`ppt_quality_check` 检查机械条件；网页在隔离 iframe 中报告实际字体、图片和对象尺寸。没有浏览器测量时保留 `awaiting_browser`，不可合成测量冒充看过页面。测量报告绑定实际页和场景版本，旧版本不能证明当前版式。

当前自动修正只覆盖**容量估算或实测提示高度不足，且向下扩展有足够空间的文字框**。仅在原轮已授权范围内执行，有持久修正预算，新版本必须重新测量；估算不能代替真实浏览器报告。不会自动删文、缩字、核验事实或完成任意美术优化；精确对象轮不借检查改其他对象。

`readyToReview` 只表示机械条件达到可审阅状态。语义、用户思想与审美仍需操作者判断。实际页面未就绪或仍有问题时，说明具体缺口，不把 “<= 3” 描述为质量合格。

第三轮由用户查看整稿后在界面明确“确认整稿”。这次确认绑定全稿当前版本、保留原话、计入一次输入，并产生对应结果。模型不能调用审核动作替用户完成；MCP 也不提供认可通过工具。确认不核验资料，`releaseIssues` 仍需按真实来源与声明解决。

`ppt_export(project_id, format_name="html" 或 "pptx", slide_id?, strict=false)` 默认输出草稿；正式交付使用 `strict=true`。需要当前版式检查、操作者认可、必要资料与流程条件齐备，以及当前结果快照。内容、素材或产物变化使旧认可失效。

`qualityAccepted`、`releaseReady` 和三轮目标是不同状态。第 4 轮之后仍可完成正式稿，必须保留超标事实。历史项目或外部变更导致计量链不完整时同样如实说明，不重置或推算次数。

`ppt_workspace_export` 是准备材料 JSON，`ppt_release_manifest` 是检查清单，实际演示稿使用 `ppt_export`。文件哈希与流程条件不等于事实真实性认证。

## 6. CLI 同一条链路

```bash
pptctl --root PATH chat send main --scope deck --client-message-id USER_INPUT_ID --message '用户的完整原话'
pptctl --root PATH chat next main
pptctl --root PATH chat respond main JOB_ID --plan reply.json
pptctl --root PATH delivery status main
pptctl --root PATH quality status main
pptctl --root PATH quality check main --auto-fix
```

重试同轮：

```bash
pptctl --root PATH delivery control main --action retry --round-id ROUND_ID
```

补答原问题：

```bash
pptctl --root PATH chat send main --scope deck --client-message-id ANSWER_ID --reply-to-message QUESTION_ID --reply-to-deck-page --auto-resume --message '用户对这一页的补充原话'
```

`PATH`、ID 和 JSON 中的版本值都必须替换为实际值。同一用户输入的网络重试复用输入 ID，内部任务重试使用 control，不再发送一条伪造“用户要求”。

## 7. 素材与渲染能力

Scene 为 1280 × 720，支持 text、rect、line、image。公开设计案例库为50套精选参考；旧内置模板目录已移除，不再作为新稿候选。案例提供视觉语言与适配建议，不是可一键套用的母版。历史文档所需渲染规则继续保留。不存在任意 PPTX 无损导入、原生数据图表、复杂 SVG 编辑或全能自动美术。

图片可用 `asset:ID`；保留既有图片时可用上下文中的 `scene-image:页ID/对象ID`。这些是素材引用，不能当作真实外部 URL，也不能凭文件名宣称已经读懂图像。PNG/JPEG 保留真实文件内容，缺素材应明确待补。

TXT/Markdown 的文本可供读取，PDF 当前只登记文件，不自动解析。需要理解图片或 PDF 时由具备相应读取能力的 Agent 明确检查原文件。实际来源、定位和口径分别记录，不以文件存在代替核验。

浏览器与 PowerPoint 可能使用不同字体度量，正式分享前仍需目标查看器检查。真实模型端到端和本版整稿全 UI 验收的状态，以 [VALIDATION.md](VALIDATION.md) 和 [UI_ACCEPTANCE.md](UI_ACCEPTANCE.md) 为准；纯 JavaScript VM 测试不等于浏览器验收。

## 一句启动指令

> 使用已连接的 PPT 工作台，继续项目 main。先读交付状态与待处理任务。我提供思想和逐页内容，你给必要选项并集中处理；新的真实用户输入只提交一次，再逐页生成或修改。整稿反馈合并一轮，指定对象只改那个对象；展示实际预览、测量与待办，最终由我确认整稿。
