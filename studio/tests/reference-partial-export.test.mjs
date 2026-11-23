import test from 'node:test';import assert from 'node:assert/strict';import {mkdtemp,rm} from 'node:fs/promises';import {tmpdir} from 'node:os';import {join} from 'node:path';import JSZip from '/app/node_modules/jszip/lib/index.js';
import {completedReferenceExport} from '/app/public/reference-delivery.js';import {exportNativePptx} from '/app/svg-engine.mjs';
test('native PPTX partial export contains one completed editable slide and excludes pending content',async t=>{
 const dataDir=await mkdtemp(join(tmpdir(),'partial-export-'));t.after(()=>rm(dataDir,{recursive:true,force:true}));
 const p={id:'test',title:'部分稿',themeId:'curated-006',stage:'editor',pages:[{id:'p0',title:'完成页',body:'保留文字',role:'content',background:'#FFFFFF',objects:[{id:'text',type:'text',x:80,y:100,w:800,h:100,fontSize:32,color:'#222222',text:'已完成可编辑文字'}]},{id:'p1',title:'未完成页',body:'尚未生成的文案',role:'content',designPending:true,objects:[]}],referenceJob:{appliedPageIds:['p0']}};
 const bytes=await exportNativePptx(completedReferenceExport(p),{dataDir}),zip=await JSZip.loadAsync(bytes);const slides=Object.keys(zip.files).filter(n=>/^ppt\/slides\/slide\d+\.xml$/.test(n));assert.equal(slides.length,1);const xml=await zip.file(slides[0]).async('string');assert(xml.includes('已完成可编辑文字'));assert(!xml.includes('尚未生成的文案'));assert.equal(p.pages.length,2);
});
