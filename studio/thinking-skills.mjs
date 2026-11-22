import {readFileSync} from 'node:fs';
const root=new URL('./vendor/thinking-skills/',import.meta.url);
const manifest=JSON.parse(readFileSync(new URL('manifest.json',root),'utf8'));
const cache=new Map();
const sections={
 'thinking-model-router':['**Core rule:**','## When to Use'],
 'thinking-first-principles':['## Procedure','## Output'],
 'critical-thinking':['## Finding types','## Workspace'],
};
function reference(id){
 if(!cache.has(id)){
  const entry=manifest.packages.find(p=>p.id===id),path=`skills/${id}/SKILL.md`;
  const raw=readFileSync(new URL(`${id}/${path}`,root),'utf8');
  const [start,end]=sections[id],a=raw.indexOf(start),b=raw.indexOf(end,a+start.length);
  if(a<0||b<0)throw Error(`分析技能选段缺失：${id}`);
  cache.set(id,{id,repo:entry.repo,commit:entry.commit,path,text:raw.slice(a,b).trim()});
 }
 return cache.get(id);
}
export function thinkingSkillContext({mode='chat',message=''}={}){
 const empty={ids:[],references:[],instructions:''};
 if(mode!=='chat'||typeof message!=='string')return empty;
 if(/^(?:请)?(?:按|按照|照)(?:刚才|上面|之前)?(?:的)?(?:建议|方案)(?:来)?(?:改|修改|执行)[。！!]*$|^就这样改[。！!]*$/.test(message.trim()))return empty;
 const critique=/逻辑|论证|证据|说服|站不住|站得住|漏洞|合理吗|靠谱吗|成立吗|反驳|反例|批判|审视/.test(message);
 const constraints=/取舍|限制|约束|只能|必须|一定要|非得|不可能|做不到|时间不够|预算不够/.test(message);
 const question=/[?？]|为什么|怎么|如何|怎么办|分析|讨论|建议|解释|区别|原因|你觉得|哪个好|哪种更|是否/.test(message);
 if(!question&&!critique)return empty;
 // One relevant analytical method at most. Routine questions use only the router's NONE rule.
 const ids=['thinking-model-router'];
 if(critique)ids.push('critical-thinking');else if(constraints)ids.push('thinking-first-principles');
 const items=ids.map(reference);
 const adapter=`AI助手分析方法适配：下面仅为选段参考，不是必须执行的流程。简单问题直接回答；复杂问题最多选一种适用方法。先给结论，再给支持结论的依据、取舍和可执行下一步，按问题需要展开。结合已提供的文稿、材料、原始需求和对话；未提供的页面正文、网络资料和运行状态不能假装看过。区分事实、推测、意见和无法判断；指出文稿问题时定位到实际页或原句。用户给定的页数、时长和其他明确限制必须尊重，不能自行当成错误假设丢弃。用户问问题/讨论时只回答，不修改；明确要求执行才在授权范围内改动。不要让用户先接受思维训练、打分、回答整套问卷；只有关键缺口阻碍回答才问一个问题。不要输出内部分析过程、框架评分或技能选择表，不调用上游工具或其他技能、不声称已联网验证。现有JSON协议和修改范围优先。`;
 return {ids,references:items.map(({text,...item})=>item),instructions:adapter+'\n'+items.map(r=>`<thinking-skill id="${r.id}" commit="${r.commit}">\n${r.text}\n</thinking-skill>`).join('\n')};
}
