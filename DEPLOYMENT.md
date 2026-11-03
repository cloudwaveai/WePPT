# WePPT 腾讯云开发环境

2026-10-29 按用户授权，`https://ppt.bbstack.date/` 已从静态页切换到 WePPT 开发工作台。此授权替代此前“不覆盖模板站”的部署限制。

## 当前服务

- 主机：`ubuntu@43.153.76.85`，使用既有严格 known_hosts SSH；接入前读取 Mac 本地 production-access 记忆。
- 发布目录：`/opt/weppt/releases/20261103-editor-68`。
- 镜像：`weppt-dev:20261103-editor-68`；配置：`compose.dev.yaml`。
- 容器：`weppt-dev-weppt-1`；rootless Docker；UID 1100；只读根目录、移除 capabilities、禁止提权。
- 网络：Caddy HTTPS → 宿主 `127.0.0.1:8766` → 容器端口 8766。容器监听地址显式配置，不开放宿主公网端口。
- 持久卷：`weppt-dev_data`、`weppt-dev_codex`、`weppt-dev_config`。升级或回滚不得删除卷。
- 原站文件 `/srv/ppt/index.html` 保留。

## 访问与模型凭据

用户要求免登录测试，现通过 `WEPPT_PUBLIC_ACCESS=open` 显式开启直接访问。打开域名即可进入工作台，读写 API 无需 Cookie 或专用链接；Host/Origin 校验保留。未配置该选项的部署仍默认要求认证。

原访问令牌及私有链接文件保留供恢复受限访问时使用，当前无需使用。模型 key 继续只在服务器端保存。

用户提供的新模型 key 已替换服务器默认 `/home/ubuntu/.codex/config.toml` 中的旧 key，以及 WePPT 的 `/opt/weppt/config/model.env`。两者均为 0600。其他应用配置及服务未改动、未重启。模型 key 未写入镜像、源码或本机文件。

WePPT 经独立 Codex 卷配置使用 `env_key=WEPPT_CODEX_API_KEY`，端点为服务器已有的 `ai.cloudwaveai.cn`，配置模型 `gpt-6-luna`，官方 Codex CLI 0.162.1。真实连接和结构化建议已验证。服务商实际底层模型身份未独立核实。

模型建议请求显式提供上下文，设置 `project_doc_max_bytes=0`，不再自动读取项目指令文件。保留 filesystem deny-root、工具网络关闭、shell/apps/agents/web 禁用；未放宽宿主 user namespace、AppArmor 或容器安全配置。

## 启动与更新

```sh
cd /opt/weppt/releases/20261103-editor-68
WEPPT_RELEASE=20261103-editor-68 docker compose -f compose.dev.yaml up -d
```

先构建新版本、核对发布清单并检查服务，再修改 Caddy。修改 Caddy 时复用 `/opt/webuddy/.release.lock`；只替换 `ppt.bbstack.date` 段，验证配置后 reload。不要覆盖其他站点配置。

## 回滚

静态页完整备份：`/opt/weppt/backups/static-before-20261029-editor-01/`。
切换前 Caddy 备份：`/opt/weppt/backups/caddy-before-20261029-editor-03/Caddyfile`。

恢复静态站时，在共享发布锁内将 PPT 站点段恢复为下列内容，运行 `caddy validate` 后 reload；保留当前其他域名配置，不能盲目覆盖整份历史 Caddyfile。

```caddy
ppt.bbstack.date {
    root * /srv/ppt
    encode gzip
    file_server
}
```

停止 WePPT 只停对应 Compose 服务，不删除持久卷，不恢复旧数据库覆盖新数据。旧模型 key 已被服务商重置，不能用回滚恢复旧凭据。

## 验证

见 `validation/public-2026-10-29.md`。Linux 容器测试 293 项，284 通过、9 项可选依赖跳过；前端 39 项逻辑检查通过。真实模型建议、预览不写入、应用一次、撤销恢复与可编辑 PPTX 导出已验证。免登录版本另外通过 22 项 HTTP 定向检查。

测试容器仅为运行可执行测试夹具，给临时 `/tmp` 设置 exec；现役容器临时目录限制未因此放宽。

## 原生图片生成配置（2026-10-29 已实测）

当前网关需要以下非秘密标识才能向官方 Codex 会话提供原生生图工具；仅投影文字调用所需的 base_url/env_key 不够。WePPT 配置卷已补齐，原 key 真实生图并应用成功。不要将这个标识当作 API key，也不要将其套用到其他供应商。

```toml
[model_providers.weppt.http_headers]
x-openai-actor-authorization = "aiseat"
```

保留现有 `env_key = "WEPPT_CODEX_API_KEY"`，不需要更换 key。不要为接入图片而开启其他应用或更改其他服务配置。文本规划保持工具禁用；图片适配器读取上述持久配置。详情和原任务恢复记录见 `validation/image-generation-2026-10-29.md`。

## 模板参考与适配（2026-10-29）

版本 10 接入原稿参考选择、当前内容预览、版本校验和模板撤销；参考映射及视觉提示约束见 `validation/template-integration-2026-10-29.md`。保留上一版 `20261029-editor-05` 及持久卷，无数据库结构迁移。

## 内容用途分类（2026-10-30）

版本 11 将内容用途设为主要筛选，页面位置保留为辅助条件。原稿按原始内容分类，分类计数按原稿/可编辑样式分别计算；默认推荐不调用模型，进一步修改仍走现有 AI 助手。保留版本 10 镜像与数据卷，发布前备份 `/data/backups/before-editor-11.sqlite`，无数据库迁移。验证见 `validation/template-categories-2026-10-30.md`。

## Jev 智能选版（2026-10-30）

版本 12 接入 Command Code 官方 System One API，模型固定为 `typesafe/jev-1.14.0`。服务器独立 `/opt/weppt/config/commandcode.env`（0600）通过 Compose 注入 `WEPPT_JEV_API_KEY` 与 `WEPPT_JEV_MODEL`。只在用户点击“智能选版”时调用，不改变 Codex 文本/生图通道。用户最后提供的新密钥已写入；密钥值不进入发布目录和记录。

发布前数据库备份 `/data/backups/before-editor-12.sqlite`，保留版本 11 镜像与数据卷。无数据结构迁移。验证记录：`validation/jev-2026-10-30.md`。

版本 13 修正单一候选的提示，不调用模型。最终发布前备份 `/data/backups/before-editor-13.sqlite`，保留版本 12。

## 预览加载优化（2026-10-30）

版本 14 复用推荐栏/网格预览、只调度可见卡片、限制次要 fetch 并发为 2，并缓存相同 URL 的结果。原稿 URL 使用内容 SHA256 版本，图片保持原始字节，服务端保留访问检查。主画布继续直接加载。

已通过 Linux 镜像 38 项 HTTP/参考适配/模板测试。切换前确认没有活动生成任务并备份 `/data/backups/before-editor-14.sqlite`；保留版本 13 镜像、原数据及配置卷。无数据库迁移，Caddy 和模型配置未修改。验证见 `validation/preview-loading-2026-10-30.md`。

## 原生图解与反馈生图（2026-10-30）

版本 15 已发布到 https://ppt.bbstack.date/。首批接入 diagram-design 的流程、分层、中心关系与对照语义，编译为可编辑对象。用户通过“换成 AI 图解”切换时，保留标题与当前手改，支持版本冲突保护、失败保留与撤销。

Linux 镜像相关测试 116 项通过；前端逻辑 41 项通过。原数据库在 `/data/backups/before-editor-15.sqlite` 备份，保留版本 14 及持久卷；切换前无活动生成任务，未更改 Caddy、模型配置或其他服务。样例在独立项目创建，不覆盖用户原稿。

版本 16 补齐整稿计划中的 diagram 字段校验与保存，使 deck_start 和 slide_add 使用相同图解协议。Linux 67 项定向测试通过，备份 `/data/backups/before-editor-16.sqlite`，保留版本 15。第一次线上样例因字段协议失败，原项目保留；修复后新建项目重测，不混淆首次与修复后结果。

版本 17 修复模型附带有效动作却返回空白聊天回复时整页被拒绝的问题；动作本身继续严格校验。Linux 68 项相关测试通过，备份 `/data/backups/before-editor-17.sqlite`，保留版本 16。现役 `weppt-dev:20261030-editor-17`。

## 完整页面设计与看图检查（2026-10-30）

版本 20 从现役版本 17 更新。18、19 为未激活的构建候选。新增整稿设计规则、每页结构化内容和 slide_add.scene 原生页面，避免完整作者布局被通用模板重排；新基础页不再自动添加项目主题页脚。

新增 Chromium 与中文字体，Codex 新结构化页面在落页前实际渲染，并进行一次截图检查；修正不得改变原文字和原始图片，修正后重新渲染。图片解析沿用项目素材身份与字节校验。Chrome 在只读容器内使用自己的临时配置/缓存，超时回收进程组。

Linux 131 项相关测试通过；前端 41 项逻辑回归通过。实际在同等只读/cap-drop/no-new-privileges/pids/tmpfs 限制下完成中文截图，字体就绪、零文字溢出。发布前无活动任务，备份 `/data/backups/before-editor-20.sqlite`，原数据、模型环境、Caddy 保持。原版本 17 为回滚锚点，禁止用旧数据库覆盖新写入。

版本 21 修正真实样例暴露的方案元数据校验问题：由服务器将保存的 composition 作为权威方案，再检查页面是否完整呈现其中的文字；不再要求模型逐字复述方案说明 JSON。文字遗漏、标题和图片检查继续保留。44 项相关测试在 Linux 镜像通过，发布前无活动任务，备份 `/data/backups/before-editor-21.sqlite`。现役 `weppt-dev:20261030-editor-21`，HTTP 健康检查通过。版本 20 的失败样例保留，独立新项目用于再次验证；实际生成与导出结果另见 `validation/page-design-2026-10-30/summary.md`。

版本 22 将整稿页的模型格式错误纳入现有最多三次的修正范围。每次重新校验完整动作，仅通过后应用一次；不接受截断 JSON，也不重试用户补充问题。新增“恢复后无重复页”和“三次仍失败即阻断”两项测试，Linux 46 项相关测试通过。发布前无活动任务，备份 `/data/backups/before-editor-22.sqlite`，现役 `weppt-dev:20261030-editor-22`。

版本 23 修正内容方案与图解双份文案的生成约束：新计划以 composition 为单一内容来源，流程按节点分组；遇到旧计划中的不一致图解，要求完整原生场景保留原文。看图上下文新增实际 candidateScene，使模型能读取并保留图解对象 ID 和编辑元数据。内容校验错误提供缺失组的原文，继续禁止删改内容。Linux 72 项相关测试通过，备份 `/data/backups/before-editor-23.sqlite`；现役 `weppt-dev:20261030-editor-23`，HTTP 健康检查通过。

版本 24 允许服务器为“文字与计划标题完全一致且唯一”的文本对象补齐 title 编辑绑定，不改变文字和布局；改写标题或歧义标题仍拒绝。未通过预检查的候选动作也保存到对应项目的 design-reviews，便于追查真实失败。Linux 73 项相关测试通过，备份 `/data/backups/before-editor-24.sqlite`；现役 `weppt-dev:20261030-editor-24`。同题样例保留已生成第一页并重试第二页，此样例不能宣称为全程零重试。

版本 25 补齐提供给模型的 sceneSpec：文字 binding/lineHeight/valign、线条 strokeWidth、完整对象字段和非负尺寸规则，并给出合法标题对象示例。生成器须用水平/垂直线段，不能使用负数宽高。未放宽场景校验。Linux 73 项相关测试通过，备份 `/data/backups/before-editor-25.sqlite`；现役 `weppt-dev:20261030-editor-25`。样例第五页因原协议字段/几何错误发生第二次显式重试，前四页保持。

版本 26 新增新建页的 textRef：布局可引用 title、block.ID.heading/body，由服务器从保存的方案填入完整原文。引用无效、同时提供 text 与 textRef 时拒绝；页面落地后保存为正常可编辑文字。整稿动作不必再重复 composition、takeaway、key_points；服务器补齐已存字段，完整覆盖检查继续执行。看图仍检查最终渲染和原文字清单。Linux 75 项相关测试通过，备份 `/data/backups/before-editor-26.sqlite`；现役 `weppt-dev:20261030-editor-26`。样例保留前四页，第三次显式重试第五页；另做过两次未应用的协议诊断模型调用。

## 背景生图目标与图层修复（2026-10-30）

版本 27 支持将矩形背景/占位原位替换为图片，保留位置、尺寸、图层和透明度；新图可指定 placement=background，放在画布底色之上、正文之下。生成图片保持原始字节，绑定文字和图解内部对象不能被误替换。所有图片目标和几何尺寸在生图前检查，错误返回中文原因及对象 ID。整稿反馈中的目标校验失败最多尝试修正三次，不自动重试实际生图调用。

Linux 92 项生图、整稿反馈、协议和图解相关测试通过。实际复现旧版拒绝背景矩形、把新增背景放在正文上方两个问题，并验证修复、撤销、并发保护及原图字节保持。发布时仅存在本次封面失败阻塞的 7 个已知排队任务，无运行任务；备份 `/data/backups/before-editor-27.sqlite`，保留原队列和配置。该次发布 `weppt-dev:20261030-editor-27`。真实用户任务复验结果见 `validation/background-image-2026-10-30/summary.md`。

## 2026-10-30 · 生图会话产物读取修复（editor-28）

真实重试发现：图片工具已写出原图，但最终模型文字误报 `IMAGE_NO_RESULT`。适配器改为读取 Codex JSON 事件中的唯一新会话 ID，仅接受该会话目录的唯一原图；不按共享目录最新文件猜测，也不接受其他会话的路径。已有文件字节及安全路径检查保持。Mac、Linux 各 66 项相关测试通过。

该次发布 `weppt-dev:20261030-editor-28`，备份 `/data/backups/before-editor-28.sqlite`。原封面失败记录和原图存于 `/data/image-recovery-20261030-v2/`，经正常 ImageJobs 流程原子恢复，未重复生图，全部前景对象保持。第一次恢复校验误把内容版本预期为 3（正常布局写入也递增至 4），事务已回滚；原失败证据和备份保留。后续任务与最终验证见 `validation/background-image-2026-10-30/summary.md`。

## 2026-10-30 · 现有页面 ID 协议修复（editor-29）

继续原反馈时，第 7 页遇到 `SCOPE_VIOLATION`：模型把新建页示例 `S001` 放进已有页 `scene_replace.scene.slideId`。通用场景说明已改为实际目标 ID，仅 `slide_add` 允许新建占位。替换场景提交前检查内外层页面 ID 一致；仅在原作用域与版本校验通过后，允许最多三次模型纠正，不替模型改 ID，不放宽跨页权限或并发保护。

Mac、Linux 各 70 项反馈与协议测试通过，包含纠正成功、次数上限与真实冲突保护。该次发布 `weppt-dev:20261030-editor-29`，备份 `/data/backups/before-editor-29.sqlite`。已通过健康检查。第 6 页的模型文字改写已用正常场景替换流程恢复原文，保留新版布局和历史；只重试原轮次剩余任务。最终交付与限制见 `validation/background-image-2026-10-30/summary.md`。

## 2026-10-30 · 提问协议与反馈参数恢复（editor-30/31）

现役 `weppt-dev:20261030-editor-31`。第 4 轮的 Logo 上传追问被旧的“每题必须 2–6 个选项”校验拒绝；模型 schema 没有这个下限。现在 schema、校验和提示词统一为 0–6 个可选建议，允许开放问题和单项建议，不制造虚假选项。修复消息只展示前四个选项的问题，完整保留六个。提问格式错误单独归类，在应用任何动作前最多三次纠正，保留原轮次、作用域和基线。

轮次仍真实记录，内部三轮目标未伪造达成；界面只显示实际轮数，不再显示“超过三轮”警告或重复内部说明。真实重试又发现窄色条 radius 超界，editor-31 为反馈页面增加 INVALID_SCENE / SCENE_OUT_OF_BOUNDS 的有界纠正；不重试供应商失败，不绕过并发或跨页权限。外观修改提示明确保持原文。

Mac/Linux 最终各 78 项反馈与协议测试、41 项 JS 界面逻辑检查通过。editor-30 在没有活动任务时发布；editor-31 仅允许原第 4 轮已知的四个阻塞排队任务，实际无运行任务或活动生图。数据库备份 `/data/backups/before-editor-30.sqlite`、`/data/backups/before-editor-31.sqlite`，保留全部队列、配置和用户数据。实际原任务复验与页面检查见 `validation/question-protocol-2026-10-30/summary.md`。

### 2026-10-30 · editor-32：按项目选择模型

已部署 `weppt-dev:20261030-editor-32`，入口 https://ppt.bbstack.date/ 。新增服务器模型配置 `/opt/weppt/config/model-profiles.json`，同步至已有 config volume 的 `/config/model-profiles.json`。DeepSeek 密钥仅在服务器 0600 的 `deepseek.env`；浏览器只提交配置 ID，不接收密钥或调用地址。原服务网关与生图、JEV 通道保持各自配置。

- 六个网关 GPT 模型使用 Codex；一个 `gpt-6-luna` 配置使用 Claude Code 2.1.314（兼容通道，不称为 Claude 模型）。九个配置均实测连接成功。网关模型名是服务返回的标识，不证明上游实现身份。
- DeepSeek 官方 `/models` 返回 `deepseek-flash`、`deepseek-v4-pro`；两个模型均完成真实 API 与页面文字修改测试。第一枚凭据认证失败，未写入；用户后补凭据通过认证后才保存。
- 项目保存选择，新任务记录 `modelBinding`；整稿和反馈子任务继承，重试保持绑定；配置被移除或模型变更时明确失败，不改用其他模型。每轮结果标注模型。
- API 与 Claude Code 当前处理文字/页面结构，未接入图片像素审阅。Codex 保留原看图检查；所有通道继续使用已有动作、范围和版本校验。
- Mac 相关后端分组共 162 项通过；Linux 同一集合 162 项通过；JavaScript 42 项通过。真实模型与浏览器证据在 `validation/multi-model-2026-10-30/`、`outputs/weppt-multi-model-2026-10-30/`。
- 切换前无排队/运行任务或生图工作；SQLite 备份 `/data/backups/before-editor-32.sqlite`。原 8 页、4 轮状态保留。不代替用户进行人工验收。

回滚代码可用 editor-31 镜像和原 compose；新增 SQLite 表可保留，不以旧备份覆盖用户在发布后新增的数据。部署未改 Caddy 或服务器上的其他应用。

### 2026-10-30 · editor-33：多模型反馈协议纠错

线上浏览器测试发现 DeepSeek 整稿反馈子任务使用了不支持的 `slide_patch` 路径；引擎拦截后原稿保持。补充完整合法路径列表，并引导精确文字编辑使用 `scene_patch`；`INVALID_AGENT_OUTPUT` 最多三次尝试，失败后停止，不放宽字段、对象范围或版本保护。

Mac/Linux 相关 88 项检查均通过，新增两项分别验证未应用前纠错及三次上限。真实 DeepSeek 整稿分派→单页修改通过；指定标题逐字匹配，全部对象样式和其他两页保持；快捷推荐生成预览但未提前修改原稿。测试脚本初次将场景元数据 title 也要求保持旧值，导致检查失败；改为核对预期标题元数据及全部对象内容/样式，未放宽产品保护。

现役 `weppt-dev:20261030-editor-33`。切换前无运行/排队任务，备份 `/data/backups/before-editor-33.sqlite`。模型配置、服务器凭据及独立图像通道沿用 editor-32。

### 2026-10-30 · editor-34/35：原稿模板适配与助手高度

editor-34 新增独立模板候选表与预览/应用接口，44 页原稿几何结构和原图作为参考。DeepSeek Flash 启用已验证的原图输入；不支持看图的配置仍只读结构。服务器模型配置仅增加能力标记，凭据不变，原配置备份为 `/opt/weppt/config/model-profiles-before-editor34.json`。原文/原图、作用域、版本及实际渲染溢出校验通过后才可应用，支持撤销和重做。

editor-35 缩短桌面输入框，右助手从 52px 标题栏下方开始，工具栏向左收。Mac 50 项、Linux 78 项相关检查、42 项 JS 检查通过。独立演示项目真实 DeepSeek 看图适配与浏览器应用/撤销/重做通过，原项目未被测试修改。证据 `validation/template-adaptation-2026-10-30/summary.md`。数据库备份 `/data/backups/before-editor-34.sqlite` 和 `/data/backups/before-editor-35.sqlite`，保留旧镜像和数据。

### 2026-10-30 · editor-36：右侧先推荐原稿模板

现役 `weppt-dev:20261030-editor-36`。默认快捷推荐从当前页内容和表达要求检索原稿模板，在右侧展示 3 个候选预览。选版采用本地规则，不调用生成模型或外部分类服务；用户选定模板后才进入既有 LLM 适配预览与明确应用流程。文字工具单独保留，匹配请求只读，页面变化会清除旧推荐。

Mac/Linux 各 34 项相关后端检查、42 项 JS 检查通过。线上独立项目桌面/手机浏览器检查通过：两种表达要求返回不同模板，选择和预览零模型调用、场景保持、JS 错误零；截图已打开检查。7 个关键运行文件与本地一致。发布前无活动任务，备份 `/data/backups/before-editor-36.sqlite`，保留 editor-35 镜像及既有配置，原 8 页、5 轮、44 条场景历史不变。证据 `validation/template-matching-2026-10-30/summary.md`。回滚代码时保留当前数据，不用旧备份覆盖新写入。

### 2026-10-30 · editor-40：内容驱动设计与有界检查循环

18:45 CST 已从 editor-36 发布到 `weppt-dev:20261030-editor-40`。默认模板借鉴与自由构图；diagram-design 指导进入模板适配、新页设计和检查。实际渲染后最多修正一次、复核一次；支持视觉的模型看原始 PNG，其余明确为结构检查。预览展示完整检查意见，用户确认后才应用。项目经验仅复用已应用且仍有效的成功方案，不自动训练或修改全局提示词。

真实 DeepSeek 测试完成一次箭头修正，复核仍指出连线语义冲突，正确标为 needs_attention；该样例未达设计验收，不作为成功经验。93 项主要相关测试、后续 15 项供应商参数和 29 项连接符修正测试分别在 Mac/Linux 通过（集合重叠）；42 项 JS 检查、线上桌面/手机浏览器及检查意见回放通过，截图已查看。12 个部署文件与本地一致。详情及保留的初次失败证据见 `validation/design-loop-2026-10-30/summary.md`。

发布前无活动任务，备份 `/data/backups/before-editor-40.sqlite`。原 8 页、5 轮及 47 条场景历史与此次发布前备份一致，保留用户新增编辑。原配置、凭据、持久卷和其他服务不变；保留 editor-36 代码回退锚点，不恢复旧数据库覆盖新写入。37–39 仅为未激活候选。

### 2026-10-30 · editor-42：反馈语义与原生箭头

20:35 CST 从 editor-40 发布至 editor-42，editor-41 仅隔离测试。普通反馈流程使用独立 adaptation，避免强制中心仓库；原文和备注优先于图型参考，复核携带上一轮意见。line 新增 startArrow/endArrow，网页和 PPTX 同为可编辑端点，避免文字箭头与线条分离。旧字段保持兼容，不改用户已有页面。

真实测试先修正主路径与反馈返回点，再验证原生端点修正；最终两次看图调用得到 revised_and_reviewed，11 段原文完整，无溢出。未宣称从空白 one-shot 或用户验收。Linux 最终 63 项相关测试通过，PPTX 端点和内容读回、文件校验、网页及 LibreOffice 实际渲染已检查。10 个部署文件与本地一致，原 8 页/5 轮/47 条场景历史与此次备份一致。证据 `validation/semantic-flow-2026-10-30/summary.md`。

初次公网浏览器受本机 DNS 错指影响而证书失败。公共 DNS 与源站证书核对正常后，浏览器临时固定已知源站且保持 TLS 校验，桌面/手机检查通过；未修改系统 DNS 或 Caddy。初次本机 LibreOffice 缺中文字体的验证结果保留，为渲染进程设置已有 CJK 字体替代后正确显示，PPTX 字体不变。

备份 `/data/backups/before-editor-42.sqlite`；凭据、配置与其他服务未改。保留 editor-40 镜像，但新箭头字段不被旧版支持；回退前必须检查新写入兼容性，优先向前修复，不用旧数据库覆盖用户新增数据。

## 整稿 one-shot 开发测试版（2026-10-31）

03:54:52 CST 发布 editor-50。整稿策划与草稿复核、逐页内容驱动设计、diagram-design 上下文、实际渲染检查及限次修正已接入。模板作为参考；页面保留原生可编辑对象。最多两轮、合计三次页面修正，调用预算持久保存；自动检查不代表人工验收。

发布前一致性备份 `/data/backups/before-editor-50.sqlite`。13 个运行文件与固定清单一致；9 个模型配置保留。原128条场景、3条素材、7条整稿和57条整稿页面记录保持；导入新样例与浏览器试改撤销后再次逐行核对通过，SQLite integrity_check=ok。未改变 Caddy、凭据或其他应用。

新建独立样例：https://ppt.bbstack.date/?project=one-shot-product-20261031-50 。它原样导入隔离测试的4页产品介绍，不伪造线上生成历史；导入没有调用模型。实际生成使用 deepseek-flash，一次用户输入、18次内部模型调用、363.55秒、零人工改稿。

公网 Chrome 实测4页和9项模型配置、标题字号编辑及撤销、所有场景完全恢复、PPTX下载；桌面与窄屏截图已查看，无页面脚本异常。测试机使用临时DNS映射，TLS验证保持。公网导出45个原生文字对象回读一致，21个版面相关OOXML成员与已渲染样例逐字节相同，Office结构检查通过。

本次证明可编辑初稿路径；尚有局部文案重复和自然换行可改进，未证明所有主题／模型稳定精修或PowerPoint桌面实机兼容。完整证据见 `validation/one-shot-2026-10-31/summary.md`。

## 内容容量与实际断行（2026-10-31 editor-52）

11:16:36 CST 上线。新增策划阶段容量提示、浏览器真实行数与末行测量，将结果交给单页／整稿检查；优先重新分配正文区域，减少等宽窄栏和缩字。新增文字JSON转义已用真实浏览器验证。旧原文、图片、同页要求、版本与调用预算保护保持。

发布前备份 `/data/backups/before-editor-52.sqlite`；6个变更运行文件匹配清单。原134条场景、3条素材、7条整稿、57条整稿页面保持，SQLite完整性通过；9个模型配置保留，Caddy与凭据不变。Mac／Linux各67项相关测试通过。

新样例：https://ppt.bbstack.date/?project=one-shot-product-20261031-51 。候选51一次输入、21次调用、390.68秒生成4页；候选52只增加测量JSON转义，普通文案生成逻辑相同。样例原样导入，无人工润色；最终模型状态needs_attention保留。39个原生文字对象完整，实际PPTX渲染和独立审稿确认可作为开发初稿。流程容量改善，但部分重复文案和前瞻措辞仍需精炼。见 `validation/content-capacity-2026-10-31/README.md`。

## 视觉升级 T1–T8（2026-11-01 editor-55）

2026-11-01 17:10:17 CST 从 editor-52 切换到 `weppt-dev:20261101-editor-55`。镜像 ID：`sha256:1ecce733d77858c84afa243094fe3cd02a2985119725e7ce74ca7f2c0379e6ac`。内容对应协作看板 T1 与 T2–T8：

- 视觉工具箱提示词。
- 设计字段与计划节奏检查。
- 大号锚点（kicker / metric，metric 只能取自用户材料）。
- 检查循环评判视觉张力。
- 几何节奏指标（只出 warning）。
- 新图元：椭圆、旋转、阴影、字距、关键词强调。
- 原型示例。
- **自动配图（默认开启）**：整稿及整稿检查完成后，为最多 3 页生成无文字配图，放入页面预留的 `image-slot` 区域。可在"执行方式"弹窗中按项目关闭，也可通过服务器环境变量 `WEPPT_AUTO_IMAGES=off` 整体关闭。

同时修复：

- PPTX 两位序号在 Office 中拆行。
- pptxgenjs 写出的多 `pPr` 无效段落。
- 整页截断自动紧凑重试一次。
- 整稿检查越界建议导致整稿 blocked。
- 生图会话出两张图被拒收。
- 修正预算全有或全无。

发布步骤：

1. 用 `COPYFILE_DISABLE=1` 打包，附 `release-manifest.json`；上传后 259 个文件 SHA-256 全部核对通过。
2. 构建复用缓存。Linux 镜像内全量测试 445 项 OK（9 项可选依赖跳过）。
3. 切换前确认无排队或运行中的任务、无待生成图片。
4. 一致性备份 `/data/backups/before-editor-55.sqlite`，integrity_check 为 ok，140 条场景、3 条素材、7 条整稿、57 条整稿页面、104 个任务与原库一致。

切换后核对：

- 容器内 200 个运行文件与清单一致。
- 本机回环和公网 HTTP 均为 200；`/api/state` 返回 `imageMode=auto`，9 个模型配置保留。
- 数据库 integrity_check 为 ok，各表计数不变。
- Caddy、凭据、其他服务未改动。

回滚锚点为 editor-52 镜像与发布目录。editor-53、editor-54 只用于基准，未上线。禁止用旧数据库覆盖新写入。

同模型同输入基准对照 T1-after，见 `validation/vivid-T2T8-2026-11-01/README.md`：

- 两套整稿一次完成，人工干预为 0。
- Memory 由 30 次调用、1333 秒降为 22 次、744 秒。
- 每页都有版式原型且相邻不重复；两张封面自动配图落地。
- 机械错误、溢出、节奏告警均为 0。

自动检查仍为 needs_attention，不代表人工验收。新图元只在 LibreOffice 中验证过，未做 PowerPoint 桌面实测。


## Codex 复核返工（2026-11-01 editor-57）

19:40:18 CST 从 editor-55 切换到 `weppt-dev:20261101-editor-57`（`sha256:f6ccaca5c73bacaeeb1fb0e7cf10f3e3a86d378cb1252b37de8888382d7f01df`）。修复内容：
- metric 必须逐字来自用户材料。
- 预留配图区的任何手改都不会被图片覆盖。
- `WEPPT_AUTO_IMAGES=off` 强制覆盖项目设置。
- 自动配图落地后整稿检查不再误判过期。
- 新增锚点不足告警与相邻页相似告警。
- 主画布载入加兜底。
- 计划阶段的非法项目字段进入纠错重试；策划复核失败时按原方案继续。

核对：发布前无活动任务，备份 `/data/backups/before-editor-57.sqlite` 完整性 ok、各表计数一致；Linux 449 项 OK；200 个运行文件与清单一致；本机与公网 HTTP 200；`imageMode=auto`、未锁定；数据库完整性 ok。回滚锚点 editor-55、editor-52。editor-56 只做过基准，未上线。证据：`validation/vivid-T2T8-2026-11-01/metrics-rework.json`。


## Codex 二次复核返工（2026-11-02 editor-58）

00:22:50 CST 从 editor-57 切换到 `weppt-dev:20261103-editor-68`（`sha256:6ccc2e1db4858eb322d1f94f92bf43a935876344d3f7dcddf765691a03ed0896`）。修复内容：
- metric 的中文数词边界。
- 主画布只认预览文档的 `ppt-ready`，失败时用 fetch + srcdoc 重新载入；后台测量帧同样改走 srcdoc。
- 可选装饰字段的非法值不再阻断整页。

发布方式：网络过慢，只上传 5 个变更文件，在服务器上由 editor-57 组装 editor-58，259 个文件按完整清单校验通过、无多余文件。

核对：发布前无活动任务，备份 `/data/backups/before-editor-58.sqlite` 完整性 ok、计数一致；Linux 镜像内 Python 449 项 OK、JS 43 项通过；200 个运行文件与清单一致；本机与公网 HTTP 200；数据库完整性 ok。回滚锚点 editor-57、editor-55、editor-52。

## 瓶身口需求 8 项（2026-11-03 editor-68）

02:32 CST 从 editor-67 切换到 `weppt-dev:20261103-editor-68`。新增：
- 优化时不闪屏：缩略图按页增量更新，主画布新旧页交叉淡入，旧页保持到新页就绪。
- 样式条：类别筛选、翻页按钮；禁止横向越界滑动触发浏览器返回。
- 配色：主色 + 1–2 个辅色，8 套预设；用于新生成（整稿 design 强制覆盖），或按页/整稿确定性换色（可撤销，低对比文字保留原色）。
- 单页适配：用户上传模板页（PNG/JPG，全工作区共享）；适配提示词要求换版式，服务端按内容框 IoU≥0.7 退回“只换颜色”的方案。
- 整稿适配：上传 3 页对标稿，由看图模型解析为 UI/元素/字体/配色/风格/避免 的结构化描述（可编辑），用于本项目生成，或生成“对标风格副本”新项目。
- 为你推荐：跨项目汇总已应用模板、整稿版式、配色与对标风格，作为排序加分与生成参考（不跨越页面角色）。
- 受众版本：员工/客户/领导同行/投资人四种，基于原稿内容生成新项目，原稿不变；新增内容缺少依据时标“待补充”。
- 一键 Logo：独立入口；Chrome 画布处理透明/非透明底（自动去底、裁边、白/深色版本），按页面留白与底色选位置和版本；整稿完成后自动应用。

发布：仅上传 28 个变更文件，在服务器上由 editor-67 组装，270 个文件按清单校验无差异、无多余文件。核对：发布前无运行中任务（另有 4 个自 11-02 13:48 起排队未运行的反馈任务，重启不影响）；备份 `/data/backups/before-editor-68.sqlite` 完整性 ok、计数一致；Linux 镜像内 Python 506 项 OK（9 项可选依赖跳过）、JS 47 项通过；205 个运行文件与清单一致；本机与公网 HTTP 200；数据库完整性 ok。

真实模型实测（隔离容器、deepseek-flash，测后已删除容器与卷）：对标风格解析 37 秒得到完整结构化描述；示例项目生成“客户版”5 页（原 3 页 + 案例待补充页 + 报价方案页），未编造案例、数字或价格，整稿完成。回滚锚点 editor-67、editor-58。
