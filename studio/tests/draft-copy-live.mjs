// Explicit isolated real-model benchmark. Never calls project persistence APIs.
// node tests/draft-copy-live.mjs /path/source.json /path/new-output-directory
import assert from 'node:assert/strict';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {runAI,MODEL} from '../ai.mjs';
const [sourceArgument,outputArgument]=process.argv.slice(2);
if(!sourceArgument||!outputArgument)throw Error('Usage: node tests/draft-copy-live.mjs SOURCE_JSON NEW_OUTPUT_DIRECTORY');
const sourcePath=resolve(sourceArgument),output=resolve(outputArgument),bytes=await readFile(sourcePath),source=JSON.parse(bytes),project=structuredClone(source);
assert(Array.isArray(project.pages)&&project.pages.length>0,'source must be a complete project');
const hash=value=>createHash('sha256').update(value).digest('hex'),sourceHash=hash(bytes);
await mkdir(output,{recursive:true});
// An exclusive marker prevents accidentally mixing evidence from multiple runs.
await writeFile(join(output,'benchmark-run.json'),JSON.stringify({sourceHash,sourcePageCount:source.pages.length,createdAt:new Date().toISOString()}),{flag:'wx'});
project.id='benchmark-'+randomUUID();project.stage='draft';
const message='字好多啊，可以精减吗，或者有些页字多点，，你这每一页字都好多';
const request={action:'revise',scope:'deck',message,project,materials:project.materials||[]};
const report={model:MODEL,sourceHash,pageCount:project.pages.length,originalStage:source.stage,testStage:'draft',isolatedProjectId:project.id,inputBodyChars:project.pages.reduce((n,p)=>n+p.body.length,0),materialChars:request.materials.reduce((n,m)=>n+(m.text||'').length,0),comparison:'This source is an already-shortened later snapshot, not the original 115-second request. Timings are not an identical-input before/after comparison.',progress:[]};
const started=Date.now();
try{
 const result=await runAI(request,{dataDir:join(output,'isolated-data'),onProgress:event=>report.progress.push({...event,elapsedMs:Date.now()-started})});
 report.wallMs=Date.now()-started;
 assert.deepEqual(result.pages,[]);assert.deepEqual(result.operations,[]);
 const changed=new Map(result.changes.map(c=>[c.pageId,c]));assert.equal(changed.size,result.changes.length);
 const after=project.pages.map(p=>({...p,body:changed.get(p.id)?.body??p.body}));
 for(const c of result.changes){const before=project.pages.find(p=>p.id===c.pageId);assert(before);assert.equal(c.title,before.title);assert.equal(c.objectId,'');assert.equal(c.properties,null);}
 assert.equal(hash(await readFile(sourcePath)),sourceHash,'source file changed');
 report.changedPages=result.changes.length;report.outputBodyChars=after.reduce((n,p)=>n+p.body.length,0);report.passed=true;
 report.requiresHumanContentReview=true;
 await writeFile(join(output,'result.json'),JSON.stringify(result,null,2),{flag:'wx'});
 await writeFile(join(output,'copy-comparison.json'),JSON.stringify(project.pages.map((p,i)=>({number:i+1,id:p.id,title:p.title,before:p.body,after:after[i].body,changed:changed.has(p.id)})),null,2),{flag:'wx'});
}catch(error){report.wallMs=Date.now()-started;report.passed=false;report.error={name:error.name,message:error.message};report.sourceUnchanged=hash(await readFile(sourcePath))===sourceHash;process.exitCode=1;}
finally{await writeFile(join(output,'report.json'),JSON.stringify(report,null,2),{flag:'wx'});console.log(JSON.stringify({passed:report.passed,wallMs:report.wallMs,pageCount:report.pageCount,changedPages:report.changedPages,inputBodyChars:report.inputBodyChars,outputBodyChars:report.outputBodyChars,output,error:report.error}));}
