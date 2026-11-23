// Isolated, resumable real-model validation. Never calls project save endpoints.
import {readFile,writeFile,mkdir,rename} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {createHash} from 'node:crypto';
import {generateSvgDesign} from '../svg-design-ai.mjs';
import {reviewDesign} from '../design-ai.mjs';
import {renderDesignEvidence} from '../render-design.mjs';
import {auditThemeCatalog,PILOT_THEME_IDS} from '../theme-design-profile.mjs';
import {fitGeneratedDecorations} from './fit-generated-decorations.mjs';
const args=process.argv.slice(2),arg=(key,fallback)=>{const i=args.indexOf(key);return i<0?fallback:args[i+1];};
const directory=resolve(arg('--out','tests/artifacts/template-rollout'));
await mkdir(directory,{recursive:true});
const catalog=JSON.parse(await readFile(new URL('../public/templates.json',import.meta.url),'utf8'));
const readiness=await auditThemeCatalog(catalog);await writeFile(join(directory,'readiness.json'),JSON.stringify(readiness,null,2));
const ids=arg('--themes','').split(',').filter(Boolean),themes=ids.length?catalog.filter(t=>ids.includes(t.id)):args.includes('--all')?catalog:catalog.filter(t=>PILOT_THEME_IDS.includes(t.id));
if(ids.some(id=>!catalog.some(t=>t.id===id)))throw Error('Unknown template');
const estimate={templates:themes.length,pages:themes.length*3,minimumGenerationCalls:themes.length*3,minimumReviewCalls:themes.length,maximumParallelCalls:2,maxRepairRounds:2,notes:'Actual duration varies. 90s generation timeout; visual review and up to two repair/review rounds add time. Static readiness is not rendered acceptance.'};
console.log(JSON.stringify(estimate));
if(!args.includes('--live')){console.log('Static asset audit only. Pass --live to run real generation and visual review.');process.exit(0);}
const source=JSON.parse(await readFile(resolve(arg('--source','tests/fixtures/engine-five.json')),'utf8'));
const selected=[],take=p=>{if(p&&!selected.some(s=>s.id===p.id))selected.push(p);};
take(source.pages.find(p=>p.role==='cover')||source.pages[0]);take(source.pages.find(p=>p.role==='toc'));
take(source.pages.filter(p=>!selected.some(s=>s.id===p.id)).sort((a,b)=>String(b.body||'').length-String(a.body||'').length)[0]);
for(const p of source.pages)if(selected.length<Math.min(3,source.pages.length))take(p);
const sourceFingerprint=createHash('sha256').update(JSON.stringify(selected.map(({id,title,body,role})=>({id,title,body,role})))).digest('hex');
const dataDir=join(directory,'isolated-data');await mkdir(dataDir,{recursive:true});
let cursor=0;
async function save(file,value){await writeFile(file+'.tmp',JSON.stringify(value,null,2));await rename(file+'.tmp',file);}
async function worker(){while(cursor<themes.length){
 const theme=themes[cursor++],dir=join(directory,theme.id);await mkdir(dir,{recursive:true});const statusPath=join(dir,'status.json');let prior;
 try{prior=JSON.parse(await readFile(statusPath,'utf8'));}catch{}
 if(prior?.status==='passed'&&prior.sourceFingerprint===sourceFingerprint&&prior.profileVersion===1&&!args.includes('--rerun')){console.log(theme.id+' cached passed');continue;}
 let project={...structuredClone(source),id:'validation-'+theme.id,themeId:theme.id,designEngine:'svg',pages:structuredClone(selected).map(p=>({...p,objects:[]}))};
 let records=[],status={themeId:theme.id,sourceFingerprint,profileVersion:1,status:'running',startedAt:new Date().toISOString(),selectedPageIds:selected.map(p=>p.id),records,repairRounds:0};await save(statusPath,status);
 try{
  for(const sourcePage of project.pages){const file=join(dir,sourcePage.id.replace(/[^\w-]/g,'_')+'.json');let result;
   if(!args.includes('--rerun'))try{const cached=JSON.parse(await readFile(file,'utf8'));if(cached.sourceTitle===sourcePage.title&&cached.sourceBody===sourcePage.body&&cached.profileVersion===1)result=cached.result;}catch{}
   for(let attempt=1;!result&&attempt<=2;attempt++){const start=Date.now();try{result=await generateSvgDesign({project,targetPageIds:[sourcePage.id],themeId:theme.id,instruction:'忠实于所选模板的视觉身份，按内容独立设计；完整保留所有原文和标点，照片不裁碎，不使用占位框。不要给g组合添加clip-path；装饰应直接绘制在画布内。中文正文留足实际栏宽，避免把候选人、录音时间点、已覆盖权重、完整总分、能力维度等术语拆到两行。'+(attempt>1?' 上次生成错误，请避免：'+records.at(-1)?.error:'' )},{dataDir,artifactDir:join(dir,'model-'+sourcePage.id+'-'+attempt)});records.push({pageId:sourcePage.id,attempt,elapsedMs:Date.now()-start,ok:true});}catch(e){records.push({pageId:sourcePage.id,attempt,elapsedMs:Date.now()-start,ok:false,error:e.message});if(attempt===2)throw e;}await save(statusPath,status);}
   await save(file,{sourceTitle:sourcePage.title,sourceBody:sourcePage.body,profileVersion:1,result});project.pages=project.pages.map(p=>p.id===sourcePage.id?result.pages[0]:p);await save(join(dir,'project.json'),project);
  }
  for(let round=0;round<=2;round++){
   const geometryRepairs=fitGeneratedDecorations(project);
   if(geometryRepairs.length){status.geometryRepairs=[...(status.geometryRepairs||[]),...geometryRepairs];await save(join(dir,'project.json'),project);}
   const evidence=await renderDesignEvidence(project,{directory:join(dir,'preview')});await save(join(dir,'render.json'),evidence);
   const review=await reviewDesign({project,instruction:'重点核对所选模板视觉身份、完整标题、图片裁片是否含参考文字、植物/照片是否退化为空占位框。检查三页是否按内容组织且没有重叠溢出。'},{dataDir});await save(join(dir,'review-'+round+'.json'),review);
   const issues=[...evidence.issues,...review.issues].filter(i=>i.severity!=='info');status.issues=issues;status.repairRounds=round;await save(statusPath,status);
   if(!issues.length){status.status='passed';break;}
   if(round===2){status.status='needs-attention';break;}
   for(const id of [...new Set(issues.map(i=>i.pageId))]){
    if(!project.pages.some(p=>p.id===id))continue;
    const result=await generateSvgDesign({project,targetPageIds:[id],themeId:theme.id,instruction:'保持模板身份与完整文案，修正实际审看问题；不要给g组合添加clip-path，中文正文留足栏宽避免术语拆行：'+JSON.stringify(issues.filter(i=>i.pageId===id)).slice(0,4800)},{dataDir,artifactDir:join(dir,'repair-'+round+'-'+id)});project.pages=project.pages.map(p=>p.id===id?result.pages[0]:p);
   }
   await save(join(dir,'project.json'),project);
  }
 }catch(error){status.status='failed';status.error=error.message;}
 status.finishedAt=new Date().toISOString();await save(statusPath,status);console.log(JSON.stringify({themeId:theme.id,status:status.status,issues:status.issues?.length,error:status.error}));
}}
const workers=Math.max(1,Math.min(2,Number(arg('--workers','2'))||2));
await Promise.all(Array.from({length:workers},worker));
const results=[];for(const theme of themes){try{results.push(JSON.parse(await readFile(join(directory,theme.id,'status.json'),'utf8')));}catch{results.push({themeId:theme.id,status:'not-run'});}}
await save(join(directory,'summary.json'),{estimate,results,passed:results.filter(r=>r.status==='passed').length,total:results.length});
if(results.some(r=>r.status!=='passed'))process.exitCode=1;
