import {adviceOnly,validateDesignAction} from './public/assistant-actions.js';
export function explicitDesignAction(input){
 if(input.action!=='revise'||input.project?.stage!=='editor'||input.scope==='object'||adviceOnly(input.message))return null;
 const text=input.message.trim().replace(/[。！!]+$/,'');
 const image=/^(?:请)?(?:帮我)?(?:用|使用)\s*(?:image(?:\s*[+＋]\s*sol)?|生图)(?:\s*模型)?[，,：:\s]*(?:帮我)?(?:重新设计|重新排版|设计|重排|美化)/i.test(text)&&!/[？?]|可以吗|能否|先讨论/.test(text);
 if(image){
  if(/第|前\s*[\d一二三四五六七八九十]+\s*页|后\s*[\d一二三四五六七八九十]+\s*页|[\d一二三四五六七八九十]+\s*[-至到、和]\s*[\d一二三四五六七八九十]+\s*页/.test(text))return null;
  const currentOnly=input.scope==='page'||/当前页|这一页|这页|本页/.test(text);
  if(/整份|整稿/.test(text)&&input.scope==='page')return {message:'请切换到「整份」后再进行整稿 Image 设计。',pages:[],changes:[],operations:[]};
  const pageIds=currentOnly?[input.pageId]:input.project.pages.map(p=>p.id);
  const result={message:'开始使用 Image 设计页面，并还原可编辑文字；原页会在结果通过检查后替换。',pages:[],changes:[],operations:[],designAction:{type:'image-redesign',pageIds,instruction:input.message}};
  validateDesignAction(result,input);return result;
 }
 const redesign=/^(?:请)?(?:帮我)?(?:把)?(?:整份(?:PPT)?|整稿|当前页|这一页|这页|本页)?(?:重新设计|重新排版|重排)(?:整份(?:PPT)?|整稿|当前页|这一页|这页|本页)?(?:[，,](?:文案不变|保留原文|文字不变))?$/i.test(text);
 const review=/^(?:请)?(?:帮我)?(?:检查(?:一下)?|审看(?:一下)?)(?:整份(?:PPT)?|整稿|当前页|这一页|这页|本页)$|^整稿检查$/i.test(text);
 if(!redesign&&!review)return null;
 if(/整份|整稿/.test(text)&&input.scope==='page')return {message:'这次要求涉及整份 PPT，请将助手范围切换到「整份」后发送。',pages:[],changes:[],operations:[]};
 if(redesign&&input.project.themeId!=='curated-139'&&!['svg','slidev','pptagent'].includes(input.project.designEngine))return {message:'这套模板暂未接入逐页重新设计。我可以先给出设计建议，或按你的要求调整已有文字和对象。',pages:[],changes:[],operations:[]};
 const currentOnly=input.scope==='page'||/当前页|这一页|这页|本页/.test(text);
 if(currentOnly&&!input.project.pages.some(p=>p.id===input.pageId))return null;
 const pageIds=currentOnly?[input.pageId]:input.project.pages.map(p=>p.id);
 const result={message:review?'开始检查指定页面，检查不会修改文稿。':'开始按当前文案与模板设计指定页面，已完成页面会分批返回。',pages:[],changes:[],operations:[],designAction:{type:redesign?'redesign':'review',pageIds,instruction:input.message}};
 validateDesignAction(result,input);return result;
}
