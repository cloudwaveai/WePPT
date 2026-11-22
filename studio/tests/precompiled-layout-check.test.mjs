import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {checkPrecompiledLayout} from '../public/precompiled-layout-check.js';
import {renderBlueprintPackage} from '../public/template-blueprints.js';
import {planBlueprintDeck} from '../public/blueprint-planner.js';

const pack=JSON.parse(await readFile(new URL('../public/template-blueprint-packs/curated-001.json',import.meta.url),'utf8'));
const theme={id:pack.themeId,palette:{background:'#fff'}};
const render=body=>{
 const page=planBlueprintDeck([{id:'p1',role:'content',title:'工作安排',body,objects:[]}],pack)[0];
 return renderBlueprintPackage(page,theme,pack,page.precompiledVariant||0);
};
test('dense real pack candidate is rejected before browser measurement and source is unchanged',async()=>{
 const body=Array.from({length:12},(_,i)=>`## 第${i+1}项工作\n明确负责人，按阶段核对交付内容，记录检查结果和后续处理安排。`).join('\n');
 const page=render(body),before=structuredClone(page);
 assert.ok(page.objects.some(o=>o.sourceField==='body'&&o.h===1));
 const result=await checkPrecompiledLayout([page],['p1'],{measure:()=>{throw Error('Known overflow should not need DOM measurement');}});
 assert.equal(result.accepted,false);assert.equal(result.review.status,'needs-attention');
 assert.deepEqual(page,before);assert.equal(page.body,body);
});
const clean=()=>({id:'p',role:'content',title:'标题',body:'原始正文',objects:[
 {id:'title',type:'text',sourceField:'title',text:'标题',x:50,y:40,w:800,h:80,fontSize:40},
 {id:'body',type:'text',sourceField:'body',sourceRange:[0,4],text:'原始正文',x:50,y:160,w:800,h:200,fontSize:26}
]});
test('safe copy remains eligible for fast layout only after rendered measurement',async()=>{
 let measured=0;const page=clean();const result=await checkPrecompiledLayout([page],['p'],{measure:async pages=>{measured++;assert.deepEqual(pages,[page]);return {issues:[]};}});
 assert.equal(result.accepted,true);assert.equal(measured,1);assert.equal(result.review.visionRan,false);
});
test('browser overflow rejects an otherwise source-exact candidate',async()=>{
 const result=await checkPrecompiledLayout([clean()],['p'],{measure:async()=>({issues:[{pageId:'p',kind:'text-overflow',severity:'error'}]})});
 assert.equal(result.accepted,false);assert.equal(result.review.issues[0].kind,'text-overflow');
});
test('overlap and missing target never pass unattended application',async()=>{
 const page=clean();page.objects[1].y=50;
 const overlap=await checkPrecompiledLayout([page],['p'],{measure:()=>{throw Error('Do not measure rejected overlap');}});
 assert.equal(overlap.accepted,false);assert.ok(overlap.review.issues.some(i=>i.kind==='text-overlap'));
 assert.equal((await checkPrecompiledLayout([],['missing'])).accepted,false);
});
test('measurement failure cannot become acceptance',async()=>{
 await assert.rejects(checkPrecompiledLayout([clean()],['p'],{measure:async()=>{throw Error('Measurement failed');}}),/Measurement failed/);
});
