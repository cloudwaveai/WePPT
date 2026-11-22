import test from 'node:test';
import assert from 'node:assert/strict';
import {acceptsEditableBackgroundReview,generateImageDesign,sourceSegments} from '/app/image-design-ai.mjs';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {deflateSync} from 'node:zlib';
for(const clean of [true,false])for(const kind of ['none','texture_restoration','inventory_coverage','unknown'])test(`background decision clean=${clean} kind=${kind}`,()=>{
 assert.equal(acceptsEditableBackgroundReview({backgroundIsTextureOnly:clean,artworkFailureKind:kind}),kind==='texture_restoration'||kind==='none'&&clean);
});
for(const value of [undefined,null,'false',0])test(`malformed background evidence ${value} stays blocking`,()=>assert.equal(acceptsEditableBackgroundReview({backgroundIsTextureOnly:value,artworkFailureKind:'texture_restoration'}),false));
function chunk(type,data){const body=Buffer.concat([Buffer.from(type),data]);let crc=0xffffffff;for(const byte of body){crc^=byte;for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}const out=Buffer.alloc(data.length+12);out.writeUInt32BE(data.length);body.copy(out,4);out.writeUInt32BE((crc^0xffffffff)>>>0,out.length-4);return out;}
const header=Buffer.alloc(13);header.writeUInt32BE(1280);header.writeUInt32BE(720,4);header[8]=8;header[9]=2;
const png=Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',header),chunk('IDAT',deflateSync(Buffer.alloc((1280*3+1)*720))),chunk('IEND',Buffer.alloc(0))]);
for(const mode of ['seam','residual','collision','manual-line'])test(`actual editable adapter preserves policy: ${mode}`,async t=>{
 const dataDir=await mkdtemp(join(tmpdir(),'review-warning-'));t.after(()=>rm(dataDir,{recursive:true,force:true}));
 const source={id:'p1',title:'原文标题',body:'全部正文完整保留。',objects:[],role:'content'},input={project:{id:'test',themeId:'curated-006',pages:[source]},targetPageIds:['p1'],referenceMode:true,singlePass:true,editableArtwork:true};
 let images=0,reviews=0;
 const contract=Object.fromEntries(['background','typography','palette','materials','motifs','spacing','compositionRules','avoid'].map(k=>[k,'黑色肌理与白色文字']));
 const options={dataDir,stagePipeline:true,textFitter:async p=>p,lineDetector:async()=>({obstacles:[]}),sourceDiagnostics:async()=>({issues:[],componentHints:[],neutralStrokeHints:[]}),
  imageTool:async({directory})=>{images++;const p=join(directory,'generated.png');await writeFile(p,png);return p;},
  evidenceRenderer:async(_,{directory})=>{await mkdir(directory,{recursive:true});await writeFile(join(directory,'page-1.png'),png);return {referenceImage:join(directory,'page-1.png'),sheetImages:[],issues:[]};},
  structuredAI:async request=>{
   if(request.action==='reference-style')return contract;
   if(request.action==='reference-style-review'){reviews++;return {matches:!['collision','manual-line'].includes(mode),reason:mode==='collision'?'文字与图形相撞':'底纹修复痕迹仅作警告',violations:mode==='collision'?[{kind:'readability',evidence:'标题与图形相撞'}]:mode==='manual-line'?[{kind:'readability',evidence:'正文文字与背景横线重叠，移动即可调整'}]:[],backgroundIsTextureOnly:false,artworkFailureKind:mode==='residual'?'unknown':'texture_restoration'};}
   if(['image-text-layout','image-text-layout-compact','image-text-layout-repair'].includes(request.action))return {backgroundHasText:false,boxes:sourceSegments(source).map((s,i)=>({id:s.id,text:s.text,x:80,y:80+i*100,w:1000,h:80,fontSize:i?28:48,fontFamily:'serif',bold:!i,color:'#ffffff',align:'left'})),artworkInventory:{complete:true,textureRect:{x:500,y:500,w:16,h:16},layers:[]}};
   throw Error('Unexpected AI action '+request.action);
  }};
 if(mode==='seam'||mode==='manual-line'){
  const result=await generateImageDesign(input,options);const page=result.pages[0];assert.equal(page.body,source.body);assert.equal(page.editableArtwork.review.status,'pass');assert.deepEqual(page.editableArtwork.review.warnings,['texture-restoration']);assert.equal(page.referenceDesign.visualChecked,true);if(mode==='manual-line')assert.equal(page.imageDesign.manualAdjustments.length,1);
 }else await assert.rejects(generateImageDesign(input,options),e=>e.code===(mode==='collision'?'REFERENCE_TEXT_REPAIR_EXHAUSTED':'EDITABLE_ARTWORK_INVALID'));
 assert.equal(images,1);assert(reviews>0);
});
