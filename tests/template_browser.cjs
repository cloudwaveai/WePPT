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
   // With a current page, applying needs an AI adaptation preview first; the dialog must be ready to generate one.
   await page.frameLocator('#template-after').locator('#slide').waitFor();
   await page.waitForFunction(()=>!document.querySelector('#template-generate').disabled&&document.querySelector('#template-preview-apply').disabled);
   assert.equal((await read()).sceneRevision,before.sceneRevision);
   await page.screenshot({path:out+'/'+({'主视觉封面':'cover','深浅双栏四项对照':'comparison','四阶段分栏流程':'process'}[name])+'.png',fullPage:true});
   await page.locator('#template-preview-cancel').click();
  }
  // Applying now always goes through an AI adaptation preview (needs a model); apply, undo and stale
  // rejection are covered by tests/test_template_adaptation.py.
  await page.reload();await page.locator('.page-frame.active').waitFor();await page.locator('#ribbon-design-tab').click();await page.locator('#ribbon-styles').click();await page.locator('[data-template-filter=reference]').click();await page.locator('#template-roles button').filter({hasText:'全部用途'}).click();await page.setViewportSize({width:390,height:844});
  await card('深浅双栏四项对照').click();await page.frameLocator('#template-after').locator('#slide').waitFor();
  await page.screenshot({path:out+'/mobile-preview.png',fullPage:true});
  assert.deepEqual(errors,[]);console.log('PASS 44 references, 3 rendered previews, readonly, mobile, no JS errors');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
