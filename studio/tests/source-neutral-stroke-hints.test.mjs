import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {diagnoseEditableArtworkSource} from '../source-inventory-diagnostics.mjs';
const exec=promisify(execFile);
test('neutral strokes carry actual source position and gray color as advisory data',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'neutral-hints-'));
 try{
  const sourcePath=join(dir,'source.png');
  await exec(process.env.PYTHON||'python',['-c',`from PIL import Image,ImageDraw;import sys
im=Image.new('RGB',(1280,720),(233,233,233));d=ImageDraw.Draw(im)
d.line((100,210,366,210),fill=(104,104,103),width=2)
d.line((900,180,900,420),fill=(86,87,87),width=3)
d.rectangle((400,300,500,400),fill=(0,0,0))
im.save(sys.argv[1])`,sourcePath]);
  const inventory={layers:[{kind:'line',points:[[100,260],[366,260]],color:'#000000',width:1,dash:'solid'}]};
  const before=JSON.stringify(inventory),r=await diagnoseEditableArtworkSource({sourcePath,inventory});
  assert.equal(JSON.stringify(inventory),before);
  assert.equal(r.issues[0].code,'invalid_source_alignment');
  const horizontal=r.neutralStrokeHints.find(h=>h.points[0][0]===100);
  assert.deepEqual(horizontal.points,[[100,210.5],[366,210.5]]);assert.equal(horizontal.color,'#686867');
  const vertical=r.neutralStrokeHints.find(h=>h.points[0][1]===180);
  assert.deepEqual(vertical.points,[[900,180],[900,420]]);assert.equal(vertical.color,'#565757');
  assert(r.neutralStrokeHints.every(h=>h.diagnosticOnly));
  assert(!r.neutralStrokeHints.some(h=>h.points[0][0]===400));
 }finally{await rm(dir,{recursive:true,force:true});}
});
