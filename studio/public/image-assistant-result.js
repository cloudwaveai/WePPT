// Derive source metadata from the original bindings, never returned model ranges.
export function synchronizeImageCopy(source,next){
 for(const field of ['title','body']){
  const base=source.layoutSource?.[field]??source[field];
  const bound=(source.objects||[]).filter(o=>o.type==='text'&&(o.layoutField===field||o.sourceField===field));
  if(typeof base!=='string'||!bound.length)continue;
  const ranges=bound.map(o=>({o,range:Array.isArray(o.sourceRange)?o.sourceRange:bound.length===1&&(o.sourceText===base||o.text===base)?[0,base.length]:null}));
  if(ranges.some(r=>!r.range)){
   if(bound.some(o=>next.objects.find(n=>n.id===o.id)?.text!==o.text))throw Error('文字来源不明确，原稿已保留。');
   continue;
  }
  ranges.sort((a,b)=>a.range[0]-b.range[0]);let cursor=0,delta=0,value='';
  for(const {o:old,range:[a,b]} of ranges){
   const o=next.objects.find(n=>n.id===old.id);
   if(!o||!Number.isInteger(a)||!Number.isInteger(b)||a<cursor||b<a||b>base.length)throw Error('文字来源范围已失效，原稿已保留。');
   const text=String(o.text??'');value+=base.slice(cursor,a)+text;
   if(old.sourceRange){o.sourceRange=[a+delta,a+delta+text.length];if(Object.hasOwn(old,'sourceStart'))o.sourceStart=o.sourceRange[0];if(Object.hasOwn(old,'sourceEnd'))o.sourceEnd=o.sourceRange[1];}
   if(Object.hasOwn(old,'sourceText'))o.sourceText=text;
   delta+=text.length-(b-a);cursor=b;
  }
  next[field]=value+base.slice(cursor);
 }
 if(source.layoutSource)next.layoutSource={...source.layoutSource,title:next.title,body:next.body};
 return next;
}
// Validate a complete Image + Sol transaction before touching the live project.
export function validateImageEdit(result,input){
 const edit=result.imageEdit;if(edit==null)return null;
 if(edit.usedImage!==true||!Array.isArray(edit.pages)||!edit.pages.length||edit.pages.length>100||!Array.isArray(edit.changedPageIds)||!edit.changedPageIds.length||new Set(edit.changedPageIds).size!==edit.changedPageIds.length)throw Error('Image 修改结果不完整，原稿已保留。');
 if(result.pages?.length||result.changes?.length||result.operations?.length||result.designAction)throw Error('Image 修改混入其他提交路径，原稿已保留。');
 const before=input.project.pages,original=new Map(before.map(p=>[p.id,p])),next=new Map(),changed=new Set(edit.changedPageIds);
 for(const page of edit.pages){
  if(!page||typeof page.id!=='string'||!page.id||next.has(page.id)||typeof page.title!=='string'||typeof page.body!=='string'||!Array.isArray(page.objects))throw Error('Image 页面格式不正确。');
  next.set(page.id,page);
  if(!changed.has(page.id)&&JSON.stringify(page)!==JSON.stringify(original.get(page.id)))throw Error('Image 修改了目标范围以外的页面。');
 }
 if(JSON.stringify(before.map(p=>p.id))!==JSON.stringify(edit.pages.map(p=>p.id)))throw Error('Image 不能新增、删除或重排页面。');
 for(const id of changed)if(!original.has(id)||!next.has(id))throw Error('Image 修改目标不存在。');
 for(const page of before)if(!next.has(page.id)&&!changed.has(page.id))throw Error('Image 丢失了未修改的页面。');
 if(input.scope!=='deck'){
  if(JSON.stringify(before.map(p=>p.id))!==JSON.stringify(edit.pages.map(p=>p.id))||[...changed].some(id=>id!==input.pageId))throw Error('Image 修改超出当前页面范围。');
 }
 if(input.scope==='object'){
  const allowed=new Set(input.objectIds||[]),old=original.get(input.pageId),page=next.get(input.pageId);
  if(!allowed.size||!old||!page||[...allowed].some(id=>!old.objects.some(o=>o.id===id)))throw Error('请先选中有效对象。');
  if(JSON.stringify(old.objects.map(o=>o.id))!==JSON.stringify(page.objects.map(o=>o.id)))throw Error('Image 改变了选中范围以外的对象结构。');
  const expected=structuredClone(old);
  expected.objects=expected.objects.map(o=>allowed.has(o.id)?{...structuredClone(page.objects.find(n=>n.id===o.id)),sourceRange:o.sourceRange}:o);
  // Preserve missing properties exactly; binding metadata is derived below.
  for(const o of expected.objects){const prior=old.objects.find(n=>n.id===o.id);for(const k of ['sourceField','layoutField','sourceRange','sourceText','sourceStart','sourceEnd']){if(Object.hasOwn(prior,k))o[k]=structuredClone(prior[k]);else delete o[k];}}
  synchronizeImageCopy(old,expected);
  for(let i=0;i<expected.objects.length;i++)if(JSON.stringify(expected.objects[i])!==JSON.stringify(page.objects[i]))throw Error('Image 修改了未选中的对象或文字来源。');
  const omit=p=>Object.fromEntries(Object.entries(p).filter(([k])=>!['objects','imageDesign','designSnapshot'].includes(k)));
  if(JSON.stringify(omit(expected))!==JSON.stringify(omit(page)))throw Error('Image 修改了选中对象之外的页面属性。');
 }
 return structuredClone(edit);
}


export function explicitImagePages(message){
 const text=String(message||'').trim().replace(/^(?:请)?(?:把|将|修改|调整|重新设计|重新排版|设计|重排|优化)?\s*/,'');
 if(/^(?:第)?\d+\s*[-到至]\s*\d+\s*页/.test(text))throw Error('请逐页列出目标页码，暂不支持页码区间。');
 const match=/^((?:第\s*)?\d+\s*页(?:[、和及，,\s]+(?:第\s*)?\d+\s*页)*)(?=$|的|[，,：:\s]|改|调整|重新|优化)/.exec(text);
 return match?[...new Set([...match[1].matchAll(/(\d+)\s*页/g)].map(m=>Number(m[1])))]:[];
}
export function resolveImageTarget(input){
 if(!input?.project?.pages)return input;
 const numbers=explicitImagePages(input.message);
 if(!numbers.length)return input;
 if(numbers.some(n=>n<1||n>input.project.pages.length))throw Error('指定页码不存在，原稿未修改。');
 if(numbers.length!==1){if(input.scope!=='deck')throw Error('请在整份范围指定多个页面。');return input;}
 const pageId=input.project.pages[numbers[0]-1].id;
 if(input.scope==='object'&&pageId!==input.pageId)throw Error('指定页码与选中对象不一致，请先选择该页对象。');
 return {...input,pageId,...(input.scope==='deck'?{scope:'page'}:{})};
}
