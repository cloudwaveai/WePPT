import test,{after} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm} from 'node:fs/promises';
import {join,resolve,dirname} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {randomUUID} from 'node:crypto';

const here=dirname(fileURLToPath(import.meta.url));
let candidate=process.env.WEPPT_TEST_SERVER;
if(!candidate){
  const root=resolve(here,'../../../..');candidate=join(root,`.account-isolation-test-${randomUUID()}.mjs`);
  const code=(await readFile(join(here,'../server.mjs'),'utf8')).replace("'./account-isolation.mjs'",JSON.stringify(pathToFileURL(resolve(here,'../account-isolation.mjs')).href));
  await writeFile(candidate,code);after(()=>rm(candidate,{force:true}));
}
const {createServer}=await import(pathToFileURL(resolve(candidate)).href);
const {workspaceId}=await import('../account-isolation.mjs');
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZ1kAAAAASUVORK5CYII=';
const project=(id='shared-id',title='original')=>({id,title,stage:'editor',themeId:'curated-139',revision:0,assets:[],messages:[],pages:[{id:'page1',title:'title',body:'body',role:'content',background:'#FFFFFF',objects:[]}]});
async function setup(t,{publicOrigin='https://ppt.cloudwaveai.cn',seed}={}){
  const dataDir=await mkdtemp(join(tmpdir(),'weppt-account-'));await mkdir(join(dataDir,'projects'));if(seed)await seed(dataDir);
  const server=await createServer({dataDir,publicOrigin});await new Promise(r=>server.listen(0,'127.0.0.1',r));
  t.after(async()=>{server.closeAllConnections();await new Promise(r=>server.close(r));await rm(dataDir,{recursive:true,force:true});});
  const base=`http://127.0.0.1:${server.address().port}`;
  const call=(user,path,method='GET',body,extra={})=>fetch(base+path,{method,headers:{'Content-Type':'application/json',...(user?{'X-WePPT-User':encodeURIComponent(user),'X-WePPT-Workspace':workspaceId(user)}:{}),...extra},body:body===undefined?undefined:JSON.stringify(body)});
  return {dataDir,call,base};
}

test('production identity required, session no-store, cross-account stale writes rejected',async t=>{
  const {call}=await setup(t);
  for(const path of ['/api/projects','/api/session','/uploads/a.png','/'])assert.equal((await call(null,path)).status,401);
  for(const value of ['%','../admin','admin%00','admin,admin01','%61dmin'])assert.equal((await call('admin','/api/session','GET',undefined,{'X-WePPT-User':value})).status,401,value);
  const session=await call('admin01','/api/session');assert.equal(session.headers.get('cache-control'),'no-store');assert.deepEqual(await session.json(),{username:'admin01',workspace:workspaceId('admin01')});
  assert.equal(session.headers.get('x-weppt-workspace'),workspaceId('admin01'));
  for(const token of ['',workspaceId('admin')])assert.equal((await call('admin01','/api/projects/new','PUT',project('new'),{'X-WePPT-Workspace':token})).status,409);
  assert.equal((await call('admin01','/api/design/reference-jobs/list','POST',{}, {'X-WePPT-Workspace':workspaceId('admin')})).status,409);
  assert.equal((await call('admin','/api/session','GET',undefined,{Origin:'https://evil.example'})).status,403);
});

test('legacy projects remain byte identical; list/read/update/delete and same IDs isolated',async t=>{
  const original=JSON.stringify({...project('legacy','private original'),revision:3});
  const {call,dataDir}=await setup(t,{seed:d=>writeFile(join(d,'projects','legacy.json'),original)});
  assert.equal((await(await call('admin','/api/projects')).json()).projects.length,1);
  assert.deepEqual((await(await call('admin01','/api/projects')).json()).projects,[]);
  assert.equal((await call('admin01','/api/projects/legacy')).status,404);
  assert.equal((await call('admin01','/api/projects/legacy','DELETE')).status,404);
  assert.equal((await call('admin01','/api/projects/legacy','PUT',{...project('legacy'),revision:3})).status,409);
  const [a,b]=await Promise.all([call('admin','/api/projects/shared-id','PUT',project('shared-id','A')),call('admin01','/api/projects/shared-id','PUT',project('shared-id','B'))]);
  assert.equal(a.status,200);assert.equal(b.status,200);
  assert.equal((await(await call('admin','/api/projects/shared-id')).json()).title,'A');
  const own=await(await call('admin01','/api/projects/shared-id')).json();assert.equal(own.title,'B');
  assert.equal((await call('admin01','/api/projects/shared-id','PUT',{...own,title:'B2'})).status,200);
  assert.equal((await call('admin01','/api/projects/shared-id','DELETE')).status,200);
  assert.equal((await(await call('admin','/api/projects/shared-id')).json()).title,'A');
  assert.equal(await readFile(join(dataDir,'projects','legacy.json'),'utf8'),original);
  assert.equal(await readFile(join(dataDir,'projects','shared-id.json'),'utf8').then(s=>JSON.parse(s).title),'A');
});

test('uploads and export resolvers cannot read another workspace asset',async t=>{
  const {call}=await setup(t);
  const asset=await(await call('admin','/api/assets','POST',{name:'private.png',data:png})).json();assert.match(asset.src,/^\/uploads\//);
  const own=await call('admin',asset.src);assert.equal(own.status,200);assert.equal(own.headers.get('cache-control'),'no-store');assert.deepEqual(Buffer.from(await own.arrayBuffer()),Buffer.from(png,'base64'));
  assert.equal((await call('admin01',asset.src)).status,404);
  const p=project();p.pages[0].objects=[{id:'image1',type:'image',src:asset.src,x:10,y:10,w:100,h:100}];
  const ok=await call('admin','/api/export','POST',p);assert.equal(ok.status,200);assert.ok((await ok.arrayBuffer()).byteLength>100);
  const denied=await call('admin01','/api/export','POST',p);assert.notEqual(denied.status,200);
  const ownAsset=await(await call('admin01','/api/assets','POST',{name:'new.png',data:png})).json();assert.equal((await call('admin01',ownAsset.src)).status,200);assert.equal((await call('admin',ownAsset.src)).status,404);
});

test('job status/cancel/resume scoped to workspace and original failed task untouched',async t=>{
  const id=randomUUID(),stamp=new Date().toISOString();
  const original=JSON.stringify({version:1,id,input:{project:project('private-job'),themeId:'curated-139',targetPageIds:['page1'],instruction:''},status:'failed',pages:[],failures:[],pageStatus:[],message:'private failure',createdAt:stamp,updatedAt:stamp});
  const {call,dataDir}=await setup(t,{seed:async d=>{await mkdir(join(d,'reference-jobs'));await writeFile(join(d,'reference-jobs',id+'.json'),original);}});
  assert.equal((await call('admin','/api/design/reference-jobs/status','POST',{id})).status,200);
  for(const action of ['status','cancel','resume'])assert.equal((await call('admin01',`/api/design/reference-jobs/${action}`,'POST',{id})).status,404,action);
  assert.equal(await readFile(join(dataDir,'reference-jobs',id+'.json'),'utf8'),original);
});

test('local mode remains compatible without identity headers and exposes local session',async t=>{
  const {call}=await setup(t,{publicOrigin:''});
  assert.equal((await call(null,'/api/projects/shared-id','PUT',project())).status,200);
  assert.equal((await(await call(null,'/api/session')).json()).username,'local');
});
