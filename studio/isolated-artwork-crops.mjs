import {normalizeEditableArtworkInventory,validateEditableArtworkInventory} from './editable-artwork.mjs';

// Preserve an isolated source asset when only its inferred polygon topology
// is wrong. Native geometry and all non-topological contracts remain strict.
function validateSingle(layer){
 for(const [x,y] of [[0,0],[1272,0],[0,712],[1272,712],[600,300]]){
  try{return validateEditableArtworkInventory({complete:true,textureRect:{x,y,w:8,h:8},layers:[layer]}).layers[0];}
  catch(error){if(error.message!=='Texture sample intersects a layer or guard')throw error;}
 }
 throw Error('No independent texture sample');
}
const overlaps=(a,b)=>a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y;
export function normalizeIsolatedArtwork(input){
 const inventory=structuredClone(input),repairs=[];
 if(input?.complete!==true||!Array.isArray(input.layers)||input.layers.length>60)return {inventory,repairs};
 const lineBounds=[];
 for(const layer of input.layers)if(layer?.kind==='line'){
  try{
   const normalized=normalizeEditableArtworkInventory({complete:true,textureRect:{x:600,y:300,w:8,h:8},layers:[layer]}).layers[0];
   const {x,y,w,h}=validateSingle(normalized).bbox;
   lineBounds.push({x:x-8,y:y-8,w:w+16,h:h+16});
  }catch{return {inventory,repairs};}
 }
 for(const [index,layer] of input.layers.entries()){
  if(layer?.kind!=='image')continue;
  try{validateSingle(layer);continue;}catch(error){if(error.message!=='Image polygon self-intersects')continue;}
  const b=layer.bbox,ps=layer.points;
  if(b.w>720||b.h>720||b.w*b.h>1280*720/4||lineBounds.some(line=>overlaps(b,line)))continue;
  if(!Array.isArray(ps)||ps.length<3||ps.some(p=>!Array.isArray(p)||p.length!==2||!p.every(n=>typeof n==='number'&&Number.isFinite(n))||p[0]<b.x||p[0]>b.x+b.w||p[1]<b.y||p[1]>b.y+b.h))continue;
  const a=ps[0],bp=ps.find(p=>p[0]!==a[0]||p[1]!==a[1]);
  if(!bp||!ps.some(p=>Math.abs((bp[0]-a[0])*(p[1]-a[1])-(bp[1]-a[1])*(p[0]-a[0]))>1e-9))continue;
  const replacement={...structuredClone(layer),points:[]};
  try{validateSingle(replacement);}catch{continue;}
  inventory.layers[index]=replacement;
  repairs.push({index,originalLayer:structuredClone(layer),bbox:structuredClone(b),source:'original-png',reason:'isolated-self-intersecting-polygon-source-crop'});
 }
 return {inventory,repairs};
}
