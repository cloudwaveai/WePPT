import test from 'node:test';
import assert from 'node:assert/strict';
import {validateImageEdit} from '../public/image-assistant-result.js';
const page=id=>({id,title:'标题',body:'正文',objects:[{id:'t',type:'text',text:'正文',x:10,y:10,w:300,h:80},{id:'s',type:'rect',x:500,y:300,w:40,h:40}]});
const input={scope:'object',pageId:'p1',objectIds:['t'],project:{pages:[page('p1'),page('p2')]}};
const result=()=>{const pages=structuredClone(input.project.pages);pages[0].objects[0].text='新正文';return {message:'已修改',pages:[],changes:[],operations:[],imageEdit:{usedImage:true,pages,changedPageIds:['p1']}};};
test('complete Image object result validates without mutating input',()=>{const r=result(),before=structuredClone(r);assert.deepEqual(validateImageEdit(r,input),r.imageEdit);assert.deepEqual(r,before);});
test('nonselected object and sibling modifications rejected',()=>{
 for(const mutate of [r=>r.imageEdit.pages[0].objects[1].x++,r=>r.imageEdit.pages[1].title='bad',r=>r.imageEdit.pages[0].objects.reverse(),r=>r.imageEdit.pages.pop()]){const r=result();mutate(r);assert.throws(()=>validateImageEdit(r,input));}
});
test('mixed mutation, missing Image evidence and invalid IDs rejected',()=>{
 for(const mutate of [r=>r.changes.push({text:'bad'}),r=>r.imageEdit.usedImage=false,r=>r.imageEdit.changedPageIds.push('p1'),r=>r.imageEdit.pages[1].id='p1',r=>r.imageEdit.changedPageIds=['p2']]){const r=result();mutate(r);assert.throws(()=>validateImageEdit(r,input));}
});
test('page scope permits page redesign but never deck changes',()=>{
 const r=result();r.imageEdit.pages[0].objects=[{id:'new',type:'text',text:'新正文'}];assert(validateImageEdit(r,{...input,scope:'page'}));r.imageEdit.changedPageIds.push('p2');assert.throws(()=>validateImageEdit(r,{...input,scope:'page'}));
});
test('answer is not a mutation',()=>assert.equal(validateImageEdit({message:'这是建议'},input),null));

test('selected objects cannot modify background or deck structure',()=>{
 for(const mutate of [r=>r.imageEdit.pages[0].background='#000000',r=>r.imageEdit.pages.reverse(),r=>{r.imageEdit.pages.pop();r.imageEdit.changedPageIds.push('p2');}]){const r=result();mutate(r);assert.throws(()=>validateImageEdit(r,input));}
 const r=result();r.imageEdit.pages.pop();r.imageEdit.changedPageIds.push('p2');assert.throws(()=>validateImageEdit(r,{...input,scope:'deck'}));
});
