import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,readdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {deflateSync} from 'node:zlib';
import {generateImageDesign,sourceSegments} from '../image-design-ai.mjs';
function chunk(type,data){const body=Buffer.concat([Buffer.from(type),data]);let crc=0xffffffff;for(const byte of body){crc^=byte;for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}const out=Buffer.alloc(data.length+12);out.writeUInt32BE(data.length);body.copy(out,4);out.writeUInt32BE((crc^0xffffffff)>>>0,out.length-4);return out;}
const header=Buffer.alloc(13);header.writeUInt32BE(1280);header.writeUInt32BE(720,4);header[8]=8;header[9]=2;
const png=Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',header),chunk('IDAT',deflateSync(Buffer.alloc((1280*3+1)*720))),chunk('IEND',Buffer.alloc(0))]);
const contract=Object.fromEntries(['background','typography','palette','materials','motifs','spacing','compositionRules','avoid'].map(k=>[k,'白色肌理与钴蓝装饰，衬线标题']));
async function fixture(t){
 const dataDir=await mkdtemp(join(tmpdir(),'image-checkpoint-'));t.after(()=>rm(dataDir,{recursive:true,force:true}));
 const source={id:'p1',title:'原文标题',body:'全部正文完整保留。',objects:[],role:'content'};
 const input={project:{id:'test',themeId:'curated-006',pages:[source]},targetPageIds:['p1'],referenceMode:true,singlePass:true};
 const state={images:0,layouts:0,repairs:0,reviews:0,audits:0,mode:'timeout'};
 const options={dataDir,checkpointDir:join(dataDir,'checkpoints'),textFitter:async p=>p,
 imageTool:async({directory})=>{state.images++;const path=join(directory,'generated.png');await writeFile(path,png);return path;},
 evidenceRenderer:async(_,{directory})=>{await mkdir(directory,{recursive:true});await writeFile(join(directory,'page-1.png'),png);if(directory.includes('check-'))state.audits++;const fail=state.mode==='audit-fail'||state.mode==='audit-repair'&&state.audits===1;return {referenceImage:join(directory,'page-1.png'),sheetImages:[],issues:fail&&directory.includes('check-')?[{severity:'error',message:'文字遮挡'}]:[]};},
 structuredAI:async request=>{
 if(request.action==='reference-style')return contract;
 if(request.action==='reference-style-review'){state.reviews++;return {matches:state.mode!=='style-fail',reason:'真实风格检查'};}
 if(request.action==='image-text-layout-repair'){state.repairs++;return {backgroundHasText:false,boxes:sourceSegments(input.project.pages[0]).map((s,i)=>({id:s.id,text:s.text,x:80,y:80+i*100,w:1000,h:80,fontSize:i?28:48,fontFamily:'serif',bold:!i,color:'#252E47',align:'left'}))};}
 state.layouts++;if(state.mode==='timeout')throw Error('AI 设计响应超时，原页面保持不变。');
 if(state.mode==='cancel'){state.controller.abort();throw Error('AI 请求已取消。');}
 if(state.mode==='error')throw Error('模型输出格式错误');
 return {backgroundHasText:state.mode==='text-remains',boxes:sourceSegments(input.project.pages[0]).map((s,i)=>({id:s.id,text:s.text,x:80,y:80+i*100,w:1000,h:80,fontSize:i?28:48,fontFamily:'serif',bold:!i,color:'#252E47',align:'left'}))};
 }};
 const checkpointFiles=async()=>{const dirs=await readdir(options.checkpointDir).catch(()=>[]);return (await Promise.all(dirs.map(dir=>readdir(join(options.checkpointDir,dir))))).flat();};
 return {input,options,state,checkpointFiles};
}
test('text timeout retry reuses generated image and still runs exact-text, DOM and style audits',async t=>{
 const f=await fixture(t);await assert.rejects(generateImageDesign(f.input,f.options),/超时/);
 assert.equal(f.state.images,1);assert.deepEqual((await f.checkpointFiles()).sort(),['background.png','checkpoint.json']);
 f.state.mode='pass';const result=await generateImageDesign(f.input,f.options);
 assert.equal(f.state.images,1);assert.equal(f.state.layouts,2);assert.equal(f.state.audits,1);assert.equal(f.state.reviews,1);
 assert.equal(result.pages[0].body,f.input.project.pages[0].body);assert.equal(result.pages[0].referenceDesign.visualChecked,true);assert.deepEqual(await f.checkpointFiles(),[]);
});
test('layout audit repair reuses the generated artwork instead of repeating Image generation',async t=>{
 const f=await fixture(t);f.state.mode='audit-repair';const result=await generateImageDesign(f.input,f.options);
 assert.equal(result.pages[0].body,f.input.project.pages[0].body);assert.equal(f.state.images,1);assert.equal(f.state.repairs,1);assert.equal(f.state.audits,2);assert.equal(f.state.reviews,1);
});
test('changed request cannot reuse stale artwork',async t=>{
 const f=await fixture(t);await assert.rejects(generateImageDesign(f.input,f.options),/超时/);f.input.instruction='改用新的内容关系';f.state.mode='pass';
 await generateImageDesign(f.input,f.options);assert.equal(f.state.images,2);
});
test('modified PNG hash forces redraw',async t=>{
 const f=await fixture(t);await assert.rejects(generateImageDesign(f.input,f.options),/超时/);
 const [dir]=await readdir(f.options.checkpointDir);await writeFile(join(f.options.checkpointDir,dir,'background.png'),png.subarray(0,png.length-12));
 f.state.mode='pass';await generateImageDesign(f.input,f.options);assert.equal(f.state.images,2);
});
for(const mode of ['text-remains','style-fail','audit-fail','error'])test(`${mode} invalidates saved artwork and returns no unaudited page`,async t=>{
 const f=await fixture(t);await assert.rejects(generateImageDesign(f.input,f.options),/超时/);f.state.mode=mode;
 await assert.rejects(generateImageDesign(f.input,f.options));assert.equal(f.state.images,1);assert.deepEqual(await f.checkpointFiles(),[]);
 f.state.mode='pass';await generateImageDesign(f.input,f.options);assert.equal(f.state.images,2);
});
test('cancellation during restore deletes checkpoint and publishes nothing',async t=>{
 const f=await fixture(t);await assert.rejects(generateImageDesign(f.input,f.options),/超时/);f.state.mode='cancel';f.state.controller=new AbortController();
 await assert.rejects(generateImageDesign(f.input,{...f.options,signal:f.state.controller.signal}),/取消/);
 assert.deepEqual(await f.checkpointFiles(),[]);assert.equal(f.state.reviews,0);assert.equal(f.state.images,1);
});
test('already-cancelled retry clears saved background without a new model call',async t=>{
 const f=await fixture(t);await assert.rejects(generateImageDesign(f.input,f.options),/超时/);
 const controller=new AbortController();controller.abort();await assert.rejects(generateImageDesign(f.input,{...f.options,signal:controller.signal}));
 assert.deepEqual(await f.checkpointFiles(),[]);assert.equal(f.state.images,1);assert.equal(f.state.layouts,1);
});
test('corrupted PNG chunks with matching manifest SHA still fail integrity and redraw',async t=>{
 const {createHash}=await import('node:crypto');const f=await fixture(t);await assert.rejects(generateImageDesign(f.input,f.options),/超时/);
 const [dir]=await readdir(f.options.checkpointDir),folder=join(f.options.checkpointDir,dir),bytes=Buffer.from(png);bytes[50]^=1;
 const manifest=JSON.parse(await readFile(join(folder,'checkpoint.json'),'utf8'));manifest.imageHash=createHash('sha256').update(bytes).digest('hex');
 await writeFile(join(folder,'background.png'),bytes);await writeFile(join(folder,'checkpoint.json'),JSON.stringify(manifest));
 f.state.mode='pass';await generateImageDesign(f.input,f.options);assert.equal(f.state.images,2);
});
