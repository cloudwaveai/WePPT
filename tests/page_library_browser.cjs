const assert=require('node:assert/strict'),fs=require('node:fs/promises');
const {chromium}=require('playwright-core');
(async()=>{
const url=process.env.PPT_STUDIO_TEST_URL,origin=new URL(url).origin,output=process.env.PPT_BROWSER_OUTPUT||'/tmp/weppt-page-library';await fs.mkdir(output,{recursive:true});
const b=await chromium.launch({headless:true,executablePath:process.env.WEPPT_CHROMIUM});
try{
 const p=await b.newPage({viewport:{width:1440,height:950},baseURL:origin}),errors=[];p.on('pageerror',e=>errors.push(e.message));await p.goto(url);
 const created=await p.request.post('/api/projects',{headers:{Origin:origin},data:{title:'页面样式检查 2026-11-05'}}).then(r=>r.json());assert(created.projectId);
 const headers={Origin:origin,'X-WePPT-Project':created.projectId};
 const request=async(path)=>p.request.get(path,{headers}).then(r=>r.json());
 await p.request.post('/api/demo',{headers,data:{}});await p.goto(origin+'/?project='+created.projectId);
 await p.locator('.page-frame.active').waitFor();
 const beforeState=await request('/api/state'),sid=beforeState.selectedSlideId;
 const before=await request('/api/scene?slide='+sid);
 const catalog=await request('/api/templates');const cards=Array.isArray(catalog)?catalog:catalog.templates;
 assert.equal(cards.filter(t=>t.current).length,16);assert(cards.some(t=>t.archived));assert(cards.some(t=>t.reference));
 await p.locator('#ribbon-design-tab').click();await p.locator('#template-strip .ribbon-template').first().waitFor();
 for(const category of ['封面','目录','章节','正文','对比','流程','数据','结束']){
  await p.locator('#template-categories button').filter({hasText:new RegExp('^'+category+' ·')}).click();
  assert(await p.locator('#template-strip .ribbon-template').count()>0,category);
 }
 await p.locator('#template-categories button').filter({hasText:/^正文 ·/}).click();
 await p.screenshot({path:output+'/page-library-strip.png'});
 const card=p.locator('#template-strip .ribbon-template').filter({hasText:'编辑式正文'});await card.click();
 await p.locator('#template-preview-apply').waitFor();await p.waitForFunction(()=>!document.querySelector('#template-preview-apply').disabled);
 await p.locator('#template-after').contentFrame().locator('#slide').waitFor();
 assert.equal((await request('/api/scene?slide='+sid)).sceneRevision,before.sceneRevision);
 await p.screenshot({path:output+'/page-library-preview.png'});
 await p.locator('#template-preview-apply').click();await p.locator('#template-preview-dialog').waitFor({state:'hidden'});
 const applied=await request('/api/scene?slide='+sid);assert.equal(applied.scene.templateId,'pagekit-editorial-v1');assert.equal(applied.sceneRevision,before.sceneRevision+1);
 for(const old of before.scene.objects.filter(o=>o.type==='text'||o.type==='image')){
  const obj=applied.scene.objects.find(o=>o.id===old.id);assert(obj,old.id);
  for(const k of ['text','binding','src'])assert.deepEqual(obj[k],old[k]);
 }
 await p.locator('#ribbon-home-tab').click();await p.locator('#undo-button').click();
 await p.waitForFunction(async({sid,project})=>{const r=await fetch('/api/scene?slide='+sid,{headers:{'X-WePPT-Project':project}}).then(r=>r.json());return r.scene.templateId!=='pagekit-editorial-v1';},{sid,project:created.projectId});
 const undone=await request('/api/scene?slide='+sid);assert.deepEqual(undone.scene,before.scene);
 assert.deepEqual(errors,[]);await fs.writeFile(output+'/page-library-checks.json',JSON.stringify({projectId:created.projectId,current:16,allCategories:true,previewReadOnly:true,applied:true,undoExact:true,errors},null,2));
 console.log('PASS 16 current styles; all strip categories; real page preview without model; apply preserves content; undo restores exact scene; originals remain available');
}finally{await b.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
