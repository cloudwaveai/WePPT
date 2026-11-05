// Run all *.cjs browser tests against a fresh local demo studio.
// Usage: node tests/run_browser_tests.mjs (set WEPPT_CHROMIUM to a Chrome binary).
import {spawn, spawnSync} from 'node:child_process';
import {mkdtempSync, readdirSync, mkdirSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';

const root=mkdtempSync(join(tmpdir(),'weppt-browser-root-'));
const port=process.env.PPT_BROWSER_PORT||8799;
const server=spawn('.venv/bin/python',['-m','ppt_workbench','studio','--demo','--port',String(port)],{
  cwd:process.cwd(),env:{...process.env,PPT_WORKBENCH_ROOT:root},stdio:['ignore','pipe','inherit']});
const url=await new Promise((res,rej)=>{
  let buf='';server.stdout.on('data',d=>{buf+=d;
    const m=buf.match(/"url":\s*"([^"]+)"/);if(m)res(m[1]);});
  server.on('exit',()=>rej(new Error('studio exited: '+buf)));
  setTimeout(()=>rej(new Error('studio start timeout: '+buf)),30000);
});
console.log('studio:',new URL(url).origin,'root:',root);
const files=readdirSync('tests').filter(f=>f.endsWith('browser.cjs')).sort();
const extra=process.argv.slice(2);
const targets=extra.length?files.filter(f=>extra.some(x=>f.includes(x))):files;
const env={...process.env,PPT_STUDIO_TEST_URL:url,PPT_PLAYWRIGHT_MODULE:'playwright-core',
  PPT_BROWSER_OUTPUT:process.env.PPT_BROWSER_OUTPUT||'/tmp/weppt-browser-tests',
  WEPPT_CHROMIUM:process.env.WEPPT_CHROMIUM||(process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':'chromium')};
const results=[];
mkdirSync(env.PPT_BROWSER_OUTPUT,{recursive:true});
for(const file of targets){
  const r=spawnSync('node',['tests/'+file],{env,encoding:'utf8',timeout:Number(process.env.PPT_BROWSER_TIMEOUT||180000)});
  writeFileSync(join(env.PPT_BROWSER_OUTPUT,file+'.log'),(r.stdout||'')+'\n'+(r.stderr||'')+(r.error?'\n'+r.error.message:''));
  const tail=(r.stdout+'\n'+r.stderr).trim().split('\n').slice(-3).join(' | ');
  results.push({file,ok:r.status===0,tail});
  console.log((r.status===0?'PASS':'FAIL'),file,'—',tail.slice(0,300));
}
server.kill('SIGTERM');
const failed=results.filter(r=>!r.ok);
console.log(JSON.stringify({total:results.length,passed:results.length-failed.length,failed:failed.map(f=>f.file)}));
process.exitCode=failed.length?1:0;
