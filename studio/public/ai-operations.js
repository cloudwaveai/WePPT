// Pure shared structural-edit contract. No DOM, server I/O, or model dependencies.
const roles=new Set(['cover','toc','content','data','flow','chapter','ending']);
const clone=value=>structuredClone(value);
const uuid=()=>globalThis.crypto.randomUUID();
const plain=value=>!!value&&typeof value==='object'&&!Array.isArray(value);
const hasOnly=(value,keys)=>Object.keys(value).every(key=>keys.includes(key));

/** Validate against the ORIGINAL page order. Missing operations is legacy/no-op. */
export function validateOperations(result,input){
  const operations=result.operations===undefined?[]:result.operations;
  if(!Array.isArray(operations)||operations.length>100)throw Error('AI 页面操作格式不正确。');
  if(!operations.length)return operations;
  if(input.action!=='revise')throw Error('初次生成不能混用页面修改操作。');
  if(input.scope==='object')throw Error('选中对象范围不能新增、拆分或合并页面。');
  if(!['page','deck',undefined].includes(input.scope))throw Error('AI 页面操作范围不正确。');
  const pages=input.project?.pages;
  if(!Array.isArray(pages))throw Error('页面列表不存在，无法应用修改。');
  const indices=new Map();
  for(const [index,page] of pages.entries()){
    if(typeof page.id!=='string'||!page.id||indices.has(page.id))throw Error('原有页面标识不正确，未应用修改。');
    indices.set(page.id,index);
  }
  const touched=new Set(),anchors=new Set();let size=pages.length;
  for(const op of operations){
    if(!plain(op)||!hasOnly(op,['type','pageIds','afterPageId','pages'])||!['insert','replace'].includes(op.type)||!Array.isArray(op.pageIds)||typeof op.afterPageId!=='string'||!Array.isArray(op.pages)||!op.pages.length||op.pages.length>100)throw Error('AI 页面操作格式不正确，不能删除全部替换页。');
    for(const page of op.pages){
      if(!plain(page)||!hasOnly(page,['title','body','role'])||typeof page.title!=='string'||typeof page.body!=='string'||page.title.length>25000||page.body.length>25000||!roles.has(page.role))throw Error('AI 新页面文案格式不正确。');
    }
    if(op.type==='insert'){
      if(op.pageIds.length)throw Error('插入页面不能同时替换来源页。');
      if(op.afterPageId&&!indices.has(op.afterPageId))throw Error('插入位置不存在，未应用修改。');
      if(input.scope==='page'&&(!input.pageId||op.afterPageId!==input.pageId))throw Error('新增页面超出当前页面范围。');
      if(anchors.has(op.afterPageId)||touched.has(op.afterPageId))throw Error('AI 页面操作位置重叠，请分步执行。');
      anchors.add(op.afterPageId);if(op.afterPageId)touched.add(op.afterPageId);
      size+=op.pages.length;
    }else{
      if(op.afterPageId!=='')throw Error('替换页面不应同时指定插入位置。');
      if(!op.pageIds.length||op.pageIds.some(id=>typeof id!=='string'||!indices.has(id))||new Set(op.pageIds).size!==op.pageIds.length)throw Error('替换的来源页面不存在或重复。');
      const first=indices.get(op.pageIds[0]);
      if(op.pageIds.some((id,index)=>indices.get(id)!==first+index))throw Error('只能按原顺序合并相邻页面。');
      if(input.scope==='page'&&(op.pageIds.length!==1||op.pageIds[0]!==input.pageId))throw Error('替换页面超出当前页面范围；合并请切换整份范围。');
      for(const id of op.pageIds){if(touched.has(id))throw Error('AI 页面操作范围重叠，请分步执行。');touched.add(id);}
      size+=op.pages.length-op.pageIds.length;
    }
  }
  if(size<1||size>100)throw Error('修改后的页数必须为1至100页，请分批处理。');
  if(result.pages?.length)throw Error('页面操作不能同时返回整份新文稿。');
  if(result.changes!==undefined&&!Array.isArray(result.changes))throw Error('AI 修改格式不正确。');
  if((result.changes||[]).some(change=>touched.has(change.pageId)))throw Error('同一页面不能同时执行文案修改和结构操作。');
  return operations;
}

/** Atomic application; caller owns undo, scope validation and laying out affectedIds. */
export function applyOperations(project,operations){
  const checked=validateOperations({operations},{action:'revise',scope:'deck',project});
  if(!checked.length)return {affectedIds:[],removedIds:[]};
  const original=project.pages,usedIds=new Set(original.map(page=>page.id));
  const nextId=()=>{let id;do{id=uuid();}while(usedIds.has(id));usedIds.add(id);return id;};
  const affectedIds=[],removedIds=[],replacementByFirst=new Map(),inserts=new Map(),skipped=new Set();
  function createdPages(op,sources=[]){
    // Retain user-added objects, imported media, and legacy un-managed objects.
    // Layout-derived text is represented by the explicit replacement copy.
    const retained=sources.flatMap(page=>(page.objects||[]).filter(object=>object.custom||!object.layoutManaged).map(clone));
    const objectIds=new Set();
    for(const object of retained){if(!object.id||objectIds.has(object.id))object.id=uuid();objectIds.add(object.id);}
    return op.pages.map((content,index)=>{
      const source=index===0?sources[0]:null;
      const page={...(source?clone(source):{}),...clone(content),id:source?.id||nextId(),variant:source?.variant||0,objects:index===0?retained:[]};
      // Stale layoutSource ranges must not recover old text over replacement copy.
      delete page.layoutSource;delete page.layoutWarnings;delete page.layoutOverflow;for(const key of ['continuationOf','continuationIndex','continuationCount','continuationRange'])delete page[key];
      return page;
    });
  }
  for(const op of checked){
    if(op.type==='insert')inserts.set(op.afterPageId,createdPages(op));
    else{
      const sources=op.pageIds.map(id=>original.find(page=>page.id===id));
      replacementByFirst.set(op.pageIds[0],createdPages(op,sources));
      op.pageIds.slice(1).forEach(id=>{skipped.add(id);removedIds.push(id);});
    }
  }
  const next=[];
  const appendChanged=pages=>{for(const page of pages||[]){next.push(page);affectedIds.push(page.id);}};
  appendChanged(inserts.get(''));
  for(const page of original){
    if(skipped.has(page.id))continue;
    if(replacementByFirst.has(page.id))appendChanged(replacementByFirst.get(page.id));else next.push(page);
    appendChanged(inserts.get(page.id));
  }
  project.pages=next;
  return {affectedIds,removedIds};
}
