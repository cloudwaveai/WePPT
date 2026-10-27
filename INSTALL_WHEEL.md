# 使用预构建安装文件

版本 0.4.0。需要 Python 3.11 或更新版本。

推荐在解压后的 `ppt-workbench` 目录创建虚拟环境，保留本包目录与 `node_modules` 的位置关系：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install './dist/ppt_workbench-0.4.0-py3-none-any.whl[mcp]'
.venv/bin/pptctl doctor
npm install --ignore-scripts
.venv/bin/pptctl --root ./work studio --project demo --demo --open
```

Windows 使用 `.venv\Scripts\python.exe` 与 `.venv\Scripts\pptctl.exe`。如果 Python 命令是 `python`，用它代替 `python3`。

wheel 已包含网页、规则 JSON 和 PPTX 导出脚本。`npm install` 安装单独的 PPTX JavaScript 依赖，需要 Node.js 18+ 与 npm。HTML 预览与 HTML 导出不依赖 Node.js。只使用网页/CLI、暂时不接 MCP 时，可在安装 wheel 时去掉 `[mcp]`。

后续通过 CLI 或 MCP 操作同一 `--root` 即可。详细的聊天使用方式、两种代理接入路径和限制见 `README.md`、`CLIENT_GUIDE.md`。

本包不包含 Python、Node.js、Claude Code、Codex、模型账号或联网下载的第三方依赖。安装依赖需要可用的软件源。不要把解压后的虚拟环境复制到另一台机器；在新机器重新创建。
