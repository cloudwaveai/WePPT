"""Isolated Windows PPTAgent converter runtime and narrow compatibility launcher.

--install installs only standalone rendering/conversion dependencies. The full
upstream research agent is POSIX-only and is deliberately not claimed supported.
--run <original CLI args> executes the unchanged pinned standalone skill CLI.
"""
from pathlib import Path
import importlib.machinery
import json
import os
import runpy
import shutil
import subprocess
import sys
import types
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'data/engine-runtimes/pptagent'
PYTHON = RUNTIME / 'python312/python.exe' if os.name == 'nt' else Path(sys.executable)
MANIFEST = json.loads((ROOT/'vendor/skills/manifest.json').read_text(encoding='utf-8'))
COMMIT = next(p['commit'] for p in MANIFEST['packages'] if p['id']=='pptagent')
SKILL = ROOT/'data/upstream-skills/pptagent'/COMMIT
OFFICE = ROOT/'data/engine-runtimes/libreoffice/program/soffice.com'

def run_checked(args, **kwargs):
    subprocess.run([str(x) for x in args],check=True,**kwargs)

def install():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        # The web converter uses only the wheel's original JavaScript converter.
        # Do not install the full research agent or its model/tool dependencies.
        run_checked([PYTHON, '-m', 'pip', 'install', '--no-deps', 'pptagent==1.1.37'])
        npm = shutil.which('npm')
        node = shutil.which('node')
        if not npm or not node:
            raise RuntimeError('Node and npm are required for PPTAgent conversion')
        env = os.environ.copy()
        env['PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD'] = '1'
        run_checked([npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], cwd=SKILL, env=env)
        env.pop('PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD', None)
        env.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(RUNTIME / 'browsers'))
        run_checked([node, SKILL / 'node_modules/playwright/cli.js', 'install', 'chromium'], env=env)
        print(json.dumps({'installed': True, 'scope': 'standalone-web-converter', 'fullAgent': False}))
        return
    if not PYTHON.exists():
        archive=RUNTIME/'python-3.12.10-embed-amd64.zip'
        urllib.request.urlretrieve('https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip',archive)
        with zipfile.ZipFile(archive) as bundle: bundle.extractall(PYTHON.parent)
    pth=PYTHON.parent/'python312._pth'
    pth.write_text(pth.read_text().replace('#import site','import site'))
    if not (PYTHON.parent/'Lib/site-packages/pip').exists():
        bootstrap=RUNTIME/'get-pip.py'
        urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py',bootstrap)
        run_checked([PYTHON,bootstrap])
    run_checked([PYTHON,'-m','pip','install','--no-deps','pptagent==1.1.37'])
    run_checked([PYTHON,'-m','pip','install','playwright==1.62.0','PyYAML==6.0.3','Pillow==13.0.0','PyMuPDF==2.1','fastmcp==2.13.3','fake-useragent==2.2.0','pdf2image==1.17.0','pypdf==6.21.4','colorlog==6.12.0','openai==3.46.0'])
    npm=shutil.which('npm.cmd') or shutil.which('npm')
    run_checked([npm,'ci','--ignore-scripts','--no-audit','--no-fund'],cwd=SKILL)
    env=os.environ.copy();env['PLAYWRIGHT_BROWSERS_PATH']=str(RUNTIME/'browsers')
    run_checked([PYTHON,'-m','playwright','install','chromium'],env=env)
    if not OFFICE.exists():
        downloads=ROOT/'data/engine-runtimes/downloads';downloads.mkdir(parents=True,exist_ok=True)
        msi=downloads/'LibreOffice_26.2.7_Win_x86-64.msi'
        if not msi.exists():urllib.request.urlretrieve('https://download.documentfoundation.org/libreoffice/stable/26.2.7/win/x86_64/'+msi.name,msi)
        run_checked(['msiexec.exe','/a',msi,'/qn','TARGETDIR='+str(OFFICE.parent.parent)])
    run_checked([PYTHON,__file__,'--run','doctor'])

def launch(arguments):
    if os.name != 'nt':
        # On Linux the upstream CLI can run normally when its own optional
        # dependencies are installed; the web converter does not require it.
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(RUNTIME / 'browsers'))
        os.environ['NODE_PATH'] = str(SKILL / 'node_modules')
        os.environ['DEEPPRESENTER_WORKSPACE_BASE'] = str(RUNTIME / 'cache')
        sys.path.insert(0, str(SKILL / 'scripts'))
        sys.argv = [str(SKILL / 'scripts/pptagent.py'), *arguments]
        runpy.run_path(sys.argv[0], run_name='__main__')
        return
    if Path(sys.executable).resolve()!=PYTHON.resolve():
        raise SystemExit(subprocess.call([str(PYTHON),str(Path(__file__).resolve()),'--run',*arguments]))
    # The package's __init__ asserts POSIX even though the standalone modules use
    # cross-platform Playwright/Node. Create only its package namespace; do not
    # disable Python assertions or modify installed upstream source files.
    site=PYTHON.parent/'Lib/site-packages'
    namespace=types.ModuleType('deeppresenter')
    namespace.__path__=[str(site/'deeppresenter')]
    namespace.__file__=str(site/'deeppresenter/__init__.py')
    namespace.__spec__=importlib.machinery.ModuleSpec('deeppresenter',loader=None,is_package=True)
    namespace.__spec__.submodule_search_locations=namespace.__path__
    namespace.__version__='1.1.37'
    sys.modules['deeppresenter']=namespace
    sys.path.insert(0,str(SKILL/'scripts'))
    os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(RUNTIME/'browsers')
    os.environ['NODE_PATH']=str(SKILL/'node_modules')
    os.environ['DEEPPRESENTER_WORKSPACE_BASE']=str(RUNTIME/'cache')
    # Windows uses soffice.com; patch only exact standalone LibreOffice calls.
    original_run=subprocess.run
    def office_run(command,*args,**kwargs):
        if isinstance(command,(list,tuple)) and command and command[0]=='libreoffice':
            command=[str(OFFICE),*command[1:]]
        return original_run(command,*args,**kwargs)
    subprocess.run=office_run
    original_which=shutil.which
    shutil.which=lambda command,*args,**kwargs: str(OFFICE) if command=='libreoffice' and OFFICE.exists() else original_which(command,*args,**kwargs)
    # Preserve the original tracked-file allowlist while converting /D:/ file
    # URL paths correctly on Windows (POSIX unquote alone rejects every file).
    from pptagent_runtime import core
    core.unquote=urllib.request.url2pathname
    sys.argv=[str(SKILL/'scripts/pptagent.py'),*arguments]
    runpy.run_path(sys.argv[0],run_name='__main__')

if __name__=='__main__':
    if sys.argv[1:2]==['--install']:install()
    elif sys.argv[1:2]==['--run']:launch(sys.argv[2:])
    else:raise SystemExit('Use --install or --run <PPTAgent standalone CLI arguments>')
