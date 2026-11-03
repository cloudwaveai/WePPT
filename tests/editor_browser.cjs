// Run against an isolated demo workspace; changes its demo page during acceptance.
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const {chromium}=require(process.env.PPT_PLAYWRIGHT_MODULE || 'playwright');
const url=process.env.PPT_STUDIO_TEST_URL;
if(!url)throw Error('Set PPT_STUDIO_TEST_URL to an isolated demo workspace.');
const output=process.env.PPT_BROWSER_OUTPUT || '/tmp/weppt-editor-browser';
(async()=>{
  await fs.mkdir(output,{recursive:true});
  const browser=await chromium.launch({channel:process.env.PPT_BROWSER_CHANNEL || 'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:950},baseURL:new URL(url).origin}),errors=[];
    page.setDefaultTimeout(15000);
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(url);await page.locator('.page-frame.active').waitFor();
    const state=()=>page.request.get('/api/state').then(r=>r.json());
    const initial=await state(),sid=initial.selectedSlideId;
    const scene=()=>page.request.get(`/api/scene?slide=${sid}`).then(r=>r.json());
    const first=await scene(),object=first.scene.objects.find(o=>o.type==='text');
    const current=async()=>(await scene()).scene.objects.find(o=>o.id===object.id);
    async function ready(){
      const saved=await scene();
      await page.waitForFunction(({sid,revision})=>{
        const frame=document.querySelector('.page-frame.active');
        return frame?.dataset.interactive==='true' && !frame.inert
          && frame.dataset.previewKey.startsWith(`${sid}:${revision}:`)
          && !document.querySelector('.page-frame:not(.active)');
      },{sid,revision:saved.sceneRevision});
    }
    async function waitValue(key,value){await page.waitForFunction(async({sid,id,key,value})=>{const r=await(await fetch(`/api/scene?slide=${sid}`)).json();return r.scene.objects.find(o=>o.id===id)[key]===value;},{sid,id:object.id,key,value});await ready();}
    const target=()=>page.frameLocator('.page-frame.active').locator(`[data-object-id="${object.id}"]`);
    await page.waitForFunction(()=>document.querySelector('#editor-save-state').textContent==='已保存');
    await target().click({position:{x:10,y:10}});await page.locator('#font-size').waitFor({state:'visible'});await page.waitForFunction(()=>!document.querySelector('#text-format').disabled);
    const nextSize=object.fontSize===42?44:42;
    await page.locator('#font-size').fill(String(nextSize));await page.locator('#font-size').press('Enter');await page.locator('#font-size').blur();await waitValue('fontSize',nextSize);
    console.log('PASS font size persists through the real edit API');
    await page.locator('#undo-button').click();await waitValue('fontSize',object.fontSize);
    await page.locator('#redo-button').click();await waitValue('fontSize',nextSize);
    await page.reload();await ready();await target().click({position:{x:10,y:10}});await page.waitForFunction(()=>!document.querySelector('#text-format').disabled);
    assert.equal(await page.locator('#font-size').inputValue(),String(nextSize));
    console.log('PASS undo, redo and reload retain edit state');
    const prior=await current();
    const box=await target().boundingBox();
    await page.mouse.move(box.x+box.width*.5,box.y+box.height*.6);await page.mouse.down();await page.mouse.move(box.x+box.width*.5+22,box.y+box.height*.6+18,{steps:8});await page.mouse.up();
    await page.waitForFunction(async({sid,id,x})=>{const r=await(await fetch(`/api/scene?slide=${sid}`)).json();return r.scene.objects.find(o=>o.id===id).x!==x;},{sid,id:object.id,x:prior.x});await ready();
    const moved=await current();assert(moved.x>prior.x);assert.equal(moved.text,prior.text);
    console.log('PASS object dragging changes geometry without altering text');
    await target().click({position:{x:10,y:10}});const handle=page.frameLocator('.page-frame.active').locator('.resize-handle.se');await handle.waitFor({state:'visible'});
    const handleBox=await handle.boundingBox();await page.mouse.move(handleBox.x+5,handleBox.y+5);await page.mouse.down();await page.mouse.move(handleBox.x+30,handleBox.y+18,{steps:6});await page.mouse.up();
    await page.waitForFunction(async({sid,id,w})=>{const r=await(await fetch(`/api/scene?slide=${sid}`)).json();return r.scene.objects.find(o=>o.id===id).w!==w;},{sid,id:object.id,w:moved.w});await ready();
    console.log('PASS resize handle persists the text box size');
    await target().dblclick({position:{x:10,y:10}});await page.locator('#text-editor').waitFor({state:'visible'});
    const content=target().locator('.text-content');await content.fill('熟悉的编辑方式，随时获得 AI 建议');await page.waitForFunction(()=>document.querySelector('#object-text').value==='熟悉的编辑方式，随时获得 AI 建议');
    await page.locator('#save-object-text').click();await waitValue('text','熟悉的编辑方式，随时获得 AI 建议');
    console.log('PASS inline text editing saves and updates the actual scene');
    await page.locator('#close-assistant').click();assert.equal(await page.locator('.chat-panel').isVisible(),false);
    await page.locator('#toggle-assistant').click();assert.equal(await page.locator('.chat-panel').isVisible(),true);
    await page.locator('#zoom-in').click();assert.equal(await page.locator('#zoom-label').textContent(),'110%');await page.locator('#zoom-fit').click();
    console.log('PASS assistant collapse and canvas zoom');
    await page.locator('[data-ai-action="polish"]').click();await page.locator('#connection-dialog').waitFor({state:'visible'});await page.locator('#close-connection').click();
    assert.match(await page.locator('#ai-status').textContent(),/连接/);
    console.log('PASS missing model is shown without a fake recommendation');
    await page.screenshot({path:`${output}/desktop.png`,fullPage:true});
    await page.setViewportSize({width:390,height:844});await page.locator('[data-mobile-tab="preview"]').click();
    assert.equal(await page.locator('.preview-panel .filmstrip').isVisible(),true);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:`${output}/mobile.png`,fullPage:true});
    console.log('PASS narrow viewport retains page navigation without horizontal overflow');
    assert.deepEqual(errors,[]);console.log('PASS no browser runtime errors');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
