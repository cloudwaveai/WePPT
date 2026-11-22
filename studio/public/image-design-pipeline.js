import {snapshotPage} from './design-audit.js';
export async function designImageProject(project,{themeId=project.themeId,targetPageIds,instruction='',request,onBatchReady=()=>{},onProgress=()=>{},signal}={}){
 const result=structuredClone(project),ids=targetPageIds||result.pages.map(p=>p.id);
 if(!ids.length||new Set(ids).size!==ids.length||ids.some(id=>!result.pages.some(p=>p.id===id)))throw Error('Image 目标页面不存在。');
 const sources=structuredClone(result.pages);let completed=0;
 for(const id of ids){
  signal?.throwIfAborted();onProgress({phase:'plan',message:`Image 正在设计第 ${completed+1} / ${ids.length} 页，并还原可编辑文字…`});
  const response=await request('/api/design/image',{project:{...result,themeId},targetPageIds:[id],instruction},signal);signal?.throwIfAborted();
  if(response.pages?.length!==1||response.pages[0].id!==id||response.pages[0].themeId!==themeId||!response.pages[0].imageDesign?.editableText)throw Error('Image 返回范围或可编辑结果无效。');
  const page=response.pages[0];page.designSnapshot=snapshotPage(page);result.pages=result.pages.map(p=>p.id===id?page:p);completed++;
  await onBatchReady({pages:[page],sources,targetPageIds:ids,completed,total:ids.length});
 }
 result.designReview={status:'pending',visionRan:false,repairRounds:0,issues:[],sourceSnapshot:[],summary:`Image 已完成 ${completed} 页设计，文字可编辑；背景与装饰为图片。请查看实际效果。`};return result;
}
