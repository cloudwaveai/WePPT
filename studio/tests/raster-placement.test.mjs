import test from 'node:test';import assert from 'node:assert/strict';
import {fitImageText,generateImageDesign,sourceSegments} from '/app/image-design-ai.mjs';
import {mkdtemp,writeFile,mkdir,rm,readdir,readFile} from 'node:fs/promises';import {join} from 'node:path';import {tmpdir} from 'node:os';import {deflateSync} from 'node:zlib';import {createHash} from 'node:crypto';
function chunk(type,data){const body=Buffer.concat([Buffer.from(type),data]);let crc=0xffffffff;for(const byte of body){crc^=byte;for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}const out=Buffer.alloc(data.length+12);out.writeUInt32BE(data.length);body.copy(out,4);out.writeUInt32BE((crc^0xffffffff)>>>0,out.length-4);return out;}
function image(dark=false,line=true){const header=Buffer.alloc(13);header.writeUInt32BE(1280);header.writeUInt32BE(720,4);header[8]=8;header[9]=2;const raw=Buffer.alloc((1280*3+1)*720);for(let y=0;y<720;y++)for(let x=0;x<1280;x++){const c=line&&y>=110&&y<=112&&x>=100&&x<=900?(dark?255:150):(dark?30:240),i=y*(1280*3+1)+1+x*3;raw[i]=raw[i+1]=raw[i+2]=c;}return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',header),chunk('IDAT',deflateSync(raw)),chunk('IEND',Buffer.alloc(0))]);}
for(const dark of [false,true])test(`pixel placement avoids a contrasting line on ${dark?'dark':'light'} artwork without rewriting text`,async t=>{
 const root=await mkdtemp(join(tmpdir(),'raster-placement-'));t.after(()=>rm(root,{recursive:true,force:true}));const file=join(root,'bg.png');await writeFile(file,image(dark));
 const obj={id:'a',type:'text',text:'原文完整保留',x:160,y:92,w:400,h:50,fontSize:28,fontFamily:'sans-serif',lineHeight:1.3,layoutManaged:true};const metrics=[];const result=await fitImageText({objects:[obj]},{rasterBackground:file,lineMetrics:metrics});
 assert.equal(result.objects[0].text,'原文完整保留');assert(result.objects[0].y!==92||result.objects[0].x!==160);assert(metrics[0].rects.every(r=>r.y+r.h+4<110||r.y-4>112));
});
test('pixel placement avoids unmanaged user shapes as well as text',async t=>{
 const root=await mkdtemp(join(tmpdir(),'raster-reserved-'));t.after(()=>rm(root,{recursive:true,force:true}));const file=join(root,'bg.png');await writeFile(file,image());
 const obj={id:'a',type:'text',text:'原文完整保留',x:160,y:92,w:400,h:50,fontSize:28,fontFamily:'sans-serif',lineHeight:1.3,layoutManaged:true};
 const user={id:'user',type:'rect',x:100,y:40,w:600,h:50,layoutManaged:false},before=structuredClone(user);const result=await fitImageText({objects:[obj,user]},{rasterBackground:file});assert(result.objects[0].y>=96);assert.deepEqual(result.objects[1],before);
});
test('fallback reuses the original verified checkpoint and preserves editable exact text',async t=>{
 const dataDir=await mkdtemp(join(tmpdir(),'fallback-adapter-'));t.after(()=>rm(dataDir,{recursive:true,force:true}));const png=image(false,false),source={id:'p1',title:'原文标题',body:'全部正文完整保留。',objects:[],role:'content'},input={project:{id:'test',themeId:'curated-006',pages:[source]},targetPageIds:['p1'],referenceMode:true,singlePass:true,editableArtwork:true};let images=0,first=true,reused=0;
 const options={dataDir,checkpointDir:join(dataDir,'checkpoints'),stagePipeline:true,textFitter:async p=>p,lineDetector:async()=>({obstacles:[]}),sourceDiagnostics:async()=>({issues:[],componentHints:[],neutralStrokeHints:[]}),
  onBackgroundReused:()=>reused++,imageTool:async({directory})=>{images++;const path=join(directory,'generated.png');await writeFile(path,png);return path;},
  evidenceRenderer:async(_,{directory})=>{await mkdir(directory,{recursive:true});await writeFile(join(directory,'page-1.png'),png);return {referenceImage:join(directory,'page-1.png'),sheetImages:[],issues:[]};},
  structuredAI:async r=>{if(r.action==='reference-style')return Object.fromEntries(['background','typography','palette','materials','motifs','spacing','compositionRules','avoid'].map(k=>[k,'白纸黑字']));if(r.action==='reference-style-review')return {matches:true,reason:'文字清晰且风格一致',violations:[]};if(r.action==='image-text-layout'){if(first)throw Error('AI 设计响应超时');return {backgroundHasText:false,boxes:sourceSegments(source).map((s,i)=>({id:s.id,text:s.text,x:80,y:80+i*100,w:1000,h:80,fontSize:i?28:48,fontFamily:'serif',bold:!i,color:'#000000',align:'left'}))};}throw Error('Unexpected '+r.action);}};
 await assert.rejects(generateImageDesign(input,options),/超时/);first=false;
 const result=await generateImageDesign(input,{...options,artworkFallback:{code:'EDITABLE_ARTWORK_INVALID',message:'图形拆分失败'}});const page=result.pages[0];assert.equal(images,1);assert.equal(reused,1);assert.equal(page.body,source.body);assert.equal(page.imageDesign.artworkFallback.sourceImageHash,createHash('sha256').update(png).digest('hex'));assert(page.objects.some(o=>o.type==='text'&&o.text===source.title));assert.equal(page.imageDesign.editableText,true);
 // A missing or changed same-source PNG cannot buy a replacement image.
 const [folder]=await readdir(options.checkpointDir);await writeFile(join(options.checkpointDir,folder,'background.png'),Buffer.from('corrupt'));
 await assert.rejects(generateImageDesign(input,{...options,artworkFallback:{code:'EDITABLE_ARTWORK_INVALID'}}),e=>e.code==='REFERENCE_CHECKPOINT_UNAVAILABLE');assert.equal(images,1);
});
