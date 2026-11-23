import {measureBlueprintCopy} from './blueprint-copy-flow.js';
// Pure deck-wide allocation. Offline-designed packs opt in; no model or I/O here.
export function compositionKey(layout){
 const boxes=(layout?.objects||[]).filter(o=>o.type==='image'||['title','body','chapter-number'].includes(o.blueprintSlot));
 return JSON.stringify(boxes.map(o=>[o.type,o.blueprintSlot||'',...[o.x,o.y,o.w,o.h].map(n=>Math.round(n/64))]).sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b))));
}
export function sameComposition(left,right){
 const boxes=l=>(l?.objects||[]).filter(o=>o.type==='image'||['title','body','chapter-number'].includes(o.blueprintSlot));
 const compare=(a,b)=>{if(a.length!==b.length)return false;
 const assigned=new Map();
 const match=(i,seen)=>{for(let j=0;j<b.length;j++)if(!seen.has(j)&&a[i].type===b[j].type&&a[i].blueprintSlot===b[j].blueprintSlot&&['x','y','w','h'].every(k=>Math.abs(a[i][k]-b[j][k])<=48)){seen.add(j);if(!assigned.has(j)||match(assigned.get(j),seen)){assigned.set(j,i);return true;}}return false;};
 return a.length>0&&a.every((_,i)=>match(i,new Set()));};
 const a=boxes(left),b=boxes(right);
 return compare(a,b)||compare(a.filter(o=>o.type==='text'),b.filter(o=>o.type==='text'));
}
function capacity(layout){return (layout.objects||[]).filter(o=>o.blueprintSlot==='body').reduce((n,o)=>n+Math.floor(o.w/24)*Math.floor(o.h/34),0);}
function relation(page){
 const text=page.title+'\n'+page.body;
 if(page.role==='chapter')return 'chapter';
 if(/对比|比较|差异|优势|不足/.test(text))return 'comparison';
 if(page.role==='flow'||/流程|步骤|阶段|时间|安排/.test(page.title))return 'sequence';
 if(page.role==='data'||/指标|数字|结果|预算|统计/.test(page.title))return 'evidence';
 if(/分工|角色|职责|团队/.test(page.title))return 'roles';
 if(/问题|风险|变更/.test(page.title))return 'problem';
 if(/目标|结论|边界|总结/.test(page.title))return 'focus';
 return 'explanation';
}
export function planBlueprintDeck(pages,pack){
 if(pack?.assignmentPolicy==='semantic-flow-v2')return planFlowDeck(pages,pack);
 if(pack?.assignmentPolicy!=='unique-content-v1')return pages;
 const result=pages.map(p=>({...p})),used=[];
 const jobs=result.map((page,index)=>({page,index})).filter(({page})=>['content','data','flow','chapter'].includes(page.role));
 // Reserve the largest suitable areas for the longest copy before short pages.
 jobs.sort((a,b)=>(b.page.body||'').length-(a.page.body||'').length||a.index-b.index);
 for(const {page} of jobs){
  const variants=page.role==='chapter'?pack.chapterVariants||[]:pack.contentVariants||[];
  const need=[...(page.body||'')].length,kind=relation(page);
  const choices=variants.map((layout,index)=>({layout,index,room:capacity(layout)})).filter(c=>!used.some(layout=>sameComposition(layout,c.layout)));
  choices.sort((a,b)=>{
   const score=c=>(c.room<need?10000+(need-c.room)*10:0)+(c.layout.relations?.includes(kind)?0:1000)+Math.abs(c.room-need);
   return score(a)-score(b)||a.index-b.index;
  });
  const selected=choices[0];
  if(!selected){page.blueprintPlanningWarning='模板独立构图不足，本页保留文案并等待补充版式，不能视为整稿通过。';continue;}
  used.push(selected.layout);page.precompiledVariant=selected.index;
  page.blueprintCompositionId=selected.layout.compositionId;
  delete page.blueprintPlanningWarning;
 }
 return result;
}

// Rectangular minimum-cost matching. A greedy long-copy-first choice can consume
// the only layout that fits another page's title. Solve title + body together.
function assignment(cost){
 const n=cost.length,m=cost[0]?.length||0,u=Array(n+1).fill(0),v=Array(m+1).fill(0),p=Array(m+1).fill(0),way=Array(m+1).fill(0);
 for(let i=1;i<=n;i++){
  p[0]=i;let j0=0;const min=Array(m+1).fill(Infinity),used=Array(m+1).fill(false);
  do{used[j0]=true;const i0=p[j0];let delta=Infinity,j1=0;
   for(let j=1;j<=m;j++)if(!used[j]){const current=cost[i0-1][j-1]-u[i0]-v[j];if(current<min[j]){min[j]=current;way[j]=j0;}if(min[j]<delta){delta=min[j];j1=j;}}
   for(let j=0;j<=m;j++){if(used[j]){u[p[j]]+=delta;v[j]-=delta;}else min[j]-=delta;}j0=j1;
  }while(p[j0]!==0);
  do{const j1=way[j0];p[j0]=p[j1];j0=j1;}while(j0);
 }
 const result=Array(n).fill(-1);for(let j=1;j<=m;j++)if(p[j])result[p[j]-1]=j-1;return result;
}
function planFlowDeck(pages,pack){
 const result=pages.map(page=>({...page}));
 for(const chapter of [false,true]){
  const jobs=result.filter(p=>chapter?p.role==='chapter':['content','data','flow'].includes(p.role));if(!jobs.length)continue;
  const raw=chapter?pack.chapterVariants||[]:pack.contentVariants||[];
  const variants=[];
  raw.forEach((layout,index)=>{
   // A named design family is a constraint, never proof of visual uniqueness.
   if(!variants.some(v=>v.layout.compositionFamily&&v.layout.compositionFamily===layout.compositionFamily||sameComposition(v.layout,layout)))variants.push({layout,index});
  });
  const measured=jobs.map(page=>variants.map(({layout})=>measureBlueprintCopy(page,layout)));
  const costs=jobs.map((page,i)=>[...variants.map(({layout},j)=>{
   const m=measured[i][j],unused=Math.max(0,m.availableHeight-m.requiredHeight)/Math.max(1,m.availableHeight);
   return (m.fits?0:1e6+m.warnings.length*10000)+(layout.relations?.includes(relation(page))?0:1000)+unused*100+j*.001;
  }),...jobs.map((_,j)=>1e8+j)]);
  // New authored packs may explicitly share same-role chapter layouts. Content
  // still uses one-to-one assignment; existing accepted packs keep their plan.
  const selected=chapter&&pack.chapterLayoutPolicy==='shared'
   ?costs.map(row=>row.indexOf(Math.min(...row)))
   :assignment(costs);
  jobs.forEach((page,i)=>{
   delete page.precompiledVariant;delete page.blueprintCompositionId;delete page.blueprintPlanningWarning;
   const choice=variants[selected[i]];
   if(!choice){page.blueprintPlanningWarning='模板独立构图不足，原文已保留，本页需要新增合适构图，整稿不能通过验收。';return;}
   page.precompiledVariant=choice.index;page.blueprintCompositionId=choice.layout.compositionId;
   if(!measured[i][selected[i]].fits)page.blueprintPlanningWarning='没有足够的独立构图同时容纳本稿的标题和正文；原文保留、字号不缩小，需重新设计。';
  });
 }
 return result;
}
