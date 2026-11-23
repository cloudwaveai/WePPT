import test from 'node:test';import assert from 'node:assert/strict';
import {applyTemplateSimilarityPolicy} from '/app/pptagent-review.mjs';
const repeated={kind:'other',severity:'major',slide:2,description:'Slide 2 repeats slide 4 main composition with three stacked rows.',suggested_fix:'Reorganize one page into a checklist.'};
const verdict=issues=>({verdict:'fail',summary:'reviewed',checkedPageIds:['p1','p2'],issues});
test('same-template composition similarity is advisory for all page roles',()=>{const r=applyTemplateSimilarityPolicy(verdict([repeated]));assert.equal(r.verdict,'pass');assert.equal(r.issues[0].kind,'repetition');assert.equal(r.issues[0].severity,'minor');});
for(const defect of ['missing source text','text overlap','clipped title','unreadable text','重复文字','漏字','文字遮挡','越界'])test(`similarity mixed with real ${defect} remains blocking`,()=>{const r=applyTemplateSimilarityPolicy(verdict([{...repeated,kind:'repetition',description:repeated.description+' '+defect}]));assert.equal(r.verdict,'fail');assert.equal(r.issues[0].severity,'major');});
test('separate overlap cannot be softened by a similarity advisory',()=>{const r=applyTemplateSimilarityPolicy(verdict([repeated,{kind:'other',severity:'major',slide:1,description:'Title overlaps the chart',suggested_fix:'Move title'}]));assert.equal(r.verdict,'fail');assert.equal(r.issues[1].severity,'major');});
test('unknown coverage remains blocking even when all reported similarities are advisory',()=>{const r=applyTemplateSimilarityPolicy({...verdict([repeated]),verdict:'unjudgeable'});assert.equal(r.verdict,'unjudgeable');});
test('fail without any findings cannot become pass',()=>assert.equal(applyTemplateSimilarityPolicy(verdict([])).verdict,'fail'));

for(const description of ['Repeated layout, but slide 4 uses wrong sales figures','Duplicated content on slides 2 and 4','重复布局但内容错误','该页内容重复','重复文本','版式相似但缺少原文','相同布局且字号过小'])test(`legacy mixed finding cannot be softened: ${description}`,()=>{const r=applyTemplateSimilarityPolicy(verdict([{...repeated,description}]));assert.equal(r.verdict,'fail');assert.equal(r.issues[0].severity,'major');});

test('independent other minor remains blocking alongside similarity',()=>assert.equal(applyTemplateSimilarityPolicy(verdict([repeated,{kind:'other',severity:'minor',slide:1,description:'Independent unresolved finding',suggested_fix:'Investigate'}])).verdict,'fail'));
