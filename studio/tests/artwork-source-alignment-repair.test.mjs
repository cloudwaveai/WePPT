import test from 'node:test';
import assert from 'node:assert/strict';
import {artworkSourceAlignmentRepair} from '../artwork-conflict-repair.mjs';

const line={kind:'line',bbox:{x:100,y:200,w:400,h:2},points:[[100,201],[500,201]],color:'#000000',width:1,dash:'solid',roundCaps:false,spacing:0};
const image={kind:'image',bbox:{x:600,y:300,w:50,h:50},points:[],color:'#000000',width:0,dash:'solid',roundCaps:false,spacing:0};
const inventory={complete:true,textureRect:{x:1100,y:600,w:16,h:16},layers:[line,image,{...line,bbox:{x:100,y:400,w:400,h:2},points:[[100,401],[500,401]]}]};
const evidence={kind:'source_coverage',issues:[{code:'invalid_source_alignment',layerIndex:0}]};

test('source failure repairs exactly its measured line and freezes all unrelated image/line bytes',()=>{
 const contract=artworkSourceAlignmentRepair(inventory,evidence),fixed={...structuredClone(line),color:'#686867'};
 assert.deepEqual(contract.indices,[0]);assert.deepEqual(contract.schema.properties.replacements.items.properties.layer.properties.kind.enum,['line']);
 const next=contract.apply({replacements:[{layerIndex:0,layer:fixed}]});
 assert.deepEqual(next.layers[0],fixed);assert.deepEqual(next.layers.slice(1),inventory.layers.slice(1));assert.equal(inventory.layers[0].color,'#000000');
});

test('all reported source lines are collected once in stable order',()=>{
 const contract=artworkSourceAlignmentRepair(inventory,{kind:'source_coverage',issues:[2,0,2].map(layerIndex=>({code:'invalid_source_alignment',layerIndex}))});
 assert.deepEqual(contract.indices,[0,2]);
 assert.deepEqual(contract.apply({replacements:[{layerIndex:2,layer:inventory.layers[2]},{layerIndex:0,layer:line}]}),inventory);
});

for(const response of [
 {replacements:[]},
 {replacements:[{layerIndex:0,layer:line},{layerIndex:2,layer:line}]},
 {replacements:[{layerIndex:2,layer:line}]},
 {replacements:[{layerIndex:0,layer:image}]},
 {...inventory},
 {replacements:[{layerIndex:0,layer:line}],extra:true},
])test('malformed or expanded replacements never alter the source: '+JSON.stringify(response),()=>{
 const before=structuredClone(inventory);assert.throws(()=>artworkSourceAlignmentRepair(inventory,evidence).apply(response),e=>e.code==='EDITABLE_ARTWORK_INVALID');assert.deepEqual(inventory,before);
});

test('unlocated coverage defects retain their original full-inventory repair route',()=>{
 for(const e of [{kind:'pixel_occlusion'},{kind:'source_coverage',issues:[]},{kind:'source_coverage',issues:[{code:'uncovered_source_component'}]}])assert.equal(artworkSourceAlignmentRepair(inventory,e),null);
 for(const layerIndex of [1,-1,99,NaN,'0'])assert.throws(()=>artworkSourceAlignmentRepair(inventory,{kind:'source_coverage',issues:[{code:'invalid_source_alignment',layerIndex}]}),e=>e.code==='EDITABLE_ARTWORK_INVALID');
});
