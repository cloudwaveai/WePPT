import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {normalizeEditableArtworkInventory,validateEditableArtworkInventory} from '../editable-artwork.mjs';

const line=()=>({kind:'line',bbox:{x:1139,y:652,w:242,h:18},points:[[1139,669],[1153,653]],color:'#000000',width:1.5,dash:'solid',roundCaps:false,spacing:0});
const inventory=layer=>({complete:true,textureRect:{x:600,y:100,w:16,h:16},layers:[layer]});

test('oversized model envelope cannot reject an otherwise valid native line',()=>{
 const source=inventory(line()),before=structuredClone(source);
 assert.throws(()=>validateEditableArtworkInventory(source),/Invalid inventory rectangle/);
 const normalized=normalizeEditableArtworkInventory(source),actual=normalized.layers[0];
 assert.deepEqual(source,before);assert.deepEqual(actual.points,before.layers[0].points);
 for(const key of ['kind','width','color','dash','roundCaps','spacing'])assert.deepEqual(actual[key],before.layers[0][key]);
 assert(actual.bbox.x+actual.bbox.w<=1280);assert(actual.bbox.y+actual.bbox.h<=720);
 assert.deepEqual(validateEditableArtworkInventory(normalized),normalized);
});

test('bottom overestimate is recovered from unchanged horizontal/vertical stroke geometry',()=>{
 const layer=line();layer.bbox={x:100,y:680,w:2,h:80};layer.points=[[101,680],[101,704]];
 const result=normalizeEditableArtworkInventory(inventory(layer));
 assert.deepEqual(result.layers[0].points,layer.points);assert(result.layers[0].bbox.y+result.layers[0].bbox.h<=720);
});

for(const mutate of [
 l=>l.points[1][0]=1284,
 l=>l.points[1][1]=724,
 l=>l.points[0][0]=-1,
 l=>l.width=100,
 l=>l.width=NaN,
 l=>l.bbox.w=-2,
 l=>l.bbox.x=-1,
 l=>l.bbox.extra=1,
 l=>l.extra=1,
 l=>l.points[1]=[NaN,650],
 l=>l.points[1]=[1139,669],
 l=>l.color='red',
])test('invalid paint and malformed attributes remain hard errors: '+mutate.toString(),()=>{
 const layer=line();mutate(layer);assert.throws(()=>normalizeEditableArtworkInventory(inventory(layer)),e=>e.code==='EDITABLE_ARTWORK_INVALID');
});

test('oversized image boxes retain their independent crop safety rules',()=>{
 const layer={...line(),kind:'image',points:[],width:0,bbox:{x:1139,y:652,w:242,h:18}};
 assert.throws(()=>normalizeEditableArtworkInventory(inventory(layer)),/Invalid inventory rectangle/);
});
