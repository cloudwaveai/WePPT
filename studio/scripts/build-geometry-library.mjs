import {readFile,writeFile,mkdir,copyFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
import {validateSvg} from '../public/vector-scene.js';
const root=fileURLToPath(new URL('../',import.meta.url)),source=join(root,'vendor/geometry-samples'),out=join(root,'public/assets/library');
export async function appendGeometry(catalog){
 const manifest=JSON.parse(await readFile(join(source,'sources.json'),'utf8'));
 await mkdir(join(out,'geometry'),{recursive:true});await mkdir(join(out,'licenses'),{recursive:true});
 for(const lib of ['flowshape','dividers','pattern'])await copyFile(join(source,lib+'-LICENSE.txt'),join(out,'licenses','geometry-'+lib+'.txt'));
 const items=[];
 for(const m of manifest){let svg,width,height;
  if(m.library==='pattern'){
   const p=JSON.parse(await readFile(join(source,m.id+'.json'),'utf8'));width=300;height=180;
   // Expand original path tiles instead of <pattern>, for editable native PPTX export.
   const tiles=[];for(let y=0;y<height;y+=p.height)for(let x=0;x<width;x+=p.width)tiles.push(`<g transform="translate(${x} ${y})">${p.path.split('~').join('')}</g>`);
   svg=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}"><defs><clipPath id="tile-bounds"><rect width="${width}" height="${height}"/></clipPath></defs><g clip-path="url(#tile-bounds)" fill="none" stroke="#252824" stroke-width="0.7">${tiles.join('')}</g></svg>`;
  }else{
   svg=await readFile(join(source,m.id+'.svg'),'utf8');
   [, ,width,height]=svg.match(/viewBox="([^"]+)"/)[1].split(/\s+/).map(Number);
   if(m.library==='flowshape')svg=svg.replace(/<rect x="0" y="0" width="240" height="320" fill="#020202"\/>/,'').replaceAll('#e4e4e4','#252824');
   // Make implicit SVG black explicit so the editor's color control can recolor it.
   if(m.library==='dividers')svg=svg.replaceAll('<path ','<path fill="#252824" ');
  }
  svg=svg.replace('<svg ',`<svg width="${width}" height="${height}" `);validateSvg(svg);
  const src=`/assets/library/geometry/${m.id}.svg`;await writeFile(join(root,'public',src.slice(1)),svg);
  items.push({id:'geometry-'+m.id,name:m.name,library:'geometry',style:m.library==='pattern'?'pattern':'geometric',tags:['几何','基础',m.use,m.id],usage:m.use,src,width,height,viewBox:`0 0 ${width} ${height}`,sha256:createHash('sha256').update(svg).digest('hex'),editableColor:true,source:m.source,license:m.license,licenseSrc:`/assets/library/licenses/geometry-${m.library}.txt`,adaptation:'透明底黑白基础版；原始配色文件保留在vendor/geometry-samples；不随模板自动改色'});
 }
 catalog.items=[...items,...catalog.items.filter(i=>i.library!=='geometry')];
 catalog.libraries=[...catalog.libraries.filter(l=>l.id!=='geometry'),{id:'geometry',name:'基础几何',version:'2026-11-06',source:'https://github.com/Jossifresben/flowshape',license:'MIT / CC0-1.0',count:items.length,description:'逐项保留来源与许可；透明底单色基础素材，插入后按需改色。'}];
 return catalog;
}
if(process.argv[1]&&fileURLToPath(import.meta.url)===process.argv[1]){const catalog=JSON.parse(await readFile(join(out,'catalog.json'),'utf8'));await writeFile(join(out,'catalog.json'),JSON.stringify(await appendGeometry(catalog)));console.log('基础几何：9项已加入');}
