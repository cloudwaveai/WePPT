import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,rm,readdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {sourceSegments,materializeImagePage,generateImageDesign,pngDimensions,fitImageText} from '../image-design-ai.mjs';
import {designImageProject} from '../public/image-design-pipeline.js';
import {explicitDesignAction} from '../assistant-routing.mjs';
import {validateDesignAction} from '../public/assistant-actions.js';

const makePage=(id='p1')=>({id,title:'执行与迭代',body:'确认后按统一标准执行，\n依据复盘结果更新SOP。',role:'content',themeId:'curated-005',objects:[{id:'logo-'+id,type:'rect',x:1100,y:650,w:100,h:30,fill:'#123456',custom:true}]});
const makeProject=()=>({id:'independent',title:'test',stage:'editor',themeId:'curated-005',designEngine:'svg',revision:0,pages:[makePage(),makePage('p2'),makePage('p3')],assets:[],messages:[]});
const layoutFor=p=>({backgroundHasText:false,boxes:sourceSegments(p).map((s,i)=>({id:s.id,x:60,y:60+i*140,w:1100,h:100,fontSize:i?30:48,fontFamily:'sans',bold:i===0,color:'#514738',align:'left'}))});
const req=(message,scope='page')=>({action:'revise',message,scope,pageId:'p1',project:makeProject()});
function pngHeader(width=1280,height=720){const header=Buffer.alloc(24);Buffer.from([137,80,78,71,13,10,26,10]).copy(header);header.writeUInt32BE(13,8);header.write('IHDR',12);header.writeUInt32BE(width,16);header.writeUInt32BE(height,20);return header;}
test('PNG dimensions reject wrong ratio, undersized and invalid images',()=>{
 assert.deepEqual(pngDimensions(pngHeader()),{width:1280,height:720});
 for(const bytes of [Buffer.alloc(8),Buffer.alloc(24),pngHeader(1024,1024),pngHeader(320,180),pngHeader(16384,9216)])assert.throws(()=>pngDimensions(bytes));
});

test('sourceSegments retains exact source slices and all non-whitespace source characters',()=>{
 const p=makePage();p.body='金额12,000元；\r\n确认A。B！？\n\n  最后：SOP / v2。';
 const segments=sourceSegments(p),covered=new Set();
 for(const s of segments){assert.equal(s.text,p[s.field].slice(s.start,s.end));if(s.field==='body')for(let i=s.start;i<s.end;i++)covered.add(i);}
 for(let i=0;i<p.body.length;i++)if(!/\s/.test(p.body[i]))assert(covered.has(i),'uncovered '+i);
});
test('materialize preserves copy, ranges, custom objects and input immutability',()=>{
 const source=makePage(),before=structuredClone(source),page=materializeImagePage(source,layoutFor(source),'/uploads/11111111-1111-1111-1111-111111111111.png','curated-005');
 assert.deepEqual(source,before);assert.equal(page.title,source.title);assert.equal(page.body,source.body);assert.deepEqual(page.layoutSource,{title:source.title,body:source.body});assert.deepEqual(page.objects.at(-1),source.objects[0]);
 for(const o of page.objects.filter(o=>o.type==='text')){assert.equal(o.sourceText,o.text);assert.equal(o.layoutField,o.sourceField);if(o.sourceField==='body')assert.equal(o.text,source.body.slice(...o.sourceRange));}
 assert.equal(page.objects.filter(o=>o.type==='image').length,1);assert.equal(page.imageDesign.editableText,true);
});
test('materialize rejects duplicate/missing/unknown segments and residual background text',()=>{
 const p=makePage();for(const mutate of [l=>l.boxes.pop(),l=>l.boxes[1].id=l.boxes[0].id,l=>l.boxes[0].id='invented',l=>l.backgroundHasText=true]){const l=layoutFor(p);mutate(l);assert.throws(()=>materializeImagePage(p,l,'/uploads/a.png',p.themeId));}
});
test('materialize rejects invalid or out-of-canvas text geometry',()=>{
 const p=makePage();for(const [key,value] of [['x',-1],['w',1300],['y',700],['h',0],['fontSize',NaN],['fontSize',12],['color','red'],['align','justify']]){const l=layoutFor(p);l.boxes[0][key]=value;assert.throws(()=>materializeImagePage(p,l,'/uploads/a.png',p.themeId),key);}
});
test('split body boxes preserve exact source ranges and separate emphasis styles',()=>{
 const p=makePage(),l=layoutFor(p),original=l.boxes[1],segment=sourceSegments(p)[1];
 l.boxes.splice(1,1,{...original,w:300,start:0,end:3,bold:false,fontSize:24},{...original,x:400,w:800,start:3,end:segment.text.length,bold:true,fontSize:42});
 const page=materializeImagePage(p,l,'/uploads/a.png',p.themeId),body=page.objects.filter(o=>o.type==='text'&&o.sourceField==='body');
 assert.equal(body[0].text+body[1].text,segment.text);assert.deepEqual(body[0].sourceRange,[segment.start,segment.start+3]);assert.deepEqual(body[1].sourceRange,[segment.start+3,segment.end]);assert.equal(body[0].bold,false);assert.equal(body[1].bold,true);assert.equal(body[1].fontSize,42);
 for(const o of body)assert.equal(o.text,p.body.slice(...o.sourceRange));
});
test('split body ranges reject overlap, omission, fractional and out-of-range offsets',()=>{
 const p=makePage(),segment=sourceSegments(p)[1];
 for(const pair of [[[0,4],[3,segment.text.length]],[[0,3],[4,segment.text.length]],[[0,2.5],[2.5,segment.text.length]],[[0,3],[3,segment.text.length+1]]]){
  const l=layoutFor(p),b=l.boxes[1];l.boxes.splice(1,1,...pair.map(([start,end])=>({...b,start,end})));assert.throws(()=>materializeImagePage(p,l,'/uploads/a.png',p.themeId));
 }
 const titleSplit=layoutFor(p),t=titleSplit.boxes[0];titleSplit.boxes.splice(0,1,{...t,start:0,end:2},{...t,start:2,end:p.title.length});assert.throws(()=>materializeImagePage(p,titleSplit,'/uploads/a.png',p.themeId));
});
test('source coverage rejects omitted trailing character after emoji',()=>{
 const p=makePage();p.body='🙂AB';const l=layoutFor(p);l.boxes[1].start=0;l.boxes[1].end=p.body.length-1;
 assert.throws(()=>materializeImagePage(p,l,'/uploads/a.png',p.themeId),'emoji must not make last source character invisible to coverage check');
});
test('exact substring boxes preserve styles and derive ranges without model offsets',()=>{
 const p=makePage(),l=layoutFor(p),b=l.boxes[1],segment=sourceSegments(p)[1];
 l.boxes.splice(1,1,{...b,text:segment.text.slice(0,3),w:300,fontSize:24,bold:false},{...b,text:segment.text.slice(3),x:400,w:800,fontSize:42,bold:true});
 const page=materializeImagePage(p,l,'/uploads/a.png',p.themeId),body=page.objects.filter(o=>o.sourceField==='body');
 assert.deepEqual(body.slice(0,2).map(o=>o.sourceRange),[[segment.start,segment.start+3],[segment.start+3,segment.end]]);assert.equal(body[0].bold,false);assert.equal(body[1].fontSize,42);assert.equal(body[0].text+body[1].text,segment.text);
});
test('substring reconstruction rejects duplicate or invented text and locates repeated source occurrences',()=>{
 const p=makePage();for(const text of ['虚构内容','']){const l=layoutFor(p);l.boxes[1].text=text;assert.throws(()=>materializeImagePage(p,l,'/uploads/a.png',p.themeId));}
 const dup=layoutFor(p);dup.boxes.push({...dup.boxes[1],text:sourceSegments(p)[1].text});assert.throws(()=>materializeImagePage(p,dup,'/uploads/a.png',p.themeId));
 p.body='重复重复结束。';const l=layoutFor(p),b=l.boxes[1];l.boxes.splice(1,1,{...b,text:'重复'},{...b,text:'重复'},{...b,text:'结束。'});const page=materializeImagePage(p,l,'/uploads/a.png',p.themeId);assert.deepEqual(page.objects.filter(o=>o.sourceField==='body').map(o=>o.sourceRange),[[0,2],[2,4],[4,7]]);
});
const fittedText=()=>({id:'fit-text',type:'text',text:'确认后按统一标准执行',x:100,y:100,w:100,h:20,fontSize:40,fontFamily:'Microsoft YaHei',bold:true,lineHeight:1.3,layoutManaged:true});
const overlaps=(a,b)=>Math.min(a.x+a.w,b.x+b.w)>Math.max(a.x,b.x)&&Math.min(a.y+a.h,b.y+b.h)>Math.max(a.y,b.y);
test('real browser fitting expands safely without changing copy, style, position or custom objects',async()=>{
 const text=fittedText(),custom={id:'custom',type:'rect',x:1000,y:600,w:100,h:60,custom:true},p={id:'fit',objects:[text,custom]},before=structuredClone(p),after=await fitImageText(p),o=after.objects[0];
 assert.deepEqual(p,before);for(const k of ['text','x','y','fontSize','fontFamily','bold'])assert.equal(o[k],text[k]);assert(o.w>=text.w&&o.h>=text.h);assert(o.x+o.w<=1280&&o.y+o.h<=720);assert.deepEqual(after.objects[1],custom);assert(!overlaps(o,custom));
});
test('real browser fitting does not expand through right-side or below text',async()=>{
 for(const obstacle of [{id:'next',type:'text',text:'右侧文字',x:240,y:100,w:300,h:90,custom:true},{id:'next',type:'text',text:'下方文字',x:100,y:130,w:400,h:90,custom:true}]){
  const after=await fitImageText({id:'fit',objects:[fittedText(),obstacle]});assert(!overlaps(after.objects[0],obstacle));assert.deepEqual(after.objects[1],obstacle);
 }
});
test('real browser fitting prevents combined width/height growth into diagonal custom or text',async()=>{
 for(const type of ['rect','text']){const obstacle={id:'diagonal',type,text:'保护内容',x:250,y:130,w:160,h:90,custom:true};const after=await fitImageText({id:'fit',objects:[fittedText(),obstacle]});assert(!overlaps(after.objects[0],obstacle),'growth overlaps diagonal '+type+': '+JSON.stringify(after.objects[0]));assert.deepEqual(after.objects[1],obstacle);}
});
test('explicit current-page and whole-deck Image commands have exact target scopes',()=>{
 assert.deepEqual(explicitDesignAction(req('用Image重新设计当前页','deck')).designAction.pageIds,['p1']);
 assert.deepEqual(explicitDesignAction(req('用Image+Sol重新设计整份','deck')).designAction.pageIds,['p1','p2','p3']);
 assert.equal(explicitDesignAction(req('用Image重新设计整份')).designAction,undefined);
 assert.equal(explicitDesignAction(req('用Image重新设计当前页','object')),null);
 assert.equal(explicitDesignAction(req('先讨论用Image重新设计当前页')),null);
});
test('explicit numbered page request never expands to whole deck',()=>{
 const result=explicitDesignAction(req('用Image重新设计第2页','deck'));
 assert(!result?.designAction||JSON.stringify(result.designAction.pageIds)===JSON.stringify(['p2']),'numbered request expanded to '+JSON.stringify(result?.designAction?.pageIds));
});
test('action validation prevents scope escape, mixed edits and implicit Image use',()=>{
 const input=req('用Image重新设计当前页'),r=explicitDesignAction(input);
 for(const mutate of [v=>v.designAction.pageIds=['p2'],v=>v.designAction.pageIds=['p1','p1'],v=>v.changes=[{pageId:'p1',text:'bad'}]]){const copy=structuredClone(r);mutate(copy);assert.throws(()=>validateDesignAction(copy,input));}
 assert.throws(()=>validateDesignAction(r,req('重新设计当前页')));
});
test('pipeline applies one requested page, preserves siblings and input',async()=>{
 const project=makeProject(),before=structuredClone(project),calls=[],applied=[];
 const result=await designImageProject(project,{targetPageIds:['p2'],request:async(path,input)=>{calls.push({path,input});const source=input.project.pages.find(p=>p.id==='p2');return {pages:[materializeImagePage(source,layoutFor(source),'/uploads/a.png',project.themeId)]};},onBatchReady:b=>applied.push(b)});
 assert.deepEqual(project,before);assert.deepEqual(result.pages[0],before.pages[0]);assert.deepEqual(result.pages[2],before.pages[2]);assert.equal(calls[0].path,'/api/design/image');assert.deepEqual(calls[0].input.targetPageIds,['p2']);assert.equal(applied.length,1);assert.deepEqual(applied[0].targetPageIds,['p2']);
});
test('pipeline does not apply late response after cancellation',async()=>{
 const project=makeProject(),controller=new AbortController();let applied=0;
 await assert.rejects(designImageProject(project,{targetPageIds:['p1'],signal:controller.signal,request:async()=>{controller.abort();const p=project.pages[0];return {pages:[materializeImagePage(p,layoutFor(p),'/uploads/a.png',project.themeId)]};},onBatchReady:()=>applied++}));assert.equal(applied,0);
});
test('pipeline rejects malformed response or failure without applying',async()=>{
 for(const response of [{pages:[]},{pages:[{...makePage('p2'),imageDesign:{editableText:true}}]},{pages:[{...makePage(),themeId:'wrong',imageDesign:{editableText:true}}]}]){let applied=0;await assert.rejects(designImageProject(makeProject(),{targetPageIds:['p1'],request:async()=>response,onBatchReady:()=>applied++}));assert.equal(applied,0);}
});
test('pipeline propagates stale callback and never requests next page',async()=>{
 const p=makeProject();let calls=0;
 await assert.rejects(designImageProject(p,{targetPageIds:['p1','p2'],request:async(_,input)=>{calls++;const page=p.pages.find(x=>x.id===input.targetPageIds[0]);return {pages:[materializeImagePage(page,layoutFor(page),'/uploads/a.png',p.themeId)]};},onBatchReady:()=>{throw Error('stale-document');}}),/stale-document/);assert.equal(calls,1);
});
async function fixture(run){const dataDir=await mkdtemp(join(tmpdir(),'image-independent-'));try{const png=join(dataDir,'fixture.png');await writeFile(png,pngHeader());await run({dataDir,png});}finally{await rm(dataDir,{recursive:true,force:true});}}
test('backend completes only after exact-text materialization and real-audit dependency',async()=>fixture(async({dataDir,png})=>{
 const project=makeProject();let images=0,audits=0;const result=await generateImageDesign({project,targetPageIds:['p1'],instruction:'test'},{dataDir,imageTool:async()=>{images++;return png;},structuredAI:async()=>layoutFor(project.pages[0]),evidenceRenderer:async()=>{audits++;return {referenceImage:png,sheetImages:[],issues:[]};}});
 assert.equal(images,2);assert.equal(audits,2);assert.equal(result.pages[0].body,project.pages[0].body);assert.equal((await readdir(join(dataDir,'uploads'))).length,1);
}));
test('backend rejects audit failure rather than returning candidate',async()=>fixture(async({dataDir,png})=>{
 const project=makeProject();let audits=0;
 await assert.rejects(generateImageDesign({project,targetPageIds:['p1']},{dataDir,imageTool:async()=>png,structuredAI:async()=>layoutFor(project.pages[0]),evidenceRenderer:async()=>({referenceImage:png,sheetImages:[],issues:++audits===2?[{severity:'error',message:'overflow'}]:[]})}),/overflow/);
 assert.deepEqual(project,makeProject());
 assert.deepEqual(await readdir(join(dataDir,'uploads')),[],'failed audit must clean unpublished image');
}));
test('backend cancellation during final audit cleans image and returns no result',async()=>fixture(async({dataDir,png})=>{
 const project=makeProject(),controller=new AbortController();let audits=0;
 await assert.rejects(generateImageDesign({project,targetPageIds:['p1']},{dataDir,signal:controller.signal,imageTool:async()=>png,structuredAI:async()=>layoutFor(project.pages[0]),evidenceRenderer:async()=>{if(++audits===2)controller.abort();return{referenceImage:png,sheetImages:[],issues:[]};}}));
 assert.deepEqual(await readdir(join(dataDir,'uploads')),[]);
}));
test('backend rejects invalid target before any model call',async()=>{
 let calls=0;await assert.rejects(generateImageDesign({project:makeProject(),targetPageIds:['p1','p2']},{imageTool:async()=>calls++,structuredAI:async()=>calls++,evidenceRenderer:async()=>calls++}));assert.equal(calls,0);
});
test('backend rejects changed canvas size before text reconstruction or upload',async()=>fixture(async({dataDir,png})=>{
 const other=join(dataDir,'other.png');await writeFile(other,pngHeader(1920,1080));let images=0,layouts=0;
 await assert.rejects(generateImageDesign({project:makeProject(),targetPageIds:['p1']},{dataDir,imageTool:async()=>++images===1?png:other,structuredAI:async()=>{layouts++;return layoutFor(makePage());},evidenceRenderer:async()=>({referenceImage:png,sheetImages:[],issues:[]})}),/尺寸不一致/);
 assert.equal(layouts,0);assert.deepEqual(await readdir(join(dataDir,'uploads')).catch(e=>e.code==='ENOENT'?[]:Promise.reject(e)),[]);
}));
