const assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
const {chromium}=require(process.env.PPT_PLAYWRIGHT_MODULE || 'playwright');
const url=process.env.PPT_STUDIO_TEST_URL;
if(!url)throw Error('Set PPT_STUDIO_TEST_URL to an isolated workspace.');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.WEPPT_CHROMIUM||(process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':'chromium')});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],requests=[],active=new Set();let max=0;
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.resourceType()==='fetch'&&/\/(?:reference-library\/previews|api\/templates\/preview|api\/preview\/)/.test(r.url())){requests.push(r.url());active.add(r);max=Math.max(max,active.size);}});
  page.on('requestfinished',r=>active.delete(r));page.on('requestfailed',r=>active.delete(r));
  await page.goto(url,{waitUntil:'domcontentloaded'});
  await page.locator('.page-frame.active').waitFor();
  await page.locator('#ribbon-design-tab').click();await page.locator('#ribbon-styles').click();
  await page.waitForFunction(()=>document.querySelectorAll('#template-roles button').length===14);
  await page.evaluate(()=>{window.savedRibbon=document.querySelector('#template-strip .ribbon-template');});
  await page.locator('[data-template-filter=reference]').click();await page.locator('[data-category=data]').click();
  const ready=()=>page.waitForFunction(()=>{const images=[...document.querySelectorAll('#template-grid img')];return images.length===2&&images.every(i=>i.complete&&i.naturalWidth>0);});
  await ready();
  assert(await page.evaluate(()=>window.savedRibbon===document.querySelector('#template-strip .ribbon-template')),'Filtering must keep ribbon DOM');
  const originalUrls=await page.locator('#template-grid img').evaluateAll(images=>images.map(img=>img.dataset.previewResource));
  for(const originalUrl of originalUrls){
   // System Chrome does not keep consumed fetch bodies for Playwright; re-read the same URL with the page's session.
   const bytes=await (await page.request.get(originalUrl)).body();
   assert(bytes.length,'Original image must be served');
   assert.equal(createHash('sha256').update(bytes).digest('hex'),new URL(originalUrl).searchParams.get('v'),'Loaded original bytes must match bundled version');
  }
  const dataRequests=()=>requests.filter(u=>/\/04-0[45]\.png/.test(u)).length;
  assert.equal(dataRequests(),2);
  await page.locator('[data-category=people]').click();await ready();
  await page.locator('[data-category=data]').click();await ready();
  assert.equal(dataRequests(),2,'Revisiting category must reuse loaded images');
  assert(max<=2,`Secondary requests in flight: ${max}`);
  const references=requests.filter(u=>u.includes('/reference-library/previews/'));
  assert(references.length<=7,`Unexpected hidden reference downloads: ${references.length}`);
  await page.locator('#template-grid .template-card').first().click();
  // With a current page, applying needs an AI adaptation preview first; the dialog must be ready to generate one.
  await page.frameLocator('#template-after').locator('#slide').waitFor();
  await page.waitForFunction(()=>!document.querySelector('#template-generate').disabled&&document.querySelector('#template-preview-apply').disabled);
  await page.locator('#template-preview-cancel').click();
  const out=process.env.PPT_BROWSER_OUTPUT || '/tmp/weppt-preview-loading';
  await require('node:fs/promises').mkdir(out,{recursive:true});
  await page.screenshot({path:out+'/data-category.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({result:'PASS',maxSecondaryConcurrent:max,referenceDownloads:references.length,originalHashes:true,ribbonPreserved:true,revisitDownloads:0,adaptationPreview:true}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
