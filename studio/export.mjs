import PptxGenJS from 'pptxgenjs';
import JSZip from 'jszip';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
const publicRoot=fileURLToPath(new URL('./public/',import.meta.url));

const clamp=(v,a,b)=>Math.max(a,Math.min(b,Number(v)));
const n=(v,f=0)=>Number.isFinite(Number(v))?Number(v):f;
const hex=(v,f='FFFFFF')=>/^#[\da-f]{6}$/i.test(v || '')?v.slice(1):/^[\da-f]{6}$/i.test(v || '')?v:f;
function shadow(s){if(!s)return undefined;const x=n(s.offsetX,4),y=n(s.offsetY,8);return {type:'outer',color:hex(s.color,'000000'),opacity:clamp(n(s.opacity,.16),0,1),blur:clamp(n(s.blur,12)*.75,0,100),offset:clamp(Math.hypot(x,y)*.75,0,200),angle:(Math.atan2(y,x)*180/Math.PI+360)%360};}
async function imageData(src,dataDir){
  if(/^data:image\/(png|jpeg|gif|webp);base64,[\da-z+/=]+$/i.test(src || ''))return src;
  const template=/^\/assets\/templates\/(curated-[0-9]+)\/([0-9]+\.(?:jpg|png|webp))$/.exec(src || '');
  if(template){const raw=await readFile(join(publicRoot,'assets','templates',template[1],template[2]));const ext=template[2].split('.').pop();return `data:image/${ext==='jpg'?'jpeg':ext};base64,${raw.toString('base64')}`;}
  const match=/^\/uploads\/([a-f\d-]+\.(?:png|jpg|gif|webp))$/i.exec(src || '');
  if(!match)throw Error('图片素材无法导出，请重新上传该图片。');
  const raw=await readFile(join(dataDir,'uploads',match[1]));const ext=match[1].split('.').pop();return `data:image/${ext==='jpg'?'jpeg':ext};base64,${raw.toString('base64')}`;
}

export async function exportPptx(project,{dataDir}={}){
  if(!Array.isArray(project.pages)||!project.pages.length)throw Error('请先生成或添加页面。');
  const pptx=new PptxGenJS();pptx.defineLayout({name:'WEPPT',width:40/3,height:7.5});pptx.layout='WEPPT';
  pptx.author='WePPT';pptx.subject='可编辑演示文稿';pptx.title=String(project.title || '演示文稿');pptx.company='';pptx.lang='zh-CN';pptx.theme={headFontFace:'Microsoft YaHei',bodyFontFace:'Microsoft YaHei',lang:'zh-CN'};
  const crops=[];
  for(const [pageIndex,page] of project.pages.entries()){
    const slide=pptx.addSlide();slide.background={color:hex(page.background)};
    if(!Array.isArray(page.objects))throw Error('页面缺少可编辑对象，请先完成排版。');
    const pageCrops=[];
    for(const object of page.objects){
      const x=n(object.x)/96,y=n(object.y)/96,w=Math.max(.005,n(object.w,100)/96),h=Math.max(.005,n(object.h,50)/96);
      const opacity=clamp(n(object.opacity,1),0,1),base={x,y,w,h,rotate:n(object.rotation),objectName:String(object.id || 'object'),shadow:shadow(object.shadow)};
      if(object.type==='text'){
        slide.addText(String(object.text ?? ''),{...base,fontFace:String(object.fontFamily || 'Microsoft YaHei'),fontSize:Math.max(1,n(object.fontSize,24)*.75),color:hex(object.color,'272824'),bold:!!object.bold,italic:!!object.italic,align:['left','center','right','justify'].includes(object.align)?object.align:'left',valign:'top',margin:0,breakLine:false,paraSpaceAfterPt:0,transparency:100*(1-opacity),lineSpacingMultiple:n(object.lineHeight,1.18),wrap:true});
      }else if(object.type==='image'){
        const data=await imageData(object.src,dataDir);
        const crop=object.crop;
        slide.addImage({...base,data,transparency:100*(1-opacity),altText:String(object.name || object.kind || '图片'),...(!crop?{sizing:{type:object.fit==='cover'?'cover':'contain',w,h}}:{})});
        pageCrops.push(crop || null);
      }else{
        const type=object.type==='ellipse'?pptx.ShapeType.ellipse:object.type==='line'?pptx.ShapeType.line:object.radius?pptx.ShapeType.roundRect:pptx.ShapeType.rect;
        const transparent=object.fill==='transparent'||object.fill==='none';
        const lineColor=object.stroke || (object.type==='line'?object.fill:'#FFFFFF');
        slide.addShape(type,{...base,radius:n(object.radius)/96,rectRadius:n(object.radius)/96,fill:{color:hex(object.fill),transparency:transparent?100:100*(1-opacity)},line:{color:hex(lineColor,'272824'),width:Math.max(0,n(object.strokeWidth,object.type==='line'?2:0)*.75),transparency:!object.stroke&&object.type!=='line'?100:100*(1-opacity)}});
      }
    }
    crops[pageIndex]=pageCrops;
    if(page.body)slide.addNotes(String(page.body));
  }
  let buffer=await pptx.write({outputType:'nodebuffer'});
  if(crops.some(list=>list.some(Boolean))){
    const zip=await JSZip.loadAsync(buffer);
    for(const [index,list] of crops.entries()){
      if(!list.some(Boolean))continue;
      const filename=`ppt/slides/slide${index+1}.xml`;let pictureIndex=0;
      let xml=await zip.file(filename).async('string');
      xml=xml.replace(/<p:pic>[\s\S]*?<\/p:pic>/g,picture=>{
        const c=list[pictureIndex++];if(!c)return picture;
        const left=clamp(n(c.x),0,.99),top=clamp(n(c.y),0,.99),width=clamp(n(c.w,1),.01,1-left),height=clamp(n(c.h,1),.01,1-top);
        const rect=`<a:srcRect l="${Math.round(left*100000)}" t="${Math.round(top*100000)}" r="${Math.round((1-left-width)*100000)}" b="${Math.round((1-top-height)*100000)}"/>`;
        return /<a:srcRect[^>]*\/>/.test(picture)?picture.replace(/<a:srcRect[^>]*\/>/,rect):picture.replace('</a:blip>','</a:blip>'+rect);
      });zip.file(filename,xml);
    }
    buffer=await zip.generateAsync({type:'nodebuffer',compression:'DEFLATE'});
  }
  return buffer;
}
