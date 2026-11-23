import {validateOperations} from './public/ai-operations.js';

const empty=message=>({message,pages:[],changes:[],operations:[],designAction:null});
const prefix='(?:请)?(?:帮我)?',current='(?:当前页|这一页|这页|本页)';
const titleCommand=new RegExp('^'+prefix+'(?:把)?(?:'+current+'(?:的)?)?标题(?:改成|改为|修改为|设为|设置为)\\s*([\\s\\S]+)$');
const insertCommand=new RegExp('^'+prefix+'((?:在)?'+current+'(?:后面|后))?(?:新增|添加|插入)(?:一|1)页([\\s\\S]*)$');
const restoreCommand=new RegExp('^'+prefix+'(?:'+current+'沿用整套模板|把'+current+'改成和前面统一的模板)[，,](?:原文不变|保留原文|文字不变)$');
function quoted(text){
 for(const [left,right]of [['“','”'],['"','"'],['「','」']]){
  if(!text.startsWith(left))continue;
  const end=text.indexOf(right,1);if(end<0)return null;
  return {value:text.slice(1,end),rest:text.slice(end+1).trim()};
 }
 return null;
}
function titleLiteral(text){
 const token=quoted(text);
 if(token)return token.rest===''?token.value:null;
 // Unquoted compound instructions must fall through in full, never partially execute.
 if(/[“”"「」,，;；。！？?!\r\n]/.test(text)||/并|再|同时|然后|顺便|以及|且/.test(text))return null;
 return text;
}
function currentPage(input){
 if(typeof input.pageId!=='string'||!input.pageId)return null;
 const matches=input.project.pages.filter(p=>p.id===input.pageId);
 return matches.length===1?matches[0]:null;
}
function insertCopy(tail){
 if(!tail)return {title:'新页面',body:'在这里写下这一页的内容'};
 let text=tail.replace(/^[，,：:]\s*/,'').replace(/^标题\s*[:：]\s*/,'');
 const title=quoted(text);if(!title||!title.value.trim()||title.value.length>500)return null;
 if(!title.rest)return {title:title.value,body:''};
 const rest=/^[，,；;\n]\s*(?:正文|内容)\s*[:：]\s*([\s\S]+)$/.exec(title.rest);
 if(!rest)return null;
 const body=quoted(rest[1]);
 return body&&body.rest===''&&body.value.length<=25000?{title:title.value,body:body.value}:null;
}
const pageChange=(page,title=page.title)=>({pageId:page.id,objectId:'',title,body:page.body,text:null,properties:null});
/** Pure exact-command route: no model, network, filesystem or source mutation. */
export function fastEditorAction(input){
 if(input?.action!=='revise'||input.project?.stage!=='editor'||!['page','deck'].includes(input.scope)||!Array.isArray(input.project.pages)||typeof input.message!=='string')return null;
 const text=input.message.trim().replace(/[。！!]$/,'').trim();if(!text)return null;
 if(restoreCommand.test(text)){
  const page=currentPage(input);if(!page||typeof page.title!=='string'||typeof page.body!=='string')return null;
  if(page.title.length>60||page.body.length>240)return null;
  return {...empty('已沿用整套模板调整当前页，原文保持不变。'),changes:[pageChange(page)],directLayout:'inherit'};
 }
 const match=titleCommand.exec(text);
 if(match){
  const page=currentPage(input),title=titleLiteral(match[1].trim());
  if(!page||typeof page.body!=='string'||title===null||!title.trim()||title.length>500)return null;
  return {...empty('已直接更新当前页标题，正文和模板保持不变。'),changes:[pageChange(page,title)]};
 }
 const insertion=insertCommand.exec(text);if(!insertion)return null;
 const copy=insertCopy(insertion[2].trim());if(!copy)return null;
 const selected=currentPage(input);
 if((insertion[1]||input.scope==='page'||input.pageId)&&!selected)return null;
 const anchor=selected||(input.scope==='deck'?input.project.pages.at(-1):null);if(!anchor)return null;
 const result={...empty('已按当前模板插入页面，可直接编辑。'),operations:[{type:'insert',pageIds:[],afterPageId:anchor.id,pages:[{...copy,role:'content'}]}],...(copy.title.length<=60&&copy.body.length<=240?{directLayout:'inherit'}:{})};
 try{validateOperations(result,input);}catch{return null;}
 return result;
}
