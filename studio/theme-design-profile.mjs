import {stat} from 'node:fs/promises';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {randomUUID} from 'node:crypto';
const root=fileURLToPath(new URL('./',import.meta.url));
export const PILOT_THEME_IDS=['curated-139','curated-005','curated-091','curated-410','curated-246'];
const photographic=new Set(['005','147','157','001','068','139','155','235','008','013','014','018','022','055','064','067','077','143','159','189','191','197','202','209','223','230','342','410','514'].map(n=>'curated-'+n));
const special={
 'curated-139':'蓝底、单一黑白主窗口、灰色边框、黑白照片和线稿构成识别。不要多层窗口挤压标题；照片裁片保留可辨认主体，不被窗口遮成碎条。',
 'curated-005':'植物是主视觉而非几个绿色矩形。保留自然植物轮廓或无字植物摄影裁片；暗色封面与浅色正文形成节奏，不能把全套做成暗色卡片。',
 'curated-091':'以实体几何与细线框的对照建立空间，克制黑白灰；不用照片和统一圆角卡片替代这种关系。',
 'curated-410':'建筑摄影和橙色锚点保持清楚边界；真实建筑裁片与白底文字共存，不能只保留橙色。',
 'curated-246':'蓝底和彩色折面的侧面、厚度、亮暗关系构成识别；用闭合路径画有方向的折面，不能退化成几个平面色块。'
};
export function buildThemeDesignProfile(theme){
 if(!theme?.id||!theme.description||!theme.adaptation)throw Error('模板缺少设计说明。');
 const references=[...new Set([theme.cover,...(theme.previews||[])].filter(Boolean))];
 if(!references.length||references.some(src=>!new RegExp('^/assets/templates/'+theme.id+'/[0-9]+\\.(jpg|png|webp)$').test(src)))throw Error('模板参考素材范围无效。');
 return {version:1,themeId:theme.id,name:theme.name,identity:theme.description,adaptation:theme.adaptation,caution:theme.caution||'',palette:theme.palette,fontFamily:theme.fontFamily||'Microsoft YaHei',references,assetMode:photographic.has(theme.id)?'photo-or-illustration':'editable-material-or-geometry',specificRule:special[theme.id]||`保留「${theme.name}」的主体、材质和空间关系：${theme.description} ${theme.adaptation}`,rules:[
 '模板是视觉约束，不是换色建议。封面应能辨认出原模板；不擅自改成通用商务两栏。',
 '标题必须逐字完整显示。正文、标点、数字按源顺序保留；不得只展示标题前半句。',
 '结构由内容关系决定：目录建立导航，流程显示顺序，比较明确维度，评分保留计算依据；不能全稿标题加大文本框。',
 '优先使用可编辑矢量重建图形。摄影、植物、人物和材质可使用所选模板中不含文字的参考裁片；禁止用空矩形冒充照片。',
 '图片是装饰参考，不作为用户公司、人物、产品或事件的事实证据。不得复用参考中的品牌、署名或文字。',
 '裁片不能含参考页文字；主体不能被裁碎或被面板遮成细条。无法取得干净裁片时使用可辨认的矢量插图，不编造图片占位。',
 '允许调整字号、栏宽和留白以容纳内容，但不改变模板视觉身份。最多两轮修正，问题仍存在时明确报告。'
 ]};
}
export async function auditThemeCatalog(themes,{publicDir=resolve(root,'public')}={}){
 const results=[];
 for(const theme of themes){const profile=buildThemeDesignProfile(theme),missing=[];for(const src of profile.references){try{const s=await stat(resolve(publicDir,src.slice(1)));if(!s.isFile()||s.size===0)missing.push(src);}catch{missing.push(src);}}
 results.push({themeId:theme.id,name:theme.name,referenceCount:profile.references.length,missing,ready:missing.length===0,visualStatus:'not-run',pilot:PILOT_THEME_IDS.includes(theme.id)});}
 return {total:results.length,ready:results.filter(x=>x.ready).length,themes:results};
}
export const assetPlacementSchema={type:'array',maxItems:4,items:{type:'object',additionalProperties:false,required:['src','x','y','w','h','crop','reason'],properties:{src:{type:'string'},x:{type:'number'},y:{type:'number'},w:{type:'number'},h:{type:'number'},reason:{type:'string'},crop:{type:'object',additionalProperties:false,required:['x','y','w','h'],properties:{x:{type:'number'},y:{type:'number'},w:{type:'number'},h:{type:'number'}}}}}};
export function createThemeAssetObjects(placements,profile){
 if(!Array.isArray(placements)||placements.length>4)throw Error('模板图片数量无效。');
 return placements.map(a=>{
  const c=a.crop;if(!profile.references.includes(a.src)||![a.x,a.y,a.w,a.h,c?.x,c?.y,c?.w,c?.h].every(Number.isFinite))throw Error('模板图片来源或尺寸无效。');
  if(a.x<0||a.y<0||a.w<24||a.h<24||a.x+a.w>1280||a.y+a.h>720||a.w*a.h>1280*720*.6)throw Error('模板图片不得替代整页或超出页面。');
  if(c.x<0||c.y<0||c.w<=0||c.h<=0||c.x+c.w>1.00001||c.y+c.h>1.00001||c.w*c.h>.6)throw Error('请使用无文字的局部素材，不能复用整张参考页。');
  return {id:randomUUID(),type:'image',x:a.x,y:a.y,w:a.w,h:a.h,src:a.src,crop:{...c},fit:'cover',rotation:0,opacity:1,layoutManaged:true,custom:false,referencePhoto:true,name:'模板素材',assetReason:String(a.reason||'').slice(0,500)};
 });
}
export function placeThemeAssets(page,objects){
 // Images sit above generated background shapes and below editable text. Reserve their
 // footprints during planning, so a decorative panel cannot silently hide them.
 const firstText=page.objects.findIndex(o=>o.type==='text');
 page.objects.splice(firstText<0?page.objects.length:firstText,0,...objects);return page;
}
