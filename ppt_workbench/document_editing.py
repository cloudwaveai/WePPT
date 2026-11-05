"""Direct document operations: no language model, reversible page membership/order."""
import copy
import json
from .core import EngineError, _json


def initialize(studio):
    with studio.wb._connection() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS studio_document_history (
            project_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, before_state TEXT NOT NULL)''')


def history(studio):
    with studio.wb._connection() as db:
        row = db.execute('SELECT revision FROM studio_document_history WHERE project_id=?', (studio.project_id,)).fetchone()
        revision = studio.wb.get_project(studio.project_id)['revision']
    return {'canUndo': bool(row and row['revision'] == revision)}


def _snapshot(state):
    return {'order': [p['id'] for p in state['slides']],
            'archived': {p['id']: p['archived'] for p in state['slides']},
            'selected': state.get('selectedSlideId')}


def operate(studio, action, revision, slide_id=None, after_id=None):
    if action not in {'insert', 'duplicate', 'remove', 'move', 'undo'}:
        raise EngineError('INVALID_REQUEST', '不支持的页面操作。')
    with studio.wb.atomic() as db:
        project = studio.wb.get_project(studio.project_id)
        studio.wb._revision(project['revision'], revision)
        if db.execute("SELECT 1 FROM studio_jobs WHERE project_id=? AND status IN ('queued','running') LIMIT 1", (studio.project_id,)).fetchone():
            raise EngineError('DOCUMENT_BUSY', '正在生成页面，请完成后调整页序；任务会在后台继续。')
        state = project['workspace'];before = _snapshot(state)
        active = {p['id']: p for p in state['slides'] if not p['archived']}
        if action in {'duplicate', 'remove', 'move'} and slide_id not in active:
            raise EngineError('SLIDE_NOT_FOUND', '当前页不存在，请刷新后重试。')
        if after_id is not None and after_id not in active:
            raise EngineError('SLIDE_NOT_FOUND', '插入位置已变化，请刷新后重试。')
        if action == 'undo':
            row = db.execute('SELECT * FROM studio_document_history WHERE project_id=?', (studio.project_id,)).fetchone()
            if not row or row['revision'] != revision:
                raise EngineError('STALE_REVISION', '后续已有修改，不能覆盖；请读取当前版本。')
            prior = json.loads(row['before_state'])
            if 'palettePreference' in prior:
                if prior['palettePreference'] is None:
                    db.execute('DELETE FROM studio_palette_preferences WHERE project_id=?',(studio.project_id,))
                else:
                    db.execute('INSERT OR REPLACE INTO studio_palette_preferences VALUES (?,?)',(studio.project_id,_json(prior['palettePreference'])))
            for sid, scene in prior.get('scenes', {}).items():
                current = studio.get_scene(sid)
                studio.put_scene(sid,current['contentRevision'],scene,'撤销整稿配色',preserve_layout=True)
            if 'appliedPalette' in prior:
                if prior['appliedPalette'] is None:
                    db.execute('DELETE FROM studio_palette_applied WHERE project_id=?',(studio.project_id,))
                else:
                    db.execute('INSERT OR REPLACE INTO studio_palette_applied VALUES (?,?)',(studio.project_id,_json(prior['appliedPalette'])))
            project=studio.wb.get_project(studio.project_id);state=project['workspace']
            by_id = {p['id']: p for p in state['slides']}
            order = prior['order'] + [p['id'] for p in state['slides'] if p['id'] not in prior['order']]
            state['slides'] = [by_id[sid] for sid in order]
            for p in state['slides']:
                p['archived'] = prior['archived'].get(p['id'], True)
            selected = prior['selected']
        else:
            selected = slide_id
            if action in {'insert', 'duplicate'}:
                source = studio.get_scene(slide_id)['scene'] if action == 'duplicate' else None
                title = active[slide_id]['title'] if source else '新幻灯片'
                page = studio.wb.add_slide(studio.project_id, title, '用户直接复制页面' if source else '用户直接新建空白页', active[slide_id].get('role','content') if source else 'content')
                selected = page['slide']['id']
                if source:
                    scene = copy.deepcopy(source);scene['slideId'] = selected
                else:
                    scene = {'schema':'ppt-scene','schemaVersion':1,'slideId':selected,'width':1280,'height':720,'background':'#FFFFFF','objects':[
                        {'id':'title','type':'text','text':'单击添加标题','x':80,'y':70,'w':1120,'h':100,'fontSize':44,'color':'#243247'},
                        {'id':'body','type':'text','text':'单击添加内容','x':80,'y':220,'w':1120,'h':390,'fontSize':24,'color':'#465366'}]}
                studio.put_scene(selected, page['revision'], scene, '复制页面' if source else '新建空白页', preserve_layout=True)
                project = studio.wb.get_project(studio.project_id);state = project['workspace']
                moving = next(p for p in state['slides'] if p['id'] == selected)
                state['slides'].remove(moving)
                position = next(i+1 for i,p in enumerate(state['slides']) if p['id']==after_id) if after_id else 0
                state['slides'].insert(position,moving)
            elif action == 'remove':
                page = active[slide_id];idx = state['slides'].index(page);page['archived'] = True
                remaining = [p for p in state['slides'] if not p['archived']]
                selected = remaining[min(idx,len(remaining)-1)]['id'] if remaining else None
            elif action == 'move':
                if after_id == slide_id:
                    return {'state':studio.state()}
                moving = active[slide_id];state['slides'].remove(moving)
                position = next(i+1 for i,p in enumerate(state['slides']) if p['id']==after_id) if after_id else 0
                state['slides'].insert(position,moving)
        state['selectedSlideId'] = selected
        studio.wb._save(db,studio.project_id,state,project['revision'],action='document-'+action)
        studio._touch(db,selected)
        db.execute('UPDATE studio_state SET selected_slide_id=? WHERE project_id=?',(selected,studio.project_id))
        if action == 'undo':
            db.execute('DELETE FROM studio_document_history WHERE project_id=?',(studio.project_id,))
        else:
            current = studio.wb.get_project(studio.project_id)['revision']
            db.execute('INSERT OR REPLACE INTO studio_document_history VALUES (?,?,?)',(studio.project_id,current,_json(before)))
    return {'state':studio.state()}
