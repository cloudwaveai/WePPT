import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,readdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';import {join} from 'node:path';import {deflateSync} from 'node:zlib';import {createHash} from 'node:crypto';
import {generateImageDesign,sourceSegments} from '../image-design-ai.mjs';
const hash=b=>createHash('sha256').update(b).digest('hex');
function chunk(type,data){const body=Buffer.concat([Buffer.from(type),data]);let crc=0xffffffff;for(const byte of body){crc^=byte;for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}const out=Buffer.alloc(data.length+12);out.writeUInt32BE(data.length);body.copy(out,4);out.writeUInt32BE((crc^0xffffffff)>>>0,out.length-4);return out;}
const header=Buffer.alloc(13);header.writeUInt32BE(1280);header.writeUInt32BE(720,4);header[8]=8;header[9]=2;
const png=Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',header),chunk('IDAT',deflateSync(Buffer.alloc((1280*3+1)*720))),chunk('IEND',Buffer.alloc(0))]);
const contract=Object.fromEntries(['background','typography','palette','materials','motifs','spacing','compositionRules','avoid'].map(k=>[k,'白色肌理与钴蓝装饰，衬线标题']));
for(const mode of ['valid','absent','checkpointFingerprint','imageHash','layoutHash','sourceFingerprint'])test('actual checkpoint manual artwork window '+mode,async t=>{
 const dataDir=await mkdtemp(join(tmpdir(),'manual-window-'));t.after(()=>rm(dataDir,{recursive:true,force:true}));
 const source={id:'p1',title:'原文标题',body:'全部正文完整保留。',objects:[],role:'content'},input={project:{id:'test',themeId:'curated-006',pages:[source]},targetPageIds:['p1'],referenceMode:true,singlePass:true,editableArtwork:true};
 const line={kind:'line',bbox:{x:100,y:299.25,w:200,h:1.5},points:[[100,300],[300,300]],color:'#000000',width:1.5,dash:'solid',roundCaps:false,spacing:0};
 let images=0,layouts=0,repairs=0,reused=0;const reservations=[];
 const options={dataDir,checkpointDir:join(dataDir,'checkpoints'),stagePipeline:true,textFitter:async p=>p,lineDetector:async()=>({obstacles:[]}),beforeStage:async stage=>reservations.push(stage),onBackgroundReused:async()=>{reused++;},
  imageTool:async({directory})=>{images++;const path=join(directory,'generated.png');await writeFile(path,png);return path;},
  evidenceRenderer:async(_,{directory})=>{await mkdir(directory,{recursive:true});await writeFile(join(directory,'page-1.png'),png);return {referenceImage:join(directory,'page-1.png'),sheetImages:[],issues:[]};},
  sourceDiagnostics:async({inventory})=>({sourceHash:hash(png),coordinateSpace:{width:1280,height:720},sourcePixels:{width:1280,height:720},componentHints:[],neutralStrokeHints:[],notes:[],issues:inventory.layers.length?[{code:'invalid_source_alignment',layerIndex:0,message:'controlled same-source mismatch'}]:[]}),
  structuredAI:async request=>{
   if(request.action==='reference-style')return contract;
   if(request.action==='image-text-layout'){layouts++;throw Error('AI 设计响应超时，保留真实PNG checkpoint');}
   if(request.action==='image-artwork-inventory-repair'){repairs++;return {replacements:[{layerIndex:0,layer:structuredClone(line)}]};}
   throw Error('Unexpected AI action '+request.action);
  }
 };
 // Create the checkpoint through the real production code, including its input,
 // style/reference hashes and valid PNG integrity checks; no manufactured ID.
 await assert.rejects(generateImageDesign(input,options),/超时/);assert.equal(images,1);assert.equal(layouts,1);
 const [name]=await readdir(options.checkpointDir),folder=join(options.checkpointDir,name),meta=JSON.parse(await readFile(join(folder,'checkpoint.json'),'utf8'));
 const boxes=sourceSegments(source).map((s,i)=>({id:s.id,text:s.text,x:80,y:80+i*100,w:1000,h:80,fontSize:i?28:48,fontFamily:'serif',bold:!i,color:'#252E47',align:'left'}));
 const record={version:1,fingerprint:meta.fingerprint,producerStage:'restoration',artworkInventoryRepairAttempts:2,artworkInventoryRepairResponses:2,artworkInventoryRepairFailureKey:'previous failure',layout:{backgroundHasText:false,boxes,artworkInventory:{complete:true,textureRect:{x:500,y:500,w:16,h:16},layers:[line]}}};
 const layoutBytes=JSON.stringify(record);await writeFile(join(folder,'layout.json'),layoutBytes);
 const authorization={checkpointFingerprint:meta.fingerprint,imageHash:meta.imageHash,layoutHash:hash(layoutBytes),sourceFingerprint:hash(JSON.stringify(source)),artworkRepairAttemptLimit:3};if(mode!=='valid'&&mode!=='absent')authorization[mode]='0'.repeat(64);
 const reservedBefore=reservations.length;let actualError;try{await generateImageDesign(input,{...options,...(mode==='absent'?{}:{artworkRepairAuthorization:authorization})});}catch(e){actualError=e;}assert.equal(actualError?.code,'EDITABLE_ARTWORK_INVALID',actualError?.stack);
 const saved=JSON.parse(await readFile(join(folder,'layout.json'),'utf8')),expected=mode==='valid'?3:2;
 assert.equal(images,1,'the same source background must be reused');assert.equal(reused,1);assert.equal(layouts,1,'cached source text/layout must not be regenerated');assert.equal(repairs,mode==='valid'?1:0,JSON.stringify({message:actualError.message,inventoryFailure:actualError.inventoryFailure,cause:actualError.cause?.message,stage:actualError.pipelineStage,reservations,authorization,meta}));
 assert.equal(saved.artworkInventoryRepairAttempts,expected);assert.equal(saved.artworkInventoryRepairResponses,expected);assert.equal(reservations.slice(reservedBefore).filter(s=>s==='text').length,mode==='valid'?1:0);
 assert.equal(hash(await readFile(join(folder,'background.png'))),meta.imageHash);assert.deepEqual(saved.layout.boxes,boxes);assert.deepEqual(source,input.project.pages[0]);
});
