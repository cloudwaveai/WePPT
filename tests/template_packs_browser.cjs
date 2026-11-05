const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const {chromium}=require(process.env.PPT_PLAYWRIGHT_MODULE||'playwright-core');
const url=process.env.PPT_STUDIO_TEST_URL,output=process.env.PPT_BROWSER_OUTPUT||'/tmp/weppt-packs';
(async()=>{
 await fs.mkdir(output,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:process.env.WEPPT_CHROMIUM});
 const page=await browser.newPage({viewport:{width:1440,height:950},baseURL:new URL(url).origin});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(url);
  const created=await page.request.post('/api/projects',{headers:{Origin:new URL(url).origin},data:{title:'Template packs test'}}).then(r=>r.json());
  await page.goto(new URL('/?project='+created.projectId,url).href);
  await page.locator('#ribbon-design-tab').click();await page.locator('#ribbon-packs').click();
  await page.locator('.pack-card').nth(3).waitFor();
  assert.equal(await page.locator('.pack-previews iframe').count(),12);
  await page.locator('.pack-previews iframe').first().contentFrame().locator('#slide').waitFor();
  await page.screenshot({path:output+'/template-gallery.png',fullPage:true});
  await page.locator('[data-pack-id="spatial-translucent-planes-v1"] button').click();
  await page.locator('#packs-dialog').waitFor({state:'hidden'});
  const headers={Origin:new URL(url).origin,'X-WePPT-Project':created.projectId};
  const selected=await page.request.get('/api/template-packs',{headers}).then(r=>r.json());
  assert.equal(selected.selectedPack,'spatial-translucent-planes-v1');
  await page.reload();await page.locator('#ribbon-design-tab').click();await page.locator('#ribbon-packs').click();
  assert.equal(await page.locator('[data-pack-id="spatial-translucent-planes-v1"] button').textContent(),'已选择');
  await page.locator('#packs-close').click();
  await page.request.post('/api/demo',{headers,data:{}});await page.reload();
  await page.locator('#ribbon-design-tab').click();await page.locator('#ribbon-packs').click();
  assert.equal(await page.locator('.pack-card button').first().textContent(),'生成整套改版副本');
  const before=await page.request.get('/api/state',{headers}).then(r=>r.json());
  await page.locator('.pack-card button').first().click();
  await page.waitForFunction(()=>document.querySelector('#packs-status').textContent.includes('选择'));
  const after=await page.request.get('/api/state',{headers}).then(r=>r.json());
  assert.deepEqual(after.slides,before.slides); // no configured model: fail honestly, source unchanged
  await page.screenshot({path:output+'/template-existing-copy.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS gallery renders twelve spatial role previews; preference survives reload; existing deck uses explicit copy; missing model leaves source intact');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
