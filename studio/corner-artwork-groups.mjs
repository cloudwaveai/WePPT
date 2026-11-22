import {validateEditableArtworkInventory,normalizeEditableArtworkInventory} from './editable-artwork.mjs';
// Small corner ornaments are one movable source asset. Main diagrams, rules
// and photographs remain separate; this never creates a slide-size image.
const slots=[{x:0,y:0,w:480,h:104},{x:1000,y:0,w:280,h:160},{x:0,y:640,w:256,h:80},{x:896,y:640,w:384,h:80}];
const keys=['kind','bbox','points','color','width','dash','roundCaps','spacing'];
const finite=n=>typeof n==='number'&&Number.isFinite(n);
function eligible(layer,slot){
 if(!layer||Object.keys(layer).length!==keys.length||keys.some(k=>!Object.hasOwn(layer,k)))return false;
 const b=layer.bbox;
 if(!b||Object.keys(b).length!==4||!['x','y','w','h'].every(k=>finite(b[k]))||b.w<=0||b.h<=0||b.x<slot.x||b.y<slot.y||b.x+b.w>slot.x+slot.w||b.y+b.h>slot.y+slot.h||b.w>400||b.h>160)return false;
 if(!/^#[a-fA-F0-9]{6}$/.test(layer.color)||!Array.isArray(layer.points)||layer.points.length>40||layer.points.some(p=>!Array.isArray(p)||p.length!==2||!p.every(finite)||p[0]<0||p[0]>1280||p[1]<0||p[1]>720))return false;
 if(layer.kind==='image'){
  if(layer.width!==0||layer.dash!=='solid'||layer.roundCaps!==false||layer.spacing!==0||!layer.points.every(([x,y])=>x>=b.x&&x<=b.x+b.w&&y>=b.y&&y<=b.y+b.h))return false;
  if(!layer.points.length)return true;
  if(layer.points.length<3)return false;
  // Crossing silhouettes are intentionally retained as their complete source
  // rectangle; malformed one/two-point or wholly collinear shapes are not.
  const [a]=layer.points,bp=layer.points.find(p=>p[0]!==a[0]||p[1]!==a[1]);
  return !!bp&&layer.points.some(p=>Math.abs((bp[0]-a[0])*(p[1]-a[1])-(bp[1]-a[1])*(p[0]-a[0]))>1e-9);
 }
 if(layer.kind!=='line'||!finite(layer.width)||layer.width>4)return false;
 // Reuse the native-line contract, including stroke width, caps, degenerate
 // segments and canvas boundaries, before a rectangle can hide that geometry.
 try{validateEditableArtworkInventory({complete:true,textureRect:{x:600,y:300,w:8,h:8},layers:[layer]});return true;}catch{return false;}
}
export function groupCornerArtwork(input){
 if(input?.complete!==true||!Array.isArray(input.layers)||input.layers.length>60)return {inventory:structuredClone(input),groups:[]};
 // Native-line normalization already owns the small bbox corrections allowed
 // by the production contract. Use it before corner selection, without ever
 // rewriting ungrouped main rules or accepting invalid paint/attributes.
 const candidates=input.layers.map(layer=>{
  if(layer?.kind!=='line')return layer;
  try{return normalizeEditableArtworkInventory({complete:true,textureRect:{x:600,y:300,w:8,h:8},layers:[layer]}).layers[0];}catch{return layer;}
 });
 const groups=[],claimed=new Set();
 for(const slot of slots){
  const indices=candidates.flatMap((layer,i)=>!claimed.has(i)&&eligible(layer,slot)?[i]:[]);
  if(!indices.length)continue;
  if(indices.length===1&&input.layers[indices[0]].kind==='image'&&!input.layers[indices[0]].points.length)continue;
  const parts=indices.map(i=>candidates[i].bbox),x=Math.min(...parts.map(b=>b.x)),y=Math.min(...parts.map(b=>b.y)),right=Math.max(...parts.map(b=>b.x+b.w)),bottom=Math.max(...parts.map(b=>b.y+b.h));
  if(right-x>400||bottom-y>160)continue;
  // A corner crop must not erase a silhouette needed by a body connector.
  // Keep the original layers when an ungrouped line can touch this crop.
  if(candidates.some((layer,i)=>!indices.includes(i)&&layer?.kind==='line'&&layer.bbox&&
   layer.bbox.x-2<right&&layer.bbox.x+layer.bbox.w+2>x&&layer.bbox.y-2<bottom&&layer.bbox.y+layer.bbox.h+2>y))continue;
  for(const i of indices)claimed.add(i);
  groups.push({indices,bbox:{x,y,w:right-x,h:bottom-y},slot});
 }
 const layers=[],evidence=[];
 for(const [index,layer] of input.layers.entries()){
  const group=groups.find(g=>g.indices.includes(index));
  if(!group){layers.push(structuredClone(layer));continue;}
  if(index!==group.indices[0])continue;
  evidence.push({layerIndices:group.indices,outputLayerIndex:layers.length,bbox:group.bbox,source:'original-png',reason:'small-corner-ornament',originalLayers:group.indices.map(i=>structuredClone(input.layers[i])),normalizedBounds:group.indices.flatMap(i=>JSON.stringify(candidates[i].bbox)!==JSON.stringify(input.layers[i].bbox)?[{layerIndex:i,originalBBox:structuredClone(input.layers[i].bbox),normalizedBBox:structuredClone(candidates[i].bbox)}]:[])});
  layers.push({kind:'image',bbox:group.bbox,points:[],color:'#000000',width:0,dash:'solid',roundCaps:false,spacing:0});
 }
 return {inventory:{...structuredClone(input),layers},groups:evidence};
}
