import {createAudienceWorkflow} from './audience-review.js';
import {sameAudienceBranch} from './audience-branch.js';
import {completedReferenceExport} from './reference-delivery.js';
import {isPrecompiledTheme} from './template-blueprints.js';
import {checkPrecompiledLayout} from './precompiled-layout-check.js';
import {recoveryKey} from './account-session.js';
import {createReferenceGeneration} from './reference-generation.js';
import {generationTasks} from './generation-tasks.js';
import {requestImageAssistant} from './image-assistant-request.js';
import {validateImageEdit,resolveImageTarget} from './image-assistant-result.js';
import {designImageProject} from './image-design-pipeline.js';
import {createConstrainedPage as createInheritedPage,inheritedCopyFits} from './inherited-page.js';
import {createThemePreview,applyThemePreview,previewFingerprint,selectPreviewPageIds,combinePreviewReview} from './theme-preview.js';
import {readPreviewCache,writePreviewCache} from './preview-cache.js';
import {updateSvgCopy} from './svg-copy.js';
import {designSvgProject} from './svg-design-pipeline.js';
import {validateDesignAction} from './assistant-actions.js';
import {ProjectStore,newProject,uid} from './store.js';
import {loadTemplates,getTemplates,getTheme,layoutDeck,layoutPage,inferRole} from './templates.js';
import {mountEditor} from './editor.js';
import {validateOperations,applyOperations} from './ai-operations.js';
import {designProject,reviewProject} from './design-pipeline.js';
import {renderMini} from './templates.js';
import {layoutPlannedPage} from './planned-layout.js';
import {snapshotPage} from './design-audit.js';
let draftRequestController=null,draftStartedAt=0,draftWaitTimer=null;
let reviseWait=null,reviseTimer=null,reviseController=null;
const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const store=new ProjectStore();let view='home',editor=null,homeText='',selectedTheme='',themeCategory='全部',materials=[],nextEditorAiDraft='',nextEditorAiScope='page',busy=false,uploading=0,selectedPageId='',draftScope='page',draftChat='',toastTimer,renderQueued=false,aiStatus={available:false,label:'正在连接 AI…'};
const generation=generationTasks({store,renderMini,onOpenProject:loadProject,onStop:()=>designController?.abort(),onOpenDrafts:openPreviewDrafts,onShowPage:pageId=>{if(store.project.stage==='editor'){view='editor';render({pageId});}}});
const referenceGeneration=createReferenceGeneration({store,request,contentProject,generation,onOpenProject:loadProject,isBusy:()=>busy||!!designController,setBusy:setDesignBusy,setController:c=>designController=c,onProgress:designProgress,onApplied:pageId=>{view='editor';render({pageId});},onApplicationConflict:applicationConflictDialog,onOpenGeneratedCopy:openGeneratedCopy,notify});
const roleNames={cover:'封面',toc:'目录',content:'内容',data:'数据',flow:'流程',chapter:'章节',ending:'结束'};
function notify(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,5500);}
async function request(path,body,signal,method){const r=await fetch(path,{method:method||(body===undefined?'GET':'POST'),headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal});const contentType=r.headers.get('content-type')||'';let data;if(contentType.includes('json')){try{data=await r.json();}catch{throw Object.assign(Error(`接口 ${path} 返回了无法读取的数据（HTTP ${r.status}），请刷新后重试。`),{status:r.status});}}else{const responseText=await r.text();const loginPage=/(?:<!doctype html|<html)/i.test(responseText)&&/(?:登录|login)/i.test(responseText);const html=/(?:<!doctype html|<html)/i.test(responseText)||contentType.includes('text/html');const message=loginPage?'登录状态可能已过期，请重新登录后再试。':html?`接口 ${path} 返回了网页而不是数据（HTTP ${r.status}），请刷新后重试。`:`接口 ${path} 返回了非 JSON 数据（HTTP ${r.status}），请刷新后重试。`;throw Object.assign(Error(message),{status:r.status});}if(!r.ok)throw Object.assign(Error(typeof data?.error==='string'?data.error:data?.error?.message||data?.message||'请求未完成，请重试'),{status:r.status});return data;}
function dialog(html){themePreviewClose?.();const m=$('#modal');$('#modal-content').innerHTML=html;if(!m.open)m.showModal();$('#modal-content').querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>m.close());return m;}
const modalHead=title=>`<div class="modal-head"><h2>${esc(title)}</h2><button data-close aria-label="关闭">×</button></div>`;
function applicationConflictDialog({message,openCopy}){
 return new Promise(resolve=>{
  const modal=dialog(`${modalHead('生成已完成，选择打开方式')}<p class="manual-help">${esc(message)}</p><p id="application-copy-error" class="manual-help" role="status"></p><div class="modal-actions"><button id="keep-current">保留当前稿</button><button id="open-result-copy" class="primary">打开生成结果副本</button></div>`);
  let pending=false;const copyButton=$('#open-result-copy'),keep=$('#keep-current');
  modal.addEventListener('cancel',event=>{if(pending)event.preventDefault();});
  modal.addEventListener('close',()=>resolve(null),{once:true});keep.onclick=()=>modal.close();
  copyButton.onclick=async()=>{if(pending)return;pending=true;copyButton.disabled=keep.disabled=true;copyButton.textContent='正在保存副本…';
   try{const saved=await openCopy();modal.close();resolve(saved);}catch(error){$('#application-copy-error').textContent=error.message;}
   finally{pending=false;copyButton.disabled=keep.disabled=false;copyButton.textContent='打开生成结果副本';}
  };
 });
}
async function openGeneratedCopy(project){
 // The original's unsaved state remains recoverable under its own account/project key.
 try{await store.flush();}catch{store.backup();}
 if(store.dirty)store.backup();clearTimeout(store.timer);store.dirty=false;store.error=null;
 store.load(project);reviseWait=null;selectedTheme=project.themeId;view='editor';history.replaceState(null,'','/?project='+encodeURIComponent(project.id));render();
}
function header(){generation.refresh();referenceGeneration.renderRecovery();const p=store.project;$('#preview-drafts')?.removeAttribute('hidden');$('#project-title').value=p?.title||'新的演示稿';$('#project-title').disabled=!p;$('#save-status').textContent=p?store.status:'';$('#save-status').title=store.error?.message||store.status;$('#export').hidden=view!=='editor';$('#open-demo').hidden=view!=='home';$('#model-status').textContent=aiStatus.label||aiStatus.model||'AI 未连接';$('#model-status').classList.toggle('unavailable',!aiStatus.available);$('#model-status').title=aiStatus.message||'本地编辑无需等待 AI';}
store.subscribe(type=>{header();if(type==='status'||type==='quiet')return;if(view==='editor'&&editor){if(!renderQueued){renderQueued=true;requestAnimationFrame(()=>{renderQueued=false;editor?.render();});}}});
window.addEventListener('beforeunload',e=>{if(store.dirty||designController){if(store.dirty)store.backup();e.preventDefault();e.returnValue='';}});
function normalizedPages(pages){const used=new Set();return pages.map((p,i)=>{const id=typeof p.id==='string'&&/^[\w-]{1,100}$/.test(p.id)&&!used.has(p.id)?p.id:uid();used.add(id);return {id,title:String(p.title||`第 ${i+1} 页`),body:String(p.body||''),role:Object.hasOwn(roleNames,p.role)?p.role:inferRole(p.title||'',p.body||'',i),variant:0,background:'#fff',objects:[]};});}
function editFingerprint(scope,pageId,objectIds=[]){const pages=store.project.pages;if(scope==='deck')return JSON.stringify(pages);const page=pages.find(p=>p.id===pageId);return JSON.stringify(scope==='object'?{id:page?.id,objects:page?.objects.filter(o=>objectIds.includes(o.id))}:page);}
function contentProject(){const p=structuredClone(store.project);delete p.previewDrafts;delete p.generationDrafts;p.pages=p.pages.map(page=>{if(!page.objects?.length)return page;const synced=layoutPage(page,p.themeId,page.variant||0);return {...page,title:synced.title,body:synced.body};});return p;}

function render(options={}){editor?.destroy();editor=null;header();if(view==='home')renderHome();else if(view==='draft')renderDraft();else{const host=$('#app');host.replaceChildren();editor=mountEditor(host,{initialPageId:options.pageId,initialAiDraft:nextEditorAiDraft,initialAiScope:nextEditorAiScope,getProject:()=>store.project,commit:(fn,label)=>store.commit(fn,label),notify,onBack:()=>{const synced=contentProject();store.commit(p=>{p.pages=synced.pages;p.stage='draft';},'返回文案讨论');view='draft';render();},onExport:exportProject,onDesign:runDesignedLayout,onThemePreview:openThemePreview,onReview:runDeckReview,onForkAudience:createAudienceVersion,onAI:editorAI,onAssets:uploadAssets,onExtractArtwork:extractPageArtwork,onImportDesign:importDesignFiles,undo:()=>store.undo(),redo:()=>store.redo(),canUndo:()=>!!store.past.length,canRedo:()=>!!store.future.length});nextEditorAiDraft='';nextEditorAiScope='page';editor.render();}}
function renderHome(){
  if(!busy)reviseWait=null;
  $('#app').innerHTML=`<section class="home-page"><h1>今天，想做一份什么 PPT？</h1><div class="home-composer"><textarea id="home-prompt" aria-label="PPT 需求" placeholder="你可以直接描述想做的 PPT，也可以粘贴已有文案，或通过「添加材料」上传参考资料。&#10;&#10;建议告诉我：这份 PPT 用来做什么、给谁看、重点讲哪些内容，以及大概需要多少页。暂时没想清楚也没关系，我们可以一起讨论。">${esc(homeText)}</textarea><div id="selected-theme" class="selected-theme" hidden></div><div id="materials" class="material-list"></div><div class="composer-actions"><button id="add-material" class="material-button"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m9 12 6-6a3 3 0 0 1 4 4l-8 8a5 5 0 0 1-7-7l9-9"/></svg>添加材料</button><button id="send-home" class="primary">发送</button></div><p class="attachment-help">Word / PPT / PDF / 图片 · 也可直接粘贴文字</p><div id="home-status" class="busy-line" role="status"></div><button id="cancel-draft" class="quiet" hidden>停止整理</button></div><p class="home-hint"><span>先选模板，再说需求；也可以直接开始。</span> <button id="manual-start" class="quiet">已有文案，直接整理</button></p><div class="templates-heading"><div><h2>精选模板 · 风格参考</h2><p>包含封面与内容页，先看看不同模板的视觉风格。</p></div></div><div id="theme-categories" class="theme-categories" role="group" aria-label="模板分类"></div><p id="theme-results" class="theme-results" role="status"></p><div id="home-themes" class="theme-grid"></div><div class="home-bottom"><button id="demo">体验可编辑示例</button></div></section>`;
  $('#cancel-draft').onclick=()=>draftRequestController?.abort();$('#home-prompt').oninput=e=>homeText=e.target.value;$('#send-home').onclick=startAI;$('#add-material').onclick=()=>$('#material-input').click();$('#manual-start').onclick=manualDialog;$('#demo').onclick=openDemo;renderThemes();renderMaterials();setHomeStatus();
}
function renderSelectedTheme(){
 const host=$('#selected-theme');if(!host)return;const theme=selectedTheme?getTheme(selectedTheme):null;host.hidden=!theme;
 if(!theme){host.replaceChildren();return;}
 host.innerHTML=`<img src="${esc(theme.cover)}" alt="${esc(theme.name)}缩略图"><div class="selected-theme-copy"><small>已选模板</small><strong id="theme-choice">${esc(theme.name)}</strong></div><button id="change-theme" type="button">更换</button><button id="remove-theme" type="button" aria-label="移除已选模板" title="移除已选模板">×</button>`;
 $('#change-theme').onclick=themeChooser;$('#remove-theme').onclick=()=>{selectedTheme='';renderThemes();};
}
let homeThemeObserver=null;
function renderThemes(){
 homeThemeObserver?.disconnect();
 const q=$('#theme-search')?.value?.trim().toLowerCase()||'',all=getTemplates();
 const categories=['全部',...new Set(all.map(t=>t.category).filter(Boolean))];
 $('#theme-categories').innerHTML=categories.map(c=>`<button type="button" data-category="${esc(c)}" aria-pressed="${c===themeCategory}">${esc(c)}<span>${c==='全部'?all.length:all.filter(t=>t.category===c).length}</span></button>`).join('');
 $('#theme-categories').querySelectorAll('button').forEach(b=>b.onclick=()=>{themeCategory=b.dataset.category;renderThemes();$('#theme-categories').querySelectorAll('button').forEach(n=>{if(n.dataset.category===themeCategory)n.focus({preventScroll:true});});});
 const list=all.filter(t=>(themeCategory==='全部'||t.category===themeCategory)&&`${t.name} ${t.category} ${t.reason||''} ${t.description||''}`.toLowerCase().includes(q));
 $('#theme-results').textContent=`${themeCategory==='全部'?'全部模板':themeCategory} · ${list.length} 套${q?'匹配结果':''}`;
 $('#home-themes').innerHTML=list.map(t=>`<button class="theme-card ${selectedTheme===t.id?'selected':''}" data-theme="${esc(t.id)}"><img data-cover="${esc(t.cover)}" alt="${esc(t.name)}封面" decoding="async" fetchpriority="low"><strong>${esc(t.name)}</strong><small>${esc(t.category||'设计参考')}</small></button>`).join('')||'<p class="empty-state">没有匹配的模板，试试其他分类或关键词。</p>';
 // Load only visible covers so offscreen previews do not compete with project reads.
 homeThemeObserver=new IntersectionObserver(entries=>{for(const entry of entries){if(!entry.isIntersecting)continue;const img=entry.target;img.src=img.dataset.cover;homeThemeObserver.unobserve(img);}}, {rootMargin:'0px'});
 $('#home-themes').querySelectorAll('img[data-cover]').forEach(img=>homeThemeObserver.observe(img));
 $('#home-themes').querySelectorAll('[data-theme]').forEach(b=>b.onclick=()=>themeDialog(b.dataset.theme));renderSelectedTheme();
}

function themeDialog(id){const t=getTheme(id);if(!t)return;dialog(`${modalHead(t.name)}<p class="theme-description">${esc(t.reason||t.description||'参考这套模板的配色、层次和视觉语言，按你的文案重新排版。')}</p><div class="theme-previews">${(t.previews?.length?t.previews:[t.cover]).map((src,i)=>`<img src="${esc(src)}" alt="${esc(t.name)}参考页面 ${i+1}" loading="lazy">`).join('')}</div><div class="modal-actions"><button data-close>再看看</button><button id="choose-theme" class="primary">使用这套风格</button></div>`);$('#choose-theme').onclick=()=>{selectedTheme=id;if(store.project&&view==='draft')store.commit(p=>p.themeId=id,'选择整套风格');$('#modal').close();if(view==='home'){renderThemes();$('.home-composer').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'center'});$('#home-prompt').focus({preventScroll:true});}else if(view==='draft')renderDraft();};}
function themeChooser(){dialog(`${modalHead('选择整套风格')}<div class="theme-grid">${getTemplates().map(t=>`<button class="theme-card" data-theme="${esc(t.id)}"><img src="${esc(t.cover)}" alt="${esc(t.name)}" loading="lazy"><strong>${esc(t.name)}</strong></button>`).join('')}</div>`);$('#modal-content').querySelectorAll('[data-theme]').forEach(b=>b.onclick=()=>themeDialog(b.dataset.theme));}
function renderMaterials(){if(!$('#materials'))return;$('#materials').innerHTML=materials.map((m,i)=>`<div class="material-chip"><span>${esc(m.name)}</span><button data-remove-material="${i}" aria-label="移除 ${esc(m.name)}">×</button></div>`).join('');$('#materials').querySelectorAll('button').forEach(b=>b.onclick=()=>{materials.splice(+b.dataset.removeMaterial,1);renderMaterials();});}
function setHomeStatus(message='',error=false){if(!$('#home-status'))return;$('#home-status').textContent=message||(busy?`GPT-6.1 Sol 正在整理逐页文案 · 已等待 ${Math.floor((Date.now()-draftStartedAt)/1000)} 秒${Date.now()-draftStartedAt>60000?'。耗时较长，可继续等待或停止整理。':''}`:uploading?'正在读取材料…':'');$('#home-status').classList.toggle('error',error);$('#cancel-draft').hidden=!busy;$('#send-home').disabled=busy||uploading>0;$('#add-material').disabled=busy;$('#manual-start').disabled=busy;}
async function fileData(file){return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=()=>reject(Error('文件读取失败'));r.readAsDataURL(file);});}
$('#material-input').onchange=async e=>{const files=[...e.target.files];e.target.value='';const originals=files.filter(file=>/\.(pptx|pdf)$/i.test(file.name));if(originals.length){if(files.length!==1){notify('请单独选择一份原稿 PPT 或 PDF；其他材料可之后添加。');return;}try{await importOriginalPresentation(originals[0]);}catch(error){notify(error.message||'原稿导入失败，当前内容保持不变。');}return;}uploading+=files.length;setHomeStatus();for(const file of files){try{if(file.size>20*1024*1024)throw Error(`${file.name} 超过 20 MB`);const result=await request('/api/materials',{name:file.name,data:await fileData(file),mime:file.type});materials.push(result);renderMaterials();}catch(err){notify(err.message);}finally{uploading--;setHomeStatus();}}};
async function uploadAssets(files,kind='image'){const owner=store.project?.id;if(!owner)throw Error('请先打开项目');uploading++;try{const results=[];for(const file of Array.from(files)){if(file.size>20*1024*1024)throw Error('单张图片请小于 20 MB');const asset=await request('/api/assets',{name:file.name,data:await fileData(file),mime:file.type,kind});results.push({...asset,kind});}if(store.project?.id!==owner)throw Error('项目已切换，素材未插入其他项目');store.commit(p=>p.assets.push(...results),'上传素材');return results;}finally{uploading--;}}

async function createProject(p){for(const m of p.materials||[]){if(m.src&&!p.assets.some(a=>a.id===m.id))p.assets.push({id:m.id||uid(),name:m.name,src:m.src,kind:m.kind==='logo'?'logo':'image'});}await store.flush();store.load(p);store.dirty=true;store.backup();await store.flush();history.replaceState(null,'','/?project='+encodeURIComponent(p.id));}
function createAudienceVersion(){audienceWorkflow.open();}
const audienceWorkflow=createAudienceWorkflow({store,dialog,request,notify,renderPage:renderMini,isBusy:()=>busy||!!designController,onConfirmed:async(branch,source)=>{
 await store.flush();
 if(store.project?.id!==source.id)throw Error('当前原稿已切换，请重新打开改编方案。');
 let saved;
 try{saved=await request('/api/projects/'+encodeURIComponent(branch.id),branch,undefined,'PUT');}
 catch(error){try{const existing=await request('/api/projects/'+encodeURIComponent(branch.id));if(sameAudienceBranch(existing,branch))saved=existing;}catch{}if(!saved)throw error;}
 if(store.project?.id!==source.id){notify('新版本已保存，可在“我的项目”中打开。');return;}
 store.load(saved);selectedTheme=saved.themeId;view='editor';selectedPageId=saved.pages[0]?.id||'';nextEditorAiDraft='';nextEditorAiScope='page';history.replaceState(null,'','/?project='+encodeURIComponent(saved.id));render();notify('已沿用原稿设计保存新版本。顶部“改动清单”可回看增删改、调序和设计来源。');
}});
async function startAI(){
  if(busy||uploading)return;if(!homeText.trim()&&!materials.length){$('#home-prompt').focus();notify('先写下想做的内容，或添加一份材料。');return;}
  busy=true;draftStartedAt=Date.now();draftRequestController=new AbortController();draftWaitTimer=setInterval(()=>setHomeStatus(),1000);setHomeStatus();const prompt=homeText.trim()||'请根据材料整理逐页演示文稿，保留事实，不添加未经提供的数据。';
  try{const p=newProject(prompt.slice(0,32),selectedTheme||getTemplates()[0]?.id);p.materials=structuredClone(materials);p.messages=[{role:'user',text:prompt,scope:'deck'}];await createProject(p);const owner=p.id;const result=await request('/api/ai',{action:'draft',message:prompt,project:store.project,materials,themeId:p.themeId},draftRequestController.signal);if(store.project.id!==owner)return;if(!Array.isArray(result.pages)||!result.pages.length)throw Error('AI 没有返回逐页文案，请补充需求后重试。');store.commit(d=>{d.pages=normalizedPages(result.pages);d.messages.push({role:'assistant',text:result.message||'逐页文案已整理，可以继续讨论或直接修改。',scope:'deck'});},'生成文案');view='draft';selectedPageId=store.project.pages[0].id;render();}
  catch(e){const message=e.name==='AbortError'?'已停止整理，需求和材料仍保留，可修改后重新发送。':e.message;setHomeStatus(message,true);notify(message);}finally{clearInterval(draftWaitTimer);draftRequestController=null;busy=false;setHomeStatus($('#home-status')?.textContent||'',$('#home-status')?.classList.contains('error'));if($('#draft-send'))$('#draft-send').disabled=false;if($('#start-layout'))$('#start-layout').disabled=false;}
}
function parseOutline(text){const lines=text.replace(/\r/g,'').split('\n');const groups=[];let current=null;for(const line of lines){const heading=line.match(/^\s*(?:#\s+|第\s*\d+\s*页[：:\s]*|\d+[.、]\s*)(.+)$/);if(heading){if(current)groups.push(current);current={title:heading[1].trim(),body:''};}else if(/^\s*---+\s*$/.test(line)){if(current){groups.push(current);current=null;}}else if(!current&&line.trim())current={title:line.trim(),body:''};else if(current)current.body+=(current.body?'\n':'')+line;}if(current)groups.push(current);return normalizedPages(groups.map(p=>({...p,body:p.body.trim()})));}
function manualDialog(){dialog(`${modalHead('整理已有文案')}<p class="manual-help">每页以「# 标题」开头，下面填写正文。这里保留原文，不调用 AI；确认后仍可以讨论和修改。</p><textarea class="manual-outline" id="manual-outline" aria-label="逐页文案" placeholder="# 封面标题\n演示副标题\n\n# 目录\n第一部分\n第二部分\n\n# 第一页内容\n正文…">${esc(homeText)}</textarea><div class="modal-actions"><button data-close>取消</button><button id="manual-confirm" class="primary">进入文案确认</button></div>`);$('#manual-confirm').onclick=async()=>{if($('#manual-confirm').disabled)return;const pages=parseOutline($('#manual-outline').value);if(!pages.length){notify('请先填写文案。');return;}try{$('#manual-confirm').disabled=true;const p=newProject(pages[0].title,selectedTheme||getTemplates()[0]?.id);p.pages=pages;p.materials=structuredClone(materials);await createProject(p);$('#modal').close();view='draft';selectedPageId=pages[0].id;render();}catch(e){notify(e.message);}};}
async function openDemo(){if(busy||uploading){notify('请等待当前请求完成。');return;}try{const p=newProject('从想法，到可以自由编辑的页面',selectedTheme||getTemplates()[0]?.id);p.pages=normalizedPages([{title:'让想法，成为看得见的表达',body:'WePPT 可编辑示例\n先讨论内容，再一起打磨每一页。',role:'cover'},{title:'这份演示，分三步完成',body:'讨论文案与结构\n选择适合内容的布局\n自由编辑与导出',role:'toc'},{title:'每一次修改，都在你掌握中',body:'直接编辑\n文字、图片、图形都是独立对象，拖动即可调整位置。\n\n保留你的内容\n更换布局时保留文案，也能随时撤销回到上一版。\n\n继续讨论\n选中一页或一个对象，让 AI 有针对性地修改。',role:'content'},{title:'从需求到演示的工作流程',body:'输入需求 → 讨论文案 → 确认排版 → 自由编辑 → 导出 PPTX',role:'flow'},{title:'现在，轮到你的想法',body:'双击修改文字，试着拖动一个对象。\n这是演示内容，可以放心编辑。',role:'ending'}]);p.pages=layoutDeck(p.pages,p.themeId);p.stage='editor';p.demo=true;await createProject(p);view='editor';render();}catch(e){notify(e.message);}}
function currentPage(){return store.project?.pages.find(p=>p.id===selectedPageId)||store.project?.pages[0];}
function renderDraft(){const project=store.project;if(!project){view='home';render();return;}const p=currentPage();selectedPageId=p?.id||'';$('#app').innerHTML=`<section class="draft-shell"><div class="draft-document"><div class="draft-document-head"><div><h1>先把内容，讨论清楚</h1><p>直接修改逐页文案，或让右侧 AI 帮你调整。</p></div><div class="draft-head-actions"><button id="draft-import-original">导入原稿 PPT/PDF，沿用原页</button><input id="draft-original-file" type="file" accept=".pptx,.pdf" hidden><button id="draft-add">＋ 添加页面</button></div></div><details class="draft-outline"><summary>文稿目录 · ${project.pages.length} 页</summary><nav>${project.pages.map((p,i)=>`<button data-jump="${esc(p.id)}">${i+1}. ${esc(p.title)}</button>`).join('')}</nav></details>${!project.pages.some(p=>p.role==='toc')?'<button id="add-toc" class="quiet">＋ 补入目录页</button>':''}<div id="draft-pages">${project.pages.map((p,i)=>`<article class="draft-page ${p.id===selectedPageId?'selected':''}" data-page="${esc(p.id)}"><div class="draft-page-head"><span>第 ${String(i+1).padStart(2,'0')} 页</span><span class="role-label">${roleNames[p.role]||'内容'}</span><div class="page-actions"><button data-up="${esc(p.id)}" ${i===0?'disabled':''}>上移</button><button data-down="${esc(p.id)}" ${i===project.pages.length-1?'disabled':''}>下移</button><details class="page-insert"><summary aria-label="插入页面">插入</summary><div class="page-insert-options"><button data-insert="${esc(p.id)}" data-position="before">上方插入</button><button data-insert="${esc(p.id)}" data-position="after">下方插入</button></div></details><button data-delete="${esc(p.id)}">删除</button></div></div><input class="draft-page-title" data-title="${esc(p.id)}" aria-label="第 ${i+1} 页标题" value="${esc(p.title)}"><div class="draft-body-preview" data-preview="${esc(p.id)}" tabindex="0" role="button" aria-label="编辑正文">${bodyPreview(p.body)}</div><div class="draft-body-tools" hidden><button data-heading="${esc(p.id)}">设为小标题</button><button data-done="${esc(p.id)}">完成编辑</button></div><textarea hidden class="draft-page-body" data-body="${esc(p.id)}" aria-label="第 ${i+1} 页正文">${esc(p.body)}</textarea></article>`).join('')||'<p class="draft-empty">添加第一张页面，写下你想表达的内容。</p>'}</div></div><aside class="draft-sidebar"><div class="sidebar-heading">AI 助手</div><div class="draft-theme"><span title="${esc(getTheme(project.themeId)?.name||'未选择')}">整套风格：${esc(getTheme(project.themeId)?.name||'未选择')}</span><button id="draft-theme">更换</button></div><div class="scope-tabs"><button data-scope="deck" class="${draftScope==='deck'?'active':''}">调整整份</button><button data-scope="page" class="${draftScope==='page'?'active':''}">修改当前页</button></div><div class="draft-target"></div><div class="chat-history" id="draft-history"></div><div id="draft-thinking-host"></div><div class="draft-chatbox"><textarea id="draft-message" aria-label="文案修改要求" placeholder="描述想调整的内容，例如：把这一页讲得更简洁，保留关键事实。">${esc(draftChat)}</textarea><div class="composer-actions"><span id="draft-ai-status" class="busy-line" role="status"></span><button id="draft-send" class="primary" ${busy?'disabled':''}>发送</button></div></div><button id="start-layout" class="primary draft-start" ${busy?'disabled':''}>确认文案，开始排版</button></aside></section>`;
  bindDraftStructure();renderReviseWait();
  $('#draft-pages').querySelectorAll('article').forEach(el=>el.addEventListener('focusin',()=>selectDraftPage(el.dataset.page)));
  $('#draft-pages').querySelectorAll('article').forEach(el=>el.addEventListener('click',()=>selectDraftPage(el.dataset.page)));
  $('#draft-pages').querySelectorAll('[data-title]').forEach(el=>el.oninput=()=>{store.commit(d=>d.pages.find(p=>p.id===el.dataset.title).title=el.value,'修改标题',true);const jump=document.querySelector(`[data-jump="${el.dataset.title}"]`);if(jump)jump.textContent=`${store.project.pages.findIndex(p=>p.id===el.dataset.title)+1}. ${el.value}`;updateDraftTarget();});
  $('#draft-pages').querySelectorAll('[data-body]').forEach(el=>{fitTextarea(el);el.oninput=()=>{store.commit(d=>d.pages.find(p=>p.id===el.dataset.body).body=el.value,'修改正文',true);fitTextarea(el);};});
  $('#draft-import-original').onclick=()=>$('#draft-original-file').click();$('#draft-original-file').onchange=async e=>{const file=e.target.files?.[0];e.target.value='';if(!file)return;try{await importOriginalPresentation(file);}catch(error){notify(error.message||'原稿导入失败，当前文稿保持不变。');}};
  $('#draft-add').onclick=()=>addDraftPage();$('#draft-pages').querySelectorAll('[data-insert]').forEach(b=>b.onclick=e=>{e.stopPropagation();addDraftPage(b.dataset.insert,b.dataset.position);});
  $('#draft-pages').querySelectorAll('[data-delete]').forEach(b=>b.onclick=e=>{e.stopPropagation();store.commit(d=>{d.pages=d.pages.filter(p=>p.id!==b.dataset.delete);},'删除页面');renderDraft();});
  for(const direction of ['up','down'])$('#draft-pages').querySelectorAll(`[data-${direction}]`).forEach(b=>b.onclick=e=>{e.stopPropagation();store.commit(d=>{const i=d.pages.findIndex(p=>p.id===b.dataset[direction]),j=i+(direction==='up'?-1:1);if(j>=0&&j<d.pages.length)[d.pages[i],d.pages[j]]=[d.pages[j],d.pages[i]];},'页面排序');renderDraft();});
  $('[data-scope="deck"]').onclick=()=>{draftScope='deck';updateDraftTarget();renderDraftChat();};$('[data-scope="page"]').onclick=()=>{draftScope='page';updateDraftTarget();renderDraftChat();};$('#draft-theme').onclick=themeChooser;$('#draft-message').oninput=e=>draftChat=e.target.value;$('#draft-send').onclick=reviseDraft;$('#draft-message').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();reviseDraft();}};$('#start-layout').onclick=generateLayout;updateDraftTarget();renderDraftChat();}

function bodyPreview(body){return String(body||'').split('\n').map(line=>/^##\s+/.test(line)?`<h3>${esc(line.replace(/^##\s+/,''))}</h3>`:line.trim()?`<p>${esc(line)}</p>`:'<div class="body-gap"></div>').join('')||'<p class="muted">点击填写正文</p>';}
function bindDraftStructure(){
 document.querySelectorAll('.page-insert').forEach(menu=>{menu.addEventListener('toggle',()=>{if(menu.open)document.querySelectorAll('.page-insert').forEach(other=>{if(other!==menu)other.open=false;});});menu.addEventListener('keydown',e=>{if(e.key==='Escape'){menu.open=false;menu.querySelector('summary').focus();e.stopPropagation();}});});

 document.querySelectorAll('[data-jump]').forEach(b=>b.onclick=()=>{selectDraftPage(b.dataset.jump);document.querySelector(`[data-page="${b.dataset.jump}"]`).scrollIntoView({block:'start'});});
 const add=$('#add-toc');if(add)add.onclick=()=>{const pages=store.project.pages.filter(p=>!['cover','toc','ending'].includes(p.role));if(!pages.length){notify('先添加内容页，再补入目录。');return;}const toc=normalizedPages([{title:'目录',role:'toc',body:pages.map(p=>p.title).join('\n')}])[0];store.commit(p=>p.pages.splice(p.pages[0]?.role==='cover'?1:0,0,toc),'补入目录页');selectedPageId=toc.id;renderDraft();};
 document.querySelectorAll('[data-preview]').forEach(preview=>{const id=preview.dataset.preview,area=document.querySelector(`[data-body="${id}"]`),tools=area.previousElementSibling;const open=()=>{preview.hidden=true;tools.hidden=false;area.hidden=false;fitTextarea(area);area.focus();};preview.onclick=open;preview.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open();}};tools.querySelector('[data-done]').onclick=()=>{preview.innerHTML=bodyPreview(area.value);preview.hidden=false;tools.hidden=true;area.hidden=true;};tools.querySelector('[data-heading]').onclick=()=>{const start=area.value.lastIndexOf('\n',area.selectionStart-1)+1;area.value=area.value.slice(0,start)+(area.value.slice(start).startsWith('## ')?area.value.slice(start+3):'## '+area.value.slice(start));area.dispatchEvent(new Event('input'));area.focus();};});
}
function renderReviseWait(){const host=$('#draft-thinking-host');if(!host||!reviseWait)return;let detail=host.querySelector('details');if(!detail){host.innerHTML='<details class="thinking-status"><summary></summary><p>请求已发送，正在等待模型返回修改结果。你可以继续查看和编辑文稿。</p><button type="button">停止修改</button></details>';detail=host.firstElementChild;detail.querySelector('button').onclick=()=>reviseController?.abort();}const seconds=reviseWait.pending?Math.floor((Date.now()-reviseWait.started)/1000):reviseWait.seconds;detail.querySelector('summary').textContent=reviseWait.pending?`思考中 · ${seconds} 秒`:`本次等待 ${seconds} 秒`;detail.querySelector('button').hidden=!reviseWait.pending;if(reviseWait.pending)detail.querySelector('p').textContent='请求已发送，正在等待模型返回修改结果。你可以继续查看和编辑文稿。';if(!reviseWait.pending){detail.open=false;detail.querySelector('p').textContent='本次请求已结束，处理结果见对话。';}}

function fitTextarea(el){el.style.height='auto';el.style.height=Math.max(130,el.scrollHeight)+'px';}
function selectDraftPage(id){if(id===selectedPageId)return;selectedPageId=id;$('#draft-pages').querySelectorAll('article').forEach(e=>e.classList.toggle('selected',e.dataset.page===id));updateDraftTarget();renderDraftChat();}
function updateDraftTarget(){if(!$('.draft-target'))return;const p=currentPage();$('.draft-target').textContent=draftScope==='deck'?`整份文稿 · ${store.project.pages.length} 页`:p?`当前页：${p.title}`:'先添加页面';$('.draft-target').title=$('.draft-target').textContent;document.querySelectorAll('[data-scope]').forEach(b=>b.classList.toggle('active',b.dataset.scope===draftScope));}
function renderDraftChat(){const messages=store.project.messages.filter(m=>draftScope==='deck'?m.scope==='deck':m.pageId===selectedPageId);$('#draft-history').innerHTML=messages.length?messages.map(m=>`<div class="chat-message ${m.role==='user'?'user':''}">${esc(m.text)}</div>`).join(''):'<p class="chat-empty">先确认表达的内容，再决定怎么排版。你可以直接改左侧文字，也可以在这里告诉 AI 你的想法。</p>';$('#draft-history').scrollTop=$('#draft-history').scrollHeight;}
function addDraftPage(anchor,position='after'){const page=normalizedPages([{title:'新的页面',body:'',role:'content'}])[0];store.commit(d=>{const index=anchor?d.pages.findIndex(p=>p.id===anchor)+(position==='before'?0:1):d.pages.length;d.pages.splice(index,0,page);},'添加页面');selectedPageId=page.id;renderDraft();$(`[data-title="${page.id}"]`).focus();}
async function reviseDraft(){if(busy||!draftChat.trim())return;const message=draftChat.trim(),scope=draftScope,pageId=scope==='page'?currentPage()?.id:undefined;if(scope==='page'&&!pageId)return;busy=true;reviseController=new AbortController();reviseWait={started:Date.now(),pending:true};reviseTimer=setInterval(renderReviseWait,1000);renderReviseWait();const id=store.project.id;const baseline=editFingerprint(scope,pageId);store.commit(d=>d.messages.push({role:'user',text:message,scope,pageId}),'发送修改要求');draftChat='';$('#draft-message').value='';$('#draft-send').disabled=true;$('#start-layout').disabled=true;$('#draft-ai-status').textContent='';renderDraftChat();
  try{const result=await request('/api/ai',{action:'revise',message,scope,pageId,project:store.project,materials:store.project.materials||[]},reviseController.signal);if(store.project.id!==id)return;if(editFingerprint(scope,pageId)!==baseline)throw Error('文案在等待期间已有修改，本次 AI 结果未覆盖你的新内容。请重新发送。');applyAI(result,{scope,pageId,stage:'draft'});renderDraft();}catch(e){if(e.name==='AbortError')e=new Error('已停止本次修改，原文保留。');notify(e.message);store.commit(d=>d.messages.push({role:'assistant',text:`本次修改未应用：${e.message}`,scope,pageId}),'记录修改状态');renderDraftChat();}finally{busy=false;clearInterval(reviseTimer);reviseController=null;if(reviseWait){reviseWait.pending=false;reviseWait.seconds=Math.floor((Date.now()-reviseWait.started)/1000);}renderReviseWait();if($('#draft-send')){$('#draft-send').disabled=false;$('#start-layout').disabled=false;$('#draft-ai-status').textContent='';}}}
function applyAI(result,{scope,pageId,objectIds,stage}){
  const inheritedIds=[];
  store.commit(d=>{
    const templateSource=stage==='editor'?structuredClone(d):null;
    const inherit=page=>{const next=createInheritedPage(templateSource,page,{anchorPageId:pageId,excludeReferencePageId:result.directLayout==='inherit'?page.id:undefined});if(next&&(result.directLayout!=='inherit'||!inheritedCopyFits(next))){next.designPending=true;inheritedIds.push(next.id);}return next;};
    const relayoutIds=new Set();let layoutAdded=0;
    const operations=validateOperations(result,{action:'revise',scope,pageId,objectIds,project:d});
    if(operations.length){const applied=applyOperations(d,operations);for(const id of applied.affectedIds)relayoutIds.add(id);}
    if(Array.isArray(result.pages)&&result.pages.length){const incoming=normalizedPages(result.pages);if(scope==='page'||scope==='object'){const index=d.pages.findIndex(p=>p.id===pageId);if(index<0)throw Error('目标页不存在');if(scope==='object')throw Error('AI 未返回所选对象的修改，未应用整页替换。');const old=d.pages[index];d.pages[index]={...old,title:incoming[0].title,body:incoming[0].body,role:Object.hasOwn(roleNames,result.pages[0].role)?incoming[0].role:old.role};relayoutIds.add(old.id);}else{d.pages=incoming.map((p,i)=>({...d.pages.find(old=>old.id===p.id),...p,objects:d.pages.find(old=>old.id===p.id)?.objects||d.pages[i]?.objects||[]}));d.pages.forEach(p=>relayoutIds.add(p.id));}}
    else if(Array.isArray(result.changes)&&result.changes.length){for(const c of result.changes){const p=d.pages.find(p=>p.id===c.pageId);if(!p)throw Error('AI 返回了无效页面');if(scope!=='deck'&&p.id!==pageId)throw Error('AI 结果超出所选页面，未应用');if(c.objectId){if(scope==='object'&&!objectIds?.includes(c.objectId))throw Error('AI 结果超出所选对象，未应用');const o=p.objects.find(o=>o.id===c.objectId);if(!o)throw Error('AI 返回的对象修改无效');if(typeof c.text==='string'){if(o.type!=='text')throw Error('图片或形状不能替换为文字');o.text=c.text;if(o.sourceField==='title'||o.layoutField==='title')p.title=c.text;}if(c.properties&&typeof c.properties==='object'){const allowed=new Set(['x','y','w','h','rotation','opacity','fontSize','color','bold','italic','align','fill','stroke','strokeWidth','radius']);for(const [key,value] of Object.entries(c.properties)){if(value===null)continue;if(!allowed.has(key))throw Error('AI 返回了不支持的对象属性');if(['x','y','w','h','rotation','opacity','fontSize','strokeWidth','radius'].includes(key)&&!Number.isFinite(value))throw Error('AI 返回的尺寸或位置无效');o[key]=value;}}}else{if(scope==='object')throw Error('AI 结果超出所选对象，未应用');if(typeof c.title==='string')p.title=c.title;if(typeof c.body==='string')p.body=c.body;relayoutIds.add(p.id);}}}
    else if(!result.message&&!operations.length)throw Error('AI 没有返回可用结果');
    if(stage==='editor'&&relayoutIds.size){const beforeLayout=d.pages.length;d.pages=d.pages.flatMap(p=>{if(!relayoutIds.has(p.id))return[p];if(result.directLayout==='inherit'){const inherited=inherit(p);if(inherited)return[inherited];}if(!p.engine){const inherited=inherit(p);if(inherited)return[inherited];}if(p.engine==='ppt-master-svg'){const updated=updateSvgCopy(p);if(updated){const changed=updated.objects.filter(o=>o.type==='text'&&o.text!==p.objects.find(old=>old.id===o.id)?.text);if(!inheritedCopyFits({...updated,objects:changed})){updated.designPending=true;inheritedIds.push(updated.id);}return[updated];}const inherited=inherit(p);if(inherited)return[inherited];return layoutDeck([p],d.themeId).map(next=>({...next,engine:undefined,layoutWarnings:[...(next.layoutWarnings||[]),'文案结构发生较大变化，已保留全文并采用临时排版；可让助手重新设计本页。']}));}if(p.designPlan&&d.themeId==='curated-139'){try{const next=layoutPlannedPage(p,getTheme(d.themeId),p.designPlan);next.designSnapshot=snapshotPage(next);return[next];}catch{const source={...p};delete source.designPlan;delete source.designSource;delete source.designSnapshot;return layoutDeck([source],d.themeId).map(next=>({...next,layoutWarnings:[...(next.layoutWarnings||[]),'内容结构已变化，本页使用临时可编辑排版；重新应用整套风格可生成新的逐页设计。']}));}}return layoutDeck([p],d.themeId);});layoutAdded=d.pages.length-beforeLayout;}
    d.messages.push({role:'assistant',text:(inheritedIds.length?'原文已保留，目标页还需要按当前模板完成排版，尚未完成。':(result.message||'已应用修改，可以继续调整或撤销。'))+(layoutAdded>0?` 为保持文字清晰，排版另外增加了 ${layoutAdded} 张续页，原文均已保留。`:''),scope,pageId});
  },'AI 修改');
  return inheritedIds;
}
async function editorAI({message,scope='page',pageId,objectIds=[]}){
 if(store.project?.audienceVersion&&scope==='deck')return audienceWorkflow.open({audience:store.project.audienceLabel||'',notes:message});
 const originalPageId=pageId,target=resolveImageTarget({message,scope,pageId,objectIds,project:store.project});pageId=target.pageId;scope=target.scope;
 if(busy||designController)throw Error('上一条 AI 请求还在进行中，请完成或停止后再试。');
 const id=store.project.id,themeId=store.project.themeId,baseline=JSON.stringify(store.project.pages),controller=new AbortController();
 designController=controller;setDesignBusy(true);
 store.commit(d=>d.messages.push({role:'user',text:message,scope,pageId}),'发送 AI 要求');
 designProgress({message:'Image＋Sol 助手正在处理你的要求…'});
 try{
  const input={action:'revise',message,scope,pageId,objectIds,project:contentProject(),materials:store.project.materials||[]};
  const result=await requestImageAssistant(input,controller.signal,event=>{if(store.project?.id===id&&!controller.signal.aborted)designProgress(event);});
  controller.signal.throwIfAborted();
  if(store.project?.id!==id)throw Error('已切换项目，本次修改未应用。');
  const action=validateDesignAction(result,input);
  if(action){
   if(store.project.stage!=='editor'||store.project.themeId!==themeId||JSON.stringify(store.project.pages)!==baseline||(editor?.getEditingPageIds?.()||[]).length)throw Error('你已继续编辑，本次设计未覆盖新修改。');
   designController=null;setDesignBusy(false);
   if(action.type==='review')await runDeckReview({targetPageIds:action.pageIds,instruction:action.instruction});
   else await runDesignedLayout({themeId,targetPageIds:action.pageIds,instruction:action.instruction,imageMode:action.type==='image-redesign'});
   if(store.project?.id===id)store.commit(p=>p.messages.push({role:'assistant',text:result.message||(action.type==='review'?'已检查指定页面。':'已开始按要求重新设计指定页面。'),scope,pageId}),'记录助手设计操作');
   return result;
  }
  const edit=validateImageEdit(result,input);
  if(edit){
   if(store.project.stage!=='editor'||store.project.themeId!==themeId||JSON.stringify(store.project.pages)!==baseline||(editor?.getEditingPageIds?.()||[]).length)throw Error('你已继续编辑，本次 Image 结果未覆盖新修改。');
   const changed=new Set(edit.changedPageIds),current=new Map(store.project.pages.map(p=>[p.id,p]));
   store.commit(p=>{p.pages=edit.pages.map(page=>changed.has(page.id)?page:current.get(page.id));p.messages.push({role:'assistant',text:result.message||'Image＋Sol 修改已完成，请查看页面。',scope,pageId});},'应用 Image＋Sol 修改');
   if(pageId!==originalPageId)render({pageId});
  }else{
   if(result.pages?.length||result.changes?.length||result.operations?.length||result.designAction)throw Error('助手未返回完整 Image 结果，原稿已保留。');
   store.commit(p=>p.messages.push({role:'assistant',text:result.message||'本次未修改页面。',scope,pageId}),'记录助手回复');
  }
  return result;
 }catch(error){if(error.name==='AbortError')error=new Error('已停止本次处理，原稿保留。');if(store.project?.id===id)store.commit(p=>p.messages.push({role:'assistant',text:'本次修改未应用：'+error.message,scope,pageId}),'记录助手处理状态');notify(error.message);throw error;}
 finally{setDesignBusy(false);}
}
function generateLayout(){if(busy)return;openThemePreview({themeId:store.project?.themeId||getTemplates()[0]?.id,autoGenerate:true}).catch(e=>notify(e.message));}

let themePreviewClose=null;
const previewSessions=new Map();
const draftsButton=document.createElement('button');draftsButton.id='preview-drafts';draftsButton.textContent='草稿箱';draftsButton.hidden=!store.project;$('#projects').before(draftsButton);
draftsButton.onclick=openPreviewDrafts;
function draftProgress(d){
 const ids=d.preview?.selectedIds||[],total=d.total||ids.length||selectPreviewPageIds(store.project.pages).length;
 const completed=ids.length?ids.filter(id=>d.preview.pages.some(p=>p.id===id)).length:Math.min(d.preview?.pages?.length||0,total);
 const done=d.state==='ready',percent=done?100:Math.min(95,Math.floor(completed/Math.max(1,total)*100));
 return {total,completed,percent,label:done?`生成完成 · ${completed} / ${total} 页`:`${percent}% · 已生成 ${completed} / ${total} 页`};
}
function updateDraftRow(d){
 const row=document.querySelector(`[data-draft-row="${d.themeId}"]`);if(!row)return;
 const progress=draftProgress(d);row.querySelector('[data-draft-status]').textContent=d.message;
 row.querySelector('progress').value=progress.percent;row.querySelector('[data-draft-progress-text]').textContent=progress.label;
}
function openPreviewDrafts(){
 const drafts=Object.values(store.project?.previewDrafts||{});
 dialog(`${modalHead('草稿箱')}<p>整份 PPT 可在后台继续生成，最多同时生成两份。可直接沿用文案和模板重新生成，也可删除草稿；模板预览请保持网页打开。</p><div id="generation-draft-rows"></div>${drafts.length?drafts.map(d=>{const progress=draftProgress(d);return `<div class="project-row" data-draft-row="${esc(d.themeId)}"><div class="draft-task-info"><strong>${esc(getTheme(d.themeId)?.name||'模板预览')}</strong><small data-draft-status>${esc(d.state==='generating'&&!previewSessions.has(store.project.id+':'+d.themeId)?'生成已中断，已保留完成页面':d.message)}</small><progress class="draft-task-progress" max="100" value="${progress.percent}" aria-label="${esc(getTheme(d.themeId)?.name||'模板预览')}生成进度"></progress><small data-draft-progress-text>${progress.label}</small></div><button data-draft-theme="${esc(d.themeId)}">查看预览</button><button data-delete-draft="${esc(d.themeId)}">删除</button></div>`;}).join(''):'<p class="empty-state">还没有预览草稿。</p>'}`);
 void referenceGeneration.fillDrafts($('#generation-draft-rows')).then(()=>{if($('#generation-draft-rows')?.childNodes.length)$('#modal-content .empty-state')?.remove();});
 if(store.project?.generationDrafts?.length)$('#modal-content .empty-state')?.remove();
 $('#modal-content').querySelectorAll('[data-delete-draft]').forEach(b=>b.onclick=async()=>{
  if(!confirm('删除这个预览草稿？文案、模板和已保存页面会保留。'))return;
  b.disabled=true;const themeId=b.dataset.deleteDraft;
  try{previewSessions.get(store.project.id+':'+themeId)?.discard();
   const clean=p=>{if(p.previewDrafts)delete p.previewDrafts[themeId];};
   clean(store.project);for(const item of [...store.past,...store.future])if(item.project.id===store.project.id)clean(item.project);
   store.mark(true);await store.flush();openPreviewDrafts();
  }catch(error){b.disabled=false;notify(error.message);}
 });
 $('#modal-content').querySelectorAll('[data-draft-theme]').forEach(b=>b.onclick=()=>openPersonalPreview({themeId:b.dataset.draftTheme}).catch(e=>notify(e.message)));
}

let themeGallery;
function loadThemeGallery(){return themeGallery||(themeGallery=fetch('/assets/theme-previews/index.json').then(r=>{if(!r.ok)throw Error('预览暂不可用');return r.json();}).catch(()=>{themeGallery=null;return null;}));}
async function openThemePreview({themeId}={}){
 if(!store.project?.pages.length)throw Error('请先添加至少一页文案。');
 const owner=store.project.id,themes=getTemplates();let chosen=themeId||store.project.themeId;
 const modal=dialog(`${modalHead('选择整套模板')}<div class="theme-preview-covers" role="group" aria-label="模板首页缩略图">${themes.map(t=>`<button type="button" class="theme-preview-cover" data-preview-theme="${esc(t.id)}" aria-label="${esc(t.name)}" aria-pressed="${t.id===chosen}" title="${esc(t.name)}"><img src="${esc(t.cover)}" alt="${esc(t.name)}首页" loading="lazy" decoding="async" width="240" height="135"></button>`).join('')}</div><div class="modal-actions"><button data-close>取消</button><button id="template-confirm" class="primary">确认模板，开始排版</button></div>`);
 modal.classList.add('theme-preview-dialog');
 const close=()=>{modal.classList.remove('theme-preview-dialog');if(themePreviewClose===close)themePreviewClose=null;};
 themePreviewClose=close;modal.addEventListener('close',close,{once:true});
 modal.querySelectorAll('[data-preview-theme]').forEach(button=>button.onclick=()=>{
  chosen=button.dataset.previewTheme;
  modal.querySelectorAll('[data-preview-theme]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.previewTheme===chosen)));
 });
 $('#template-confirm').onclick=async()=>{
  if(store.project?.id!==owner){modal.close();return;}
  if(busy||designController){notify('当前请求还在处理中，请完成或停止后再排版。');return;}
  modal.close();close();
  try{if(isPrecompiledTheme(chosen))await runDesignedLayout({themeId:chosen});else await referenceGeneration.run({themeId:chosen});}catch(error){notify(error.message||'排版未完成，原稿已保留。');}
 };
}
async function openPersonalPreview({themeId,autoGenerate=false}={}){
 if(!store.project?.pages.length)throw Error('请先添加至少一页文案。');
 const theme=getTheme(themeId);if(!theme)throw Error('模板不存在。');
 themePreviewClose?.();
 const sessionKey=store.project.id+':'+themeId,existingSession=previewSessions.get(sessionKey);
 if(existingSession&&existingSession.baseline===previewFingerprint(store.project)){existingSession.resume();return;}
 const baseline=previewFingerprint(store.project),snapshot=structuredClone(store.project),selectedIds=selectPreviewPageIds(snapshot.pages);
 const themes=getTemplates(),index=themes.findIndex(t=>t.id===themeId);
 const referenceImages=(theme.previews?.length?theme.previews:[theme.cover]).slice(0,3);
 const imageCards=(images,kind)=>images.map((src,i)=>`<article class="theme-preview-page"><p>${kind==='sample'?['封面示例','目录示例','正文示例'][i]:`风格参考 ${i+1}`}</p><img class="theme-preview-image" src="${esc(src)}" alt="${esc(theme.name)} · ${kind==='sample'?['封面示例','目录示例','正文示例'][i]:`参考 ${i+1}`}" decoding="async"></article>`).join('');
 const modal=dialog(`${modalHead(`整套风格 · ${theme.name}`)}<div class="theme-preview-navigation"><button id="theme-preview-prev" aria-label="上一个模板">← 上一个</button><details class="theme-preview-picker" id="theme-preview-picker"><summary id="theme-preview-select" aria-label="切换模板" title="切换模板"><span>切换模板</span><img src="${esc(theme.cover)}" alt="${esc(theme.name)}首页" width="96" height="54"><svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" stroke-width="1.5"/></svg></summary><div class="theme-preview-covers" role="group" aria-label="模板首页缩略图">${themes.map(t=>`<button type="button" class="theme-preview-cover" data-preview-theme="${esc(t.id)}" aria-label="${esc(t.name)}" aria-pressed="${t.id===themeId}" title="${esc(t.name)}"><img src="${esc(t.cover)}" alt="${esc(t.name)}首页" loading="lazy" decoding="async" width="240" height="135"></button>`).join('')}</div></details><button id="theme-preview-next" aria-label="下一个模板">下一个 →</button></div><p id="theme-preview-description" class="theme-preview-description">先看风格参考。喜欢这个风格，再用你的内容生成预览。</p><p id="theme-preview-status" role="status">浏览模板无需等待生成，不会修改当前文稿。</p><div id="theme-preview-pages" class="ed-preview-grid">${imageCards(referenceImages,'reference')}</div><div id="theme-preview-issues"></div><div class="modal-actions"><button id="theme-preview-collapse">收进草稿箱</button><button id="theme-preview-retry" hidden>重新生成预览</button><button id="theme-preview-generate" class="primary">用我的内容生成预览</button><button id="theme-preview-apply" class="primary" hidden disabled>确认效果，应用到整份 PPT</button></div>`);
 modal.classList.add('theme-preview-dialog');
 const status=$('#theme-preview-status'),description=$('#theme-preview-description'),grid=$('#theme-preview-pages'),issues=$('#theme-preview-issues'),apply=$('#theme-preview-apply'),retry=$('#theme-preview-retry'),generateButton=$('#theme-preview-generate');
 let controller=null,preview=null,closed=false,runId=0,mode='sample';
 const stale=()=>!store.project||previewFingerprint(store.project)!==baseline;
 const draw=pages=>{grid.innerHTML=pages.map(pg=>{const original=snapshot.pages.findIndex(p=>p.id===pg.id||p.id===pg.continuationOf);return `<article class="theme-preview-page"><p>你的第 ${original+1} 页 · ${esc(roleNames[pg.role]||'内容')}${pg.continuationIndex?'（续页）':''}</p><div class="ed-mini">${renderMini(pg)}</div></article>`;}).join('');};
 const nodes=[...$('#modal-content').childNodes],fragment=document.createDocumentFragment();let attached=true;
 const persist=(state,message,value=preview)=>{if(closed||store.project?.id!==snapshot.id)return;store.commit(p=>{p.previewDrafts={...p.previewDrafts,[themeId]:{themeId,baseline,state,message,total:selectedIds.length,preview:value}};},'保存预览草稿',true);updateDraftRow(store.project.previewDrafts[themeId]);};
 const close=()=>{if(!attached)return;attached=false;nodes.forEach(n=>fragment.append(n));modal.classList.remove('theme-preview-dialog');modal.removeEventListener('cancel',cancel);if(themePreviewClose===close)themePreviewClose=null;};
 const collapse=()=>{if(mode==='sample')persist('sample','风格参考，尚未生成个人预览');close();modal.close();notify(mode==='generating'?'已收起到草稿箱，生成继续进行。':'预览已保留在草稿箱。');};
 const dismiss=()=>{if(mode==='generating')controller?.abort();else{closed=true;previewSessions.delete(sessionKey);}close();modal.close();};
 const cancel=event=>{event.preventDefault();dismiss();};
 const resume=()=>{themePreviewClose?.();$('#modal-content').replaceChildren(fragment);attached=true;modal.classList.add('theme-preview-dialog');themePreviewClose=close;modal.addEventListener('cancel',cancel);if(!modal.open)modal.showModal();};
 themePreviewClose=close;modal.addEventListener('cancel',cancel);
 const dismissButton=modal.querySelector('.modal-head [data-close]');dismissButton.onclick=dismiss;dismissButton.title='关闭窗口并结束本次生成';dismissButton.setAttribute('aria-label','关闭');
 $('#theme-preview-collapse').onclick=collapse;
 previewSessions.set(sessionKey,{baseline,resume,discard(){closed=true;controller?.abort();previewSessions.delete(sessionKey);}});
 const switchTheme=id=>openPersonalPreview({themeId:id}).catch(e=>notify(e.message));
 $('#theme-preview-prev').onclick=()=>switchTheme(themes[(index+themes.length-1)%themes.length].id);
 $('#theme-preview-next').onclick=()=>switchTheme(themes[(index+1)%themes.length].id);
 const picker=$('#theme-preview-picker');
 picker.querySelectorAll('[data-preview-theme]').forEach(button=>button.onclick=()=>{
  if(button.dataset.previewTheme===themeId){picker.open=false;$('#theme-preview-select').focus();return;}
  void switchTheme(button.dataset.previewTheme).then(()=>$('#theme-preview-select')?.focus());
 });
 picker.addEventListener('keydown',event=>{if(event.key==='Escape'&&picker.open){event.preventDefault();event.stopPropagation();picker.open=false;$('#theme-preview-select').focus();}});
 picker.addEventListener('toggle',()=>{if(picker.open)picker.querySelector('[aria-pressed="true"]')?.scrollIntoView({block:'nearest'});});
 grid.addEventListener('error',event=>{
  const img=event.target;if(img.tagName!=='IMG'||!img.classList.contains('theme-preview-image')||img.dataset.fallback)return;
  img.dataset.fallback='true';img.src=theme.cover;img.alt=`${theme.name} · 封面参考`;
  img.closest('article').querySelector('p').textContent='封面参考';
  if(mode==='sample')status.textContent='部分样稿暂不可用，先显示封面参考。仍可切换模板或生成你的内容。';
 },true);
 loadThemeGallery().then(gallery=>{
  if(closed||mode!=='sample')return;
  const entry=gallery?.entries?.[themeId];if(!entry?.images?.length)return;
  grid.innerHTML=imageCards(entry.images,entry.kind);
  if(entry.kind==='sample')description.textContent='这是已完成的三页风格样稿，内容为示例。用你的内容生成后，确认效果再应用。';
 });
 function showReady(value,cached=false){
  preview=value;mode='ready';persist('ready',value.review?.issues?.some(i=>i.severity==='error')?'生成完成，部分页面需要修复':'预览已完成',value);draw(preview.pages);delete status.dataset.elapsed;
  description.textContent='以下是你的内容生成的真实预览。确认后原样应用，再设计剩余页面。';
  const errors=(preview.review?.issues||[]).filter(i=>i.severity==='error');
  status.textContent=errors.length?'预览存在内容或排版问题，请重新生成后再应用。':`${cached?'已恢复这份文稿的预览，无需重新生成。':'你的内容预览已完成。'}共 ${preview.pages.length} 页，确认后只生成其余页面。`;
  issues.replaceChildren();for(const issue of preview.review?.issues||[]){const line=document.createElement('p');line.className='theme-preview-warning';line.textContent=issue.message;issues.append(line);}
  apply.hidden=false;apply.disabled=!!errors.length;retry.textContent=errors.length?'修复有问题的页面':'重新生成预览';retry.hidden=false;generateButton.hidden=true;
 }
 async function generate(){
  if(closed)return;if(stale()){status.textContent='文稿已发生变化，请关闭后重新打开预览。';apply.disabled=true;retry.hidden=true;return;}
  if(busy||designController){status.textContent='另一个任务还在处理中。你可以继续浏览模板，完成或停止该任务后再生成。';return;}
  const source=contentProject(),previousPreview=preview,run=++runId;controller=new AbortController();designController=controller;busy=true;preview=null;mode='generating';apply.hidden=true;apply.disabled=true;retry.hidden=true;generateButton.hidden=true;issues.replaceChildren();persist('generating','正在生成预览…');
  description.textContent=`正在用你的内容设计 ${selectedIds.length} 个代表页面；下方暂时保留已有预览。收进草稿箱后继续生成；点击右上角 × 会关闭并结束本次生成。`;
  status.textContent='正在设计你的内容…';status.dataset.elapsed='0';
  const ready=new Map(),started=Date.now();
  const timer=setInterval(()=>{if(!closed&&run===runId)status.dataset.elapsed=String(Math.floor((Date.now()-started)/1000));},1000);
  try{
   const value=await createThemePreview(source,{themeId,request,previousPreview,signal:controller.signal,onProgress:event=>{if(closed||run!==runId)return;if(stale()){controller.abort();return;}status.textContent=event.message.replace('已完成页面可以编辑','正在生成真实预览');persist('generating',status.textContent,store.project.previewDrafts?.[themeId]?.preview||null);},onBatchReady:batch=>{if(closed||run!==runId||stale())return;for(const page of batch.pages)ready.set(page.id,page);description.textContent='正在逐页生成你的内容，全部完成后可确认应用。';draw([...ready.values()]);persist('generating',`已生成 ${ready.size} / ${selectedIds.length} 页`,{sourceFingerprint:previewFingerprint(source),themeId,selectedIds,pages:[...ready.values()],review:{issues:selectedIds.filter(id=>!ready.has(id)).map(pageId=>({pageId,severity:'error',kind:'generation-incomplete'}))}});}});
   if(closed||run!==runId)return;if(stale())throw Error('文稿已发生变化，请关闭后重新打开预览。');
   showReady(value);void writePreviewCache(snapshot,themeId,value);
  }catch(error){if(!closed&&run===runId){const missing=selectedIds.filter(id=>!ready.has(id));preview=ready.size?{sourceFingerprint:previewFingerprint(source),themeId,selectedIds,pages:[...ready.values()],review:{issues:(missing.length?missing:selectedIds).map(pageId=>({pageId,severity:'error',kind:'generation-incomplete'}))}}:previousPreview;mode='stopped';status.textContent=stale()?'文稿已发生变化，请关闭后重新打开预览。':error.name==='TimeoutError'?'生成时间过长，已停止等待。当前文稿未修改，可以重试或更换风格。':error.name==='AbortError'?'已关闭生成，已完成的预览页保留在草稿箱。':`预览未完成：${error.message}。当前文稿未修改。`;retry.hidden=stale();apply.disabled=true;persist('stopped',status.textContent);}}
  finally{clearInterval(timer);if(!closed&&run===runId){delete status.dataset.elapsed;}if(run===runId&&designController===controller){designController=null;busy=false;}}
 }
 retry.onclick=generate;generateButton.onclick=generate;
 apply.onclick=async()=>{
  if(!preview||apply.disabled)return;
  if(busy||designController){notify('另一个任务仍在处理中，完成或停止后再应用预览。');return;}
  try{
   const accepted=applyThemePreview(store.project,preview,baseline);apply.disabled=true;
   close();modal.close();previewSessions.delete(sessionKey);store.commit(p=>{Object.assign(p,accepted.project);if(p.previewDrafts)delete p.previewDrafts[themeId];},'确认并应用真实模板预览');view='editor';render({pageId:preview.pages[0]?.id});
   if(accepted.remainingIds.length)await runDesignedLayout({themeId,targetPageIds:accepted.remainingIds,retainedReview:preview.review});
   else if(!preview.review?.visionRan)await runDeckReview({targetPageIds:preview.pages.map(p=>p.id)});
   else notify('已应用确认的真实预览，全部页面已完成。');
  }catch(error){notify(error.message||'本次应用未完成，已保留当前文稿。');}
 };
 const savedDraft=store.project.previewDrafts?.[themeId];
 if(savedDraft?.baseline===baseline&&savedDraft.preview){
  if(savedDraft.state==='ready')showReady(savedDraft.preview,true);
  else{preview=savedDraft.preview;mode='stopped';draw(preview.pages);status.textContent='生成已停止，已完成的预览页已保留。可重新生成未完成部分。';retry.hidden=false;generateButton.hidden=true;}
  return;
 }
 if(autoGenerate){const cached=await readPreviewCache(snapshot,themeId);if(closed||mode!=='sample'||stale())return;if(cached)showReady(cached,true);else await generate();}
 else void readPreviewCache(snapshot,themeId).then(value=>{if(value&&!closed&&mode==='sample'&&!stale())showReady(value,true);});
}

let designController=null,designStartedAt=0,designTimer=null;
function designProgress(event){if(generation.progress(event))return;let host=$('#design-progress');if(!host){host=document.createElement('section');host.id='design-progress';host.className='design-progress';host.innerHTML='<div><span role="status"></span><small class="design-elapsed"></small><button type="button">停止</button></div><details><summary>查看已排版页面</summary><div class="design-progress-pages"></div></details>';$('#app').before(host);host.querySelector('button').onclick=()=>designController?.abort();}host.querySelector('[role=status]').textContent=event.message;if(event.pages?.length)host.dataset.background='true';if(event.pages){host.querySelector('.design-progress-pages').innerHTML=event.pages.map(p=>`<div>${renderMini(p)}</div>`).join('');}host.querySelector('details').hidden=!host.querySelector('.design-progress-pages').children.length;}
function setDesignBusy(value,{release=true}={}){if(release)busy=value;if(value){designStartedAt=Date.now();clearInterval(designTimer);designTimer=setInterval(()=>{const clock=$('.design-elapsed');if(clock){const elapsed=Math.floor((Date.now()-designStartedAt)/1000);clock.textContent=`已用时 ${Math.floor(elapsed/60)}分${elapsed%60}秒`;}},1000);}else{clearInterval(designTimer);designTimer=null;}const start=$('#start-layout');if(start){start.disabled=value;start.textContent=value?'正在逐页设计…':'确认文案，开始排版';}if($('#draft-send'))$('#draft-send').disabled=value;if(!value){$('#design-progress')?.remove();designController=null;}}
async function runDesignedLayout({themeId='curated-139',targetPageIds,instruction='',retainedReview,imageMode=false}={}){
 if(busy||designController)throw Error('当前请求还在处理中，请完成或停止后再设计。');if(!store.project?.pages.length)throw Error('请先确认至少一页文案。');
 if(imageMode)return referenceGeneration.run({mode:'image',themeId,targetPageIds,instruction});
 let precompiledCandidate=null;
 if(isPrecompiledTheme(themeId)){
  const original=JSON.stringify(store.project),candidateSource=contentProject(),ids=targetPageIds||candidateSource.pages.map(page=>page.id),selected=new Set(ids),checkController=new AbortController();
  designController=checkController;setDesignBusy(true);
  let check;
  try{
   designProgress({phase:'planning',message:'正在核对当前文案是否适合预绘模板'});
   const pages=layoutDeck(candidateSource.pages.filter(page=>selected.has(page.id)),themeId);
   check=await checkPrecompiledLayout(pages,ids);
   if(checkController.signal.aborted)throw new DOMException('已停止排版，原稿已保留。','AbortError');
   if(JSON.stringify(store.project)!==original)throw Error('检查期间文稿已有变化，未覆盖你的修改。');
   if(check.accepted)precompiledCandidate={pages,review:check.review};
  }finally{setDesignBusy(false);}
  if(!precompiledCandidate){notify(check.review.summary);return referenceGeneration.run({themeId,targetPageIds,instruction});}
 }
 const owner=store.project.id,baseline=JSON.stringify({pages:store.project.pages,themeId:store.project.themeId,designEngine:store.project.designEngine}),source=contentProject(),controller=new AbortController(),expected=new Map(),protectedPages=new Set();let delivered=false;
 if(targetPageIds)source.pages=source.pages.map(p=>targetPageIds.includes(p.id)?p:structuredClone(store.project.pages.find(old=>old.id===p.id)));
 designController=controller;setDesignBusy(true);
 generation.start(targetPageIds||source.pages.map(p=>p.id));
 const fingerprint=p=>JSON.stringify(p);
 const ownProject=()=>{if(store.project?.id!==owner||store.project.designEngine!==source.designEngine||delivered&&(store.project.themeId!==themeId||store.project.stage!=='editor')){controller.abort();throw Error('已切换文稿或风格，本次设计已停止。');}};
 const protectEditing=()=>{for(const id of editor?.getEditingPageIds?.()||[])protectedPages.add(id);};
 const onBatchReady=({pages,sources,targetPageIds:batchTargets,completed,total})=>{
  ownProject();protectEditing();
  if(!delivered&&(JSON.stringify({pages:store.project.pages,themeId:store.project.themeId,designEngine:store.project.designEngine})!==baseline||protectedPages.size))throw Error('等待期间文稿已有变化，本次设计未覆盖你的新修改。');
  const first=!delivered,updates=new Map(pages.map(p=>[p.id,p]));
  store.commit(p=>{
   if(first){p.pages=sources.map(pg=>batchTargets.includes(pg.id)?{...pg,designPending:true}:pg);p.themeId=themeId;p.stage='editor';for(const pg of p.pages)expected.set(pg.id,fingerprint(pg));}
   p.pages=p.pages.map(pg=>{const next=updates.get(pg.id);if(!next)return pg;if(protectedPages.has(pg.id)||fingerprint(pg)!==expected.get(pg.id)||busy&&!first){protectedPages.add(pg.id);return pg;}expected.set(pg.id,fingerprint(next));return next;});
   p.designReview={summary:`已设计 ${completed} / ${total} 页；可先编辑已完成页面，整稿检查尚未完成。`,status:'pending',visionRan:false,repairRounds:0,issues:[],sourceSnapshot:[]};
  },`应用第 ${completed} 页以内已完成的设计`);
  generation.batch(pages.filter(pg=>!protectedPages.has(pg.id)),total);
  delivered=true;if(first){busy=false;view='editor';render({pageId:pages[0]?.id});notify('第一批页面已可编辑，后续设计和检查继续进行。');}
 };
 try{
  let designed;
  if(isPrecompiledTheme(themeId)){
   const ids=targetPageIds||source.pages.map(page=>page.id),selected=new Set(ids),sourcePages=source.pages.map(page=>structuredClone(page));
   designProgress({phase:'designing',message:'正在应用已预制的模板版式与素材'});
   const layouts=precompiledCandidate.pages,byId=new Map(layouts.map(page=>[page.id,page]));
   const pages=sourcePages.map(page=>byId.get(page.id)||page);
   onBatchReady({pages:layouts,sources:sourcePages,targetPageIds:ids,completed:layouts.length,total:ids.length});
   const designReview=precompiledCandidate.review;
   designed={pages,designReview};
  }else designed=await (imageMode?designImageProject:['svg','slidev','pptagent'].includes(source.designEngine)?designSvgProject:designProject)(source,{themeId,targetPageIds,instruction,request,onBatchReady,onProgress:event=>{ownProject();designProgress(event);},signal:controller.signal});
  ownProject();protectEditing();
  if(retainedReview&&!retainedReview.visionRan){retainedReview=await reviewProject(designed,{targetPageIds:retainedReview.targetPageIds,instruction,request,onProgress:designProgress,signal:controller.signal});ownProject();protectEditing();}
  if(!delivered){
   if(JSON.stringify({pages:store.project.pages,themeId:store.project.themeId,designEngine:store.project.designEngine})!==baseline)throw Error('文稿已有变化，未覆盖你的修改。');
   store.commit(p=>{p.pages=designed.pages;p.themeId=themeId;p.designReview=designed.designReview;},'保留未完成页面及文案');
   generation.finish('failed','本次排版尚未完成，文案已保留，可继续生成未完成页。');notify('本次排版尚未完成，文案已保留，可继续生成未完成页。');return;
  }
  const updates=new Map(designed.pages.map(p=>[p.id,p]));
  store.commit(p=>{p.pages=p.pages.map(pg=>{if(!updates.has(pg.id)||protectedPages.has(pg.id)||fingerprint(pg)!==expected.get(pg.id)||busy){protectedPages.add(pg.id);return pg;}return updates.get(pg.id);});p.designReview=combinePreviewReview(retainedReview,designed.designReview,p.pages);if(protectedPages.size){p.designReview={...p.designReview,status:'needs-attention',visionRan:false,summary:'已保留你的编辑，修改后的页面需要重新检查。',issues:[...p.designReview.issues,...[...protectedPages].map(pageId=>({pageId,kind:'stale-review',severity:'warning',message:'此页在检查期间已有修改，请重新检查。'}))]};}},'记录后台设计检查与修正');
  generation.finish(store.project.pages.some(p=>p.designPending)?'failed':'complete',store.project.pages.some(p=>p.designPending)?'部分页面未完成，已完成页面已保留。':'页面已生成，检查结果已保存。');
  notify(!protectedPages.size&&imageMode?designed.designReview.summary:store.project.pages.some(p=>p.designPending)?`仍有 ${store.project.pages.filter(p=>p.designPending).length} 页未完成，已完成页面已保留。`:protectedPages.size?'后台检查已完成；保留了你编辑过的页面，请重新检查最新稿件。':store.project.designReview.issues.length?'页面已生成，部分页面仍需调整。':'逐页设计及整稿检查已完成。');
 }catch(error){
  generation.finish(controller.signal.aborted?'stopped':'failed',error.name==='AbortError'?'已停止，已完成页面已保留。':error.message);
  if((delivered||retainedReview)&&store.project?.id===owner){store.commit(p=>{p.designReview={summary:'后续设计或检查已停止，已完成页面和当前编辑均已保留。',status:'needs-attention',visionRan:false,repairRounds:0,issues:[...(retainedReview?.issues||[]),{pageId:p.pages.find(pg=>pg.designPending)?.id||p.pages[0]?.id,kind:'design-incomplete',severity:'warning',message:error.name==='AbortError'?'任务已停止，未完成的页面可重新设计。':error.message}]};},'保留已完成的设计');notify('已保留完成的页面和当前编辑，其余页面尚未完成。');return;}
  throw error;
 }finally{if(generation.active)generation.finish('interrupted','生成已中断，已完成页面已保留。');setDesignBusy(false,{release:!delivered});}
}
async function runDeckReview({targetPageIds,instruction=''}={}){
 if(busy||designController)throw Error('当前设计或检查还在处理中，请完成或停止后再试。');if(!store.project?.pages.length)return;
 const source=structuredClone(store.project),baseline=JSON.stringify(source.pages),owner=source.id;designController=new AbortController();setDesignBusy(true);
 try{const result=await reviewProject(source,{targetPageIds,instruction,request,onProgress:designProgress,signal:designController.signal});if(store.project?.id!==owner||JSON.stringify(store.project.pages)!==baseline)throw Error('检查期间页面已有变化，请对最新页面重新检查。');store.commit(p=>p.designReview=result,'记录整稿检查');notify(result.summary);}finally{setDesignBusy(false);}
}

async function exportProject(){const button=$('#export');if(!store.project?.pages.length)return;button.disabled=true;button.textContent='正在导出…';try{await store.flush();const r=await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(completedReferenceExport(store.project))});if(!r.ok){const e=await r.json();throw Error(e.error?.message||e.error||'导出失败');}const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download=(store.project.title||'演示文稿')+'.pptx';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);notify(store.project.referenceJob?.appliedPageIds?.length?'已导出完成页；未完成页未包含在本次导出中。':'已导出可编辑 PPTX。');}catch(e){notify(e.message);}finally{button.disabled=false;button.textContent='导出 PPTX';}}
async function openProjects(){
  try{
    await store.flush();const data=await request('/api/projects');
    dialog(`${modalHead('我的项目')}${data.projects.length?data.projects.map(p=>`<div class="project-row"><div class="project-details"><strong>${esc(p.title)}</strong><small>${p.stage==='editor'?'PPT 编辑':'文案讨论'} · ${esc(p.updatedAt?new Date(p.updatedAt).toLocaleString('zh-CN'):'')}</small></div><div class="project-actions"><button data-project="${esc(p.id)}">打开</button><button class="danger-text" data-delete-project="${esc(p.id)}" aria-label="删除 ${esc(p.title)}">删除</button></div></div>`).join(''):'<p class="empty-state">还没有项目。从一个想法开始吧。</p>'}`);
    $('#modal-content').querySelectorAll('[data-project]').forEach(b=>b.onclick=()=>loadProject(b.dataset.project));
    $('#modal-content').querySelectorAll('[data-delete-project]').forEach(b=>b.onclick=()=>confirmDeleteProject(data.projects.find(p=>p.id===b.dataset.deleteProject)));
  }catch(e){notify(e.message);}
}
function confirmDeleteProject(project){
  if(projectOpening)return;
  dialog(`${modalHead('删除项目')}<p class="manual-help">确定删除「${esc(project.title)}」吗？项目中的文案和 PPT 将从我的项目中移除，此操作无法撤销。</p><p id="delete-error" class="action-error" role="alert"></p><div class="modal-actions"><button id="cancel-delete" autofocus>取消</button><button id="confirm-delete" class="danger-text">删除项目</button></div>`);
  $('#cancel-delete').onclick=openProjects;
  $('#confirm-delete').onclick=async()=>{
    const button=$('#confirm-delete');button.disabled=true;button.textContent='正在删除…';
    const modal=$('#modal'),preventClose=e=>e.preventDefault();modal.addEventListener('cancel',preventClose);
    const controls=[...$('#modal-content').querySelectorAll('button')];controls.forEach(b=>b.disabled=true);
    try{
      if((busy&&!referenceGeneration.active)||uploading)throw Error('请求或上传进行中，请完成后再删除项目。');
      const jobs=await referenceGeneration.syncDrafts();
      if(jobs.some(j=>j.projectId===project.id&&['queued','running','cancelling'].includes(j.status)))throw Error('这个项目正在生成，请先在草稿箱停止任务，再删除项目。');
      if(store.project?.id===project.id){await referenceGeneration.detach();await store.flush();}
      await request('/api/projects/'+encodeURIComponent(project.id),undefined,AbortSignal.timeout(20000),'DELETE');
      try{localStorage.removeItem(recoveryKey(project.id));}catch{}
      if(store.project?.id===project.id){editor?.destroy();editor=null;clearTimeout(store.timer);store.project=null;store.past=[];store.future=[];store.dirty=false;store.error=null;view='home';history.replaceState(null,'','/');render();}
      generation.removeProject(project.id);await openProjects();notify('项目已删除。');
    }catch(e){if($('#delete-error'))$('#delete-error').textContent=e.message;}
    finally{modal.removeEventListener('cancel',preventClose);controls.forEach(b=>b.disabled=false);button.textContent='删除项目';}
  };
}
let loggingOut=false;
async function logout(){
  if(loggingOut)return;
  if((busy&&!referenceGeneration.active)||uploading){notify('请求或上传进行中，完成后再退出登录。');return;}
  loggingOut=true;const button=$('#logout');button.disabled=true;button.textContent='正在退出…';
  try{
    await referenceGeneration.detach();await store.flush();
    await request('/logout',{},AbortSignal.timeout(20000));
    location.replace('/login');
  }catch(e){notify('退出未完成：'+e.message);loggingOut=false;button.disabled=false;button.textContent='退出登录';}
}
$('#logout').onclick=logout;

let projectOpening=false;
async function loadProject(id){if(projectOpening)return;projectOpening=true;const buttons=[...document.querySelectorAll('[data-project]')];buttons.forEach(b=>{b.disabled=true;if(b.dataset.project===id)b.textContent='正在打开…';});try{await referenceGeneration.detach();await store.flush();const p=await request('/api/projects/'+encodeURIComponent(id));store.load(p);reviseWait=null;selectedTheme=p.themeId;view=p.stage==='editor'?'editor':'draft';$('#modal').close();history.replaceState(null,'','/?project='+encodeURIComponent(id));render();let recovery;try{recovery=JSON.parse(localStorage.getItem(recoveryKey(id))||'null');}catch{}if(recovery&&JSON.stringify(recovery)!==JSON.stringify(p)){dialog(`${modalHead('发现未保存的修改')}<p class="manual-help">上次离开时有修改未成功保存。可以恢复到当前项目，或继续使用服务器已保存版本。</p><div class="modal-actions"><button id="discard-recovery">使用已保存版本</button><button id="restore-recovery" class="primary">恢复修改</button></div>`);$('#discard-recovery').onclick=()=>{localStorage.removeItem(recoveryKey(id));$('#modal').close();};$('#restore-recovery').onclick=()=>{store.commit(d=>Object.assign(d,{...recovery,revision:p.revision}),'恢复未保存修改');$('#modal').close();render();};}}catch(e){notify(e.message);}finally{projectOpening=false;buttons.forEach(b=>{b.disabled=false;b.textContent='打开';});}}
async function goHome(clear=false){if(referenceGeneration.active)await referenceGeneration.detach();if(busy||uploading){notify('请求或上传进行中，完成后再切换项目。');return;}try{await store.flush();editor?.destroy();editor=null;store.project=null;store.past=[];store.future=[];if(clear){homeText='';materials=[];selectedTheme='';}view='home';history.replaceState(null,'','/');render();}catch(e){notify(e.message);}}
$('#open-demo').onclick=openDemo;$('#home').onclick=()=>goHome();$('#new-project').onclick=()=>goHome(true);$('#projects').onclick=()=>{if((busy&&!referenceGeneration.active)||uploading){notify('请求或上传进行中，完成后再切换项目。');return;}openProjects();};$('#save-status').onclick=()=>{if(store.error?.status===409){dialog(`${modalHead('另一个窗口已更新这份文稿')}<p class="manual-help">当前修改已保存在本机恢复副本中。重新载入后，你可以选择恢复这些修改，或使用已保存版本。</p><div class="modal-actions"><button data-close>继续保留当前内容</button><button id="reload-conflict" class="primary">重新载入并比较版本</button></div>`);$('#reload-conflict').onclick=()=>{const id=store.project.id;store.backup();store.dirty=false;store.error=null;loadProject(id);};}else store.save();};$('#project-title').onchange=e=>store.commit(p=>p.title=e.target.value.trim()||'未命名演示稿','修改项目名称');$('#export').onclick=exportProject;
document.addEventListener('click',e=>document.querySelectorAll('.page-insert[open]').forEach(menu=>{if(!menu.contains(e.target))menu.open=false;}));
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();store.flush().then(()=>notify('已保存。')).catch(err=>notify(err.message));}if(view==='draft'&&(e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'&&!['INPUT','TEXTAREA'].includes(document.activeElement.tagName)){e.preventDefault();e.shiftKey?store.redo():store.undo();renderDraft();}});
$('#app').innerHTML='<p class="loading-page">正在准备你的创作空间…</p>';
try{await loadTemplates();void loadThemeGallery();render();const id=new URLSearchParams(location.search).get('project');if(id)await loadProject(id);request('/api/ai/status').then(status=>{aiStatus=status;header();}).catch(e=>{aiStatus={available:false,label:'AI 暂未连接',message:e.message};header();});}catch(e){$('#app').innerHTML=`<div class="empty-state">启动未完成：${esc(e.message)}<br><button onclick="location.reload()">重新加载</button></div>`;}

async function importOriginalPresentation(file){
 if(busy||designController||uploading)throw Error('请等待当前操作完成后再导入原稿。');
 if(!/\.(pptx|pdf)$/i.test(file.name))throw Error('请选择 PPTX 或 PDF 原稿。');if(file.size>20*1024*1024)throw Error('原稿需小于20MB。');
 const fromHome=view==='home',button=$('#draft-import-original');busy=true;if(button){button.disabled=true;button.textContent='正在导入原稿…';}if(fromHome){const status=$('#home-status');if(status)status.textContent='正在导入原稿并保留页面与图片…';$('#send-home').disabled=true;$('#add-material').disabled=true;}
 try{const data=await fileData(file),path=/\.pdf$/i.test(file.name)?'/api/design/import-pdf':'/api/design/import-pptx';const result=await request(path,{name:file.name,data});if(!Array.isArray(result.pages)||!result.pages.length)throw Error('没有从原稿中导入页面。');
  const title=file.name.replace(/\.(pptx|pdf)$/i,'');const project=newProject(title,'');project.stage='editor';project.pages=result.pages;project.sourceFile={name:file.name,type:/\.pdf$/i.test(file.name)?'pdf':'pptx'};await createProject(project);view='editor';selectedPageId=project.pages[0]?.id||'';render({pageId:selectedPageId});notify(`原稿已导入 ${project.pages.length} 页，保留页面内容、图片与版式。可在编辑器里创建供应商版或团队版。`);
 }finally{busy=false;if(button){button.disabled=false;button.textContent='导入原稿 PPT/PDF，沿用原页';}if(fromHome){const status=$('#home-status');if(status)status.textContent='';if($('#send-home'))$('#send-home').disabled=false;if($('#add-material'))$('#add-material').disabled=false;}}
}

async function importDesignFiles(files){
 if(busy||designController)throw Error('请等待当前任务完成后导入。');if(!files.length)return;const owner=store.project.id;busy=true;
 try{const pages=[],inputs=[];for(const file of files){if(/\.pptx$/i.test(file.name)){if(file.size>20*1024*1024)throw Error('PPTX需小于20MB。');const data=await new Promise((res,rej)=>{const reader=new FileReader();reader.onload=()=>res(reader.result.split(',')[1]);reader.onerror=rej;reader.readAsDataURL(file);});const result=await request('/api/design/import-pptx',{name:file.name,data});pages.push(...result.pages);}else{if(file.size>2*1024*1024)throw Error('单个SVG需小于2MB。');inputs.push({id:crypto.randomUUID(),title:file.name.replace(/\.svg$/i,''),body:'',role:'content',svg:await file.text()});}}
 if(inputs.length){const result=await request('/api/design/import-svg',{pages:inputs,themeId:store.project.themeId});pages.push(...result.pages);}if(store.project?.id!==owner)throw Error('已切换文稿，导入未应用。');if(store.project.pages.length+pages.length>100)throw Error('导入后超过100页，请拆分文稿。');store.commit(p=>{p.pages.push(...pages);p.designEngine='svg';},'导入可编辑设计');render({pageId:pages[0]?.id});notify(`已导入 ${pages.length} 页，文字与图形可分别编辑。`);
 }finally{busy=false;}
}

async function extractPageArtwork(pageId){
 if(busy||designController)throw Error('请先完成当前操作。');
 await store.flush();const owner=store.project?.id,revision=store.project?.revision,source=store.project?.pages.find(p=>p.id===pageId);
 if(!source)throw Error('页面不存在。');const before=JSON.stringify(source);
 const result=await request('/api/design/artwork-layers',{projectId:owner,pageId,revision},AbortSignal.timeout(240000));
 if(store.project?.id!==owner||store.project.revision!==revision||JSON.stringify(store.project.pages.find(p=>p.id===pageId))!==before)throw Error('等待期间文稿已有修改，拆分结果未覆盖新内容。');
 if(result.projectId!==owner||result.sourceRevision!==revision||result.page?.id!==pageId||result.page.title!==source.title||result.page.body!==source.body||result.page.editableArtwork?.version!==1||result.review?.matches!==true||result.review.backgroundIsTextureOnly!==true)throw Error('拆分结果未通过范围与完整性检查。');
 const oldBackground=source.objects.filter(o=>o.type==='image'&&o.layoutManaged&&!o.custom&&o.x===0&&o.y===0&&o.w===1280&&o.h===720);
 if(oldBackground.length!==1)throw Error('原底图已变化。');
 for(const o of source.objects.filter(o=>o.id!==oldBackground[0].id))if(JSON.stringify(o)!==JSON.stringify(result.page.objects.find(n=>n.id===o.id)))throw Error('拆分结果改变了原有对象，未应用。');
 store.commit(p=>{const index=p.pages.findIndex(x=>x.id===pageId);p.pages[index]=result.page;},'拆分本页线条和图片');
 await store.flush();notify('本页线条和图片已可分别选中、移动和编辑；原有文字保持。');
 return result;
}
