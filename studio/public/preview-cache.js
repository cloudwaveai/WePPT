import {accountCacheName} from './account-session.js';
import {previewFingerprint} from './theme-preview.js';

const memory=new Map(),limit=12;
let database;
const bounded=promise=>new Promise((resolve,reject)=>{const timer=setTimeout(()=>resolve(null),1200);promise.then(value=>{clearTimeout(timer);resolve(value);},error=>{clearTimeout(timer);reject(error);});});
async function keyFor(project,themeId){
 const input=`v3-preview-recovery\n${themeId}\n${previewFingerprint(project)}`;
 if(!globalThis.crypto?.subtle)return input;
 const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(input));
 return [...new Uint8Array(bytes)].map(b=>b.toString(16).padStart(2,'0')).join('');
}
function db(){
 if(!globalThis.indexedDB)return Promise.resolve(null);
 if(!database)database=new Promise(resolve=>{
  const request=indexedDB.open(accountCacheName('weppt-theme-previews'),1);
  request.onupgradeneeded=()=>request.result.createObjectStore('previews',{keyPath:'key'});
  request.onsuccess=()=>resolve(request.result);request.onerror=request.onblocked=()=>resolve(null);
 });
 return bounded(database);
}
function remember(key,value){memory.delete(key);memory.set(key,structuredClone(value));while(memory.size>limit)memory.delete(memory.keys().next().value);}
export async function readPreviewCache(project,themeId){
 try{
  const key=await keyFor(project,themeId);
  if(memory.has(key))return structuredClone(memory.get(key));
  const database=await db();if(!database)return null;
  const record=await bounded(new Promise(resolve=>{const tx=database.transaction('previews'),r=tx.objectStore('previews').get(key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>resolve(null);}));
  const value=record?.value;
  if(!value||value.themeId!==themeId||!Array.isArray(value.pages)||!value.pages.length||value.review?.issues?.some(i=>i.severity==='error'))return null;
  remember(key,value);return structuredClone(value);
 }catch{return null;}
}
export async function writePreviewCache(project,themeId,value){
 if(!value?.pages?.length||value.review?.issues?.some(i=>i.severity==='error'))return;
 try{
  const key=await keyFor(project,themeId);remember(key,value);
  const database=await db();if(!database)return;
  await bounded(new Promise(resolve=>{
   const tx=database.transaction('previews','readwrite'),store=tx.objectStore('previews');
   store.put({key,value:structuredClone(value),savedAt:Date.now()});
   const all=store.getAll();all.onsuccess=()=>{for(const row of all.result.sort((a,b)=>b.savedAt-a.savedAt).slice(limit))store.delete(row.key);};
   tx.oncomplete=tx.onerror=tx.onabort=()=>resolve();
  }));
 }catch{/* Preview caching is optional; storage failure must not block editing. */}
}
