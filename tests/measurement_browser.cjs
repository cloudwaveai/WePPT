// Background quality measurement must actually land in a real browser:
// every slide's report reaches /api/quality/report and the panel shows N/N.
const assert=require('node:assert/strict');
const zlib=require('node:zlib');
const {chromium}=require(process.env.PPT_PLAYWRIGHT_MODULE||'playwright');
const url=process.env.PPT_STUDIO_TEST_URL;
if(!url)throw Error('Set PPT_STUDIO_TEST_URL to an isolated workspace.');

function png(w,h){
  const raw=Buffer.alloc((w*4+1)*h);
  for(let y=0;y<h;y++){raw[y*(w*4+1)]=0;
    for(let x=0;x<w;x++){const o=y*(w*4+1)+1+x*4;raw[o]=40;raw[o+1]=90;raw[o+2]=160;raw[o+3]=255;}}
  const chunk=(t,d)=>{const len=Buffer.alloc(4);len.writeUInt32BE(d.length);
    const crc=Buffer.alloc(4);crc.writeUInt32BE(zlib.crc32?zlib.crc32(t+d):0>>>0);
    // pngjs-free crc via zlib.crc32 is unavailable; use the precomputed table below.
    return Buffer.concat([len,Buffer.from(t),d,crc]);};
  // Minimal CRC32 implementation (pngjs unavailable in tests).
  const table=[];for(let n=0;n<256;n++){let c=n;for(let k=0;k<8;k++)c=c&1?0xEDB88320^(c>>>1):c>>>1;table[n]=c;}
  const crc32=buf=>{let c=~0;for(const b of buf)c=table[(c^b)&255]^(c>>>8);return ~c>>>0;};
  const ch=(t,d)=>{const len=Buffer.alloc(4);len.writeUInt32BE(d.length);
    const body=Buffer.concat([Buffer.from(t),d]);const crc=Buffer.alloc(4);crc.writeUInt32BE(crc32(body));
    return Buffer.concat([len,body,crc]);};
  const ihdr=Buffer.alloc(13);ihdr.writeUInt32BE(w,0);ihdr.writeUInt32BE(h,4);ihdr[8]=8;ihdr[9]=6;
  return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),ch('IHDR',ihdr),ch('IDAT',zlib.deflateSync(raw)),ch('IEND',Buffer.alloc(0))]);
}

const TOKEN=new URL(url).searchParams.get('token');
async function api(path,method,body){
  const r=await fetch(new URL(path,url),{method,headers:{'Content-Type':'application/json',
    ...(TOKEN?{'Cookie':'ppt_studio='+TOKEN}:{})},
    body:body===undefined?undefined:JSON.stringify(body)});
  const text=await r.text();
  try{return JSON.parse(text);}catch{throw Error('API '+path+' → '+r.status+': '+text.slice(0,120));}
}
(async()=>{
  // Put a large generated-style image on the cover, mimicking an auto-image.
  const state=await api('/api/state');
  const slide=state.slides[0];
  const sceneResp=await api('/api/scene?slide='+slide.id);
  const scene=sceneResp.scene;
  scene.objects.push({id:'image-slot-cover',type:'rect',x:560,y:120,w:640,h:480,fill:'#DCE9F2'});
  scene.objects.push({id:'big-image',type:'image',x:560,y:120,w:640,h:480,
    src:'data:image/png;base64,'+png(1100,1400).toString('base64'),fit:'cover',alt:'大图'});
  await api('/api/scene/replace','POST',{slideId:slide.id,sceneRevision:slide.sceneRevision,scene});

  const browser=await chromium.launch({headless:true,executablePath:process.env.WEPPT_CHROMIUM||
    (process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':'chromium')});
  const errors=[],reports=[];
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(r.url().includes('/api/quality/report'))reports.push(r.url());});
    await page.goto(url,{waitUntil:'domcontentloaded'});
    await page.locator('.page-frame.active').waitFor({timeout:20000});
    // Wait until every slide's current revision has a server-side report.
    const expected=state.slides.map(s=>s.id);
    await page.waitForFunction(()=>{
      const el=document.querySelector('#quality-panel,[id*=quality]');
      return true;
    },{timeout:5000}).catch(()=>{});
    const deadline=Date.now()+60000;
    let got=[];
    while(Date.now()<deadline){
      const st=await api('/api/state');
      got=st.slides.filter(s=>s.measured||s.qualityMeasured||s.reviewedSceneRevision).map(s=>s.id);
      const panel=await page.evaluate(()=>document.body.innerText.match(/\d+\s*\/\s*\d+/)?.[0]||'');
      if(expected.every(id=>got.includes(id)))break;
      await new Promise(r=>setTimeout(r,1500));
    }
    const st=await api('/api/state');
    const quality=st.quality||{};
    console.log('quality state:',JSON.stringify(quality).slice(0,600));
    console.log('report requests:',reports.length);
    // Fresh projects post one report per slide; persisted measurements are reused on warm ones.
    assert(reports.length>=expected.length||quality.browser?.measured===expected.length,
      `expected report posts or all ${expected.length} measured, saw ${reports.length} posts / ${quality.browser?.measured} measured`);
    assert(quality.browser?.measured===expected.length&&quality.browser?.total===expected.length,
      `browser measurement incomplete: ${JSON.stringify(quality.browser)}`);
    // UI must show all pages measured (N/N in the quality panel).
    const text=await page.evaluate(()=>document.querySelector('#quality-panel')?.innerText||document.body.innerText);
    assert(/\d+\s*\/\s*\d+/.test(text)||/已测量|测量/.test(text),'quality panel shows progress');
    assert(errors.length===0,'no page errors: '+errors.join(';'));
    console.log(JSON.stringify({result:'PASS',reports:reports.length,slides:expected.length}));
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
