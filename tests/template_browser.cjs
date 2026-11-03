const assert=require('node:assert/strict');
const {chromium}=require(process.env.PPT_PLAYWRIGHT_MODULE || 'playwright');
const out=process.env.PPT_BROWSER_OUTPUT || '/tmp/weppt-template-browser';
const url=process.env.PPT_STUDIO_TEST_URL; if(!url)throw Error('Set PPT_STUDIO_TEST_URL to an isolated demo workspace.');
const origin=new URL(url).origin;
(async()=>{
 await require('node:fs/promises').mkdir(out,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:process.env.WEPPT_CHROMIUM||(process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':'chromium')});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}), errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);
  await page.locator('.page-frame.active').waitFor();
  const state=await(await page.request.get(origin+'/api/state')).json(),sid=state.selectedSlideId;
  const read=async()=>await(await page.request.get(origin+'/api/scene?slide='+sid)).json();
  const before=await read();
  await page.locator('#ribbon-design-tab').click();
  await page.locator('#ribbon-styles').click();
  await page.locator('[data-template-filter="reference"]').click();
  await page.locator('#template-roles button').filter({hasText:'全部用途'}).click();
  await page.waitForFunction(()=>document.querySelectorAll('#template-grid .template-card').length===44);
  await page.screenshot({path:out+'/reference-library.png',fullPage:true});
  const card=title=>page.locator('#template-grid .template-card').filter({has:page.locator('strong',{hasText:title})});
  for(const name of ['主视觉封面','深浅双栏四项对照','四阶段分栏流程']){
   await card(name).click();
   await page.waitForFunction(()=>!document.querySelector('#template-preview-apply').disabled);
   await page.frameLocator('#template-after').locator('#slide').waitFor();
   assert.equal((await read()).sceneRevision,before.sceneRevision);
   await page.screenshot({path:out+'/'+({'主视觉封面':'cover','深浅双栏四项对照':'comparison','四阶段分栏流程':'process'}[name])+'.png',fullPage:true});
   await page.locator('#template-preview-cancel').click();
  }
  await card('深浅双栏四项对照').click();await page.waitForFunction(()=>!document.querySelector('#template-preview-apply').disabled);
  await page.locator('#template-preview-apply').click();await page.locator('#template-preview-dialog').waitFor({state:'hidden'});
  const applied=await read();assert.equal(applied.scene.templateId,'reference-04-09');assert.equal(applied.sceneRevision,before.sceneRevision+1);
  for(const old of before.scene.objects.filter(o=>o.type==='text'||o.type==='image')){const after=applied.scene.objects.find(o=>o.id===old.id);assert(after);assert.equal(after.text,old.text);assert.equal(after.src,old.src);}
  await page.locator('#close-templates').click();await page.locator('#ribbon-home-tab').click();await page.locator('#undo-button').click();
  await page.waitForFunction(async({sid,rev})=>{const r=await(await fetch('/api/scene?slide='+sid)).json();return r.sceneRevision>rev;},{sid,rev:applied.sceneRevision});
  assert.deepEqual((await read()).scene,before.scene);console.log('PASS apply and undo');
  // Real stale preview: edit saved page while the candidate remains open.
  await page.locator('#ribbon-design-tab').click();await page.locator('#ribbon-styles').click();await page.locator('#template-roles button').filter({hasText:'全部用途'}).click();await card('深浅双栏四项对照').click();await page.waitForFunction(()=>!document.querySelector('#template-preview-apply').disabled);
  const current=await read();const text=current.scene.objects.find(o=>o.type==='text');
  const r=await page.request.post(origin+'/api/edit',{headers:state.csrfToken?{'X-PPT-CSRF':state.csrfToken}:{},data:{slideId:sid,sceneRevision:current.sceneRevision,changes:[{objectId:text.id,properties:{fontSize:text.fontSize+1}}]}});assert(r.ok(),await r.text());
  await page.locator('#template-preview-apply').click();
  await page.waitForFunction(()=>/变化|未应用/.test(document.querySelector('#template-preview-status').textContent));
  assert.equal((await read()).sceneRevision,current.sceneRevision+1);
  await page.reload();await page.locator('.page-frame.active').waitFor();await page.locator('#ribbon-design-tab').click();await page.locator('#ribbon-styles').click();await page.locator('[data-template-filter=reference]').click();await page.locator('#template-roles button').filter({hasText:'全部用途'}).click();await page.setViewportSize({width:390,height:844});
  await card('深浅双栏四项对照').click();await page.waitForFunction(()=>!document.querySelector('#template-preview-apply').disabled);
  await page.screenshot({path:out+'/mobile-preview.png',fullPage:true});
  assert.deepEqual(errors,[]);console.log('PASS 44 references, 3 rendered previews, readonly, apply, unchanged text/image payload, undo, stale rejection, mobile, no JS errors');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
