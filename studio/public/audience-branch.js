import {audienceSource,validateAudiencePlan} from './audience-plan.js';
import {audienceLayoutFingerprint} from './audience-layout.js';

export function audienceSelection(project,plan,selections=[],{order}={}){
 const source=audienceSource(project),entries=[],checked=validateAudiencePlan({message:plan.message,narrative:plan.narrative??'',entries:plan.entries},source);
 const indices=order===undefined?checked.entries.map((_,index)=>index):order;
 if(!Array.isArray(indices)||indices.length!==checked.entries.length||new Set(indices).size!==indices.length||Array.from(indices).some(index=>!Number.isSafeInteger(index)||index<0||index>=checked.entries.length))throw Error('页面顺序无效，请重新调整方案。');
 const defaultPositions=new Map();let defaultIndex=0,targetIndex=0;
 for(const [index,entry] of checked.entries.entries()){
  if(entry.action==='add'&&selections[index]?.remove===true)throw Error('新增页请取消采用，不能标为删除原页。');
  if(selections[index]?.remove===true)continue;
  if(entry.action==='add'&&selections[index]?.accept===false||entry.action==='delete'&&selections[index]?.accept!==false)continue;
  defaultPositions.set(index,++defaultIndex);
 }
 for(const index of indices){
  const entry=checked.entries[index];
  const selection=selections[index]||{},before=source.pages.find(page=>page.id===entry.sourcePageId);
  if(entry.action==='add'&&selection.accept===false)continue;
  const next=selection.remove===true?{...entry,action:'delete',title:before.title,body:before.body,role:before.role,reason:'用户选择从新版本删除此原页，原稿保持不变。',questions:[]}:selection.accept===false?{...entry,action:'keep',title:before.title,body:before.body,role:before.role,reason:'未采纳此项建议，保留原页文案；顺序以当前目录为准。',questions:[]}:{...entry,title:selection.title??entry.title,body:selection.body??entry.body};
  if(next.action!=='delete'&&next.action!=='add')next.action=next.title===before.title&&next.body===before.body&&next.role===before.role?'keep':'edit';
  if(next.action!=='delete'){
   targetIndex++;
   const note='页面顺序按用户确认的目录调整。';
   if(defaultPositions.get(index)!==targetIndex&&!next.reason.includes(note))next.reason=(note+next.reason).slice(0,4000);
  }
  entries.push(next);
 }
 return validateAudiencePlan({message:plan.message,narrative:checked.narrative,entries},source);
}

export function createAudienceBranch(source,plan,{audience,notes='',id,reviewId,layout,now=new Date().toISOString()}={}){
 if(!id||!reviewId||id===source.id)throw Error('新版本标识无效。');
 const canonical=audienceSource(source),checked=validateAudiencePlan({message:plan.message,narrative:plan.narrative??'',entries:plan.entries},canonical);
 if(!checked.summary.changed)throw Error('当前没有实际增删改或调序，请先调整方案。');
 const fingerprints=audienceLayoutFingerprint(source,checked),retained=checked.entries.filter(e=>e.action!=='delete');
 if(!layout||Object.entries(fingerprints).some(([key,value])=>layout[key]!==value))throw Error('原稿或方案已变化，请重新预览原稿版式。');
 if(!Array.isArray(layout.issues)||layout.issues.length)throw Error('版式仍有未解决的问题，请先检查预览。');
 if(!Array.isArray(layout.pages)||!Array.isArray(layout.records)||layout.pages.length!==retained.length||layout.records.length!==retained.length)throw Error('版式页面不完整，请重新预览。');
 if(new Set(layout.pages.map(p=>p.id)).size!==layout.pages.length)throw Error('版式页面标识重复，请重新预览。');
 const pages=[],entries=[];
 for(const [index,entry] of checked.entries.entries()){
  const original=source.pages.find(page=>page.id===entry.sourcePageId),before=canonical.pages.find(page=>page.id===entry.sourcePageId),at=pages.length,page=entry.action==='delete'?null:layout.pages[at],record=entry.action==='delete'?null:layout.records[at];
  if(page){
   const expectedMode=entry.action==='keep'?'preserved':entry.action==='add'?'added':'rewritten';
   if(!page.id||record.entryIndex!==index||record.pageId!==page.id||record.sourcePageId!==(original?.id||null)||record.mode!==expectedMode||!source.pages.some(p=>p.id===record.referencePageId))throw Error('版式来源与方案不符，请重新预览。');
   if(entry.action==='keep'?JSON.stringify(page)!==JSON.stringify(original):page.title!==entry.title||page.body!==entry.body||page.role!==entry.role||!page.objects?.length)throw Error('预览内容与确认方案不符，请重新预览。');
   pages.push(structuredClone(page));
  }
  entries.push({...structuredClone(entry),...checked.positions[index],targetPageId:page?.id||null,...(record?{designMode:record.mode,referencePageId:record.referencePageId,referenceIndex:source.pages.findIndex(p=>p.id===record.referencePageId)+1,...(record.note?{designNote:record.note}:{})}:{}),before:before?{title:before.title,body:before.body}:null,after:entry.action==='delete'?null:{title:entry.title,body:entry.body}});
 }
 const suffix=`（${audience}版）`,title=source.title.endsWith(suffix)?source.title:source.title.slice(0,500-suffix.length)+suffix;
 return {id,title,revision:0,stage:'editor',themeId:source.themeId||'',designEngine:source.designEngine||'svg',pages,assets:structuredClone(source.assets||[]),materials:structuredClone(source.materials||[]),parentProjectId:source.id,audienceLabel:audience,audienceVersion:true,
  audienceReview:{schemaVersion:3,reviewId,sourceProjectId:source.id,sourceRevision:source.revision,sourceTitle:source.title,audience,notes,narrative:checked.narrative,confirmedAt:now,layoutConfirmedAt:now,summary:checked.summary,entries,sourcePages:structuredClone(source.pages)},
  messages:[{role:'user',scope:'deck',text:`创建面向「${audience}」的版本。${notes}`},{role:'assistant',scope:'deck',text:`已确认改编内容与原稿版式：保留 ${checked.summary.keep} 页，改写 ${checked.summary.edit} 页，删除 ${checked.summary.delete} 页，新增 ${checked.summary.add} 页，调序 ${checked.summary.moved} 页。可直接编辑；从「改动清单」查看逐页内容与设计来源。`}]
 };
}

export function sameAudienceBranch(a,b){
 const content=value=>{const next=structuredClone(value);delete next.revision;delete next.updatedAt;return next;};
 return !!a&&!!b&&JSON.stringify(content(a))===JSON.stringify(content(b));
}
