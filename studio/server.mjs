import {createAccountServer} from './account-isolation.mjs';
import {createReferenceJobs} from './reference-design-jobs.mjs';
import {importSvgPages,importPptxPages,importPdfPages,exportNativePptx} from './svg-engine.mjs';
import {validateVectorObject} from './public/vector-scene.js';
import {generateSvgDesign} from './svg-design-ai.mjs';
import http from 'node:http';
import {readFile,writeFile,mkdir,readdir,rename,unlink,stat} from 'node:fs/promises';
import {join,resolve,extname,basename,sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import {randomUUID} from 'node:crypto';
import {spawn} from 'node:child_process';
import {aiStatus,runAI} from './ai.mjs';
import {exportPptx} from './export.mjs';
import {planDesign,reviewDesign} from './design-ai.mjs';

const ROOT=fileURLToPath(new URL('.',import.meta.url));
const projectLimitMB=Number(process.env.WEPPT_MAX_PROJECT_MB||128);
if(!Number.isSafeInteger(projectLimitMB)||projectLimitMB<1||projectLimitMB>1024)throw Error('WEPPT_MAX_PROJECT_MB must be an integer from 1 to 1024.');
const projectLimitBytes=projectLimitMB*1024*1024;
export class HttpError extends Error{constructor(status,message){super(message);this.status=status;}}
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.mjs':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json; charset=utf-8','.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.webp':'image/webp','.gif':'image/gif','.svg':'image/svg+xml','.ico':'image/x-icon'};
const validId=id=>typeof id==='string'&&/^[\w-]{1,100}$/.test(id);
function validateProject(project,id){
  if(!project||typeof project!=='object'||project.id!==id||!validId(id))throw new HttpError(400,'项目标识不正确。');
  if(typeof project.title!=='string'||project.title.length>500||!['draft','editor'].includes(project.stage))throw new HttpError(400,'项目名称或阶段不正确。');
  if(!Array.isArray(project.pages)||project.pages.length>200)throw new HttpError(400,'页面数量不能超过 200。');
  const ids=new Set();
  for(const page of project.pages){
    if(!validId(page.id)||ids.has(page.id)||typeof page.title!=='string'||typeof page.body!=='string')throw new HttpError(400,'页面内容或标识不正确。');ids.add(page.id);
    if(page.body.length>100000||(page.objects?.length || 0)>1000)throw new HttpError(400,'单页内容过多，请拆页。');
    if(page.objects){if(!Array.isArray(page.objects))throw new HttpError(400,'页面对象格式不正确。');const objectIds=new Set();for(const o of page.objects){if(!validId(o.id)||objectIds.has(o.id)||!['text','image','rect','ellipse','line','vector'].includes(o.type))throw new HttpError(400,'页面对象标识或类型不正确。');objectIds.add(o.id);if(o.type==='vector')validateVectorObject(o);for(const key of ['x','y','w','h'])if(!Number.isFinite(o[key])||Math.abs(o[key])>20000)throw new HttpError(400,'对象位置或尺寸不正确。');if(o.w<0||o.h<0)throw new HttpError(400,'对象尺寸不能为负数。');}}
  }
  if(!Number.isInteger(project.revision)||project.revision<0)throw new HttpError(400,'项目版本不正确。');
}
function json(res,status,value){const bytes=Buffer.from(JSON.stringify(value));res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Content-Length':bytes.length,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.end(bytes);}
async function body(req){
  if(!String(req.headers['content-type'] || '').startsWith('application/json'))throw new HttpError(415,'请求必须是 JSON。');
  const parts=[];let size=0;for await(const part of req){size+=part.length;if(size>projectLimitBytes)throw new HttpError(413,`请求数据超过 ${projectLimitMB} MB，请拆分文稿或联系管理员调整文稿容量。`);parts.push(part);}try{return JSON.parse(Buffer.concat(parts).toString('utf8'));}catch{throw new HttpError(400,'无法读取请求内容。');}
}
function decodeUpload(input,max=20*1024*1024){
  if(typeof input.name!=='string'||!input.name.trim()||input.name.length>300||typeof input.data!=='string')throw new HttpError(400,'缺少文件名或内容。');
  const source=input.data.replace(/^data:[^,]*;base64,/, '');if(!/^[a-z\d+/=\r\n]+$/i.test(source))throw new HttpError(400,'文件编码不正确。');
  const raw=Buffer.from(source,'base64');if(!raw.length||raw.length>max)throw new HttpError(413,'文件过大或为空。');return raw;
}
function imageKind(raw){if(raw.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])))return 'png';if(raw[0]===255&&raw[1]===216&&raw[2]===255)return 'jpg';if(/^GIF8[79]a/.test(raw.subarray(0,6).toString()))return 'gif';if(raw.subarray(0,4).toString()==='RIFF'&&raw.subarray(8,12).toString()==='WEBP')return 'webp';return null;}
async function extract(input){
  return new Promise((resolveExtract,reject)=>{
    const child=spawn(process.env.PYTHON || 'python',['-X','utf8',join(ROOT,'extract_material.py')],{windowsHide:true,stdio:['pipe','pipe','pipe']});let output='',errors='';const timer=setTimeout(()=>{child.kill();reject(new HttpError(408,'文档解析超时，请拆分材料。'));},30000);
    child.stdout.on('data',x=>output+=x.toString());child.stderr.on('data',x=>errors=(errors+x.toString()).slice(-1000));child.on('error',()=>{clearTimeout(timer);reject(new HttpError(503,'文档解析程序未安装，请检查 Python。'));});child.on('close',code=>{clearTimeout(timer);try{const result=JSON.parse(output);if(code!==0||result.error)reject(new HttpError(422,result.error || '文档无法解析。'));else resolveExtract(result.text);}catch{reject(new HttpError(422,'文档无法解析，请确认文件格式。'));}});child.stdin.on('error',()=>{});child.stdin.end(JSON.stringify(input));
  });
}

async function createWorkspaceServer({dataDir=process.env.WEPPT_DATA_DIR || join(ROOT,'data'),publicDir=join(ROOT,'public'),publicOrigin=process.env.WEPPT_PUBLIC_ORIGIN || ''}={}){
  let deploymentOrigin=null;
  if(publicOrigin){
    const parsed=new URL(publicOrigin);
    if(!['https:','http:'].includes(parsed.protocol)||parsed.username||parsed.password||parsed.pathname!=='/'||parsed.search||parsed.hash)throw Error('WEPPT_PUBLIC_ORIGIN must be an HTTP(S) origin without credentials, path or query.');
    deploymentOrigin=parsed;
  }
  dataDir=resolve(dataDir);publicDir=resolve(publicDir);await mkdir(join(dataDir,'projects'),{recursive:true});await mkdir(join(dataDir,'uploads'),{recursive:true});
  const referenceJobs=createReferenceJobs({dataDir});
  const queues=new Map();
  const serialized=(id,work)=>{const pending=(queues.get(id)||Promise.resolve()).catch(()=>{}).then(work);queues.set(id,pending);pending.finally(()=>{if(queues.get(id)===pending)queues.delete(id);}).catch(()=>{});return pending;};
  const projectPath=id=>join(dataDir,'projects',id+'.json');
  const load=async id=>{try{return JSON.parse(await readFile(projectPath(id),'utf8'));}catch(e){if(e.code==='ENOENT')throw new HttpError(404,'项目不存在。');throw e;}};
  const asset=async input=>{
    const raw=decodeUpload(input,8*1024*1024),ext=imageKind(raw);if(!ext)throw new HttpError(415,'请上传 PNG、JPEG、GIF 或 WebP 图片。');
    const id=randomUUID(),file=`${id}.${ext}`;await writeFile(join(dataDir,'uploads',file),raw,{flag:'wx'});return {id,name:basename(input.name),src:`/uploads/${file}`,kind:input.kind==='logo'?'logo':'image'};
  };
  const server=http.createServer(async(req,res)=>{
    try{
      const host=(req.headers.host || '').toLowerCase(),localHost=/^(?:127\.0\.0\.1|localhost)(?::\d+)?$/i.test(host),publicHost=deploymentOrigin&&host===deploymentOrigin.host;
      if(!localHost&&!publicHost)throw new HttpError(403,'不允许此访问域名。');
      const expectedOrigin=publicHost?deploymentOrigin.origin:`http://${host}`;
      const origin=req.headers.origin;if(origin && origin!==expectedOrigin)throw new HttpError(403,'不接受其他网站发起的请求。');
      if(['cross-site'].includes(req.headers['sec-fetch-site']))throw new HttpError(403,'不接受跨站请求。');
      const url=new URL(req.url,`http://${host}`),path=decodeURIComponent(url.pathname),method=req.method;
      if(method==='POST'&&path.startsWith('/api/design/reference-jobs/')){
        const input=await body(req),action=path.slice('/api/design/reference-jobs/'.length);
        if(action==='list'){json(res,200,{jobs:await referenceJobs.list(),deletedJobIds:await referenceJobs.deletedIds()});return;}
        if(action==='start'){validateProject(input.project,input.project?.id);json(res,202,await referenceJobs.start(input));return;}
        if(action==='delete'){json(res,200,await referenceJobs.remove(input.id,{stop:input.stop===true}));return;}
        if(!['status','resume','cancel'].includes(action))throw new HttpError(404,'生成接口不存在。');
        const result=await referenceJobs[action==='status'?'get':action](input.id,...(action==='resume'?[{resumeRequestId:input.resumeRequestId}]:[]));json(res,200,result);return;
      }
      if(method==='GET'&&path==='/api/health'){json(res,200,{status:'ok',app:'weppt-new'});return;}
      if(method==='GET'&&path==='/api/ai/status'){json(res,200,aiStatus());return;}
      if(method==='GET'&&path==='/api/projects'){
        const projects=[];for(const file of await readdir(join(dataDir,'projects'))){if(!file.endsWith('.json'))continue;try{const p=await load(file.slice(0,-5));projects.push({id:p.id,title:p.title,stage:p.stage,themeId:p.themeId,updatedAt:p.updatedAt,pageCount:p.pages.length});}catch{}}
        projects.sort((a,b)=>String(b.updatedAt).localeCompare(String(a.updatedAt)));json(res,200,{projects});return;
      }
      const match=/^\/api\/projects\/([\w-]{1,100})$/.exec(path);
      if(match){const id=match[1];if(method==='GET'){json(res,200,await load(id));return;}if(method==='PUT'){
        const input=await body(req);validateProject(input,id);
        const saved=await serialized(id,async()=>{let existing=null;try{existing=await load(id);}catch(e){if(e.status!==404)throw e;}
          if(existing && input.revision!==existing.revision)throw new HttpError(409,'此项目已有更新，请重新打开项目后继续。当前修改未覆盖服务器版本。');
          if(!existing&&input.revision!==0)throw new HttpError(409,'项目尚未保存，请以新项目重新保存。');
          const next={...input,revision:(existing?.revision || 0)+1,updatedAt:new Date().toISOString()};const temporary=projectPath(id)+'.'+randomUUID()+'.tmp';await writeFile(temporary,JSON.stringify(next));await rename(temporary,projectPath(id));return next;});json(res,200,req.headers.prefer==='return=minimal'?{id:saved.id,revision:saved.revision,updatedAt:saved.updatedAt}:saved);return;
      }if(method==='DELETE'){await serialized(id,async()=>{await load(id);await unlink(projectPath(id));});json(res,200,{ok:true});return;}}
      if(method==='POST'&&path==='/api/assets'){json(res,201,await asset(await body(req)));return;}
      if(method==='POST'&&path==='/api/materials'){
        const input=await body(req);const raw=decodeUpload(input);if(imageKind(raw)){const image=await asset(input);json(res,200,{...image,text:`图片素材：${image.name}。图片已保存，可在编辑器插入；未进行图片文字识别。`});return;}
        const text=await extract({...input,data:raw.toString('base64')});json(res,200,{name:basename(input.name),text,kind:'document'});return;
      }
      if(method==='POST'&&path==='/api/audience/plan'){
        const input=await body(req);
        if(!validId(input.projectId)||!Number.isSafeInteger(input.revision)||input.revision<0)throw new HttpError(400,'原稿标识或版本无效。');
        const project=await load(input.projectId);validateProject(project,project.id);
        if(project.revision!==input.revision)throw new HttpError(409,'原稿已有更新，请重新打开后生成改编方案。');
        const controller=new AbortController();res.on('close',()=>{if(!res.writableEnded)controller.abort();});
        const {planAudienceVersion}=await import('./audience-version.mjs');
        const result=await planAudienceVersion({project,audience:input.audience,notes:input.notes},{dataDir,signal:controller.signal});
        const current=await load(input.projectId);if(current.revision!==input.revision)throw new HttpError(409,'生成方案期间原稿已有更新，请重新生成。');
        if(!res.destroyed)json(res,200,result);return;
      }
      if(method==='POST'&&path==='/api/ai'){
        const input=await body(req),controller=new AbortController();res.on('close',()=>{if(!res.writableEnded)controller.abort();});if(input.stream===true&&input.action==='revise'&&input.project?.stage==='editor'){await (await import('./image-assistant-stream.mjs')).streamImageAssistant(res,onProgress=>(import('./image-assistant.mjs').then(m=>m.runImageAssistant(input,{dataDir,signal:controller.signal,onProgress}))));return;}const result=input.action==='revise'&&input.project?.stage==='editor'?await (await import('./image-assistant.mjs')).runImageAssistant(input,{dataDir,signal:controller.signal}):await runAI(input,{dataDir,signal:controller.signal});if(!res.destroyed)json(res,200,result);return;
      }
      if(method==='POST'&&path==='/api/design/artwork-layers'){
        const input=await body(req);if(!validId(input.projectId)||!validId(input.pageId)||!Number.isInteger(input.revision))throw new HttpError(400,'项目、页面或版本无效。');
        const project=await load(input.projectId);validateProject(project,project.id);if(project.revision!==input.revision)throw new HttpError(409,'文稿已有新修改，请重新拆分当前页面。');
        const controller=new AbortController();res.on('close',()=>{if(!res.writableEnded)controller.abort();});
        const {splitExistingPageArtwork}=await import('./editable-artwork-repair.mjs');
        const result=await splitExistingPageArtwork(project,input.pageId,{dataDir,signal:controller.signal,artifactDir:join(dataDir,'artwork-split-evidence',randomUUID())});
        const current=await load(input.projectId);if(current.revision!==input.revision)throw new HttpError(409,'拆分期间文稿已更新，候选未覆盖你的修改。');
        if(!res.destroyed)json(res,200,{...result,projectId:project.id,sourceRevision:project.revision});return;
      }
      if(method==='POST'&&path==='/api/design/image'){
        const input=await body(req);validateProject(input.project,input.project?.id);const controller=new AbortController();res.on('close',()=>{if(!res.writableEnded)controller.abort();});const {generateImageDesign}=await import('./image-design-ai.mjs');const result=await generateImageDesign({...input,editableArtwork:true},{dataDir,signal:controller.signal});if(!res.destroyed)json(res,200,result);return;
      }
      if(method==='POST'&&path==='/api/design/html'){
        const input=await body(req);validateProject(input.project,input.project?.id);const controller=new AbortController();res.on('close',()=>{if(!res.writableEnded)controller.abort();});const {generateHtmlEngineDesign}=await import('./engine-design-ai.mjs');const result=await generateHtmlEngineDesign(input,{dataDir,signal:controller.signal});if(!res.destroyed)json(res,200,result);return;
      }
      if(method==='POST'&&path==='/api/design/svg'){
        const input=await body(req);validateProject(input.project,input.project?.id);const controller=new AbortController();res.on('close',()=>{if(!res.writableEnded)controller.abort();});const result=await generateSvgDesign(input,{dataDir,signal:controller.signal});if(!res.destroyed)json(res,200,result);return;
      }
      if(method==='POST'&&path==='/api/design/import-pptx'){
        const input=await body(req),bytes=decodeUpload(input,20*1024*1024);const controller=new AbortController();res.on('close',()=>{if(!res.writableEnded)controller.abort();});const result=await importPptxPages(bytes,{dataDir,signal:controller.signal});if(!res.destroyed)json(res,200,result);return;
      }
      if(method==='POST'&&path==='/api/design/import-pdf'){
        const input=await body(req),bytes=decodeUpload(input,20*1024*1024);if(!/\.pdf$/i.test(input.name))throw new HttpError(400,'请选择 PDF 原稿。');const controller=new AbortController();res.on('close',()=>{if(!res.writableEnded)controller.abort();});const result=await importPdfPages(bytes,{signal:controller.signal});if(!res.destroyed)json(res,200,result);return;
      }
      if(method==='POST'&&path==='/api/design/import-svg'){
        const input=await body(req);const controller=new AbortController();res.on('close',()=>{if(!res.writableEnded)controller.abort();});const result=await importSvgPages(input,{dataDir,signal:controller.signal});if(!res.destroyed)json(res,200,result);return;
      }
      if(method==='POST'&&(path==='/api/design/plan'||path==='/api/design/review')){
        const input=await body(req);validateProject(input.project,input.project?.id);
        const controller=new AbortController();res.on('close',()=>{if(!res.writableEnded)controller.abort();});
        const result=await (path.endsWith('/plan')?planDesign:reviewDesign)(input,{dataDir,publicDir,signal:controller.signal});
        if(!res.destroyed)json(res,200,result);return;
      }
      if(method==='POST'&&path==='/api/export'){
        const input=await body(req);validateProject(input,input.id);const native=input.pages.some(p=>p.engine==='ppt-master-svg'||p.objects.some(o=>o.type==='vector'||o.flowTypesetting===true));const bytes=await (native?exportNativePptx:exportPptx)(input,{dataDir});res.writeHead(200,{'Content-Type':'application/vnd.openxmlformats-officedocument.presentationml.presentation','Content-Length':bytes.length,'Content-Disposition':`attachment; filename="WePPT.pptx"; filename*=UTF-8''${encodeURIComponent((input.title || '演示文稿')+'.pptx')}`,'Cache-Control':'no-store'});res.end(bytes);return;
      }
      if(method==='GET'&&!path.startsWith('/api/')){
        const upload=/^\/uploads\/([a-f\d-]+\.(png|jpg|gif|webp))$/i.exec(path);let file;
        if(upload)file=join(dataDir,'uploads',upload[1]);else{file=resolve(publicDir,'.'+(path==='/'?'/index.html':path));if(file!==publicDir&&!file.startsWith(publicDir+sep))throw new HttpError(403,'路径不允许访问。');}
        let bytes;try{bytes=await readFile(file);}catch(e){if(e.code==='ENOENT'||e.code==='EISDIR')throw new HttpError(404,'文件不存在。');throw e;}
        res.writeHead(200,{'Content-Type':types[extname(file).toLowerCase()] || 'application/octet-stream','Content-Length':bytes.length,'Cache-Control':upload?'no-store':'no-cache','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'});res.end(bytes);return;
      }
      throw new HttpError(404,'接口不存在。');
    }catch(error){if(!res.headersSent&&!res.destroyed)json(res,error.status || 500,{error:error.status?error.message:(error.message || '操作失败，内容未被覆盖。')});}
  });
  server.requestTimeout=600000;server.headersTimeout=15000;return server;
}

export async function createServer(options={}) {
  const dataDir=options.dataDir || process.env.WEPPT_DATA_DIR || join(ROOT,'data');
  const publicOrigin=options.publicOrigin ?? process.env.WEPPT_PUBLIC_ORIGIN ?? '';
  return createAccountServer({...options,dataDir,publicOrigin,createWorkspace:createWorkspaceServer});
}

if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const port=Number(process.env.PORT || 8788),host=process.env.HOST || '127.0.0.1',server=await createServer();server.listen(port,host,()=>console.log(`WePPT New: http://${host}:${port}`));
}
