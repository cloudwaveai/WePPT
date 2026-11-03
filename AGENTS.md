# AGENTS.md

## Devin × Codex 协作

本仓库的 PPT 视觉升级采用双 agent 协作：Devin 负责诊断与任务卡，Codex 负责实现与验证。
协作看板：`docs/collab/devin-codex.md`。

Codex 开始任何"让 PPT 更灵动/视觉升级"相关工作前：

1. 先读 `docs/collab/devin-codex.md` 的 §0 协议和目标任务卡。
2. 一次只做一张卡；完成后在该卡的「Codex 回写」与 §3 实施日志中记录改动、测试结果、对比图路径。
3. 不修改任务卡正文；有异议写在回写区。
4. 原文/原图保护、版本校验、不编造事实等安全边界不在放宽范围内。

当前状态（2026-11-03）：线上 editor-68，已含瓶身口 8 项需求（配色、对标风格、用户模板、受众版本、Logo 等，见 DEPLOYMENT.md 最新一节）。

## 常用命令

- 测试：`.venv/bin/python -m unittest discover -s tests`
- 前端逻辑：`node tests/ui_logic.mjs`
- 浏览器测试：`WEPPT_CHROMIUM="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" node tests/run_browser_tests.mjs`（启动临时演示项目并逐个跑 tests/*browser*.cjs；可用文件名过滤）
- PPTX 导出依赖：`npm install`（pptxgenjs 4.0.1；导出脚本还会用到它的依赖 jszip）
- 本机页面渲染（设计检查、contact sheet）需指定 Chrome：`WEPPT_CHROMIUM="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`
- 本机 LibreOffice 渲染 PPTX 时，要用 `FONTCONFIG_FILE` 把 Noto Sans SC、Microsoft YaHei 映射到已安装的 Noto Sans CJK SC，否则中文显示为方框（做法见 `validation/vivid-T2T8-2026-11-01/README.md`）。

## 基准与发布

- 同模型同输入基准：`validation/vivid-T2T8-2026-11-01/benchmark.py` + `launch-benchmarks.sh`。在服务器隔离容器中运行：新数据卷、配置只读，生图使用只含 `config.toml` 的独立 Codex 目录。
- 接入服务器（43.153.76.85）前，先读 `~/.codex/memories/webuddy-production-access.md`，并核验密钥 0600、指纹及严格 known_hosts。
- 发布流程见 `DEPLOYMENT.md` 最新一节：
  1. `COPYFILE_DISABLE=1` 打包并附清单。
  2. 构建镜像，在 Linux 镜像内跑全量测试。
  3. 确认无活动任务。
  4. 备份数据库。
  5. `docker compose up -d`。
  6. 核对运行文件、HTTP 与数据库。

## 发布补充（editor-68 起）

- 服务器 Docker 为 rootless，直接以 ubuntu 用户执行 `docker`，不要加 sudo。
- 增量发布：取上一版 `release-manifest.json`，本地计算 `ppt_workbench/`、`tests/` 及清单内文件的 sha256，只打包变更文件；服务器 `cp -a` 上一版目录后解包，按新清单逐个校验且确认无多余文件，再 `docker compose -f compose.dev.yaml build`，镜像内跑全量测试。
- 部分测试模块互相导入，单独运行时需 `PYTHONPATH=tests`。
