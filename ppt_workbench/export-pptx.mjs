// Editable PPTX export. No shell commands or remote asset loading.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

let PptxGenJS, JSZip;
try {
  const load = name => {
    try { return createRequire(import.meta.url)(name); }
    catch { return createRequire(path.join(process.cwd(), 'package.json'))(name); }
  };
  PptxGenJS = load('pptxgenjs');
  JSZip = load('jszip');  // Installed as a pptxgenjs dependency.
} catch {
  process.stderr.write(JSON.stringify({code:'PPTX_DEPENDENCY_MISSING',message:'未安装 pptxgenjs。请在软件项目目录执行 npm install，然后重试。'})+'\n');
  process.exit(2);
}

// pptxgenjs 4.0.1 writes <a:pPr> before every run of a multi-run paragraph, which
// is invalid DrawingML (Office may repair it, LibreOffice drops the text). Keep
// only each paragraph's first properties element; runs and text are untouched.
const paragraphProperties = /<a:pPr\b[^>]*\/>|<a:pPr\b[^>]*>[\s\S]*?<\/a:pPr>/g;
const singleParagraphProperties = xml => xml.replace(/<a:p>[\s\S]*?<\/a:p>/g, paragraph => {
  let seen = false;
  return paragraph.replace(paragraphProperties, match => (seen ? '' : (seen = true, match)));
});

// Read dimensions only. Preserve the original encoding and all media bytes.
function imageDimensions(src) {
  const b=Buffer.from(src.slice(src.indexOf(',')+1),'base64');
  if(b.length>=24 && b.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])))
    return [b.readUInt32BE(16),b.readUInt32BE(20)];
  if(b[0]===255 && b[1]===216){
    let i=2;
    while(i+4<=b.length){
      if(b[i++]!==255)continue;
      while(b[i]===255)i++;
      const marker=b[i++];
      if(marker===217||marker===218)break;
      if(marker===216||marker===1||(marker>=208&&marker<=215))continue;
      if(i+2>b.length)break;
      const n=b.readUInt16BE(i);
      if(n<2||i+n>b.length)break;
      if([192,193,194,195,197,198,199,201,202,203,205,206,207].includes(marker) && n>=7)
        return [b.readUInt16BE(i+5),b.readUInt16BE(i+3)];
      i+=n;
    }
  }
  throw new Error('图片原始尺寸无法读取，未导出拉伸的替代图片。');
}

try {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const output = process.argv[2];
  if (!output || !Array.isArray(input.scenes) || !input.scenes.length) throw new Error('Invalid export input');
  const pptx = new PptxGenJS();
  pptx.layout = 'LAYOUT_WIDE';
  pptx.author = 'PPT Workbench';
  pptx.subject = 'Editable page-by-page presentation';
  pptx.title = input.title || input.scenes[0].title || 'Presentation';
  pptx.company = '';
  pptx.lang = 'zh-CN';
  pptx.theme = {headFontFace:'Microsoft YaHei',bodyFontFace:'Microsoft YaHei',lang:'zh-CN'};
  const rgb = value => value.replace('#','');
  // Same leftmost-longest scan as rendering.emphasis_segments.
  const segments = (text, phrases) => {
    const ordered = [...new Set(phrases || [])].sort((a, b) => b.length - a.length);
    const parts = []; let plain = '', index = 0;
    while (index < text.length) {
      const match = ordered.find(p => text.startsWith(p, index));
      if (match) { if (plain) { parts.push([plain, false]); plain = ''; } parts.push([match, true]); index += match.length; }
      else { plain += text[index]; index += 1; }
    }
    if (plain) parts.push([plain, false]);
    return parts;
  };
  // Explicit paragraph breaks: pptxgenjs would otherwise break after every piece of a split run.
  const runs = obj => {
    const lines = obj.text.split('\n'), result = [];
    lines.forEach((line, number) => {
      const pieces = segments(line, obj.emphasis).map(([text, emphasized]) =>
        ({text, options: emphasized ? {bold: true, color: rgb(obj.emphasisColor || obj.color)} : {}}));
      if (!pieces.length) pieces.push({text: '', options: {}});
      if (number < lines.length - 1) pieces[pieces.length - 1].options.breakLine = true;
      result.push(...pieces);
    });
    return result;
  };
  const shadows = {soft: {type: 'outer', blur: 18, offset: 6, angle: 90, color: '0F172A', opacity: .14},
                   lift: {type: 'outer', blur: 30, offset: 12, angle: 90, color: '0F172A', opacity: .26}};
  const shapeExtras = obj => ({
    ...(obj.rotation ? {rotate: ((obj.rotation % 360) + 360) % 360} : {}),
    ...(shadows[obj.shadow] ? {shadow: {...shadows[obj.shadow]}} : {}),
  });
  for (const scene of input.scenes) {
    const slide = pptx.addSlide();
    slide.background = {color:rgb(scene.background)};
    const scale = 13.3333333333 / scene.width;
    const points = scale * 72;
    for (const obj of scene.objects) {
      const box = {x:obj.x*scale,y:obj.y*scale,w:obj.w*scale,h:obj.h*scale,objectName:obj.id};
      const transparency = Math.round((1-obj.opacity)*100);
      if (obj.type === 'text') {
        // A box shorter than two lines that passed browser overflow checks is a
        // measured single line. Office fonts may be wider, so never let them wrap
        // it into a second line over neighbouring content.
        const singleLine = !obj.text.includes('\n') && obj.h < obj.fontSize * obj.lineHeight * 1.9;
        slide.addText(obj.emphasis ? runs(obj) : obj.text, {...box,fontFace:obj.fontFamily,fontSize:obj.fontSize*points,
          color:rgb(obj.color),bold:obj.bold,italic:obj.italic,align:obj.align,
          valign:obj.valign==='middle'?'mid':obj.valign,margin:0,breakLine:false,
          // CSS line-height is a multiple of the font size; OOXML spcPct is a multiple of the
          // font's own line height (~1.24em for CJK fonts). Exact points keep the browser pitch.
          lineSpacing:Math.round(obj.fontSize*obj.lineHeight*points*100)/100,paraSpaceAfter:0,paraSpaceBefore:0,
          ...(obj.letterSpacing ? {charSpacing: obj.letterSpacing * points} : {}),
          isTextBox:true,fit:'none',wrap:!singleLine,transparency,lang:'zh-CN'});
      } else if (obj.type === 'rect' || obj.type === 'ellipse') {
        const options = {...box,...shapeExtras(obj),
          ...(obj.type === 'rect' ? {rectRadius:obj.radius*scale} : {}),
          fill:obj.fill==='none'?{color:'FFFFFF',transparency:100}:{color:rgb(obj.fill),transparency},
          line:obj.stroke==='none'?{color:'FFFFFF',transparency:100}:{color:rgb(obj.stroke),width:obj.strokeWidth*points,transparency}};
        const shape = obj.type === 'ellipse' ? pptx.ShapeType.ellipse : obj.radius>0 ? pptx.ShapeType.roundRect : pptx.ShapeType.rect;
        slide.addShape(shape, options);
      } else if (obj.type === 'line') {
        slide.addShape(pptx.ShapeType.line,{...box,line:{color:rgb(obj.stroke),width:obj.strokeWidth*points,transparency,
          beginArrowType:obj.startArrow?'triangle':'none',endArrowType:obj.endArrow?'triangle':'none'}});
      } else if (obj.type === 'image') {
        const [iw,ih]=imageDimensions(obj.src);
        if(!iw||!ih)throw new Error('图片原始尺寸无效。');
        let placement={...box};
        if(obj.fit==='contain'){
          const ratio=Math.min(box.w/iw,box.h/ih),w=iw*ratio,h=ih*ratio;
          placement={x:box.x+(box.w-w)/2,y:box.y+(box.h-h)/2,w,h};
        }else if(obj.fit==='cover'){
          // PptxGenJS uses w/h as the intrinsic ratio when sizing is supplied.
          placement={...box,w:iw/96,h:ih/96,sizing:{type:'cover',w:box.w,h:box.h}};
        }
        slide.addImage({...placement,data:obj.src,altText:obj.id+' — '+obj.alt,transparency});
      }
    }
    slide.addNotes('Slide ID: '+scene.slideId+'\n'+(scene.notes||''));
  }
  const zip = await JSZip.loadAsync(await pptx.write({outputType:'nodebuffer'}));
  for (const name of Object.keys(zip.files).filter(name => /^ppt\/slides\/slide\d+\.xml$/.test(name))) {
    zip.file(name, singleParagraphProperties(await zip.file(name).async('string')));
  }
  fs.writeFileSync(output, await zip.generateAsync({type:'nodebuffer', compression:'DEFLATE'}));
  process.stdout.write(JSON.stringify({path:output,slideCount:input.scenes.length,rendererVersion:pptx.version})+'\n');
} catch (error) {
  process.stderr.write(JSON.stringify({code:'PPTX_EXPORT_FAILED',message:String(error.message||error)})+'\n');
  process.exit(1);
}
