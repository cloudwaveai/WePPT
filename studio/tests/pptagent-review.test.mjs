import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,rm,readFile,mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {reviewWithPptagent,runPptagentBridge} from '../pptagent-review.mjs';
// Valid one-pixel PNG; image contents need not be realistic for bridge integrity tests.
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64');
async function fixture(t,n=4){
 const directory=await mkdtemp(join(tmpdir(),'pptagent-review-'));t.after(()=>rm(directory,{recursive:true,force:true}));
 const pages=Array.from({length:n},(_,i)=>({id:`p${i+1}`,title:'Title',body:'Body'}));
 await Promise.all(pages.map((_,i)=>writeFile(join(directory,`page-${i+1}.png`),png)));
 return {directory,project:{pages},evidence:{referenceImage:join(directory,'page-1.png'),manifest:pages.map((p,i)=>({number:i+1,pageId:p.id,title:p.title})),issues:[]}};
}
test('actual pinned bridge prepares, validates and rejects changed source pixels',async t=>{
 const f=await fixture(t),request={directory:f.directory,manifest:f.evidence.manifest,sceneFingerprint:'scene'};
 const prepared=await runPptagentBridge({...request,operation:'prepare'});
 assert.match(prepared.systemPrompt,/strict presentation visual reviewer/);assert.equal(prepared.contactSheets.length,1);
 const record={...request,operation:'record',reviews:[{verdict:'pass',summary:'Visible pages checked',issues:[],checkedPageIds:['p1','p2','p3','p4']}],fullSizePageIds:['p1','p2','p3','p4']};
 const result=await runPptagentBridge(record);assert.equal(result.status,'pass');assert.equal(result.finalized,false);
 await writeFile(join(f.directory,'page-1.png'),Buffer.concat([png,Buffer.from('changed')]));
 await assert.rejects(runPptagentBridge(record),/changed/);
});
test('small decks include every full-size image and record honest coverage',async t=>{
 const f=await fixture(t);let calls=0;
 const result=await reviewWithPptagent(f.project,f.evidence,{directory:f.directory,structuredAI:async request=>{
 calls++;assert.equal(request.images.length,6);assert.match(request.prompt,/nonadjacent/);
 return {verdict:'pass',summary:'Checked images',issues:[],checkedPageIds:['p1','p2','p3','p4']};}});
 assert.equal(calls,1);assert.equal(result.reviewEvidence.status,'pass');assert.equal(result.reviewEvidence.fullSizePageIds.length,4);
});
test('missing model coverage never passes',async t=>{
 const f=await fixture(t);
 const result=await reviewWithPptagent(f.project,f.evidence,{directory:f.directory,structuredAI:async()=>({verdict:'pass',summary:'Partial',issues:[],checkedPageIds:['p1']})});
 assert.equal(result.reviewEvidence.status,'unjudgeable');assert.ok(result.issues.some(i=>i.kind==='coverage'));
});
test('same-template repetition remains a warning with complete image coverage',async t=>{
 const f=await fixture(t);let calls=0;
 const result=await reviewWithPptagent(f.project,f.evidence,{directory:f.directory,structuredAI:async request=>{
 calls++;return {verdict:'pass',summary:'Review',issues:calls===1?[{severity:'minor',slide:4,description:'Repeated layout from slide 1',suggested_fix:'Reorganize slide 4'}]:[],checkedPageIds:calls===1?['p1','p2','p3','p4']:['p4','p1']};}});
 assert.equal(calls,1);assert.equal(result.reviewEvidence.status,'pass');assert.equal(result.issues[0].severity,'warning');
});
test('cancelled review cannot return pass',async t=>{
 const f=await fixture(t),controller=new AbortController();controller.abort();
 await assert.rejects(reviewWithPptagent(f.project,f.evidence,{directory:f.directory,signal:controller.signal}),/cancelled/);
});
test('bridge refuses pass with upstream-invalid major finding',async t=>{
 const f=await fixture(t),base={directory:f.directory,manifest:f.evidence.manifest,sceneFingerprint:'scene'};
 await runPptagentBridge({...base,operation:'prepare'});
 await assert.rejects(runPptagentBridge({...base,operation:'record',fullSizePageIds:[],reviews:[{verdict:'pass',summary:'Invalid pass',checkedPageIds:['p1'],issues:[{severity:'major',slide:1,description:'Clipped',suggested_fix:'Resize'}]}]}),/cannot pass/);
});
test('large decks compare distant contact sheets within image attachment limits',async t=>{
 const f=await fixture(t,36);const viewed=[];
 const result=await reviewWithPptagent(f.project,f.evidence,{directory:f.directory,structuredAI:async request=>{
 assert.ok(request.images.length<=16);viewed.push(request.images);
 const context=JSON.parse(request.prompt.slice(request.prompt.indexOf('\n{"stage"')+1));
 return {verdict:'pass',summary:'Visible contact sheets inspected',issues:[],checkedPageIds:context.expectedPageIds};}});
 assert.ok(viewed.some(images=>images.some(p=>p.endsWith('contact-01.jpg'))&&images.some(p=>p.endsWith('contact-09.jpg'))));
 assert.equal(result.reviewEvidence.checkedPageIds.length,36);assert.equal(result.reviewEvidence.status,'pass');
});
test('dense and program-flagged pages receive full-size images',async t=>{
 const f=await fixture(t,8);f.project.pages[5].body='文'.repeat(451);f.evidence.issues=[{pageId:'p8',kind:'bounds',severity:'error',message:'Out of bounds'}];
 const result=await reviewWithPptagent(f.project,f.evidence,{directory:f.directory,structuredAI:async request=>{
 const context=JSON.parse(request.prompt.slice(request.prompt.indexOf('\n{"stage"')+1));
 return {verdict:'pass',summary:'Inspected',issues:[],checkedPageIds:context.expectedPageIds};}});
 assert.deepEqual(result.reviewEvidence.fullSizePageIds,['p6','p8']);assert.equal(result.reviewEvidence.status,'fail');
});
test('fail without findings produces a blocking coverage issue and includes global rules',async t=>{
 const f=await fixture(t);
 const result=await reviewWithPptagent(f.project,f.evidence,{directory:f.directory,rules:'REQUIRED_GLOBAL_STYLE_RULE',structuredAI:async request=>{
 assert.equal(request.images[0],f.evidence.referenceImage);assert.match(request.prompt,/REQUIRED_GLOBAL_STYLE_RULE/);
 return {verdict:'fail',summary:'Failed to judge cleanly',issues:[],checkedPageIds:f.project.pages.map(p=>p.id)};}});
 assert.equal(result.reviewEvidence.status,'fail');assert.ok(result.issues.some(i=>i.kind==='coverage'&&i.severity==='error'));
});
test('nonvisual metadata does not change scene fingerprint',async t=>{
 const f=await fixture(t),ai=async()=>({verdict:'pass',summary:'Checked',issues:[],checkedPageIds:f.project.pages.map(p=>p.id)});
 const first=await reviewWithPptagent(f.project,f.evidence,{directory:f.directory,structuredAI:ai});
 f.project.messages=[{role:'user',text:'chat only'}];f.project.revision=99;
 const second=await reviewWithPptagent(f.project,f.evidence,{directory:f.directory,structuredAI:ai});
 assert.equal(first.reviewEvidence.sourceFingerprint,second.reviewEvidence.sourceFingerprint);
 f.project.pages[0].title='Changed scene';
 const third=await reviewWithPptagent(f.project,f.evidence,{directory:f.directory,structuredAI:ai});
 assert.notEqual(second.reviewEvidence.sourceFingerprint,third.reviewEvidence.sourceFingerprint);
});
test('explicit distant relationships receive a bounded paired full-size check',async t=>{
 const f=await fixture(t,12);let calls=0,paired=false;
 const result=await reviewWithPptagent(f.project,f.evidence,{directory:f.directory,rules:'GLOBAL_STYLE_RULE',structuredAI:async request=>{
 calls++;assert.match(request.prompt,/GLOBAL_STYLE_RULE/);const context=JSON.parse(request.prompt.slice(request.prompt.indexOf('\n{"stage"')+1));
 if(context.fullSizePageIds.includes('p1')&&context.fullSizePageIds.includes('p12'))paired=true;
 return {verdict:'fail',summary:'Duplicate scenes',issues:calls===1?[{severity:'major',slide:12,description:'Slide 12 has text overlap near the shared marker from slide 1',suggested_fix:'Move the overlapping title on slide 12'}]:[],checkedPageIds:context.expectedPageIds};}});
 assert.equal(calls,2);assert.ok(paired);assert.equal(result.reviewEvidence.status,'fail');
});
test('bridge timeout rejects after terminating child',async t=>{
 const f=await fixture(t);
 await assert.rejects(runPptagentBridge({directory:f.directory,manifest:f.evidence.manifest,sceneFingerprint:'scene',operation:'prepare'},{timeoutMs:1}),/timed out/);
});

test('program-only template similarity remains advisory without extra paid pair comparisons',async t=>{
 const f=await fixture(t,12);let paired=false;
 f.evidence.issues=[{pageId:'p12',kind:'repetition',severity:'warning',message:'文字区域几何结构与第 1 页近似；需检查主体。'}];
 const before=structuredClone(f.evidence.issues);
 const result=await reviewWithPptagent(f.project,f.evidence,{directory:f.directory,structuredAI:async request=>{
  const context=JSON.parse(request.prompt.slice(request.prompt.indexOf('\n{"stage"')+1));
  assert.match(request.prompt,/not proof/);assert.equal(context.programIssues[0].severity,'warning');
  if(context.fullSizePageIds.includes('p1')&&context.fullSizePageIds.includes('p12'))paired=true;
  return {verdict:'pass',summary:'Shared captions but visibly different main artwork and composition',issues:[],checkedPageIds:context.expectedPageIds};
 }});
 assert.equal(paired,false);assert.deepEqual(f.evidence.issues,before);assert.equal(result.reviewEvidence.status,'pass');
 assert.deepEqual(result.issues,before);assert.deepEqual(result.reviewEvidence.fullSizePageIds,[]);
});

test('visual confirmation of same-template layout similarity remains advisory',async t=>{
 const f=await fixture(t,8);
 f.evidence.issues=[{pageId:'p8',kind:'repetition',severity:'warning',message:'Same text frames as page 1'}];
 const result=await reviewWithPptagent(f.project,f.evidence,{directory:f.directory,structuredAI:async request=>{
  const context=JSON.parse(request.prompt.slice(request.prompt.indexOf('\n{"stage"')+1));
  const paired=context.fullSizePageIds.includes('p1')&&context.fullSizePageIds.includes('p8');
  return {verdict:'pass',summary:paired?'Actual repeated main skeleton':'Contact images inspected',issues:[{severity:'minor',slide:8,description:'Repeated main layout from page 1',suggested_fix:'Optional composition variation'}],checkedPageIds:context.expectedPageIds};
 }});
 assert.equal(result.reviewEvidence.status,'pass');
 assert(result.issues.some(i=>i.kind==='repetition'&&i.severity==='warning'));
});

test('missing full-size coverage for concrete bounds issues remains unjudgeable',async t=>{
 const f=await fixture(t,8);
 f.evidence.issues=[{pageId:'p8',kind:'repetition',severity:'warning',message:'文字区域与 1 页近似'},{pageId:'p1',kind:'bounds',severity:'error',message:'Object outside canvas'},{pageId:'p8',kind:'bounds',severity:'error',message:'Object outside canvas'}];
 const result=await reviewWithPptagent(f.project,f.evidence,{directory:f.directory,structuredAI:async request=>{
  const context=JSON.parse(request.prompt.slice(request.prompt.indexOf('\n{"stage"')+1));
  return {verdict:'pass',summary:'Only supplied coverage inspected',issues:[],checkedPageIds:context.fullSizePageIds.length?['p8']:context.expectedPageIds};
 }});
 assert.equal(result.reviewEvidence.status,'unjudgeable');
 assert(result.issues.some(i=>i.kind==='coverage'&&i.severity==='error'));
});

test('full bridge passes editable decorative-line collisions as retained warnings',async t=>{
 const f=await fixture(t);f.evidence.issues=[{pageId:'p2',kind:'overlap',severity:'error',overlapRatio:.1,message:'文本框轻微重叠。'}];
 const result=await reviewWithPptagent(f.project,f.evidence,{directory:f.directory,structuredAI:async()=>({verdict:'fail',summary:'小排版手工调整',issues:[{kind:'manual_layout',severity:'major',slide:2,description:'正文文字与背景横线重叠，文字完整。',suggested_fix:'向下移动该文本框。'}],checkedPageIds:f.project.pages.map(p=>p.id)})});
 assert.equal(result.reviewEvidence.status,'pass');assert(result.issues.every(i=>i.severity==='warning'));assert(result.issues.some(i=>i.manualAdjustment));
});
