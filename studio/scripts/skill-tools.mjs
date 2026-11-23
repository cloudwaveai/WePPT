// Local tool entrypoint. HTTP/model requests cannot supply arbitrary commands.
import {spawn} from 'node:child_process';
import {resolve,join} from 'node:path';
import {upstreamCatalog,upstreamPackage,measureUpstreamText} from '../upstream-skills.mjs';
const [action,...args]=process.argv.slice(2);
if(action==='status')console.log(JSON.stringify(upstreamCatalog(),null,2));
else if(action==='measure'){
 let input='';for await(const chunk of process.stdin)input+=chunk;
 console.log(JSON.stringify(await measureUpstreamText(JSON.parse(input)),null,2));
}else if(action==='convert-svg'){
 if(args.length!==2)throw Error('Usage: convert-svg <workspace with svg_output> <output.pptx>');
 const skill=upstreamPackage('ppt-master');if(!skill.installed)throw Error('Run npm run setup:skills first');
 const run=command=>new Promise((resolveRun,reject)=>{const child=spawn(process.env.PYTHON||'python',['-X','utf8',...command],{windowsHide:true,stdio:'inherit',shell:false});child.on('error',reject);child.on('close',code=>code===0?resolveRun():reject(Error('Upstream tool exited '+code)));});
 await run([join(skill.directory,'scripts/svg_quality_checker.py'),resolve(args[0]),'--quick-generate','--canonical-authoring','--stage','final','--json']);
 await run([join(skill.directory,'scripts/svg_to_pptx.py'),resolve(args[0]),'--quick-generate','--primary-language','zh-CN','-t','none','-o',resolve(args[1])]);
}else throw Error('Supported tools: status, measure, convert-svg');
