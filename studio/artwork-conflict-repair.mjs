import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {editableArtworkInventorySchema} from './editable-artwork.mjs';
const exec=promisify(execFile);
const invalid=message=>Object.assign(Error(message),{code:'EDITABLE_ARTWORK_INVALID'});

/** Source-position failures name the lines to remeasure; freeze every other layer. */
export function artworkSourceAlignmentRepair(inventory,evidence){
 if(evidence?.kind!=='source_coverage'||!Array.isArray(evidence.issues)||!evidence.issues.length||evidence.issues.some(issue=>issue?.code!=='invalid_source_alignment'))return null;
 const indices=[...new Set(evidence.issues.map(issue=>issue.layerIndex))].sort((a,b)=>a-b);
 if(indices.length>60||indices.some(i=>!Number.isInteger(i)||inventory?.layers?.[i]?.kind!=='line'))throw invalid('源线条定位证据无效，未扩大修复范围。');
 const layerSchema=structuredClone(editableArtworkInventorySchema.properties.layers.items);layerSchema.properties.kind.enum=['line'];
 const schema={type:'object',additionalProperties:false,required:['replacements'],properties:{replacements:{type:'array',minItems:indices.length,maxItems:indices.length,items:{type:'object',additionalProperties:false,required:['layerIndex','layer'],properties:{layerIndex:{type:'integer',enum:indices},layer:layerSchema}}}}};
 return {indices,schema,apply(response){
  if(!response||Object.keys(response).length!==1||!Array.isArray(response.replacements)||response.replacements.length!==indices.length)throw invalid('源线条修复未完整返回指定图层。');
  const seen=new Set(),next=structuredClone(inventory);
  for(const item of response.replacements){
   if(!item||Object.keys(item).length!==2||!indices.includes(item.layerIndex)||seen.has(item.layerIndex)||item.layer?.kind!=='line')throw invalid('源线条修复改变了指定范围或图层职责。');
   seen.add(item.layerIndex);next.layers[item.layerIndex]=structuredClone(item.layer);
  }
  return next;
 }};
}

// Repair only the source conflict. A full regenerated inventory can introduce
// unrelated geometry changes and consumes most of the response on valid layers.
export function artworkConflictRepair(inventory,evidence){
 if(evidence?.kind!=='pixel_occlusion'||!Array.isArray(evidence.images)||!evidence.images.length)return null;
 const conflicts=evidence.conflicts??[evidence];
 if(!Array.isArray(conflicts)||!conflicts.length||conflicts.length>60||conflicts.some(c=>!Number.isInteger(c.layerIndex)||inventory.layers[c.layerIndex]?.kind!=='line'||!Array.isArray(c.images)||!c.images.length))throw invalid('元素冲突证据无效，未扩大修复范围。');
 const imageIndices=[...new Set(conflicts.flatMap(c=>c.images.map(i=>i.imageIndex)))];
 // Occlusion establishes missing image ownership, not a defective line path.
 // Keep every line immutable; source alignment has a separate repair contract.
 const indices=[...imageIndices].sort((a,b)=>a-b);
 if(indices.length>60||indices.some(i=>!Number.isInteger(i)||i<0||i>=inventory.layers.length)||imageIndices.some(i=>inventory.layers[i]?.kind!=='image'))throw invalid('元素冲突证据无效，未扩大修复范围。');
 const layerSchema=structuredClone(editableArtworkInventorySchema.properties.layers.items);
 layerSchema.properties.kind.enum=['image'];layerSchema.properties.points.minItems=3;
 const schema={type:'object',additionalProperties:false,required:['replacements'],properties:{replacements:{type:'array',minItems:indices.length,maxItems:indices.length,items:{type:'object',additionalProperties:false,required:['layerIndex','layer'],properties:{layerIndex:{type:'integer',enum:indices},layer:layerSchema}}}}};
 return {indices,imageIndices,schema,apply(response){
  if(!response||Object.keys(response).length!==1||!Array.isArray(response.replacements)||response.replacements.length!==indices.length)throw invalid('元素冲突修复未完整返回指定图层。');
  const seen=new Set(),next=structuredClone(inventory);
  for(const item of response.replacements){
   if(!item||Object.keys(item).length!==2||!indices.includes(item.layerIndex)||seen.has(item.layerIndex)||item.layer?.kind!==inventory.layers[item.layerIndex].kind||!Array.isArray(item.layer.points)||item.layer.points.length<3)throw invalid('元素冲突修复改变了指定范围或图层职责。');
   seen.add(item.layerIndex);next.layers[item.layerIndex]=structuredClone(item.layer);
  }
  return next;
 }};
}

// Raw pixel positions remain server diagnostics. The model receives one global
// coordinate space even when source PNG dimensions differ from slide geometry.
export function modelSafeArtworkEvidence(evidence){
 const dimensions=value=>value&&Number.isInteger(value.width)&&value.width>0&&Number.isInteger(value.height)&&value.height>0?value:null;
 const visit=(value,inherited)=>{
  if(Array.isArray(value))return value.map(item=>visit(item,inherited));
  if(!value||typeof value!=='object')return value;
  const size=dimensions(value.sourceSize)||inherited,result={};
  for(const [key,item] of Object.entries(value)){
   if(key==='sourceSize')continue;
   if(/pixel/i.test(key)){
    if(size&&/bounds$/i.test(key)&&Array.isArray(item)&&item.length===4&&item.every(Number.isFinite)&&item[2]>item[0]&&item[3]>item[1]){
     const [x0,y0,x1,y1]=item,x=Math.max(0,x0*1280/size.width),y=Math.max(0,y0*720/size.height),right=Math.min(1280,x1*1280/size.width),bottom=Math.min(720,y1*720/size.height);
     if(right>x&&bottom>y){const stem=key.replace(/pixels?/ig,'').replace(/bounds$/i,'');result['global'+(stem?stem[0].toUpperCase()+stem.slice(1):'')+'Bounds']={x,y,w:right-x,h:bottom-y};}
    }
    continue;
   }
   result[key]=visit(item,size);
  }
  return result;
 };
 return visit(evidence,null);
}

const CROP=String.raw`import json,sys,math
from PIL import Image
cfg=json.load(open(sys.argv[1],encoding='utf8'));im=Image.open(cfg['sourcePath']);w,h=im.size
if im.format!='PNG' or w*h>16000000:raise ValueError('Invalid repair evidence source')
im=im.convert('RGB');out=[]
for item in cfg['regions']:
 b=item['bbox'];sx=w/1280;sy=h/720
 box=(max(0,math.floor((b['x']-20)*sx)),max(0,math.floor((b['y']-20)*sy)),min(w,math.ceil((b['x']+b['w']+20)*sx)),min(h,math.ceil((b['y']+b['h']+20)*sy)))
 if box[2]<=box[0] or box[3]<=box[1]:raise ValueError('Invalid repair evidence crop')
 crop=im.crop(box);scale=min(4,768/max(crop.size));size=(max(1,round(crop.width*scale)),max(1,round(crop.height*scale)))
 crop.resize(size,Image.Resampling.LANCZOS).save(item['path'])
 out.append(dict(layerIndex=item['layerIndex'],globalRect=dict(x=box[0]/sx,y=box[1]/sy,w=(box[2]-box[0])/sx,h=(box[3]-box[1])/sy),displayPixels=list(size)))
print(json.dumps(out))`;

export async function artworkConflictEvidence({sourcePath,inventory,contract,directory,signal}){
 signal?.throwIfAborted();
 const prefix='conflict-'+randomUUID(),regions=contract.imageIndices.slice(0,3).map((layerIndex,i)=>({layerIndex,bbox:inventory.layers[layerIndex].bbox,path:join(directory,prefix+'-'+i+'.png')}));
 for(const {bbox:b} of regions)if(!b||![b.x,b.y,b.w,b.h].every(Number.isFinite)||b.x<0||b.y<0||b.w<=0||b.h<=0||b.x+b.w>1280||b.y+b.h>720)throw invalid('元素冲突局部坐标无效。');
 const config=join(directory,prefix+'.json');await writeFile(config,JSON.stringify({sourcePath,regions}),{flag:'wx'});
 const {stdout}=await exec(process.env.PYTHON||'python',['-c',CROP,config],{signal,timeout:20000,maxBuffer:65536,windowsHide:true});
 signal?.throwIfAborted();return {images:regions.map(r=>r.path),regions:JSON.parse(stdout)};
}
