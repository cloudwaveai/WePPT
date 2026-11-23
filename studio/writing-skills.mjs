import {readFileSync} from 'node:fs';
const root=new URL('./vendor/writing-skills/',import.meta.url);
const manifest=JSON.parse(readFileSync(new URL('manifest.json',root),'utf8'));
const selections={
 'doc-coauthoring':[['### Initial Questions','### Info Dumping']],
 'copywriting':[['## Drafting Protocol','## Copywriting Principles']],
 'copy-editing':[['### Sentence-Level Checks','### AI-Tell Check'],['### Problem: No Proof','### Problem: Reads as AI-Written']],
};
const bundles=new Map();
function bundle(id){
 if(!bundles.has(id)){
  const entry=manifest.packages.find(p=>p.id===id),path=`skills/${id}/SKILL.md`;
  const raw=readFileSync(new URL(`${id}/${path}`,root),'utf8');
  const text=selections[id].map(([start,end])=>{const a=raw.indexOf(start),b=raw.indexOf(end,a+start.length);if(a<0||b<0)throw Error(`写作技能选段缺失：${id}`);return raw.slice(a,b).trim();}).join('\n');
  bundles.set(id,{id,repo:entry.repo,commit:entry.commit,path,text});
 }
 return bundles.get(id);
}
/** Fixed, pinned upstream excerpts; no user-controlled paths or external tool execution. */
export function writingSkillContext({mode,project,message='',scope='deck'}={}){
 const literalStyle=/^(?:请)?(?:把)?(?:标题|正文|文字)(?:(?:取消)?(?:加粗|斜体)|(?:的)?(?:颜色|字号|字体)?(?:改为|改成|改|设为|设置为)(?:蓝色|红色|黑色|白色|灰色|绿色|黄色|橙色|紫色|#[\da-f]{3,8}|\d+(?:px|磅)?))[。！!]?$/i.test(message.trim());
 const relevant=mode==='draft'||(mode==='chat'&&scope!=='object'&&!literalStyle&&(
  project?.stage==='draft'||/文案|写作|润色|措辞|大纲|叙事|逻辑|受众|审稿|空话|套话|精简|改写|标题|正文/.test(message)));
 if(!relevant)return {ids:[],references:[],instructions:''};
 const ids=['doc-coauthoring','copywriting','copy-editing'],items=ids.map(bundle);
 const adapter=`PPT 写作技能适配：以下为固定版本上游原文选段，完整原文和引用文件保存在项目中。只借用适合本次任务的方法，现有 JSON 格式、用户最新要求和修改范围优先。不要执行上游的文件操作、额外工具调用或多轮问卷；不新增审批步骤。先利用原始需求、对话和材料理解受众与目的；信息不足可说明假设，只有无法继续时问一个关键问题。营销中的客户对应本次听众，行动也可以是理解或学会；培训、汇报不得强加销售诉求。标题和正文服务同一主线，每页承担不同任务。交付前在本次调用内通读并修正空话、重复、跳跃和无依据主张；用户仅要建议时只指出问题，不改稿；局部修改不重写全篇。数字和事实只来自材料，不能把上游示例当作用户事实。不声称经过独立审稿或增加额外模型轮次。`;
 return {ids,references:items.map(({text,...r})=>r),compactInstructions:adapter.replace('以下为固定版本上游原文选段','以下为固定版本上游方法的精简适配')+'\n写作方法要点：先根据已给材料确定受众、目的与期望行动；起草前确定论点和证据、具体表达收益与差异，不凭空添加证明；修改时逐句核对清晰、具体、简洁，删除重复和套话，保留事实、原意与用户声音。',instructions:adapter+'\n'+items.map(r=>`<writing-skill id="${r.id}" commit="${r.commit}">\n${r.text}\n</writing-skill>`).join('\n')};
}
