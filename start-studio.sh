#!/usr/bin/env bash
set -euo pipefail
PPT_STUDIO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PPT_STUDIO_DIR"
if ! command -v python3 >/dev/null 2>&1; then
  echo '请先安装 Python 3.11 或更新版本。'
  exit 1
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "需要 Python 3.11 或更新版本")'
if [ ! -f .venv/bin/python ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import importlib.metadata,importlib.util,sys; sys.exit(0 if importlib.metadata.version("ppt-workbench") == "0.4.0" and importlib.util.find_spec("mcp") else 1)' >/dev/null 2>&1; then
  echo '在本目录安装或更新 PPT Workbench 0.4.0 与 MCP 依赖。'
  .venv/bin/python -m pip install -e '.[mcp]'
fi
if command -v npm >/dev/null 2>&1; then
  if [ ! -d node_modules/pptxgenjs ]; then
    npm install --ignore-scripts --no-audit --no-fund
  fi
else
  echo '未找到 npm：HTML 预览可用；PPTX 导出需要安装 Node.js 后运行 npm install。'
fi
exec .venv/bin/pptctl --root "$PPT_STUDIO_DIR/work" studio --open "$@"
