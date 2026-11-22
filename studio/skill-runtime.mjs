import {upstreamReferences} from './upstream-skills.mjs';
import {writingSkillContext} from './writing-skills.mjs';
import {thinkingSkillContext} from './thinking-skills.mjs';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const VERSION='weppt-design-2026-11-10.generation-rules2.layout-diversity1.chapter-pages1.chapter-layout-unified1';
const ROOT=new URL('./skills/weppt/',import.meta.url);
// Global product invariant: applies even when a short request does not route to design skills.
const STYLE_CONTINUITY_RULES=readFileSync(fileURLToPath(new URL('references/GENERATION_RULES.md',ROOT)),'utf8').trim();

const ALLOWED=new Set(['narrative','visual-direction','template-adaptation','page-design','precise-edit','visual-review']);
const cache=new Map();
function readSkill(id,brief=false){
 if(!ALLOWED.has(id))throw Error('未知内嵌设计技能。');
 if(!cache.has(id)){
  const raw=readFileSync(fileURLToPath(new URL(`${id}/SKILL.md`,ROOT)),'utf8');
  if(!/^---\r?\nname: [\w-]+\r?\ndescription: .+\r?\n---\r?\n/.test(raw))throw Error(`内嵌技能 ${id} 元数据不完整。`);
  const full=raw.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/,'').trim();
  const core=full.split(/\r?\n## 执行\r?\n/)[0].trim();cache.set(id,{full,core});
 }
 return cache.get(id)[brief?'core':'full'];
}

const aesthetic=/(?:审美|美观|好看|难看|不好看|丑|高级感|精致|漂亮|太土|视觉|设计|排版|布局|构图|留白|图文|层次|风格|模板|配色|阴影|透明|质感|图片比例|字体搭配|太挤|拥挤|单调|重复)/i;
const narrative=/(?:文案|大纲|目录|章节|标题表达|逻辑|叙事|结构|拆页|拆分|页数|内容太多|重点|演讲|阅读|受众|培训)/;
const review=/(?:审稿|审看|检查|评价|点评|评估|为什么|哪里不好|有什么问题|建议|意见)/;
const template=/(?:模板|参考|风格|换一套|还原)/;
const design=/(?:重排|排版|布局|构图|重新设计|设计.{0,5}页|图文|流程|比较|对比|层次)/;

/** Fixed local allowlist. Returned rules are data for existing model calls, not a tool loader. */
export function buildSkillContext({mode='chat',project,message='',scope='deck'}={}){
 if(!['draft','chat','plan','review'].includes(mode))throw Error('内嵌技能任务类型不正确。');
 let text=typeof message==='string'?message:'';const ids=[];
 // Follow-up confirmation can inherit routing signals, never executable instructions.
 if(/按.{0,8}(?:建议|刚才|上面)|就这样改|照这个改/.test(text))text+='\n'+(Array.isArray(project?.messages)?project.messages.slice(-3).map(m=>typeof m?.text==='string'?m.text:'').join('\n'):'');
 const add=id=>{if(!ids.includes(id))ids.push(id);};
 if(mode==='draft'){add('narrative');add('visual-direction');}
 else if(mode==='plan'){add('visual-direction');add('template-adaptation');add('page-design');}
 else if(mode==='review'){add('visual-direction');add('visual-review');}
 else{
  add('precise-edit');
  if(aesthetic.test(text)){add('visual-direction');if(review.test(text))add('visual-review');else if(template.test(text))add('template-adaptation');else if(design.test(text))add('page-design');}
  else if(review.test(text)){add('visual-direction');add('visual-review');}
  if(narrative.test(text))add('narrative');
 }
 // Routing context never treats user-provided content, filenames or URLs as instructions.
 const stage=project?.stage==='draft'?'文案讨论':project?.stage==='editor'?'可编辑页面':'未指定';
 const area=scope==='object'?'选中对象':scope==='page'?'当前页':'整份';
 const header=`WePPT 内嵌设计技能 ${VERSION}。当前阶段：${stage}；作用范围：${area}。只使用当前任务提供的工具与输出格式；技能不扩大修改权限。用户只要求建议时不执行修改。以下是按本次任务加载的规则。\n${STYLE_CONTINUITY_RULES}`;
 const upstream=upstreamReferences({mode,ids});
 const writing=writingSkillContext({mode,project,message:text,scope});
 const thinking=thinkingSkillContext({mode,message});
 const assemble=compact=>[header,...ids.map(id=>`\n<skill id="${id}">\n${readSkill(id,mode==='draft'||compact&&id!=='precise-edit')}\n</skill>`),upstream.instructions,compact?(writing.compactInstructions||writing.instructions):writing.instructions,thinking.instructions].join('\n');
 let instructions=assemble(false);
 // Keep the complete generation contract and precise edit boundaries; compact optional skill detail if needed.
 if(instructions.length>10000)instructions=assemble(true);
 if(instructions.length>10000)throw Error('内嵌技能超出上下文预算，请精简规则。');
 return {ids:[...ids,...writing.ids,...thinking.ids],version:VERSION,instructions,upstream:[...upstream.references,...writing.references,...thinking.references]};
}
