"""Server-owned model profiles; public clients select IDs, never credentials or URLs."""
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from .core import EngineError


def profiles():
    path=os.environ.get('WEPPT_MODEL_PROFILES_FILE')
    if not path:
        return {}
    try:
        raw=Path(path).read_bytes()
        if len(raw)>65536:raise ValueError
        entries=json.loads(raw)
        if not isinstance(entries,list) or len(entries)>40:raise ValueError
        result={}
        for p in entries:
            if not isinstance(p,dict) or set(p)-{'id','label','mode','model','base_url','key_env','max_tokens','vision'}:raise ValueError
            if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',p['id']) or p['id'] in result:raise ValueError
            if not isinstance(p['label'],str) or not 1<=len(p['label'])<=100:raise ValueError
            if p['mode'] not in ('codex','claude','api') or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:-]{0,127}',p['model']):raise ValueError
            if p['mode'] in ('claude','api'):
                url=urlsplit(p['base_url'])
                if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment:raise ValueError
                if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,100}',p['key_env']):raise ValueError
            if type(p.get('max_tokens',8192)) is not int or not 256<=p.get('max_tokens',8192)<=32768:raise ValueError
            if type(p.get('vision',False)) is not bool:raise ValueError
            result[p['id']]=p
        return result
    except (OSError,ValueError,TypeError,KeyError):
        raise EngineError('MODEL_CONFIG_INVALID','服务器模型配置无效，请检查配置。') from None


def binding(profile):
    return {k:profile[k] for k in ('id','label','mode','model')}


def resolve(saved):
    if not isinstance(saved,dict):raise EngineError('MODEL_NOT_CONFIGURED','请选择已配置的模型。')
    p=profiles().get(saved.get('id'))
    if not p or any(saved.get(k)!=p[k] for k in ('mode','model')):
        raise EngineError('MODEL_PROFILE_CHANGED','这项任务的模型配置已变更；未改用其他模型。')
    return p


def availability(p):
    from .agent_bridge import diagnose
    ready=(bool(os.environ.get(p.get('key_env',''))) if p['mode'] in ('claude','api') else True)
    if p['mode']!='api':ready=ready and diagnose(p['mode'])['available']
    return {**binding(p),'available':bool(ready),'vision':p['mode']=='codex' or bool(p.get('vision'))}


def initialize(studio):
    with studio.wb._connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS studio_model_selection (project_id TEXT PRIMARY KEY, profile_id TEXT)')
        db.execute('INSERT OR IGNORE INTO studio_model_selection VALUES (?,NULL)',(studio.project_id,))


def selected(studio):
    with studio.wb._connection() as db:
        row=db.execute('SELECT profile_id FROM studio_model_selection WHERE project_id=?',(studio.project_id,)).fetchone()
    if not row or not row[0]:return None
    p=profiles().get(row[0])
    if not p:return {'id':row[0],'label':'所选模型已移除','mode':studio.agent_mode,'model':'unavailable'}
    return binding(p)


def select(studio,profile_id):
    p=profiles().get(profile_id) if isinstance(profile_id,str) else None
    if not p:raise EngineError('MODEL_NOT_CONFIGURED','请选择服务器已配置的模型。')
    if not availability(p)['available']:raise EngineError('MODEL_UNAVAILABLE','这个模型的客户端或密钥尚未配置。')
    with studio.wb.atomic() as db:
        if db.execute("SELECT 1 FROM studio_jobs WHERE project_id=? AND status IN ('queued','running') LIMIT 1",(studio.project_id,)).fetchone():
            raise EngineError('MODEL_BUSY','当前任务尚未完成，请完成或停止后再切换模型。')
        studio.set_agent_mode(p['mode'])
        db.execute('UPDATE studio_model_selection SET profile_id=? WHERE project_id=?',(p['id'],studio.project_id))
        studio._touch(db)
    return studio.state()


def public_state(studio):
    chosen=selected(studio)
    return {'selectedModelProfile':chosen,'modelProfiles':[availability(p) for p in profiles().values()]}
