import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
async function run(exe,args,options={}){return new Promise((yes,no)=>{const p=spawn(exe,args,{cwd:root,windowsHide:true,...options,stdio:['pipe','pipe','pipe']});let out='',err='';p.stdout.on('data',b=>out+=b);p.stderr.on('data',b=>err=(err+b).slice(-12000));p.on('error',no);p.on('close',code=>code?no(Error(err||out||`Converter exit ${code}`)):yes(out));p.stdin.end(options.input||'');});}
try{
 let raw='';for await(const c of process.stdin)raw+=c;const input=JSON.parse(raw);
 if(!['slidev','pptagent'].includes(input.engine)||typeof input.html!=='string'||!input.outputDir)throw Error('Invalid worker request');
 const outputDir=resolve(input.outputDir);await mkdir(outputDir,{recursive:true});
 if(input.engine==='pptagent'){
  const result=await run(process.env.WEPPT_PPTAGENT_PYTHON||(process.platform==='win32'?join(root,'data/engine-runtimes/pptagent/python312/python.exe'):(process.env.PYTHON||'python3')),['-X','utf8',join(root,'scripts/pptagent-design-worker.py')],{input:JSON.stringify({slides:[{html:input.html}],outputDir})});
  process.stdout.write(JSON.stringify(JSON.parse(result)));
 }else{
  const runtime=join(root,'data/engine-runtimes/slidev');await mkdir(join(runtime,'jobs'),{recursive:true});const dir=await mkdtemp(join(runtime,'jobs/web-'));
  try{
   const entry=join(dir,'slides.md'),pptxPath=join(outputDir,'engine.pptx');
   await writeFile(entry,`---\ntheme: default\ncanvasWidth: 1280\naspectRatio: 16/9\nlayout: none\nfonts:\n  sans: Microsoft YaHei\n  local: Microsoft YaHei\n---\n\n<style>\n.slidev-layout{padding:0!important;width:1280px!important;height:720px!important;}\n${input.styles}\n</style>\n\n${input.body.replace(/\r?\n/g,' ')}\n`);
   const log=await run(process.execPath,[join(runtime,'node_modules/@slidev/cli/bin/slidev.mjs'),'export',entry,'--format','pptx-editable','--output',pptxPath,'--with-clicks','false','--executable-path',process.env.WEPPT_BROWSER_PATH||(process.platform==='win32'?'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe':'/usr/bin/chromium')],{cwd:runtime,env:{...process.env,NODE_ENV:'development'}});
   await writeFile(join(outputDir,'conversion.log'),log);process.stdout.write(JSON.stringify({pptxPath,reviewStatus:'unreviewed',finalized:false}));
  }finally{await rm(dir,{recursive:true,force:true});}
 }
}catch(error){process.stderr.write(error.stack||String(error));process.exitCode=1;}
