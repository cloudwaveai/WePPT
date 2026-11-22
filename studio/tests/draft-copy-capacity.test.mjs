import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,readFile,chmod,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
const linux={skip:process.platform==='win32'};
const makeInput=()=>({action:'revise',scope:'deck',message:'请精简一下',materials:[{name:'原始材料',text:'完整材料保留标记'}],project:{stage:'draft',themeId:'curated-005',pages:Array.from({length:12},(_,i)=>({id:'p'+i,title:'标题',body:'必须执行，不得泄露。',role:'content'}))}});
async function fixture(fn){
 const dir=await mkdtemp(join(tmpdir(),'draft-capacity-')),exe=join(dir,'fake-codex'),record=join(dir,'calls.jsonl');
 const keys=['WEPPT_CODEX_PATH','WEPPT_TEST_RECORD','WEPPT_TEST_HOLD_BATCH'],saved=Object.fromEntries(keys.map(k=>[k,process.env[k]]));
 const source=`#!/usr/bin/env node
const fs=require('node:fs'),args=process.argv.slice(2),schema=JSON.parse(fs.readFileSync(args[args.indexOf('--output-schema')+1],'utf8'));
const batch=!!schema.properties?.changes?.items?.properties?.pageId?.enum;
let prompt='';process.stdin.setEncoding('utf8');process.stdin.on('data',s=>prompt+=s);process.stdin.on('end',()=>{
 fs.appendFileSync(process.env.WEPPT_TEST_RECORD,JSON.stringify({pid:process.pid,json:args.includes('--json'),batch,hasMaterial:prompt.includes('完整材料保留标记')})+'\\n');
 if(prompt.includes('__HOLD__')||batch&&process.env.WEPPT_TEST_HOLD_BATCH==='1'){setInterval(()=>{},1000);return;}
 const result=batch?{changes:[]}:{message:'未修改',changes:[],operations:[]};
 if(args.includes('--json')){process.on('SIGTERM',()=>{});setInterval(()=>{},1000);console.log(JSON.stringify({type:'item.completed',item:{type:'agent_message',text:JSON.stringify(result)}}));console.log(JSON.stringify({type:'turn.completed'}));}
 else fs.writeFileSync(args[args.indexOf('--output-last-message')+1],JSON.stringify(result));
});`;
 await writeFile(exe,source);await chmod(exe,0o755);process.env.WEPPT_CODEX_PATH=exe;process.env.WEPPT_TEST_RECORD=record;
 const records=async()=>{try{return(await readFile(record,'utf8')).trim().split('\n').filter(Boolean).map(JSON.parse);}catch{return[];}};
 const waitFor=async count=>{const end=Date.now()+10000;while(Date.now()<end){const rows=await records();if(rows.length>=count)return rows;await new Promise(r=>setTimeout(r,20));}throw Error('fake process did not start');};
 try{const api=await import('../ai.mjs?capacity='+Math.random());await fn({api,dir,records,waitFor});}
 finally{for(const {pid}of await records())try{process.kill(pid,'SIGKILL');}catch{}for(const k of keys)if(saved[k]===undefined)delete process.env[k];else process.env[k]=saved[k];await rm(dir,{recursive:true,force:true});}
}
const hold=(api,dir,controller)=>api.runStructuredAI({action:'image-hold',prompt:'__HOLD__',schema:{type:'object'}},{dataDir:dir,signal:controller.signal});
test('orchestrator occupies no permit: one existing call plus two batches hit shared cap exactly',linux,()=>fixture(async({api,dir,records,waitFor})=>{
 process.env.WEPPT_TEST_HOLD_BATCH='1';const first=new AbortController(),batch=new AbortController();
 const pending=hold(api,dir,first);pending.catch(()=>{});await waitFor(1);
 const concise=api.runAI(makeInput(),{dataDir:dir,signal:batch.signal});concise.catch(()=>{});await waitFor(3);
 await assert.rejects(hold(api,dir,new AbortController()),e=>e.status===429);
 assert.equal((await records()).filter(r=>r.batch).length,2);
 batch.abort();await assert.rejects(concise);first.abort();await assert.rejects(pending);
 for(const {pid}of await records())assert.throws(()=>process.kill(pid,0));
}));
test('with two active calls simplification uses one ordinary call and still retains materials',linux,()=>fixture(async({api,dir,records,waitFor})=>{
 const a=new AbortController(),b=new AbortController(),pa=hold(api,dir,a),pb=hold(api,dir,b);pa.catch(()=>{});pb.catch(()=>{});await waitFor(2);
 const result=await api.runAI(makeInput(),{dataDir:dir});assert.deepEqual(result.changes,[]);
 const rows=await records();assert.equal(rows.length,3);assert.equal(rows[2].batch,false);assert.equal(rows[2].hasMaterial,true);
 a.abort();b.abort();await Promise.allSettled([pa,pb]);
}));
test('draft-concise completion event returns before teardown and reaps resistant processes',linux,()=>fixture(async({api,dir,records})=>{
 const started=Date.now(),result=await api.runAI(makeInput(),{dataDir:dir});assert.deepEqual(result.changes,[]);assert(Date.now()-started<8000);
 const rows=await records();assert.equal(rows.length,2);assert(rows.every(r=>r.json&&r.batch&&r.hasMaterial));
 for(const {pid}of rows)assert.throws(()=>process.kill(pid,0));
}));
