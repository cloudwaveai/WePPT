import {createHash} from 'node:crypto';
import {validateSvg} from './public/vector-scene.js';
import {libraryExportMode} from './public/library-assets.js';

// Complex effects use an individual high-resolution transparent picture.
// Keep the original SVG in the package; Office SVG renderers differ on blur.
export async function prepareLibraryExport(pages,tab,{signal}={}){
 const pictures=new Map();
 await tab.route('**/*',route=>route.abort());
 for(const page of pages)for(const object of page.objects||[]){
  if(object.type!=='vector'||!object.libraryAssetId)continue;
  signal?.throwIfAborted();validateSvg(object.svg);
  if(libraryExportMode(object)==='native'){
   object.svg=await tab.evaluate(svg=>{
    const doc=new DOMParser().parseFromString(svg,'image/svg+xml'),root=doc.documentElement;
    const vb=root.getAttribute('viewBox').split(/[ ,]+/).map(Number);
    for(const node of root.querySelectorAll('*')){
     for(const [key,base]of [['width',vb[2]],['height',vb[3]]])if(/^[\d.]+%$/.test(node.getAttribute(key)||''))node.setAttribute(key,String(parseFloat(node.getAttribute(key))*base/100));
     if(['polyline','polygon'].includes(node.localName)){
      const nums=(node.getAttribute('points')||'').trim().split(/[ ,]+/).map(Number),path=doc.createElementNS(root.namespaceURI,'path');
      for(const a of node.attributes)if(a.name!=='points')path.setAttribute(a.name,a.value);
      path.setAttribute('d',nums.reduce((s,n,i)=>s+(i%2?' ':i===0?'M':' L')+n,'')+(node.localName==='polygon'?' Z':''));node.replaceWith(path);
     }
    }
    return new XMLSerializer().serializeToString(root);
   },object.svg);
   continue;
  }
  const svg=object.svg;
  const src=await tab.evaluate(async({svg,w,h})=>{
   const image=new Image();image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg);await image.decode();
   const canvas=document.createElement('canvas');canvas.width=Math.min(4096,Math.max(1,Math.ceil(w*3)));canvas.height=Math.min(4096,Math.max(1,Math.ceil(h*3)));
   canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);return canvas.toDataURL('image/png');
  },{svg,w:object.w,h:object.h});
  const hash=createHash('sha256').update(Buffer.from(src.split(',')[1],'base64')).digest('hex');pictures.set(hash,svg);
  object.type='image';object.src=src;object.fit='contain';delete object.svg;
 }
 return pictures;
}

export async function embedLibrarySvgPictures(zip,pictures){
 if(!pictures.size)return;
 const media=new Map();let index=0;
 for(const file of Object.values(zip.files).filter(f=>/^ppt\/media\/.*\.png$/i.test(f.name))){
  const hash=createHash('sha256').update(await file.async('nodebuffer')).digest('hex'),svg=pictures.get(hash);if(!svg)continue;
  const name=`weppt-library-${++index}.svg`;zip.file('ppt/media/'+name,svg);media.set(file.name.split('/').pop(),name);
 }
 if(!media.size)throw Error('复杂素材未能保留矢量原件，导出已停止。');
 for(const file of Object.values(zip.files).filter(f=>/^ppt\/slides\/_rels\/slide\d+\.xml\.rels$/.test(f.name))){
  let rels=await file.async('string'),xml=await zip.file(file.name.replace('/_rels/','/').replace(/\.rels$/,'')).async('string');
  for(const match of rels.matchAll(/<Relationship\b[^>]*\/?\s*>/g)){
   const rid=/\bId="([^"]+)"/.exec(match[0])?.[1],target=/\bTarget="([^"]+)"/.exec(match[0])?.[1],name=media.get(target?.split('/').pop());if(!name)continue;
   const svgRid='wepptSvg'+rid;
   rels=rels.replace('</Relationships>',`<Relationship Id="${svgRid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/${name}"/></Relationships>`);
   // Do not add asvg:svgBlip: LibreOffice ignores blur when rendering that
   // extension. The PNG is the visible representation; SVG is source-only.
  }
  zip.file(file.name,rels);zip.file(file.name.replace('/_rels/','/').replace(/\.rels$/,''),xml);
 }
 let types=await zip.file('[Content_Types].xml').async('string');if(!/Extension="svg"/.test(types))types=types.replace('</Types>','<Default Extension="svg" ContentType="image/svg+xml"/></Types>');zip.file('[Content_Types].xml',types);
}
