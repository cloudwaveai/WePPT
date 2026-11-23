import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,readdir,rm,mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {runImageAssistant,validateImageAssistantPlan,materializeImageObjects} from '../image-assistant.mjs';
const object={id:'title',type:'text',text:'原标题',x:80,y:60,w:600,h:100,fontSize:48,color:'#222222',bold:true,rotation:0,opacity:1,sourceField:'title',layoutField:'title',sourceText:'原标题',layoutManaged:true};
const project=()=>({id:'trial',stage:'editor',title:'测试',themeId:'curated-005',pages:[{id:'p1',title:'原标题',body:'正文',layoutSource:{title:'原标题',body:'正文'},objects:[structuredClone(object),{id:'body',type:'text',text:'正文',x:80,y:220,w:700,h:100,fontSize:30,color:'#333333',custom:true}]},{id:'p2',title:'其他页',body:'不可改',objects:[]}]});
const input=(message='把标题改成新标题',scope='page')=>({action:'revise',scope,pageId:'p1',objectIds:['title'],message,project:project()});
const plan=(fields=['text'],text='新标题')=>({kind:'edit',message:'开始处理',pages:[{pageId:'p1',mode:'objects',title:'原标题',body:'正文',instruction:'把标题改成新标题',objects:[{id:'title',text,fields}]}]});
const restored=(overrides={})=>({objects:[{...object,text:'新标题',italic:false,align:'left',fill:'#ffffff',stroke:'#000000',strokeWidth:0,radius:0,...overrides}]});
function png(){const b=Buffer.alloc(24);Buffer.from([137,80,78,71,13,10,26,10]).copy(b);b.writeUInt32BE(1280,16);b.writeUInt32BE(720,20);return b;}
async function fixture(fn){const dir=await mkdtemp(join(tmpdir(),'image-assistant-'));try{const image=join(dir,'image.png');await writeFile(image,png());await fn({dir,image});}finally{await rm(dir,{recursive:true,force:true});}}
const evidence=async(_,{directory})=>({referenceImage:join(directory,'reference.png'),sheetImages:[],issues:[]});

test('scope rejects page escape, object escape, whole page in object scope and mixed copy',()=>{
 for(const change of [p=>p.pages[0].pageId='p2',p=>p.pages[0].objects[0].id='body',p=>p.pages[0].mode='redesign',p=>p.pages[0].body='新正文']){const p=plan();change(p);assert.throws(()=>validateImageAssistantPlan(p,input('改字','object')));}
 const p=plan();p.pages.push({...p.pages[0],pageId:'p2'});assert.throws(()=>validateImageAssistantPlan(p,input('重新设计当前页','deck')));
 assert.throws(()=>validateImageAssistantPlan(plan(),input('重新设计第2页','deck')));
});
test('discussion cannot carry edits; changing style cannot silently change text',()=>{
 assert.throws(()=>validateImageAssistantPlan(plan(),input('先讨论，不要修改')));
 assert.throws(()=>validateImageAssistantPlan({...plan(),kind:'answer'},input()));
 assert.throws(()=>validateImageAssistantPlan(plan(['color'],'别的标题'),input()));
 assert.equal(validateImageAssistantPlan({kind:'answer',message:'建议',pages:[]},input()).kind,'answer');
});
test('text restoration uses generated result, preserves source baseline and unselected objects',()=>{
 const source=project().pages[0],before=structuredClone(source);
 const result=materializeImageObjects(source,plan().pages[0],restored({x:400,fontSize:99,color:'#ff0000'}));
 assert.equal(result.objects[0].text,'新标题');assert.equal(result.objects[0].sourceText,'新标题');assert.equal(result.title,'新标题');assert.equal(result.layoutSource.title,'新标题');
 assert.equal(result.objects[0].x,80);assert.equal(result.objects[0].fontSize,48);assert.equal(result.objects[0].color,'#222222');
 assert.deepEqual(result.objects[1],source.objects[1]);assert.deepEqual(source,before);
 assert.throws(()=>materializeImageObjects(source,plan().pages[0],restored({text:'漏字'})));
});
test('color and motion come from Image restoration only for requested fields',()=>{
 const result=materializeImageObjects(project().pages[0],plan(['color','y'],'原标题').pages[0],restored({text:'原标题',y:100,color:'#ff0000',x:900}));
 assert.equal(result.objects[0].color,'#ff0000');assert.equal(result.objects[0].y,100);assert.equal(result.objects[0].x,80);
 assert.throws(()=>materializeImageObjects(project().pages[0],plan(['y'],'原标题').pages[0],restored({y:700})));
});
test('question returns answer without any Image or renderer calls',()=>fixture(async({dir})=>{
 let images=0,renders=0;const result=await runImageAssistant(input('这页怎么改？'),{dataDir:dir,structuredAI:async()=>({kind:'answer',message:'可以改善标题层级',pages:[]}),imageTool:async()=>images++,evidenceRenderer:async()=>renders++});
 assert.equal(result.imageEdit,undefined);assert.equal(images,0);assert.equal(renders,0);assert.equal(result.message,'可以改善标题层级');
}));
test('all literal text edits run Image then Sol and return atomic pages',()=>fixture(async({dir,image})=>{
 const request=input(),before=structuredClone(request);let calls=[],count=0;
 const result=await runImageAssistant(request,{dataDir:dir,structuredAI:async({action})=>{calls.push(action);return ++count===1?plan():restored();},imageTool:async()=>{calls.push('real-image-dependency');return image;},evidenceRenderer:evidence});
 assert.deepEqual(calls,['image-assistant-plan','real-image-dependency','image-assistant-object-restore']);assert.equal(result.imageEdit.usedImage,true);assert.equal(result.imageEdit.pages[0].objects[0].text,'新标题');assert.deepEqual(result.imageEdit.pages[1],before.project.pages[1]);assert.deepEqual(request,before);assert.deepEqual(await readdir(join(dir,'image-jobs')),[]);
}));
test('failed or cancelled Image never returns a direct-edit fallback',()=>fixture(async({dir,image})=>{
 const request=input(),before=structuredClone(request);let restores=0;
 await assert.rejects(runImageAssistant(request,{dataDir:dir,structuredAI:async()=>{restores++;return plan();},imageTool:async()=>{throw Error('image unavailable');},evidenceRenderer:evidence}),/image unavailable/);assert.equal(restores,1);assert.deepEqual(request,before);
 const controller=new AbortController();await assert.rejects(runImageAssistant(request,{dataDir:dir,signal:controller.signal,structuredAI:async()=>plan(),imageTool:async()=>{controller.abort();return image;},evidenceRenderer:evidence}));assert.deepEqual(request,before);
}));
test('real visual audit failure prevents publishing edits',()=>fixture(async({dir,image})=>{
 let calls=0,renders=0;await assert.rejects(runImageAssistant(input(),{dataDir:dir,structuredAI:async()=>++calls===1?plan():restored(),imageTool:async()=>image,evidenceRenderer:async()=>({referenceImage:image,issues:++renders===2?[{kind:'overflow',severity:'error',message:'too tall'}]:[]})}),/too tall/);
}));
test('whole-page copy change stages text before Image design and preserves sibling',()=>fixture(async({dir})=>{
 const p={kind:'edit',message:'开始',pages:[{pageId:'p1',mode:'redesign',title:'新标题',body:'新正文',instruction:'改写这一页并重新设计',objects:[]}]};let pageCalls=0;
 const result=await runImageAssistant(input('改写这一页并重新设计'),{dataDir:dir,structuredAI:async()=>p,pageDesigner:async({project,editMode})=>{pageCalls++;assert.equal(editMode,true);assert.equal(project.pages[0].title,'新标题');assert.equal(project.pages[0].body,'新正文');return {pages:[{...project.pages[0],imageDesign:{editableText:true}}]};}});
 assert.equal(pageCalls,1);assert.equal(result.imageEdit.pages[0].body,'新正文');assert.deepEqual(result.imageEdit.pages[1],project().pages[1]);
}));
test('object artwork uses actual generated asset, only in its own rectangle',()=>{
 const source={id:'p',objects:[{id:'bg',type:'rect',x:0,y:0,w:1280,h:720},{id:'icon',type:'rect',x:100,y:100,w:80,h:80}]},p={objects:[{id:'icon',text:'',fields:['artwork']}]};
 const r={objects:[{id:'icon'}]};const result=materializeImageObjects(source,p,r,'/uploads/test.png');
 assert.deepEqual(result.objects[0],source.objects[0]);assert.equal(result.objects[1].type,'image');assert.equal(result.objects[1].src,'/uploads/test.png');assert.deepEqual(result.objects[1].crop,{x:100/1280,y:100/720,w:80/1280,h:80/720});
 const overlapping=structuredClone(source);overlapping.objects.push({id:'caption',type:'text',x:100,y:100,w:100,h:50});assert.throws(()=>materializeImageObjects(overlapping,p,r,'/uploads/test.png'));
});

test('repeated selected body edits shift only trusted bindings and survive later synchronization',async()=>{
 const {validateImageEdit}=await import('../public/image-assistant-result.js');
 const {updateSvgCopy}=await import('../public/svg-copy.js');
 let source={id:'p',title:'标题',body:'aaaBBB',engine:'ppt-master-svg',layoutSource:{title:'标题',body:'aaaBBB'},objects:[{...object,id:'a',text:'aaa',sourceText:'aaa',sourceField:'body',layoutField:'body',sourceRange:[0,3]},{...object,id:'b',text:'BBB',sourceText:'BBB',sourceField:'body',layoutField:'body',sourceRange:[3,6]}]};
 for(const text of ['AAAAA','新','最终正文']){
  const next=materializeImageObjects(source,{objects:[{id:'a',text,fields:['text']}]},{objects:[{...object,id:'a',text}]});
  assert.equal(next.body,text+'BBB');assert.deepEqual(next.objects[1].sourceRange,[text.length,text.length+3]);
  const result={imageEdit:{usedImage:true,pages:[next],changedPageIds:['p']}};
  assert(validateImageEdit(result,{scope:'object',pageId:'p',objectIds:['a'],project:{pages:[source]}}));
  assert.equal(updateSvgCopy(JSON.parse(JSON.stringify(next))).objects[0].text,text);
  const invalid=structuredClone(result);invalid.imageEdit.pages[0].objects[1].x++;assert.throws(()=>validateImageEdit(invalid,{scope:'object',pageId:'p',objectIds:['a'],project:{pages:[source]}}));source=next;
 }
});
