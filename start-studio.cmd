@echo off
setlocal
cd /d "%~dp0"
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 'Python 3.11 or newer is required')"
if errorlevel 1 (
  echo Please install Python 3.11 or newer and enable its PATH command.
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  python -m venv .venv
  if errorlevel 1 exit /b 1
)
.venv\Scripts\python.exe -c "import importlib.metadata,importlib.util,sys; sys.exit(0 if importlib.metadata.version('ppt-workbench') == '0.4.0' and importlib.util.find_spec('mcp') else 1)" >nul 2>&1
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install -e ".[mcp]"
  if errorlevel 1 exit /b 1
)
where npm >nul 2>&1
if errorlevel 1 (
  echo npm is missing. HTML preview works; install Node.js for PPTX export.
) else (
  if not exist node_modules\pptxgenjs (
    call npm install --ignore-scripts --no-audit --no-fund
    if errorlevel 1 exit /b 1
  )
)
.venv\Scripts\pptctl.exe --root "%CD%\work" studio --open %*
exit /b %errorlevel%
