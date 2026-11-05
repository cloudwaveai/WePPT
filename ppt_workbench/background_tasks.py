"""Durable reference-style workflow; browser lifetime never owns execution."""
import json
import uuid
from .core import EngineError, _json, _now
from . import owners


def initialize(studio):
    with studio.wb._connection() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS studio_background_tasks (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL,
          status TEXT NOT NULL, stage TEXT NOT NULL, payload TEXT NOT NULL,
          result TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')


def state(studio):
    with studio.wb._connection() as db:
        rows=db.execute('SELECT * FROM studio_background_tasks WHERE project_id=? ORDER BY created_at DESC LIMIT 10',(studio.project_id,)).fetchall()
    tasks = [{'id':r['id'],'kind':r['kind'],'status':r['status'],'stage':r['stage'],
             'result':json.loads(r['result']) if r['result'] else None,
             'error':json.loads(r['error']) if r['error'] else None} for r in rows]
    # Preparation completing is not the same as the derived deck completing.
    # Keep its live progress visible from the source document too.
    with studio.wb._connection() as db:
        for task in tasks:
            target = (task['result'] or {}).get('projectId')
            if not target:
                continue
            # Read the already initialized owner table directly. The generic
            # visibility helper initializes tables with executescript, which
            # commits active SQLite savepoints on Python 3.11.
            owner = owners.current()
            target_owner = db.execute('SELECT owner FROM studio_project_owners WHERE project_id=?',(target,)).fetchone()
            if owner is not None and target_owner and target_owner['owner'] != owner:
                continue
            deck = db.execute('SELECT id,status,last_error FROM studio_decks WHERE project_id=?',(target,)).fetchone()
            if deck:
                pages = db.execute('SELECT status FROM studio_deck_pages WHERE deck_id=?',(deck['id'],)).fetchall()
                done = sum(p['status']=='complete' for p in pages)
                labels = {'running':'改版中','complete':'改版稿已生成，待检查','blocked':'改版未完成',
                          'paused':'改版已暂停','cancelled':'改版已取消','waiting_answer':'等待补充资料'}
                task['stage'] = f"{labels.get(deck['status'],'改版准备中')} · {done}/{len(pages)} 页"
                if deck['last_error']:
                    error = json.loads(deck['last_error'])
                    task['stage'] += '：' + error.get('message','请打开草稿查看')
            else:
                job = db.execute('SELECT status FROM studio_jobs WHERE project_id=? ORDER BY created_at DESC LIMIT 1',(target,)).fetchone()
                task['stage'] = '改版准备未完成，请打开草稿查看' if job and job['status']=='failed' else '正在组织改版内容'
    return tasks


def submit_style(studio, template_id, revision):
    from .user_templates import _get, _vision_mode
    from .model_profiles import selected
    row=_get(studio,template_id,'style')
    if not json.loads(row['body']).get('profile') and not _vision_mode(studio)[2]:
        raise EngineError('TEMPLATE_NEEDS_VISION','当前模型不能读取图片，请切换支持看图的模型。')
    with studio.wb.atomic() as db:
        studio.wb._revision(studio.wb.get_project(studio.project_id)['revision'],revision)
        existing=db.execute("SELECT id FROM studio_background_tasks WHERE project_id=? AND status IN ('queued','running')",(studio.project_id,)).fetchone()
        if existing:return {'taskId':existing['id'],'state':studio.state()}
        if db.execute("SELECT 1 FROM studio_jobs WHERE project_id=? AND status IN ('queued','running')",(studio.project_id,)).fetchone():
            raise EngineError('DOCUMENT_BUSY','当前稿件仍在生成；完成后可统一改版。')
        tid='W-'+uuid.uuid4().hex
        db.execute('INSERT INTO studio_background_tasks VALUES (?,?,?,?,?,?,?,?,?,?)',(tid,studio.project_id,'style','queued','等待处理',_json({'templateId':template_id,'projectRevision':revision,'modelBinding':selected(studio),'agentMode':studio.agent_mode}),None,None,_now(),_now()))
        studio._touch(db)
    return {'taskId':tid,'state':studio.state()}


def recover(studio):
    with studio.wb.atomic() as db:
        rows=db.execute("SELECT id FROM studio_background_tasks WHERE project_id=? AND status='running'",(studio.project_id,)).fetchall()
        for row in rows:
            db.execute("UPDATE studio_background_tasks SET status='failed',stage=?,error=?,updated_at=? WHERE id=?",('处理被中断',_json({'code':'WORKFLOW_INTERRUPTED','message':'服务已重启，原稿保留。请查看草稿后重新发起改版。'}),_now(),row['id']))
        if rows:studio._touch(db)


def run_pending(studio):
    with studio.wb.atomic() as db:
        row=db.execute("SELECT * FROM studio_background_tasks WHERE project_id=? AND status='queued' ORDER BY created_at LIMIT 1",(studio.project_id,)).fetchone()
        if not row:return None
        tid=row['id'];payload=json.loads(row['payload'])
        db.execute("UPDATE studio_background_tasks SET status='running',stage='读取参考风格',updated_at=? WHERE id=?",(_now(),tid));studio._touch(db)
    marker=owners.set_scoped(owners.project_owner(studio.wb,studio.project_id))
    result={}
    try:
        from .model_profiles import selected
        def check_model():
            if 'modelBinding' in payload and (selected(studio)!=payload['modelBinding'] or studio.agent_mode!=payload['agentMode']):
                raise EngineError('MODEL_PROFILE_CHANGED','任务的模型选择已变化，未改用其他模型。参考图与原稿保留，请重新发起改版。')
        check_model()
        from .user_templates import _get, analyze_style, select_style
        row=_get(studio,payload['templateId'],'style')
        if not json.loads(row['body']).get('profile'):analyze_style(studio,payload['templateId'])
        # Expensive analysis runs outside the transaction. Reject stale source before deriving.
        with studio.wb.atomic() as db:
            check_model()
            studio.wb._revision(studio.wb.get_project(studio.project_id)['revision'],payload['projectRevision'])
            has_pages=bool(studio.state()['slides'])
            if not has_pages:
                select_style(studio,payload['templateId'])
        if has_pages:
            from .derived import derive
            result=derive(studio,'restyle',style_id=payload['templateId'],source_revision=payload['projectRevision'])
            stage='改版稿已进入后台生成'
        else:
            result={'styleId':payload['templateId']};stage='风格已就绪'
        with studio.wb.atomic() as db:
            db.execute("UPDATE studio_background_tasks SET status='complete',stage=?,result=?,updated_at=? WHERE id=?",(stage,_json(result),_now(),tid));studio._touch(db)
    except Exception as exc:
        if not isinstance(exc,EngineError):
            import logging
            logging.getLogger(__name__).exception('Reference workflow %s failed',tid)
        error=exc.to_dict() if isinstance(exc,EngineError) else {'code':'WORKFLOW_FAILED','message':'改版准备未完成，原稿保留。请重试或查看服务日志。'}
        with studio.wb.atomic() as db:
            db.execute("UPDATE studio_background_tasks SET status='failed',stage='未完成',error=?,updated_at=? WHERE id=?",(_json(error),_now(),tid));studio._touch(db)
    finally:owners.reset(marker)
    return result or {}


def project_activity(wb, project_id):
    with wb._connection() as db:
        task=db.execute("SELECT status FROM studio_background_tasks WHERE project_id=? AND status IN ('queued','running') LIMIT 1",(project_id,)).fetchone()
        if task:return '准备改版中' if task['status']=='running' else '等待改版'
        job=db.execute("SELECT status FROM studio_jobs WHERE project_id=? AND status IN ('queued','running') ORDER BY created_at LIMIT 1",(project_id,)).fetchone()
        if job:return '生成中' if job['status']=='running' else '排队中'
        last=db.execute('SELECT status FROM studio_jobs WHERE project_id=? ORDER BY created_at DESC LIMIT 1',(project_id,)).fetchone()
        if last and last['status']=='failed':return '未完成'
    return '已保存'
