// Editable PPTX export. No shell commands or remote asset loading.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

let PptxGenJS;
try {
  try { PptxGenJS = createRequire(import.meta.url)('pptxgenjs'); }
  catch { PptxGenJS = createRequire(path.join(process.cwd(), 'package.json'))('pptxgenjs'); }
} catch {
  process.stderr.write(JSON.stringify({code:'PPTX_DEPENDENCY_MISSING',message:'未安装 pptxgenjs。请在软件项目目录执行 npm install，然后重试。'})+'\n');
  process.exit(2);
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
  for (const scene of input.scenes) {
    const slide = pptx.addSlide();
    slide.background = {color:rgb(scene.background)};
    const scale = 13.3333333333 / scene.width;
    const points = scale * 72;
    for (const obj of scene.objects) {
      const box = {x:obj.x*scale,y:obj.y*scale,w:obj.w*scale,h:obj.h*scale,objectName:obj.id};
      const transparency = Math.round((1-obj.opacity)*100);
      if (obj.type === 'text') {
        slide.addText(obj.text, {...box,fontFace:obj.fontFamily,fontSize:obj.fontSize*points,
          color:rgb(obj.color),bold:obj.bold,italic:obj.italic,align:obj.align,
          valign:obj.valign==='middle'?'mid':obj.valign,margin:0,breakLine:false,
          lineSpacingMultiple:obj.lineHeight,paraSpaceAfter:0,paraSpaceBefore:0,
          isTextBox:true,fit:'none',transparency,lang:'zh-CN'});
      } else if (obj.type === 'rect') {
        const options = {...box,rectRadius:obj.radius*scale,
          fill:obj.fill==='none'?{color:'FFFFFF',transparency:100}:{color:rgb(obj.fill),transparency},
          line:obj.stroke==='none'?{color:'FFFFFF',transparency:100}:{color:rgb(obj.stroke),width:obj.strokeWidth*points,transparency}};
        slide.addShape(obj.radius>0?pptx.ShapeType.roundRect:pptx.ShapeType.rect, options);
      } else if (obj.type === 'line') {
        slide.addShape(pptx.ShapeType.line,{...box,line:{color:rgb(obj.stroke),width:obj.strokeWidth*points,transparency}});
      } else if (obj.type === 'image') {
        slide.addImage({...box,data:obj.src,sizing:{type:obj.fit,w:box.w,h:box.h},
          altText:obj.id+' — '+obj.alt,transparency});
      }
    }
    slide.addNotes('Slide ID: '+scene.slideId+'\n'+(scene.notes||''));
  }
  await pptx.writeFile({fileName:output,compression:true});
  process.stdout.write(JSON.stringify({path:output,slideCount:input.scenes.length,rendererVersion:pptx.version})+'\n');
} catch (error) {
  process.stderr.write(JSON.stringify({code:'PPTX_EXPORT_FAILED',message:String(error.message||error)})+'\n');
  process.exit(1);
}
