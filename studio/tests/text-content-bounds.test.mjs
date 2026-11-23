import test from 'node:test';import assert from 'node:assert/strict';
import {fitImageText} from '/app/image-design-ai.mjs';
const text=(id,y,h,extra={})=>({id,type:'text',text:'完整原文',x:80,y,w:500,h,fontSize:28,fontFamily:'Noto Sans CJK SC,sans-serif',lineHeight:1.3,bold:false,layoutManaged:true,...extra});
test('browser tightens unused generated text box whitespace without moving text or changing style',async()=>{
 const p={objects:[text('a',80,220),text('b',200,220)]},before=structuredClone(p);const result=await fitImageText(p);const [a,b]=result.objects;
 assert(a.h<100);assert(b.h<100);assert(a.y+a.h<b.y);
 for(let i=0;i<2;i++)for(const k of ['x','y','text','fontSize','fontFamily','bold','lineHeight'])assert.deepEqual(result.objects[i][k],before.objects[i][k]);
});
test('user custom text boxes preserve their original dimensions',async()=>{
 const custom=text('c',80,220,{custom:true}),before=structuredClone(custom);const p=await fitImageText({objects:[custom]});assert.deepEqual(p.objects[0],before);
});
test('multiline content is measured at the actual wrapping width',async()=>{
 const obj=text('a',80,400,{text:'完整原文'.repeat(20),w:180});const p=await fitImageText({objects:[obj]});assert(p.objects[0].h>100);assert.equal(p.objects[0].text,'完整原文'.repeat(20));
});
