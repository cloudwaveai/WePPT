const assert=require('node:assert/strict'),fs=require('fs');
const {chromium}=require(process.env.PPT_PLAYWRIGHT_MODULE || 'playwright');
const url=process.env.PPT_STUDIO_TEST_URL;if(!url)throw Error('Set an isolated test project URL');
const origin=new URL(url).origin,pid=new URL(url).searchParams.get('project');
const out=process.env.PPT_BROWSER_OUTPUT||'/tmp/weppt-template-adaptation';fs.mkdirSync(out,{recursive:true});
(async()=>{const b=await chromium.launch({headless:true,executablePath:process.env.WEPPT_CHROMIUM||(process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':'chromium')});try{
 const page=await b.newPage({viewport:{width:1440,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url,{waitUntil:'domcontentloaded'});await page.locator('.page-frame.active').waitFor({timeout:30000});
 const state=await(await page.request.get(origin+'/api/state?project='+pid)).json(),sid=state.selectedSlideId;
 if(!['codex','claude','api'].includes(state.agent?.mode)||!state.agent?.available){console.log('SKIP template adaptation needs a configured model (set one for this project)');return;}
 const read=async()=>await(await page.request.get(origin+'/api/scene?project='+pid+'&slide='+sid)).json();const before=await read();
 const geometry=await page.evaluate(()=>{const box=s=>{const r=document.querySelector(s).getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,height:r.height}};return {header:box('.app-header'),ribbon:box('.ribbon'),assistant:box('.chat-panel'),feed:box('.chat-feed'),composer:box('.composer')}});
 assert.equal(geometry.assistant.y,52);assert(geometry.ribbon.right<=geometry.assistant.x+1);assert(geometry.feed.height>=350,JSON.stringify(geometry));assert(geometry.composer.height<190);
 await page.screenshot({path:out+'/taller-assistant.png'});
 await page.locator('#ribbon-design-tab').click();await page.locator('#ribbon-styles').click();await page.locator('[data-template-filter="reference"]').click();await page.locator('#template-roles button').filter({hasText:'全部用途'}).click();
 const card=page.locator('#template-grid .template-card').filter({has:page.locator('strong',{hasText:'深浅双栏四项对照'})});await card.click();
 await page.frameLocator('#template-after').locator('#slide').waitFor();assert(await page.locator('#template-preview-apply').isDisabled());assert.equal((await read()).sceneRevision,before.sceneRevision);
 await page.locator('#template-adaptation-approach').selectOption('content');
 const responsePromise=page.waitForResponse(r=>r.url().includes('/api/templates/adapt')&&r.request().method()==='POST',{timeout:600000});
 await page.locator('#template-generate').click();const response=await responsePromise;const proposal=await response.json();assert(response.ok(),JSON.stringify(proposal));
 await page.waitForFunction(()=>!document.querySelector('#template-preview-apply').disabled,{},{timeout:30000});
 assert.equal(proposal.referenceReadMode,'image-and-layout');assert.deepEqual(proposal.measurement.overflow,[]);assert.equal((await read()).sceneRevision,before.sceneRevision);
 await page.screenshot({path:out+'/reference-and-ai-preview.png'});await page.frameLocator('#template-after').locator('#slide').screenshot({path:out+'/adapted-slide.png'});
 await Promise.all([page.waitForResponse(r=>r.url().includes('/api/templates/apply')&&r.request().method()==='POST'),page.locator('#template-preview-apply').click()]);await page.locator('#template-preview-dialog').waitFor({state:'hidden'});
 const applied=await read();assert.equal(applied.scene.templateId,'reference-04-09');assert.equal(applied.sceneRevision,before.sceneRevision+1);
 for(const o of before.scene.objects.filter(o=>['text','image'].includes(o.type))){const n=applied.scene.objects.find(n=>n.id===o.id);assert(n);assert.equal(n.text,o.text);assert.equal(n.src,o.src);}
 await page.locator('#close-templates').click();await page.locator('#ribbon-home-tab').click();await page.locator('.page-frame.active').waitFor();await page.screenshot({path:out+'/applied-workbench.png'});
 const applyRevision=applied.sceneRevision;
 await Promise.all([page.waitForResponse(r=>r.url().includes('/api/editor/history')&&r.request().method()==='POST'),page.locator('#undo-button').click()]);assert.deepEqual((await read()).scene,before.scene);
 await Promise.all([page.waitForResponse(r=>r.url().includes('/api/editor/history')&&r.request().method()==='POST'),page.locator('#redo-button').click()]);assert.deepEqual((await read()).scene,applied.scene);
 await page.setViewportSize({width:1100,height:800});const compact=await page.evaluate(()=>({feed:document.querySelector('.chat-feed').getBoundingClientRect().height,top:document.querySelector('.chat-panel').getBoundingClientRect().y}));assert.equal(compact.top,52);assert(compact.feed>220);
 await page.setViewportSize({width:390,height:844});await page.locator('[data-mobile-tab="chat"]').click();assert(await page.locator('.chat-panel').isVisible());await page.screenshot({path:out+'/mobile-assistant.png'});
 assert.deepEqual(errors,[]);const report={projectId:pid,geometry,compact,model:proposal.modelBinding,referenceReadMode:proposal.referenceReadMode,proposalId:proposal.proposalId,applyRevision,previewDidNotMutate:true,allContentPreserved:true,undoRedoExact:true,errors};fs.writeFileSync(out+'/browser-check.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}catch(e){console.error(e);throw e}finally{await b.close()}})().catch(()=>process.exit(1));
