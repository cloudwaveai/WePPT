import test from 'node:test';import assert from 'node:assert/strict';import {manualPageResume,referenceResumeAvailability} from '../reference-resume-policy.mjs';
const state=(code,used={})=>({pageId:'p1',budget:{used:{image:1,text:3,styleReview:1,pageRun:1,...used},terminal:code?{code}:null}});
const job=(states,extra={})=>({status:'partial',pages:[],failures:[],pageStatus:states,deckReviewUsed:0,...extra});
test('only allowlisted quality failures spend remaining matching-stage budgets',()=>{
 for(const code of ['EDITABLE_ARTWORK_INVALID','REFERENCE_TEXT_REPAIR_EXHAUSTED','IMAGE_TEXT_GEOMETRY_INVALID'])assert.deepEqual(manualPageResume(state(code)),{stage:'text',needsRound:true});
 assert.deepEqual(manualPageResume(state('REFERENCE_STYLE_REVIEW_INVALID')),{stage:'styleReview',needsRound:true});
 for(const code of ['REFERENCE_CHECKPOINT_UNAVAILABLE','REFERENCE_PERSIST_FAILED','REFERENCE_SOURCE_INVALID','UNAUTHORIZED','UNKNOWN','AbortError'])assert.equal(manualPageResume(state(code)),null);
});
test('budget boundaries reject negative/fractional/missing/exhausted counts',()=>{
 for(const value of [-1,.5,undefined,NaN])for(const stage of ['text','pageRun'])assert.equal(manualPageResume(state('EDITABLE_ARTWORK_INVALID',{[stage]:value})),null);
 assert(manualPageResume(state('EDITABLE_ARTWORK_INVALID',{text:5,pageRun:5})));
 assert.equal(manualPageResume(state('REFERENCE_STYLE_REVIEW_INVALID',{styleReview:8})).needsRound,true);
 assert(manualPageResume(state('REFERENCE_STYLE_REVIEW_INVALID',{text:6,styleReview:7})));
});
test('blocked cache cannot re-enable UI through status/list policy',()=>{const s={...state('EDITABLE_ARTWORK_INVALID'),manualResumeBlocked:'PNG hash mismatch'};assert.equal(manualPageResume(s),null);assert(manualPageResume(s,{ignoreBlocked:true}));assert.deepEqual(referenceResumeAvailability(job([s])),{canResume:false,resumeReason:'PNG hash mismatch'});});
test('a successful page with a preserved failure is still unfinished',()=>{const s=state('EDITABLE_ARTWORK_INVALID');assert.equal(referenceResumeAvailability(job([s],{pages:[{id:'p1'}],failures:[{pageId:'p1'}]})).canResume,true);assert.equal(referenceResumeAvailability(job([s],{pages:[{id:'p1'}],reviewBlocked:true})).canResume,true);});
test('mixed terminal pages allow only the eligible subset and deleted wins over running',()=>{assert(referenceResumeAvailability(job([state('UNAUTHORIZED'),state('EDITABLE_ARTWORK_INVALID')])).canResume);assert.equal(referenceResumeAvailability(job([state('UNAUTHORIZED'),state('EDITABLE_ARTWORK_INVALID',{text:6})])).canResume,true);assert.equal(referenceResumeAvailability(job([],{status:'running',deletedAt:'now'})).canResume,false);});
test('deck review is bounded after all target pages exist',()=>{for(const [used,blocked,expected] of [[2,false,true],[3,false,true],[0,true,true]])assert.equal(referenceResumeAvailability(job([],{deckReviewUsed:used,reviewBlocked:blocked})).canResume,expected);});
test('interrupted page with no terminal still needs an executable stage',()=>{assert.equal(referenceResumeAvailability(job([state(null,{image:2,text:6,styleReview:8})],{status:'interrupted'})).canResume,true);});
