// Isolated Slidev runtime. Never installs global packages or edits the application manifest.
import {mkdir,writeFile,readFile,copyFile} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {dirname,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
const root=fileURLToPath(new URL('../',import.meta.url));
const runtime=join(root,'data/engine-runtimes/slidev');
const lock=new URL('./slidev-runtime-lock.json',import.meta.url);
const manifest={name:'weppt-slidev-runtime',private:true,type:'module',dependencies:{'@slidev/cli':'53.1.0','@slidev/theme-default':'0.25.0','playwright-chromium':'1.65.0'}};
await mkdir(runtime,{recursive:true});
await writeFile(join(runtime,'package.json'),JSON.stringify(manifest,null,2)+'\n');
if(existsSync(lock))await copyFile(lock,join(runtime,'package-lock.json'));
const npmCandidates=[process.env.npm_execpath,join(dirname(process.execPath),'node_modules/npm/bin/npm-cli.js'),join(dirname(process.execPath),'../lib/node_modules/npm/bin/npm-cli.js'),'/usr/share/nodejs/npm/bin/npm-cli.js'].filter(Boolean);
const npmCli=npmCandidates.find(existsSync);
if(!npmCli)throw Error('Cannot locate npm CLI; run through npm run setup:slidev or install npm.');
const start=Date.now();
await new Promise((resolve,reject)=>{
 const child=spawn(process.execPath,[npmCli,existsSync(lock)?'ci':'install','--no-audit','--no-fund'],{cwd:runtime,windowsHide:true,stdio:'inherit',env:{...process.env,PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD:'1'}});
 child.on('error',reject);child.on('close',code=>code===0?resolve():reject(Error('Slidev dependency install failed: '+code)));
});
const result={installed:true,versions:manifest.dependencies,elapsedMs:Date.now()-start,runtime,browser:'Uses WEPPT_BROWSER_PATH or platform browser; browser binaries not globally installed'};
await writeFile(join(runtime,'setup-result.json'),JSON.stringify(result,null,2));
console.log(JSON.stringify(result));
