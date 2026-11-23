import test from 'node:test';
import assert from 'node:assert/strict';
import {providerFailure} from '../provider-failure.mjs';
import {planCompositions} from '../composition-planner.mjs';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
test('prompt authoring, auth filenames and numeric substrings cannot imply expired login',()=>{
 for(const s of ['native-shape-authoring.md\nError: worker exited','auth.json warning\nError: unknown failure','request 140123\nError: failed'])assert.equal(providerFailure(s,1).diagnostic.category,'unknown');
});
test('only explicit provider evidence yields safe classifications',()=>{
 for(const [s,category,retryable] of [['Error: unexpected status 401 Unauthorized','authorization',false],['ERROR HTTP 403 forbidden','authorization',false],['Error: HTTP 429 insufficient_quota','quota',false],['Error: HTTP 429 too many requests','rate_limit',true],['Error: unexpected status 503','provider_unavailable',true],['Error: stream disconnected','network',true],['Error: unsupported model','model_unavailable',false],['Error: timeout','timeout',false]]){
 const e=providerFailure(s+' secret-token',1);assert.equal(e.diagnostic.category,category);assert.equal(e.diagnostic.retryable,retryable);assert.ok(!JSON.stringify(e).includes('secret-token'));
 }
});
const project={themeId:'midnight',pages:[{id:'a',title:'A',body:'Source',role:'content'}]};
const page={pageId:'a',pageJob:'Explain',relation:'sequence',composition:'Distinct arrangement',geometrySignature:'geometry',readingPath:'top down',zones:[{purpose:'body',x:.1,y:.1,w:.7,h:.7}]};
async function fixture(fn){const dataDir=await mkdtemp(join(tmpdir(),'provider-test-'));try{await fn(dataDir);}finally{await rm(dataDir,{recursive:true,force:true});}}
test('v4 retries a transient failed page once and persists only successful plan',()=>fixture(async dataDir=>{
 let calls=0,saves=0;
 const r=await planCompositions({project},{dataDir,pageWorkers:2,structuredAI:async()=>{if(++calls===1)throw providerFailure('Error: HTTP 503',1);return {pages:[page]};},onCheckpoint:async()=>saves++});
 assert.equal(calls,2);assert.equal(saves,1);assert.equal(r.pages.length,1);
}));
test('retry exhaustion and hard failures never loop',()=>fixture(async dataDir=>{
 for(const [log,count] of [['Error: HTTP 503',2],['Error: HTTP 401',1],['Error: HTTP 429 insufficient_quota',1],['Error: unknown',1]]){
 let calls=0;await assert.rejects(planCompositions({project},{dataDir,pageWorkers:2,structuredAI:async()=>{calls++;throw providerFailure(log,1);},onCheckpoint:async()=>assert.fail('failed page persisted')}));assert.equal(calls,count);
 }
}));
test('cancel during backoff prevents another model call',()=>fixture(async dataDir=>{
 let calls=0;const controller=new AbortController();
 await assert.rejects(planCompositions({project},{dataDir,pageWorkers:2,signal:controller.signal,structuredAI:async()=>{calls++;throw providerFailure('Error: HTTP 503',1);},onProgress:p=>{if(JSON.stringify(p).includes('正在重试'))controller.abort();}}));assert.equal(calls,1);
}));
