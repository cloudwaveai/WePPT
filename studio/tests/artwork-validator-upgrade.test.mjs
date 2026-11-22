import test from 'node:test';import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm} from 'node:fs/promises';import {tmpdir} from 'node:os';import {join} from 'node:path';import {randomUUID,createHash} from 'node:crypto';
import {createReferenceJobs} from '../reference-design-jobs.mjs';
const hash=value=>createHash('sha256').update(value).digest('hex');
async function fixture(t,{deleted=false,corrupt=false,alreadyUsed=false}={}){
 const dataDir=await mkdtemp(join(tmpdir(),'artwork-upgrade-'));t.after(()=>rm(dataDir,{recursive:true,force:true}));
 const id=randomUUID(),page={id:'p1',title:'完整标题',body:'完整原文',role:'content',objects:[]},project={id:'source',themeId:'curated-006',pages:[page]},fingerprint='a'.repeat(64),source=Buffer.from('hash-verified source fixture'),imageHash=hash(source),used={image:1,text:3,styleReview:0,pageRun:1};
 const checkpoint=join(dataDir,'reference-checkpoints',id,'image-background-'+hash('p1'));await mkdir(checkpoint,{recursive:true});await mkdir(join(dataDir,'reference-jobs'));
 const legacy=alreadyUsed?{version:2,fingerprint,imageHash,used:true}:undefined;
 const saved={version:1,fingerprint,layout:{boxes:[],artworkInventory:{complete:true}},artworkInventoryRepairAttempts:alreadyUsed?3:2,artworkInventoryRepairResponses:alreadyUsed?3:2,...(legacy?{legacyArtworkCorrection:legacy}:{})};
 await writeFile(join(checkpoint,'background.png'),source);await writeFile(join(checkpoint,'checkpoint.json'),JSON.stringify({version:1,fingerprint,imageHash:corrupt?'b'.repeat(64):imageHash}));await writeFile(join(checkpoint,'layout.json'),JSON.stringify(saved));
 const input={project,themeId:project.themeId,targetPageIds:['p1'],instruction:''};
 const job={version:1,pipelineVersion:6,id,editableArtworkVersion:1,artworkValidationRevision:4,input,status:'failed',pages:[],failures:[{pageId:'p1',code:'EDITABLE_ARTWORK_INVALID'}],pageStatus:[{pageId:'p1',status:'failed',attempts:1,budget:{version:1,used,backgroundReuses:0,redrawAuthorized:false,terminal:{code:'EDITABLE_ARTWORK_INVALID'}}}],compositionPlan:{targetPageIds:['p1'],pages:[{pageId:'p1'}]},pageInputs:{p1:{project,themeId:project.themeId,targetPageIds:['p1']}},createdAt:new Date().toISOString(),updatedAt:new Date().toISOString(),...(deleted?{deletedAt:new Date().toISOString()}:{})};
 const path=join(dataDir,'reference-jobs',id+'.json');await writeFile(path,JSON.stringify(job));let generated=0,planned=0;
 const jobs=createReferenceJobs({dataDir,stagePipeline:true,prepareStyle:async()=>({}),plan:async()=>{planned++;throw Error('existing plan must survive');},generate:async request=>{generated++;return {pages:[{...request.project.pages[0],themeId:project.themeId,objects:[{id:'text',type:'text',text:page.title}]}]};},review:async()=>({issues:[],summary:'controlled review',reviewEvidence:{status:'pass',checkedPageIds:['p1']}})});
 return {dataDir,id,path,checkpoint,used,jobs,calls:()=>({generated,planned})};
}
async function finish(f){for(let i=0;i<200;i++){const s=await f.jobs.get(f.id);if(!['queued','running'].includes(s.status))return s;await new Promise(r=>setTimeout(r,5));}throw Error('bounded test did not finish');}
test('revision 4 artwork can use the new deterministic validator on explicit resume without resetting paid budgets or planning',async t=>{
 const f=await fixture(t);await f.jobs.resume(f.id);const result=await finish(f);assert.equal(result.status,'completed');
 assert.deepEqual(result.pageStatus[0].budget.used,{...f.used,pageRun:2});assert.deepEqual(f.calls(),{generated:1,planned:0});
 const saved=JSON.parse(await readFile(f.path,'utf8'));assert.equal(saved.artworkValidationRevision,5);assert.equal(saved.pageStatus[0].artworkRevalidation.toRevision,5);
 await f.jobs.resume(f.id);assert.equal(f.calls().generated,1);
});
test('an already consumed hash-bound correction remains consumed after the validator upgrade',async t=>{
 const f=await fixture(t,{alreadyUsed:true});await f.jobs.resume(f.id);assert.equal((await finish(f)).status,'completed');
 const saved=JSON.parse(await readFile(join(f.checkpoint,'layout.json'),'utf8'));assert.equal(saved.artworkInventoryRepairAttempts,3);assert.equal(saved.legacyArtworkCorrection.used,true);
});
test('deleted jobs remain deleted and receive no calls or writes',async t=>{
 const f=await fixture(t,{deleted:true}),before=await readFile(f.path,'utf8');await assert.rejects(f.jobs.resume(f.id),e=>e.status===410);assert.deepEqual(f.calls(),{generated:0,planned:0});assert.equal(await readFile(f.path,'utf8'),before);
});
test('an unverified source hash cannot reopen a terminal task',async t=>{
 const f=await fixture(t,{corrupt:true});await f.jobs.resume(f.id);assert.equal((await f.jobs.get(f.id)).status,'failed');assert.deepEqual(f.calls(),{generated:0,planned:0});
});
