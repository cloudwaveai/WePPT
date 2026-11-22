// This function is intentionally self-contained: the export worker serializes it
// into the browser with tab.evaluate, and CDP can exercise the same DOM path.
export async function measureNativeTextLines(object){
 const source=String(object.text??''),paragraphs=source.split('\n'),result=[];
 const fontSize=Number(object.fontSize)||24,lineHeight=Number(object.lineHeight)||1.42,lineThreshold=Math.max(1,fontSize*lineHeight*.5);
 const requestedFamily=String(object.fontFamily||'Microsoft YaHei');
 // An unavailable face alone falls back to the browser's initial serif font.
 // Keep Latin dates/numbers in the requested family class on Linux as well.
 // Explicit generic choices remain authoritative; installed faces still win.
 const hasGeneric=/(?:^|,)\s*(?:sans-serif|serif|monospace|system-ui|cursive|fantasy)\s*(?:,|$)/i.test(requestedFamily);
 const primaryFamily=requestedFamily.split(',')[0].replace(/["']/g,'').trim();
 const generic=/Consolas|Courier|Monaco|Menlo|Noto Sans Mono|Liberation Mono/i.test(primaryFamily)?'monospace':/Georgia|Times|Cambria|Constantia|Garamond|Baskerville|Palatino|SimSun|Songti|宋体|Noto Serif|Liberation Serif/i.test(primaryFamily)?'serif':'sans-serif';
 const measurementFamily=hasGeneric?requestedFamily:requestedFamily+', '+generic;
 const element=document.createElement('div');
 element.lang='zh-CN';
 Object.assign(element.style,{
  all:'initial',position:'absolute',left:'-100000px',top:'0',display:'block',visibility:'hidden',
  boxSizing:'border-box',width:Math.max(.01,Number(object.w)||.01)+'px',height:'auto',
  minWidth:'0',maxWidth:'none',padding:'0',margin:'0',border:'0',
  fontFamily:measurementFamily,fontSize:fontSize+'px',
  fontWeight:object.bold?'700':'400',fontStyle:object.italic?'italic':'normal',
  lineHeight:String(lineHeight),letterSpacing:'normal',
  whiteSpace:'pre-wrap',lineBreak:'strict',overflowWrap:'anywhere',wordBreak:'normal',
  textAlign:['left','center','right'].includes(object.align)?object.align:'left',
  direction:'ltr',writingMode:'horizontal-tb',textIndent:'0'
 });
 // Keep a four-character Chinese heading balanced when fallback metrics allow
 // three glyphs but not four. Wide single-line and authored narrow titles stay
 // at their original size and position; only the native line break changes.
 if(object.blueprintSlot==='title'&&/^\p{Script=Han}{4}$/u.test(source))element.style.textWrap='balance';
 (document.body||document.documentElement).append(element);
 try{
  // Appending text before awaiting fonts ensures any declared face is requested.
  element.textContent=source;
  if(document.fonts)await document.fonts.ready;
  for(const paragraph of paragraphs){
   if(!paragraph){result.push('');continue;}
   element.replaceChildren();
   // Keep dates and grouped numeric values together when the complete token
   // fits this frame. Preserve the original characters: no nonbreaking-hyphen
   // substitution or invisible characters may enter the exported source text.
   let tokenOffset=0;
   const frameWidth=element.getBoundingClientRect().width;
   for(const match of paragraph.matchAll(/\b\d{4}-\d{2}-\d{2}\b|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b/g)){
    if(match.index>tokenOffset)element.append(document.createTextNode(paragraph.slice(tokenOffset,match.index)));
    const token=document.createElement('span');token.style.whiteSpace='nowrap';token.textContent=match[0];element.append(token);
    if(token.getBoundingClientRect().width>frameWidth+.01)token.replaceWith(document.createTextNode(match[0]));
    tokenOffset=match.index+match[0].length;
   }
   if(tokenOffset<paragraph.length)element.append(document.createTextNode(paragraph.slice(tokenOffset)));
   const range=document.createRange();let offset=0,start=0,lineTop=null;
   try{
    const walker=document.createTreeWalker(element,NodeFilter.SHOW_TEXT);
    for(let textNode=walker.nextNode();textNode;textNode=walker.nextNode()){
     let localOffset=0;
     for(const character of textNode.data){
      const localEnd=localOffset+character.length;
      range.setStart(textNode,localOffset);range.setEnd(textNode,localEnd);
      const rectangles=range.getClientRects(),rect=rectangles.length?rectangles[0]:range.getBoundingClientRect();
      // Fallback glyphs (notably emoji) can have different ink tops on the same
      // line. A true wrap advances by approximately the declared line height.
      if(lineTop!==null&&Math.abs(rect.top-lineTop)>lineThreshold){result.push(paragraph.slice(start,offset));start=offset;lineTop=rect.top;}
      if(lineTop===null)lineTop=rect.top;
      offset+=character.length;localOffset=localEnd;
     }
    }
    result.push(paragraph.slice(start));
   }finally{range.detach();}
  }
  // Explicit newlines are represented by line boundaries (including empty
  // lines). Soft wrapping must never lose, normalize or duplicate source text.
  if(result.join('')!==paragraphs.join(''))throw Error('原生文字断行未完整保留原文。');
  return result;
 }finally{element.remove();}
}
