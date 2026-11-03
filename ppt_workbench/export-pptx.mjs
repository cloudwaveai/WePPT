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
          lineSpacingMultiple:obj.lineHeight,paraSpaceAfter:0,paraSpaceBefore:0,
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
        slide.addImage({...box,data:obj.src,sizing:{type:obj.fit,w:box.w,h:box.h},
          altText:obj.id+' — '+obj.alt,transparency});
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
