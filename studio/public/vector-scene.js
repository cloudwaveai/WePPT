const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
const num=(v,f=0)=>Number.isFinite(Number(v))?Number(v):f;
const tags=new Set('svg g defs path rect circle ellipse line polyline polygon text tspan image linearGradient radialGradient stop clipPath mask filter feGaussianBlur feOffset feFlood feComposite feMerge feMergeNode feColorMatrix feBlend feDropShadow marker metadata title desc'.toLowerCase().split(' '));
/** Conservative allowlist before any SVG reaches a live document or converter. */
export function validateSvg(svg,{allowUse=false}={}){
 if(typeof svg!=='string'||svg.length>2000000||!/^\s*<svg\b/i.test(svg))throw Error('SVG 必须是有效且小于2MB的独立页面。');
 if(/<!|<\?|\bon\w+\s*=|javascript:|@import|@font-face|expression\s*\(/i.test(svg))throw Error('SVG 包含禁止的脚本、实体或外部样式。');
 for(const m of svg.matchAll(/<\/?([\w:-]+)/g)){const tag=m[1].toLowerCase();if(!tags.has(tag)&&!(allowUse&&tag==='use'))throw Error('SVG 暂不支持元素：'+m[1]);}
 for(const m of svg.matchAll(/\b(?:[\w-]+:)?href\s*=\s*(["'])(.*?)\1/gi))if(!/^#[\w:.-]+$/.test(m[2])&&!/^data:image\/(?:png|jpeg|webp);base64,[a-z\d+/=]+$/i.test(m[2]))throw Error('SVG 图片必须内嵌，不能访问网络或本机文件。');
 for(const m of svg.matchAll(/url\s*\(([^)]*)\)/gi))if(!/^\s*['"]?#[\w:.-]+['"]?\s*$/.test(m[1]))throw Error('SVG 不允许外部资源引用。');
 return true;
}
export function validateVectorObject(o){if(o?.type!=='vector')throw Error('无效矢量对象');validateSvg(o.svg);if(o.nativeData&&(!['chart','table'].includes(o.nativeType)||typeof o.nativeData!=='object'))throw Error('无效原生图表数据');return true;}
export function vectorDataUrl(o){validateVectorObject(o);return 'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(o.svg);}
function inner(svg){return svg.replace(/^\s*<svg\b[^>]*>/i,'').replace(/<\/svg>\s*$/i,'');}
export function pageToSvg(page){
 const objects=(page.objects||[]).map((o,index)=>{
  const x=num(o.x),y=num(o.y),w=Math.max(.01,num(o.w)),h=Math.max(.01,num(o.h));const id='object-'+index;
  const rotation=num(o.rotation),opacity=Math.min(1,Math.max(0,num(o.opacity,1)));
  const shadow=o.shadow?`<defs><filter id="${id}-shadow" x="-100%" y="-100%" width="300%" height="300%"><feDropShadow dx="${num(o.shadow.offsetX)}" dy="${num(o.shadow.offsetY)}" stdDeviation="${Math.max(0,num(o.shadow.blur))/2}" flood-color="${esc(o.shadow.color||'#000000')}" flood-opacity="${Math.min(1,Math.max(0,num(o.shadow.opacity,.15)))}"/></filter></defs>`:'';
  const wrap=body=>`${shadow}<g id="${id}" data-pptx-bounds="${x} ${y} ${w} ${h}" opacity="${opacity}"${rotation?` transform="rotate(${rotation} ${x+w/2} ${y+h/2})"`:''}>${shadow?body.replace(/^<(rect|circle|ellipse|image|path|polygon|text)\b/,`<$1 filter="url(#${id}-shadow)"`):body}</g>`;
  if(o.type==='vector'){if(o.shadow)throw Error('矢量组合新增阴影暂未接入原生导出；请使用SVG内原有阴影。');
   validateVectorObject(o);const vb=/viewBox\s*=\s*["']([^"']+)["']/i.exec(o.svg)?.[1]?.split(/[ ,]+/).map(Number);if(!vb||vb.length!==4||vb.some(n=>!Number.isFinite(n))||vb[2]<=0||vb[3]<=0)throw Error('矢量对象缺少有效viewBox。');
   let body=inner(o.svg);
   // Imported preset geometry is now a standalone editable shape. Its former
   // render-only marker would make the upstream converter skip it on export.
   // Native chart/table groups still own their original replacement metadata.
   if(!o.nativeType)body=body.replace(/\sdata-pptx-part\s*=\s*(["'])geometry-detail\1/gi,'');
   const prefix=id+'-';body=body.replace(/\sid=(["'])(.*?)\1/g,(_,quote,v)=>` id=${quote}${prefix}${v}${quote}`).replace(/url\(#([^)]*)\)/g,(_,v)=>`url(#${prefix}${v})`).replace(/(href=")#([^"]+)/g,(_,a,v)=>`${a}#${prefix}${v}`);
   return wrap(`<g transform="translate(${x} ${y}) scale(${w/vb[2]} ${h/vb[3]}) translate(${-vb[0]} ${-vb[1]})">${body}</g>`);
  }
  if(o.type==='text'){
   const fs=num(o.fontSize,24),lh=num(o.lineHeight,1.3),lines=Array.isArray(o.exportLines)?o.exportLines:String(o.text??'').split('\n');const anchor=o.align==='center'?'middle':o.align==='right'?'end':'start',tx=x+(anchor==='middle'?w/2:anchor==='end'?w:0);
   return `${shadow}<text${shadow?` filter="url(#${id}-shadow)"`:''} id="${id}" opacity="${opacity}"${rotation?` transform="rotate(${rotation} ${x+w/2} ${y+h/2})"`:""} x="${tx}" y="${y+num(o.svgBaseline,fs*.85)}" font-family="${esc(o.fontFamily||'Microsoft YaHei')}" font-size="${fs}" font-weight="${o.bold?'bold':'normal'}" font-style="${o.italic?'italic':'normal'}" fill="${esc(o.color||'#222222')}" text-anchor="${anchor}">${lines.map((line,i)=>`<tspan x="${tx}"${i?` dy="${fs*lh}"`:''}>${esc(line)}</tspan>`).join('')}</text>`;
  }
  if(o.type==='image'){if(!/^data:image\/(png|jpeg|webp);base64,/i.test(o.src||''))throw Error('导出前图片必须转换为内嵌素材。');if(o.crop){const cw=Math.min(1,Math.max(.01,num(o.crop.w,1))),ch=Math.min(1,Math.max(.01,num(o.crop.h,1))),cx=Math.min(1-cw,Math.max(0,num(o.crop.x))),cy=Math.min(1-ch,Math.max(0,num(o.crop.y)));return `<defs><clipPath id="${id}-crop"><polygon points="${x},${y} ${x+w},${y} ${x+w},${y+h} ${x},${y+h}"/></clipPath></defs>`+wrap(`<image clip-path="url(#${id}-crop)" x="${+(x-cx/cw*w).toFixed(6)}" y="${+(y-cy/ch*h).toFixed(6)}" width="${w/cw}" height="${h/ch}" href="${esc(o.src)}" preserveAspectRatio="none"/>`);}return wrap(`<image x="${x}" y="${y}" width="${w}" height="${h}" href="${esc(o.src)}" preserveAspectRatio="${o.fit==='stretch'?'none':`xMidYMid ${o.fit==='cover'?'slice':'meet'}`}"/>`);}
  const paint=`fill="${esc(o.fill==='transparent'?'none':o.fill||'none')}" stroke="${esc(o.stroke||'none')}" stroke-width="${num(o.strokeWidth)}"`;
  if(o.type==='ellipse')return wrap(`<ellipse cx="${x+w/2}" cy="${y+h/2}" rx="${w/2}" ry="${h/2}" ${paint}/>`);
  if(o.type==='line')return wrap(`<line x1="${x}" y1="${y}" x2="${x+w}" y2="${y+h}" ${paint}/>`);
  if(o.type==='rect')return wrap(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${num(o.radius)}" ${paint}/>`);
  throw Error('不支持导出的对象类型：'+o.type);
 }).join('\n');
 return `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1280" height="720" viewBox="0 0 1280 720" lang="zh-CN" font-family="Microsoft YaHei" data-pptx-page-role="${esc(page.role||'content')}"><rect id="page-background" data-pptx-role="background" width="1280" height="720" fill="${esc(page.background||'#FFFFFF')}"/><g id="page-content" data-pptx-bounds="0 0 1280 720">${objects}</g></svg>`;
}
