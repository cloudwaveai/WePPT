import test from 'node:test';import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';import {tmpdir} from 'node:os';import {join} from 'node:path';import {deflateSync} from 'node:zlib';
import {generateImageDesign,sourceSegments} from '../image-design-ai.mjs';
function chunk(type,data){const body=Buffer.concat([Buffer.from(type),data]);let crc=0xffffffff;for(const byte of body){crc^=byte;for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}const out=Buffer.alloc(data.length+12);out.writeUInt32BE(data.length);body.copy(out,4);out.writeUInt32BE((crc^0xffffffff)>>>0,out.length-4);return out;}
const header=Buffer.alloc(13);header.writeUInt32BE(1280);header.writeUInt32BE(720,4);header[8]=8;header[9]=2;const raw=Buffer.alloc((1280*3+1)*720,238);for(let y=0;y<720;y++)raw[y*(1280*3+1)]=0;
const png=Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',header),chunk('IDAT',deflateSync(raw)),chunk('IEND',Buffer.alloc(0))]);
const contract=Object.fromEntries(['background','typography','palette','materials','motifs','spacing','compositionRules','avoid'].map(k=>[k,'白色底纹，黑色几何装饰与清晰衬线标题']));
const cases=[
 {name:'false texture warning',flag:false,kind:'texture_restoration',pass:true,warning:true},
 {name:'true texture warning',flag:true,kind:'texture_restoration',pass:true,warning:true},
 {name:'true clean texture',flag:true,kind:'none',pass:true},
 {name:'false none',flag:false,kind:'none'},
 {name:'false unknown',flag:false,kind:'unknown'},
 {name:'true unknown',flag:true,kind:'unknown'},
 {name:'false remaining artwork',flag:false,kind:'inventory_coverage'},
 {name:'true inconsistent remaining artwork',flag:true,kind:'inventory_coverage'},
 {name:'texture with unreadable text',flag:false,kind:'texture_restoration',violation:'readability'},
 {name:'texture with wrong motif',flag:false,kind:'texture_restoration',violation:'motif'},
 {name:'pure texture with unreadable text',flag:true,kind:'texture_restoration',violation:'readability'},
 {name:'pure texture with wrong motif',flag:true,kind:'texture_restoration',violation:'motif'},
 {name:'missing texture boolean',kind:'texture_restoration'},
 {name:'nonboolean texture flag',flag:'false',kind:'texture_restoration'}
];
for(const c of cases)test('actual image inspection '+c.name,async t=>{
 const dataDir=await mkdtemp(join(tmpdir(),'texture-warning-'));t.after(()=>rm(dataDir,{recursive:true,force:true}));
 const source={id:'p1',title:'原文标题',body:'全部正文完整保留。',objects:[],role:'content'},input={project:{id:'test',themeId:'curated-006',pages:[source]},targetPageIds:['p1'],referenceMode:true,singlePass:true,editableArtwork:true};
 const inventory={complete:true,textureRect:{x:600,y:500,w:16,h:16},layers:[]};
 const boxes=()=>sourceSegments(source).map((s,i)=>({id:s.id,text:s.text,x:80,y:80+i*100,w:1000,h:80,fontSize:i?28:48,fontFamily:'serif',bold:!i,color:'#252E47',align:'left'}));
 let images=0,styleReviews=0,artworkRepairs=0,textRepairs=0;const calls=[];
 const options={dataDir,checkpointDir:join(dataDir,'checkpoints'),stagePipeline:true,textFitter:async p=>p,lineDetector:async()=>({obstacles:[]}),
  imageTool:async({directory})=>{images++;const p=join(directory,'source.png');await writeFile(p,png);return p;},
  evidenceRenderer:async(_,{directory})=>{await mkdir(directory,{recursive:true});const p=join(directory,'page-1.png');await writeFile(p,png);return {referenceImage:p,sheetImages:[],issues:[]};},
  sourceDiagnostics:async()=>({coordinateSpace:{width:1280,height:720},sourcePixels:{width:1280,height:720},componentHints:[],neutralStrokeHints:[],notes:[],issues:[]}),
  structuredAI:async request=>{calls.push(request.action);
   if(request.action==='reference-style')return contract;
   if(request.action==='image-text-layout')return {backgroundHasText:false,boxes:boxes(),artworkInventory:structuredClone(inventory)};
   if(request.action==='image-text-layout-repair'){textRepairs++;return {backgroundHasText:false,boxes:boxes()};}
   if(request.action==='image-artwork-inventory-repair'){artworkRepairs++;return structuredClone(inventory);}
   if(request.action==='reference-style-review'){styleReviews++;return {matches:!c.violation,reason:c.violation?'正文与图形碰撞或存在错误图形':c.kind==='inventory_coverage'?'底图仍残留完整黑色阶梯图形':c.kind==='texture_restoration'?'仅有纹理修复接缝，文字清晰，所有图形已独立编辑':'底图检查结果',violations:c.violation?[{kind:c.violation,evidence:'明确的可见缺陷'}]:[],...(c.flag===undefined?{}:{backgroundIsTextureOnly:c.flag}),artworkFailureKind:c.kind};}
   throw Error('Unexpected action '+request.action);
  }
 };
 if(c.pass){const result=await generateImageDesign(input,options),page=result.pages[0];assert.equal(page.body,source.body);assert.equal(page.title,source.title);assert.equal(page.editableArtwork.complete,true);assert.equal(page.imageDesign.editableArtwork,true);assert.equal(page.referenceDesign.visualChecked,true);if(c.warning){assert.deepEqual(page.editableArtwork.review.warnings,['texture-restoration']);assert.equal(page.editableArtwork.review.textureRestorationPending,true);}else assert.equal(page.editableArtwork.review?.warnings?.includes('texture-restoration')??false,false);assert.equal(artworkRepairs,0);assert.equal(textRepairs,0);assert.equal(styleReviews,1);}
 else await assert.rejects(generateImageDesign(input,options),e=>['EDITABLE_ARTWORK_INVALID','REFERENCE_STYLE_MISMATCH','REFERENCE_TEXT_REPAIR_EXHAUSTED','REFERENCE_STYLE_REVIEW_INVALID'].includes(e.code),JSON.stringify({calls}));
 assert.equal(images,1,'a warning or review refusal must not redraw the source');assert(styleReviews>=1);assert(artworkRepairs<=2);assert(textRepairs<=2);
});
