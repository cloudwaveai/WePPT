import {readFile,writeFile,mkdir,readdir,copyFile} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import React from 'react';
import {appendGeometry} from './build-geometry-library.mjs';
import {renderToStaticMarkup} from 'react-dom/server';
import {shapes} from '../node_modules/coolshapes-react/dist/esm/coolshapes.js';
import geopattern from 'geopattern';
import blobshape from 'blobshape';
import {validateSvg} from '../public/vector-scene.js';
const root=fileURLToPath(new URL('../',import.meta.url)),out=join(root,'public/assets/library');
const libraries=[
 {id:'coolshapes',name:'Coolshapes',package:'coolshapes-react',source:'https://github.com/realvjy/coolshapes-react',description:'原版渐变抽象造型，关闭颗粒噪声后静态导出。'},
 {id:'geopattern',name:'GeoPattern',package:'geopattern',source:'https://github.com/btmills/geopattern',upstream:'https://github.com/jasonlong/geo_pattern',description:'原版项目明确链接的JavaScript移植，16种几何图案的固定种子生成结果。'},
 {id:'blobshape',name:'Blobshape',package:'blobshape',source:'https://github.com/lokesh-coder/blobshape',description:'原版生成器产生的固定种子有机轮廓。'},
 {id:'tabler',name:'Tabler Icons',package:'@tabler/icons',source:'https://github.com/tabler/tabler-icons',description:'原版全部outline和filled SVG图标。'}
];
await mkdir(out,{recursive:true});const items=[];
for(const library of libraries){const base=join(root,'node_modules',library.package),pkg=JSON.parse(await readFile(join(base,'package.json'),'utf8'));library.version=pkg.version;library.license=pkg.license;library.licenseSrc=`/assets/library/licenses/${library.id}.txt`;await mkdir(join(out,library.id),{recursive:true});await mkdir(join(out,'licenses'),{recursive:true});await copyFile(join(base,'LICENSE'),join(out,'licenses',library.id+'.txt'));}
function normalize(raw){
 let svg=raw.replace(/\bid="url\(#([\w:.-]+)\)"/g,'id="$1"').replace(/url\(#([\w:.-]+)"/g,'url(#$1)"').trim().replace(/<\?xml[^>]*>/g,'').replace(/\sclass="[^"]*"/g,'').replace(/currentColor/g,'#111111').replace(/url\(&quot;#([\w:.-]+)&quot;\)/g,'url(#$1)');
 const opening=svg.match(/^<svg\b[^>]*>/)?.[0];if(!opening)throw Error('SVG root missing');
 let vb=opening.match(/viewBox="([^"]+)"/)?.[1];
 if(!vb){const w=Number(opening.match(/\bwidth="([\d.]+)"/)?.[1]),h=Number(opening.match(/\bheight="([\d.]+)"/)?.[1]);if(!(w>0&&h>0))throw Error('SVG dimensions missing');vb=`0 0 ${w} ${h}`;svg=svg.replace('<svg ',`<svg viewBox="${vb}" `);}
 const [x,y,width,height]=vb.split(/\s+/).map(Number);if(![x,y,width,height].every(Number.isFinite)||width<=0||height<=0)throw Error('SVG dimensions invalid');
 svg=svg.replace(/(<svg\b[^>]*?)\swidth="[^"]*"/,'$1').replace(/(<svg\b[^>]*?)\sheight="[^"]*"/,'$1');
 svg=svg.replace('<svg ',`<svg width="${width}" height="${height}" `);
 // Some generators use an omitted first stop offset; native PPTX requires it explicit.
 svg=svg.replace(/<stop\b([^>]*?)(\/?)>/g,(m,a,end)=>/\boffset=/.test(a)?m:`<stop offset="0"${a}${end}>`);
 validateSvg(svg);return {svg,width,height,viewBox:vb};
}
async function add(library,name,style,raw,tags=[],extra={}){
 const slug=name.toLowerCase().replace(/[^a-z0-9-]+/g,'-'),id=library+'-'+slug;const item=normalize(raw),src=`/assets/library/${library}/${slug}.svg`;
 await writeFile(join(out,library,slug+'.svg'),item.svg);
 items.push({id,name,library,style,tags:[...new Set(tags)],src,width:item.width,height:item.height,viewBox:item.viewBox,sha256:createHash('sha256').update(item.svg).digest('hex'),...extra});
}
for(const [category,components]of Object.entries(shapes))for(const [index,component]of components.entries()){
 await add('coolshapes',`${category}-${String(index+1).padStart(2,'0')}`,'gradient',renderToStaticMarkup(React.createElement(component,{size:400,noise:false})).replaceAll('${shapeId}',`${category}-${index+1}`),[category,'abstract','gradient','抽象','渐变'],{editableColor:false});
}
const patterns=['octogons','overlappingCircles','plusSigns','xes','sineWaves','hexagons','overlappingRings','plaid','triangles','squares','concentricCircles','diamonds','tessellation','nestedSquares','mosaicSquares','chevrons'];
const colors=['#E9EEF5','#DDEADF','#F3E4D3','#292F3B'];
for(const pattern of patterns)for(const [i,color]of colors.entries()){
 const seed=`weppt-${pattern}-${i+1}`;
 await add('geopattern',`${pattern}-${i+1}`,'pattern',geopattern.generate(seed,{color,generator:pattern}).toSvg(),[pattern,'geometric','background','图案','背景'],{seed,generator:pattern,editableColor:false});
}
for(let i=0;i<36;i++){
 const edges=5+i%7,growth=4+i%5,seed=`${growth}-${edges}-${1000+i}`,generated=blobshape({size:400,growth,edges,seed});
 await add('blobshape',`blob-${String(i+1).padStart(2,'0')}`,'organic',`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><path fill="#5879B8" d="${generated.path}"/></svg>`,['blob','organic','fluid','有机','轮廓'],{seed:generated.seedValue,editableColor:true});
}
const tablerRoot=join(root,'node_modules/@tabler/icons'),metadata=JSON.parse(await readFile(join(tablerRoot,'icons.json'),'utf8'));
for(const style of ['outline','filled'])for(const file of (await readdir(join(tablerRoot,'icons',style))).filter(f=>f.endsWith('.svg')).sort()){
 const name=file.slice(0,-4),meta=metadata[name]||{};
 await add('tabler',`${style}-${name}`,style,await readFile(join(tablerRoot,'icons',style,file),'utf8'),[name,...(meta.tags||[]),meta.category||'',style,'icon','图标'].filter(Boolean),{editableColor:true});
}
for(const library of libraries)library.count=items.filter(i=>i.library===library.id).length;
const catalog=await appendGeometry({version:1,libraries,items});await writeFile(join(out,'catalog.json'),JSON.stringify(catalog));
await writeFile(join(out,'NOTICE.md'),`# Local SVG library\n\nGenerated with scripts/build-asset-library.mjs. No React is loaded by the application browser. Original MIT license texts are retained in licenses/. SVG artwork is normalized for local viewing; Coolshapes noise is disabled. Five upstream reference defects are corrected: literal shapeId in star8/star9, missing URL closing parentheses in wheel3/moon3, and a url()-wrapped clipPath id in flower4. Do not infer full native-export compatibility from catalog availability.\n\n${libraries.map(l=>`- ${l.name} ${l.version}: ${l.source} (${l.license}, ${l.count} items)`).join('\n')}\n\nGeoPattern JavaScript port is explicitly listed at https://github.com/jasonlong/geo_pattern#ports--related-projects .\n`);
console.log(JSON.stringify({total:items.length,libraries:libraries.map(({id,version,count})=>({id,version,count}))}));
