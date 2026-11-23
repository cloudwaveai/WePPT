import http from 'node:http';
import {createHash} from 'node:crypto';
import {join,resolve} from 'node:path';

export const workspaceId=username=>createHash('sha256').update(username).digest('hex');
const fail=(status,message)=>Object.assign(Error(message),{status});
function reply(res,status,value){res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.end(JSON.stringify(value));}
function identity(value){
  if(typeof value!=='string'||!value||value.length>1536)throw fail(401,'请重新登录。');
  let name;try{name=decodeURIComponent(value);}catch{throw fail(401,'请重新登录。');}
  if(!/^[^\u0000-\u0020\u007f/:\\]{1,128}$/u.test(name)||encodeURIComponent(name)!==value)throw fail(401,'请重新登录。');
  return name;
}

/** The production reverse proxy must overwrite X-WePPT-User with the verified
 * gateway identity, and this listener must remain inaccessible from the public
 * network. This header is an internal assertion, not a browser credential. */
export async function createAccountServer({dataDir,publicOrigin='',createWorkspace,legacyUsername=process.env.WEPPT_LEGACY_USERNAME||'admin',...options}){
  const root=resolve(dataDir),isolated=!!publicOrigin,instances=new Map();
  let deployment;
  if(isolated){
    deployment=new URL(publicOrigin);
    if(!['https:','http:'].includes(deployment.protocol)||deployment.username||deployment.password||deployment.pathname!=='/'||deployment.search||deployment.hash)throw Error('WEPPT_PUBLIC_ORIGIN must be an HTTP(S) origin without credentials, path or query.');
  }
  const workspace=async username=>{
    if(!instances.has(username)){
      const directory=!isolated||username===legacyUsername?root:join(root,'accounts',workspaceId(username));
      const pending=createWorkspace({...options,dataDir:directory,publicOrigin});
      instances.set(username,pending);pending.catch(()=>{if(instances.get(username)===pending)instances.delete(username);});
    }
    return instances.get(username);
  };
  const server=http.createServer(async(req,res)=>{
    try{
      const host=(req.headers.host||'').toLowerCase(),local=/^(?:127\.0\.0\.1|localhost)(?::\d+)?$/i.test(host),published=deployment&&host===deployment.host;
      if(!local&&!published)throw fail(403,'不允许此访问域名。');
      const expectedOrigin=published?deployment.origin:`http://${host}`;
      if(req.headers.origin&&req.headers.origin!==expectedOrigin||req.headers['sec-fetch-site']==='cross-site')throw fail(403,'不接受其他网站发起的请求。');
      if(req.method==='GET' && req.url==='/api/health'){reply(res,200,{status:'ok',app:'weppt-new'});return;}
      const username=isolated?identity(req.headers['x-weppt-user']):'local',id=isolated?workspaceId(username):'local';
      res.setHeader('X-WePPT-Workspace',id);
      let pathname;try{pathname=decodeURIComponent(new URL(req.url,`http://${host}`).pathname);}catch{throw fail(400,'请求地址无效。');}
      if(isolated&&pathname.startsWith('/api/')&&(!['GET','HEAD'].includes(req.method)||req.headers['x-weppt-workspace']!==undefined)&&req.headers['x-weppt-workspace']!==id)throw fail(409,'登录账号已变化，请刷新页面后再操作。当前请求未执行。');
      if(pathname==='/api/session'&&req.method==='GET'){if(new URL(req.url,`http://${host}`).searchParams.get('bootstrap')==='1')res.setHeader('Clear-Site-Data','"cache"');reply(res,200,{username,workspace:id});return;}
      const instance=await workspace(username);
      if(!res.destroyed)instance.emit('request',req,res);
    }catch(error){if(!res.headersSent&&!res.destroyed)reply(res,error.status||500,{error:error.status?error.message:'账号工作区暂时不可用，请重试。'});}
  });
  server.requestTimeout=600000;server.headersTimeout=15000;
  return server;
}
