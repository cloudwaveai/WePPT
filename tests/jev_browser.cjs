const assert=require('node:assert/strict');
const {chromium}=require(process.env.PPT_PLAYWRIGHT_MODULE || 'playwright');
const url=process.env.PPT_STUDIO_TEST_URL;
if(!url)throw Error('Set PPT_STUDIO_TEST_URL. Clicking smart selection calls the configured model.');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.WEPPT_CHROMIUM||(process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':'chromium')});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],posts=[];
  page.setDefaultTimeout(60000);page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST' && r.url().includes('/api/templates/recommendations'))posts.push(r);});
  await page.goto(url,{waitUntil:'domcontentloaded'});
  await page.locator('.slide-thumb.active').waitFor();
  const origin=new URL(url).origin;
  const state=await(await page.request.get(origin+'/api/state')).json(),sid=state.selectedSlideId;
  const read=async()=>await(await page.request.get(origin+'/api/scene?slide='+sid+'&metadata=1')).json();
  const before=await read();
  await page.locator('#ribbon-design-tab').click();await page.locator('#ribbon-styles').click();
  await page.waitForFunction(()=>!document.querySelector('#template-smart').disabled);
  assert.equal(posts.length,0,'Opening templates must not call the decision model');
  async function choose(){
   const pending=page.waitForResponse(r=>r.url().includes('/api/templates/recommendations')&&r.request().method()==='POST');
   await page.locator('#template-smart').click();
   const response=await pending;assert(response.ok());
   const result=await response.json();
   assert.equal(result.recommendationEngine,'jev',JSON.stringify({engine:result.recommendationEngine,status:result.recommendationStatus}));
   await page.waitForFunction(()=>document.querySelector('#template-smart-status').textContent.includes('智能选版完成'));
   assert.equal(await page.locator('#template-grid .template-card strong').first().innerText(),result.recommendations[0].name);
   return result;
  }
  await choose();const cached=await choose();assert.equal(cached.cached,true);
  assert.equal(posts.length,2);
  assert.deepEqual(await read(),before,'Recommendation must leave page untouched');
  const out=process.env.PPT_BROWSER_OUTPUT || '/tmp/weppt-jev-browser-output';
  await require('node:fs/promises').mkdir(out,{recursive:true});
  await page.screenshot({path:out+'/smart-selection.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS explicit smart selection, Jev order, cached repeat, unchanged scene, no JS errors');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
