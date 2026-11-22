"""Convert trusted server-generated HTML into an UNREVIEWED native PPTX draft.

JSON stdin: {slides:[{html:string}], outputDir:string}. No review is fabricated.
The caller must sanitize HTML and isolate each request. No standalone build or
finalize gate is altered: this calls the original lower-level strict converter.
"""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'data/engine-runtimes/pptagent'


def convert(request):
    started = time.perf_counter()
    slides = request.get('slides')
    if not isinstance(slides, list) or not 1 <= len(slides) <= 100:
        raise ValueError('slides must contain 1–100 trusted HTML pages')
    htmls = [s.get('html') if isinstance(s, dict) else s for s in slides]
    if any(not isinstance(s, str) or not s.strip() or len(s) > 2_000_000 for s in htmls):
        raise ValueError('Each slide requires nonempty HTML, maximum 2 MB')
    manifest = json.loads((ROOT / 'vendor/skills/manifest.json').read_text(encoding='utf-8'))
    commit = next(p['commit'] for p in manifest['packages'] if p['id'] == 'pptagent')
    skill = ROOT / 'data/upstream-skills/pptagent' / commit
    site_packages = RUNTIME / 'python312/Lib/site-packages' if os.name == 'nt' else Path(sysconfig.get_path('purelib'))
    converter = Path(os.environ.get('WEPPT_PPTAGENT_CONVERTER', str(site_packages / 'deeppresenter/html2pptx/html2pptx_cli.js')))
    node = shutil.which('node')
    if not converter.exists() or not node or not (skill / 'node_modules').is_dir():
        raise RuntimeError('PPTAgent converter unavailable; run scripts/setup-pptagent-runtime.py --install')
    parent = Path(request['outputDir']).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix='draft-', dir=parent))
    source = workspace / 'slides'
    source.mkdir()
    for index, html in enumerate(htmls, 1):
        (source / f'slide{index:03}.html').write_text(html, encoding='utf-8')
    (workspace / 'task.json').write_text(json.dumps({'slides': len(slides), 'aspect_ratio': '16:9', 'language': 'zh'}), encoding='utf-8')
    pptx = workspace / 'unreviewed-draft.pptx'
    env = os.environ.copy()
    env['NODE_PATH'] = str(skill / 'node_modules')
    env.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(RUNTIME / 'browsers'))
    geometry_script = r"""
const {chromium}=require('playwright'); const fs=require('fs'); const path=require('path');
const {pathToFileURL}=require('url');
(async()=>{const browser=await chromium.launch(); const results=[];
try { for(const name of fs.readdirSync(process.argv[1]).filter(n=>n.endsWith('.html')).sort()) {
 const page=await browser.newPage({viewport:{width:1280,height:720}});
 await page.goto(pathToFileURL(path.join(process.argv[1],name)).href);
 await page.evaluate(()=>document.fonts.ready);
 const errors=await page.evaluate(()=>{
  const errors=[];const b=document.body.getBoundingClientRect();
  if(Math.abs(b.width-1280)>1||Math.abs(b.height-720)>1)errors.push('Body must be 1280 x 720 pixels');
  for(const element of document.querySelectorAll('p,h1,h2,h3,h4,h5,h6,li,img,svg')) {
   const r=element.getBoundingClientRect();const style=getComputedStyle(element);
   if(style.display==='none'||style.visibility==='hidden')continue;
   if(r.left<b.left-1||r.top<b.top-1||r.right>b.right+1||r.bottom>b.bottom+1)
    errors.push('Out-of-bounds '+element.tagName+': '+(element.textContent||'').slice(0,60));
   if(element.scrollHeight>element.clientHeight+2||element.scrollWidth>element.clientWidth+2)
    errors.push('Content overflows '+element.tagName+': '+(element.textContent||'').slice(0,60));
  } return errors;
 });results.push({slide:name,errors});await page.close();
} } finally {await browser.close();} console.log(JSON.stringify(results));
if(results.some(r=>r.errors.length))process.exitCode=2;
})().catch(e=>{console.error(e.stack);process.exitCode=1});
"""
    measured = subprocess.run([node, '-e', geometry_script, str(source)], env=env, cwd=skill,
                              capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    (workspace / 'geometry-check.json').write_text(measured.stdout or '{}', encoding='utf-8')
    if measured.returncode:
        raise RuntimeError('PPTAgent browser geometry check failed: ' + (measured.stdout + measured.stderr)[-6000:])
    command = [node, str(converter), '--html_dir', str(source), '--layout', '16:9', '--output', str(pptx)]
    # No --soft: the original overflow, asset and text-position validators run.
    result = subprocess.run(command, env=env, cwd=skill, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=120)
    (workspace / 'converter.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode != 0:
        raise RuntimeError('PPTAgent strict conversion failed: ' + (result.stderr or result.stdout)[-6000:])
    ns = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
          'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
    pages = []
    with zipfile.ZipFile(pptx) as bundle:
        names = sorted((n for n in bundle.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)),
                       key=lambda n: int(re.search(r'slide(\d+)', n).group(1)))
        if len(names) != len(slides):
            raise RuntimeError('PPTAgent output page count mismatch')
        for name in names:
            tree = ET.fromstring(bundle.read(name))
            pages.append({'nativeShapes': len(tree.findall('.//p:sp', ns)),
                          'pictures': len(tree.findall('.//p:pic', ns)),
                          'text': [item.text or '' for item in tree.findall('.//a:t', ns)]})
    metrics = {'elapsedMs': round((time.perf_counter() - started) * 1000), 'slideCount': len(pages), 'pages': pages}
    output = {'ok': True, 'engine': 'pptagent', 'workspace': str(workspace),
              'pptxPath': str(pptx), 'metrics': metrics,
              'reviewStatus': 'unreviewed', 'finalized': False, 'deliveryReady': False,
              'validation': {'strictConverterPassed': True, 'visualReviewPassed': False,
                             'browserGeometryPassed': True,
                             'contentCompletenessVerified': False, 'exportRenderVerified': False},
              'warnings': ['Editable converter draft only. Original standalone visual review and finalize gates have not been passed.']}
    (workspace / 'draft-result.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    return output


if __name__ == '__main__':
    try:
        print(json.dumps(convert(json.loads(sys.stdin.read())), ensure_ascii=False))
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
