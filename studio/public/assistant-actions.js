// Shared workflow contract: chat chooses a tool; the app still validates its scope.
export const DESIGN_ACTION_SCHEMA={anyOf:[{type:'null'},{type:'object',additionalProperties:false,required:['type','pageIds','instruction'],properties:{type:{type:'string',enum:['redesign','review','image-redesign']},pageIds:{type:'array',minItems:1,maxItems:100,items:{type:'string'}},instruction:{type:'string',maxLength:6000}}}]};
export function adviceOnly(message=''){
 return /(?:先|只|仅).{0,8}(?:讨论|聊聊|给建议|建议|思路|分析|诊断)|(?:先|暂时)(?:不要|别)(?:改|修改|执行|应用)|只说思路|仅讨论|不执行修改|不要修改|不要改动/.test(message);
}
export function validateDesignAction(result,input){
 const action=result.designAction;if(action==null)return null;
 if(input.action!=='revise'||input.project?.stage!=='editor'||input.scope==='object')throw Error('此范围不支持页面设计操作，请选择当前页或整份。');
 if(adviceOnly(input.message))throw Error('你要求先给建议，本次设计未执行。');
 if(typeof action!=='object'||Array.isArray(action)||Object.keys(action).some(k=>!['type','pageIds','instruction'].includes(k))||!['redesign','review','image-redesign'].includes(action.type)||typeof action.instruction!=='string'||action.instruction.length>6000||!Array.isArray(action.pageIds)||!action.pageIds.length||action.pageIds.length>100||new Set(action.pageIds).size!==action.pageIds.length)throw Error('助手设计请求格式不正确。');
 if(action.type==='image-redesign'&&!/image|生图/i.test(input.message))throw Error('请明确要求使用 Image 设计。');
 const ids=new Set(input.project.pages.map(p=>p.id));
 if(action.pageIds.some(id=>!ids.has(id)||input.scope==='page'&&id!==input.pageId))throw Error('助手设计超出选定页面范围，未执行。');
 if((result.pages||[]).length||(result.changes||[]).length||(result.operations||[]).length)throw Error('页面设计不能同时混入文案或对象修改，请分步执行。');
 if(action.type==='redesign'&&input.project.themeId!=='curated-139'&&!['svg','slidev','pptagent'].includes(input.project.designEngine))throw Error('这套模板尚未接入逐页重新设计，可先讨论建议或调整已有对象。');
 return structuredClone(action);
}
