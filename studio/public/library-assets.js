import {validateSvg} from './vector-scene.js';
export function queryLibrary(items,query='',library='',limit=80){
 const tokens=String(query).toLowerCase().trim().split(/\s+/).filter(Boolean);
 return items.filter(a=>(!library||a.library===library)&&tokens.every(t=>[a.id,a.name,a.style,...a.tags].join(' ').toLowerCase().includes(t))).slice(0,limit);
}
export function recolorLibrarySvg(svg,color){
 validateSvg(svg);if(!/^#[a-f\d]{6}$/i.test(color))throw Error('素材颜色格式无效。');
 // Mask luminance and clip geometry are not visible paint.
 return svg.split(/(<(?:mask|clipPath)\b[\s\S]*?<\/(?:mask|clipPath)>)/gi).map(part=>/^<(?:mask|clipPath)\b/i.test(part)?part:part.replace(/currentColor/gi,color).replace(/\b(fill|stroke|stop-color)\s*=\s*(["'])([^"']*)\2/gi,(all,key,quote,value)=>/^(none|transparent|url\()/i.test(value)?all:`${key}=${quote}${color}${quote}`)).join('');
}
export function libraryExportMode(o){return o?.type==='vector'&&o.libraryAssetId&&/<(?:mask|filter|clipPath)\b/i.test(o.svg||'')?'svg-picture':'native';}
export function createLibraryObject(item,svg,{x=440,y=220,w=280,h,color,custom=true}={}){
 if(!item?.id||!['coolshapes','geopattern','blobshape','tabler','geometry'].includes(item.library))throw Error('素材库条目无效。');
 validateSvg(svg);
 if(color)svg=recolorLibrarySvg(svg,color);else svg=svg.replace(/currentColor/gi,'#252824');
 // Export unwraps the outer SVG; preserve inherited paint for outline icons.
 const root=/^\s*<svg\b([^>]*)>/i.exec(svg);
 const inherited=[...root[1].matchAll(/\b(fill|stroke|stroke-width|stroke-linecap|stroke-linejoin|fill-rule|clip-rule|opacity|color)\s*=\s*(["'])(.*?)\2/gi)].map(m=>`${m[1]}="${m[3].replace(/"/g,'&quot;')}"`).join(' ');
 if(inherited)svg=svg.replace(root[0],root[0]+`<g ${inherited}>`).replace(/<\/svg>\s*$/i,'</g></svg>');
 const aspect=Number(item.height)/Number(item.width);h??=w*(Number.isFinite(aspect)&&aspect>0?aspect:1);
 if(![x,y,w,h].every(Number.isFinite)||w<=0||h<=0||x<0||y<0||x+w>1280||y+h>720)throw Error('素材必须放在页面内。');
 return {id:crypto.randomUUID(),type:'vector',x,y,w,h,svg,rotation:0,opacity:1,custom,layoutManaged:!custom,name:item.name,libraryAssetId:item.id,library:item.library};
}
