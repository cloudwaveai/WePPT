import {readFile,writeFile,mkdir,copyFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {join} from 'node:path';
const catalog=JSON.parse(await readFile('public/templates.json','utf8'));
const base='public/assets/theme-previews';await mkdir(base,{recursive:true});
const entries={};
for(const theme of catalog){
 let dir;
 if(theme.id==='curated-091')dir='tests/artifacts/template-migration-091';
 else if(['005','246','410','373','481'].some(n=>theme.id===`curated-${n}`))dir=`tests/artifacts/template-migration-batch2/${theme.id}`;
 else if(['129','147','157','001','068','155','228','235','501','006'].some(n=>theme.id===`curated-${n}`))dir=`tests/artifacts/template-migration-batch3/${theme.id}`;
 else if(theme.id!=='curated-139')dir=`tests/artifacts/template-continuation/${theme.id}`;
 if(!dir){entries[theme.id]={kind:'reference',images:theme.previews.slice(0,3)};continue;}
 const report=JSON.parse(await readFile(join(dir,'validation.json'),'utf8'));if(!report.passed)throw Error(`${theme.id} not validated`);
 const images=[];
 for(let i=1;i<=3;i++){
  const bytes=await readFile(join(dir,`office-${i}.png`));
  const name=`${theme.id}-${i}-${createHash('sha256').update(bytes).digest('hex').slice(0,12)}.png`;
  await copyFile(join(dir,`office-${i}.png`),join(base,name));images.push(`/assets/theme-previews/${name}`);
 }
 entries[theme.id]={kind:'sample',images};
}
await writeFile(join(base,'index.json'),JSON.stringify({version:1,entries}));
console.log(`Published ${Object.keys(entries).length} local preview entries; no user projects changed.`);
