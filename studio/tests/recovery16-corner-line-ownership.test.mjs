import test from 'node:test';import assert from 'node:assert/strict';import {groupCornerArtwork} from '../corner-artwork-groups.mjs';
const arrow=()=>({kind:'image',bbox:{x:1100,y:115,w:40,h:16},points:[[1100,115],[1140,123],[1100,131],[1110,123]],color:'#000000',width:0,dash:'solid',roundCaps:false,spacing:0});
const ornament=()=>({kind:'image',bbox:{x:1160,y:115,w:32,h:16},points:[],color:'#000000',width:0,dash:'solid',roundCaps:false,spacing:0});
const line=(x=1110,dash='solid')=>({kind:'line',bbox:{x:x-1,y:115,w:2,h:64},points:[[x,116],[x,178]],color:'#000000',width:2,dash,roundCaps:dash==='dotted',spacing:dash==='solid'?0:8});
const inventory=layers=>({complete:true,textureRect:{x:600,y:300,w:16,h:16},layers});
function unchanged(layers){const input=inventory(layers),before=structuredClone(input),result=groupCornerArtwork(input);assert.deepEqual(input,before,'grouping cannot mutate the supplied inventory');assert.deepEqual(result.inventory,before,'outside line ownership must preserve every original polygon and layer');assert.deepEqual(result.groups,[]);}
test('single corner arrow silhouette survives an intersecting main connector',()=>unchanged([line(),arrow()]));
test('multiple ornaments do not merge across a main connector in their empty gap',()=>unchanged([arrow(),ornament(),line(1150)]));
test('source layer order does not change the external-line exclusion',()=>unchanged([ornament(),line(1150),arrow()]));
for(const dash of ['dotted','dashed'])test('external '+dash+' line retains the original silhouette',()=>unchanged([arrow(),line(1110,dash)]));
test('a nearby external stroke guard preserves the polygon even when raw boxes do not touch',()=>unchanged([arrow(),line(1142.5)]));
test('line canonical bounds protect polygons even when the declared bbox misses real endpoints',()=>{const l=line();l.bbox={x:1200,y:115,w:2,h:64};unchanged([arrow(),l]);});
test('no external line permits the existing single-corner conversion',()=>{const a=arrow(),r=groupCornerArtwork(inventory([a]));assert.equal(r.groups.length,1);assert.deepEqual(r.inventory.layers[0].bbox,a.bbox);assert.deepEqual(r.inventory.layers[0].points,[]);});
test('no external line permits normal multi-ornament grouping',()=>{const r=groupCornerArtwork(inventory([arrow(),ornament()]));assert.equal(r.groups.length,1);assert.equal(r.inventory.layers.length,1);assert.deepEqual(r.groups[0].layerIndices,[0,1]);assert.deepEqual(r.inventory.layers[0].points,[]);});
test('a distant main line remains independent while corner grouping proceeds',()=>{const l=line(800),r=groupCornerArtwork(inventory([arrow(),ornament(),l]));assert.equal(r.groups.length,1);assert.equal(r.inventory.layers.length,2);assert.deepEqual(r.inventory.layers[1],l);});
