import {mergeProjectVersions,sameSavedProject} from './project-version-recovery.js';
import {recoveryKey} from './account-session.js';
const clone = value => structuredClone(value);
export const projectSaveTimeout=bytes=>Math.min(600000,Math.max(120000,Math.ceil(bytes/1024/1024)*8000+30000));
export const uid = () => crypto.randomUUID();
export class ProjectStore {
  savedProject = null; project = null; past = []; future = []; listeners = new Set(); timer = null; saving = false; dirty = false; status = '已保存'; generation = 0; error = null;
  subscribe(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  emit(type='change') { for (const fn of this.listeners) fn(type); }
  load(project) { if(this.dirty)throw Error('当前项目尚未保存，请先重试保存。'); this.project=clone(project);this.savedProject=clone(project); this.past=[]; this.future=[]; this.generation++; this.error=null; this.status='已保存'; this.emit('load'); }
  commit(mutator,label='编辑',silent=false) {
    if(!this.project)return;
    const before=clone(this.project), next=clone(this.project); mutator(next);
    if(JSON.stringify(before)===JSON.stringify(next))return;
    this.past.push({project:before,label}); if(this.past.length>80)this.past.shift();this.future=[];this.project=next;this.mark(silent);
  }
  mark(silent=false){ this.generation++;this.dirty=true;this.error=null;this.status='保存中…';this.backup();clearTimeout(this.timer);this.timer=setTimeout(()=>this.save(),400);this.emit(silent?'quiet':'change'); }
  backup(){try{localStorage.setItem(recoveryKey(this.project.id),JSON.stringify(this.project));}catch{}}
  undo(){if(!this.past.length)return;this.future.push({project:clone(this.project)});const revision=this.project.revision;this.project=this.past.pop().project;this.project.revision=revision;this.mark();}
  redo(){if(!this.future.length)return;this.past.push({project:clone(this.project)});const revision=this.project.revision;this.project=this.future.pop().project;this.project.revision=revision;this.mark();}
  async save(){
    clearTimeout(this.timer);if(this.saving||!this.dirty||!this.project)return;
    this.saving=true;const gen=this.generation,snapshot=clone(this.project);this.status='保存中…';this.emit('status');const serialized=JSON.stringify(snapshot),controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),projectSaveTimeout(new TextEncoder().encode(serialized).byteLength));
    try{
      const path='/api/projects/'+encodeURIComponent(snapshot.id),base=clone(this.savedProject),send=async payload=>{
       const r=await fetch(path,{method:'PUT',headers:{'Content-Type':'application/json','Prefer':'return=minimal'},body:payload===snapshot?serialized:JSON.stringify(payload),signal:controller.signal});
       const result=await r.json();if(!r.ok)throw Object.assign(Error(result.error?.message||result.error||'保存失败，请重试'),{status:r.status});
       return {...clone(payload),revision:result.revision,updatedAt:result.updatedAt};
      },read=async()=>{const r=await fetch(path,{signal:AbortSignal.timeout(5000)});if(!r.ok)throw Object.assign(Error('无法读取项目最新版本。'),{status:r.status});const p=await r.json();if(p.id!==snapshot.id)throw Error('返回的项目不匹配。');return p;};
      let saved,rebased=false;
      try{saved=await send(snapshot);}
      catch(error){
       if(error.status===409){
        const remote=await read(),merged=mergeProjectVersions(base,snapshot,remote);
        if(!merged)throw Object.assign(Error('项目存在不同内容，修改已保留；可比较版本或打开生成结果副本。'),{status:409});
        try{saved=await send(merged);}catch(error){const remote=error.status?null:await read().catch(()=>null);if(!remote||!sameSavedProject(merged,remote))throw error;saved=remote;}rebased=true;
       }else if(!error.status){
        // A lost response may follow an accepted PUT. Confirm this exact snapshot only.
        const remote=await read().catch(()=>null);if(!remote||!sameSavedProject(snapshot,remote))throw error;saved=remote;
       }else throw error;
      }
      if(this.project?.id===snapshot.id){
       if(rebased){
        const replay=mergeProjectVersions(snapshot,this.project,saved);
        if(!replay)throw Object.assign(Error('保存期间又有内容修改，已保留本机副本，请比较版本。'),{status:409});
        this.project=replay;
       }
       this.savedProject=clone(saved);
       this.project.revision=saved.revision;this.project.updatedAt=saved.updatedAt;
       this.dirty=gen!==this.generation;this.status=this.dirty?'保存中…':'已保存';this.error=null;
       if(!this.dirty)localStorage.removeItem(recoveryKey(snapshot.id));else this.backup();
       if(rebased)this.emit('change');
      }
    }catch(e){this.error=e.name==='AbortError'?Error('保存等待超时，修改已保留，请重试。'):e;this.status=e.status===409?'版本冲突 · 点击处理':'保存失败 · 点击重试';this.backup();}
    finally{clearTimeout(timeout);this.saving=false;this.emit('status');if(this.dirty&&!this.error)this.timer=setTimeout(()=>this.save(),0);}
  }
  async flush(){clearTimeout(this.timer);while(this.saving)await new Promise(r=>setTimeout(r,50));if(this.dirty)await this.save();while(this.saving)await new Promise(r=>setTimeout(r,50));if(this.error)throw this.error;if(this.dirty)return this.flush();}
}
export function newProject(title='新的演示稿',themeId='') {return {id:uid(),title,stage:'draft',themeId,designEngine:'svg',pages:[],assets:[],messages:[],revision:0};}
