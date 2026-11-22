import test from 'node:test';
import assert from 'node:assert/strict';
import {isManualLayoutFinding,applyManualLayoutIssues,acceptManualLayoutViolations} from '/app/manual-layout-policy.mjs';
import {applyTemplateSimilarityPolicy} from '/app/pptagent-review.mjs';

const line={kind:'readability',severity:'major',slide:15,description:'第二条说明文字穿过竖直框线，并与右侧水平线重叠，影响阅读。',suggested_fix:'移动这段文字避开装饰线。'};
test('actual incident text-line collision is advisory in single-page and whole-deck checks',()=>{
 assert.equal(isManualLayoutFinding(line),true);
 const single=acceptManualLayoutViolations({matches:false,reason:'需要挪动文字',violations:[{kind:'readability',evidence:line.description}]});
 assert.equal(single.matches,true);assert.equal(single.violations.length,0);assert.equal(single.advisories[0].manualAdjustment,true);
 const deck=applyTemplateSimilarityPolicy({verdict:'fail',issues:[line]});assert.equal(deck.verdict,'pass');assert.equal(deck.issues[0].severity,'minor');assert.equal(deck.issues[0].manualAdjustment,true);
});
test('DOM decorative-line evidence stays visible as a warning',()=>{
 const issue={kind:'background-line-overlap',severity:'error',message:'文字对象 a 第1行穿过背景装饰线 rule1',lineRect:{x:100,y:200,w:300,h:30}};
 const result=applyManualLayoutIssues([issue]);assert.equal(result[0].severity,'warning');assert.deepEqual(result[0].lineRect,issue.lineRect);assert.equal(issue.severity,'error');
});
for(const ratio of [.1,.3,.31,1,NaN,undefined])test(`text box overlap ratio ${ratio} retains measured tolerance`,()=>{
 const issue={kind:'overlap',severity:'error',overlapRatio:ratio,message:'两个文本框重叠。'};
 assert.equal(applyManualLayoutIssues([issue])[0].severity,ratio<=.3?'warning':'error');
});
for(const defect of ['missing source text','wrong sales data','duplicated content','unreadable paragraph','clipped title','严重文字遮挡','大面积重叠','缺少结论','漏字','内容错误','素材缺失','裁切正文','超出画布'])test(`mixed manual finding cannot hide ${defect}`,()=>{
 const issue={...line,kind:'manual_layout',description:line.description+' '+defect};
 assert.equal(isManualLayoutFinding(issue),false);
 assert.equal(applyTemplateSimilarityPolicy({verdict:'fail',issues:[issue]}).verdict,'fail');
});
test('unrelated error, unknown coverage and fail-without-findings remain blocking',()=>{
 assert.equal(applyTemplateSimilarityPolicy({verdict:'fail',issues:[line,{kind:'other',severity:'minor',description:'Unknown defect',suggested_fix:'Investigate'}]}).verdict,'fail');
 assert.equal(applyTemplateSimilarityPolicy({verdict:'unjudgeable',issues:[line]}).verdict,'unjudgeable');
 assert.equal(applyTemplateSimilarityPolicy({verdict:'fail',issues:[]}).verdict,'fail');
 for(const kind of ['asset','coverage','bounds','overflow'])assert.equal(applyManualLayoutIssues([{kind,severity:'error',message:'真实程序错误'}])[0].severity,'error');
});
test('manual advisory cannot hide separate content loss in single-page review',()=>{
 const verdict=acceptManualLayoutViolations({matches:false,violations:[{kind:'readability',evidence:line.description},{kind:'readability',evidence:'missing source text'}]});
 assert.equal(verdict.matches,false);assert.equal(verdict.violations.length,1);assert.equal(verdict.advisories.length,1);
});

for(const description of ['Unknown issue','Paragraph hidden behind an opaque image','Title is obscured by chart','Body is occluded by a shape','正文被图块完全盖住','无法判断文字是否完整','Text is not readable because two blocks cover it','正文已不具备可读性'])test(`manual label alone cannot waive ${description}`,()=>{
 const issue={kind:'manual_layout',severity:'major',slide:1,description,suggested_fix:'Investigate'};
 assert.equal(isManualLayoutFinding(issue),false);assert.equal(applyTemplateSimilarityPolicy({verdict:'fail',issues:[issue]}).verdict,'fail');
});
