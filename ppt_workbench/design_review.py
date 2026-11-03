"""Render and visually review new, unpublished pages. Never edit existing pages."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
from collections import Counter
from .core import EngineError
from .page_design import prepare_scene
from .rendering import render_html
from .quality import audit_scene


def render_candidate(scene, folder):
    return render_document(render_html(scene, interactive=False), folder)


def render_document(markup, folder, width=1280, height=720):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    chrome = os.environ.get('WEPPT_CHROMIUM') or shutil.which('chromium') or shutil.which('google-chrome')
    if not chrome:
        raise EngineError('DESIGN_RENDER_UNAVAILABLE', '服务器尚未配置页面渲染器。')
    script = """<script>(document.readyState==='complete'?Promise.resolve():new Promise(r=>window.addEventListener('load',r,{once:true}))).then(()=>document.fonts.ready).then(()=>{const e=document.createElement('script');e.type='application/json';e.id='design-measurement';e.textContent=JSON.stringify({fontsReady:document.fonts.status==='loaded',imageFailures:[...document.images].filter(i=>!i.complete||!i.naturalWidth).map(i=>i.dataset.objectId||'contact-page'),overflow:[...document.querySelectorAll('.text')].filter(e=>e.scrollHeight>e.clientHeight+2||e.scrollWidth>e.clientWidth+2).map(e=>e.dataset.objectId)});document.body.append(e)});</script>"""
    from .content_capacity import TEXT_FLOW_SCRIPT
    script = script.replace('const e=document.createElement', TEXT_FLOW_SCRIPT + 'const e=document.createElement')
    script = script.replace('JSON.stringify({fontsReady:', 'JSON.stringify({textFlow,fontsReady:')
    # User text can contain HTML-looking literals; keep dump-dom's JSON marker intact.
    script = script.replace('document.body.append(e)',
                            "e.textContent=e.textContent.replaceAll('<',String.fromCharCode(92)+'u003c');document.body.append(e)")
    path = folder / 'candidate.html'; path.write_text(markup.replace('</body>',script+'</body>'))
    png = folder / 'candidate.png'
    command=[chrome,'--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
             '--disable-background-networking','--no-first-run','--hide-scrollbars','--force-device-scale-factor=1',
             '--host-resolver-rules=MAP * ~NOTFOUND',f'--window-size={width},{height}','--virtual-time-budget=2000',
             '--user-data-dir='+str(folder/'browser-profile'),'--screenshot='+str(png.resolve()),'--dump-dom',path.resolve().as_uri()]
    environment = dict(os.environ, XDG_CONFIG_HOME=str((folder/'browser-config').resolve()),
                       XDG_CACHE_HOME=str((folder/'browser-cache').resolve()))
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, env=environment)
    try:
        stdout, stderr = process.communicate(timeout=35)
    except subprocess.TimeoutExpired:
        raise EngineError('DESIGN_RENDER_FAILED', '页面渲染超时，已停止本次浏览器。')
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        shutil.rmtree(folder/'browser-profile',ignore_errors=True)
        shutil.rmtree(folder/'browser-config',ignore_errors=True)
        shutil.rmtree(folder/'browser-cache',ignore_errors=True)
    match = re.search(r'<script type="application/json" id="design-measurement">(.*?)</script>',stdout.decode('utf-8','replace'),re.S)
    if process.returncode or not png.is_file() or not match:
        (folder/'browser-error.log').write_bytes(stderr)
        (folder/'browser-dom.html').write_bytes(stdout)
        raise EngineError('DESIGN_RENDER_FAILED','页面实际渲染未完成，不能声称已经看图检查。',
                          {'exitCode':process.returncode,'hasScreenshot':png.is_file(),'hasMeasurement':bool(match)})
    measurement=json.loads(match[1])
    if not measurement['fontsReady'] or measurement.get('imageFailures'):
        raise EngineError('DESIGN_RENDER_FAILED','页面字体尚未就绪。')
    return png, measurement


def run_json_page(markup, folder):
    """Launch headless Chrome on a self-measuring page; return its JSON element.

    The page script must append a <script type="application/json"
    id="design-measurement"> element itself. Shares render_document's launch and
    cleanup behaviour without requiring a screenshot or font readiness.
    """
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    chrome = os.environ.get('WEPPT_CHROMIUM') or shutil.which('chromium') or shutil.which('google-chrome')
    if not chrome:
        raise EngineError('DESIGN_RENDER_UNAVAILABLE', '服务器尚未配置页面渲染器。')
    path = folder / 'logo-page.html'; path.write_text(markup)
    command=[chrome,'--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
             '--disable-background-networking','--no-first-run','--hide-scrollbars','--force-device-scale-factor=1',
             '--host-resolver-rules=MAP * ~NOTFOUND','--window-size=1280,720','--virtual-time-budget=4000',
             '--user-data-dir='+str(folder/'browser-profile'),'--dump-dom',path.resolve().as_uri()]
    environment = dict(os.environ, XDG_CONFIG_HOME=str((folder/'browser-config').resolve()),
                       XDG_CACHE_HOME=str((folder/'browser-cache').resolve()))
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, env=environment)
    try:
        stdout, stderr = process.communicate(timeout=45)
    except subprocess.TimeoutExpired:
        raise EngineError('LOGO_PROCESS_TIMEOUT', 'Logo 处理超时，已停止本次浏览器。')
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        shutil.rmtree(folder/'browser-profile',ignore_errors=True)
        shutil.rmtree(folder/'browser-config',ignore_errors=True)
        shutil.rmtree(folder/'browser-cache',ignore_errors=True)
    match = re.search(r'<script type="application/json" id="design-measurement">(.*?)</script>',stdout.decode('utf-8','replace'),re.S)
    if process.returncode or not match:
        (folder/'browser-error.log').write_bytes(stderr)
        (folder/'browser-dom.html').write_bytes(stdout)
        raise EngineError('LOGO_PROCESS_FAILED','Logo 图片处理未完成。',
                          {'exitCode':process.returncode,'hasResult':bool(match)})
    return json.loads(match[1])


def _inventory(scene):
    from .design_loop import connector_glyph
    return (Counter(o['text'] for o in scene['objects'] if o['type']=='text' and not connector_glyph(o)),
            Counter(o['src'] for o in scene['objects'] if o['type']=='image'))


def review_new_page(studio, job, plan, context, mode, run_turn):
    from .design_loop import review_candidate
    plan=copy.deepcopy(plan)
    action=plan['actions'][0]
    planned=context.get('currentDeckPage',{})
    if not planned.get('composition'):
        return plan
    action['composition']=copy.deepcopy(planned['composition'])
    root=studio.wb.project_dir(studio.project_id)/'design-reviews'/job['id']
    attempt=len(list(root.glob('pass-*'))) if root.exists() else 0
    folder=root/f'pass-{attempt+1}'
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'draft.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
    scene=prepare_scene(action, resolve_images=studio._resolve_images)
    if scene is None:
        raise EngineError('DESIGN_LAYOUT_REQUIRED','此页需要完整 scene 或原生 diagram，不能仅填模板编号。')
    original_images={o['id']:o['src'] for o in scene['objects'] if o['type']=='image'}
    def validate_repair(candidate, base=None):
        candidate=copy.deepcopy(candidate)
        if candidate.get('type') in ('scene_patch','scene_objects'):
            from .design_loop import patch_candidate
            revised=patch_candidate(scene if base is None else base,candidate,(context.get('scene') or {}).get('sceneRevision',1))
            candidate={**action,'scene':revised};candidate.pop('diagram',None)
        if candidate.get('type')!='slide_add' or any(candidate.get(k)!=action.get(k) for k in ('title','role')):
            raise EngineError('DESIGN_REVIEW_SCOPE','设计修正只能替换当前候选页。')
        candidate['composition']=copy.deepcopy(planned['composition'])
        for obj in (candidate.get('scene') or {}).get('objects',[]):
            if obj.get('type')=='image' and obj.get('id') in original_images:
                if obj.get('src')=='scene-image:'+scene['slideId']+'/'+obj['id']:
                    obj['src']=original_images[obj['id']]
        revised=prepare_scene(candidate,resolve_images=studio._resolve_images)
        if revised is None or _inventory(revised)!=_inventory(scene):
            raise EngineError('DESIGN_REVIEW_SCOPE','设计修正改变了文字或原始图片。')
        if scene.get('diagram') and revised.get('diagram') != scene['diagram']:
            raise EngineError('DESIGN_REVIEW_SCOPE','不能丢失图解关系与编辑元数据。')
        return revised
    def runner(review_mode,prompt,review_context,**kwargs):
        return run_turn(review_mode,prompt,review_context,workdir=studio.wb.project_dir(studio.project_id),**kwargs)
    review_context=copy.deepcopy(context);review_context['draftAction']=action
    task=context.get('generationTask') or {}
    if task.get('kind')=='deck_page' and task.get('pageIndex'):
        # The previous page's ACTUAL layout, so the reviewer can see a repeated skeleton.
        with studio.wb._connection() as db:
            row=db.execute('SELECT slide_id FROM studio_deck_pages WHERE deck_id=? AND page_index=?',
                           (task.get('deckId'),task['pageIndex']-1)).fetchone()
        if row and row['slide_id']:
            from .quality import visual_stats
            try:review_context['previousPageStats']=visual_stats(studio.get_scene(row['slide_id'])['scene'])
            except EngineError:pass
    review_context['semanticSource']={'authority':'saved-page-plan','content':copy.deepcopy(planned),
        'instruction':'以已保存的内容方案确定关系；候选页的布局与连线不代表已验证事实。'}
    final,measurement,report=review_candidate(scene,folder,review_context,mode,runner,validate_repair,
        '返回一个完整 slide_add，保持 draftAction 的标题、角色、完整文字和图片，用 scene 给出新布局。',
        model_binding=job.get('payload',{}).get('modelBinding'))
    if final!=scene:
        updated=copy.deepcopy(action);updated.pop('diagram',None);updated['scene']=final
        plan['actions']=[updated]
    if report['status'] not in ('reviewed','revised_and_reviewed'):
        plan['reply'] += '\n自动设计检查未完成或仍有待确认问题，已保留完整候选页。'
    elif report['reviewMode']=='structure-only':
        plan['reply'] += '\n已完成结构检查；当前模型未读取页面截图。'
    return plan
