import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ppt_workbench.studio import Studio
from ppt_workbench.core import EngineError
from ppt_workbench.agent_bridge import validate_plan
from ppt_workbench.page_design import prepare_scene
from ppt_workbench.deck_review import run_review
from test_page_design import action

STRATEGY = dict(audience='非技术读者', outcome='理解记忆读写机制', storyArc='问题、机制、边界',
 visualLanguage='编辑式科普图解', typography='标题48正文26', imagePolicy='原生关系图',
 rhythm='概念引入后展开过程，案例收束', alternatives=[dict(id='a',concept='信息路径',rationale='突出机制'),
 dict(id='b',concept='对话案例',rationale='突出变化')], selectedDirection='a', selectionReason='机制是重点')
BRIEF = dict(claim='说明能力边界', visualForm='左右证据对照', visualReason='区分已实现与待验证',
 evidence='源材料列出的状态', readingPath='先左后右', density='anchor', continuity='承接产品概览')


def deck_plan():
 page={k:v for k,v in action().items() if k not in {'type','scene'}}
 page['designBrief']=copy.deepcopy(BRIEF)
 return dict(title='科普整稿',execution='agent',strategy=copy.deepcopy(STRATEGY),pages=[copy.deepcopy(page),copy.deepcopy(page)])


class DeckDesignTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.studio=Studio(self.temp.name,'test',agent='manual')

 def test_strategy_and_page_brief_are_validated_and_round_trip(self):
  plan=deck_plan();validate_plan(dict(reply='计划',actions=[dict(type='deck_start',**plan)]))
  self.studio.create_deck(plan,'用户完整需求')
  context=self.studio.next_job()['context']
  self.assertEqual(context['deckStrategy'],STRATEGY)
  self.assertEqual(context['currentDeckPage']['designBrief'],BRIEF)
  self.assertEqual(len(context['designRoster']),2)
  self.assertTrue(context['designReferences'])
  self.assertEqual(context['contentCapacity']['blockCount'],len(plan['pages'][0]['composition']['blocks']))
  bad=copy.deepcopy(plan);bad['strategy'].update(selectedDirection='missing')
  with self.assertRaises(EngineError):validate_plan(dict(reply='计划',actions=[dict(type='deck_start',**bad)]))
  # A missing design note is filled from the page content instead of failing the whole plan.
  sparse=copy.deepcopy(plan);sparse['pages'][0].pop('designBrief')
  filled=validate_plan(dict(reply='计划',actions=[dict(type='deck_start',**sparse)]))['actions'][0]
  self.assertEqual(filled['pages'][0]['designBrief']['claim'],plan['pages'][0]['composition']['purpose'])

 def test_plan_review_revises_before_locking_and_does_not_repeat(self):
  from ppt_workbench.deck_design import review_plan
  proposal=dict(reply='初始方案',actions=[dict(type='deck_start',**deck_plan())])
  job={'id':'J-plan','payload':{'attachments':[]}}
  revised=copy.deepcopy(proposal['actions'][0]);revised['pages'][0]['composition']['blocks'][0]['body']='仍保留事实的新分组'
  def runner(mode,prompt,context,**kwargs):
   self.assertEqual(context['draftDeckPlan'],proposal['actions'][0])
   self.assertEqual(context['sourceRequest'],'原始用户需求')
   self.assertEqual(len(context['contentCapacity']),len(proposal['actions'][0]['pages']))
   return dict(reply='REVISE：删除制作说明，保留产品事实。',actions=[revised])
  final=review_plan(self.studio,job,proposal,{'sourceRequest':'原始用户需求'},'claude',runner)
  self.assertEqual(final['actions'][0],revised)
  self.assertEqual(self.studio.state()['slides'],[])
  self.assertEqual(review_plan(self.studio,job,proposal,{},'claude',lambda *a,**k:self.fail('must reuse reviewed proposal')),final)

 def test_verdict_allows_explanation_but_not_incidental_pass_word(self):
  from ppt_workbench.design_loop import review_verdict
  for text,expected in [('PASS','PASS'),('**PASS**：检查通过','PASS'),('REVISE：删除制作要求','REVISE'),('NEEDS_ATTENTION — 待确认','NEEDS_ATTENTION'),('本次不应 PASS','UNKNOWN'),('PASSING','UNKNOWN'),('', 'UNKNOWN')]:
   self.assertEqual(review_verdict(text),expected)

 def test_plan_review_rejects_changed_page_count(self):
  from ppt_workbench.deck_design import review_plan
  proposal=dict(reply='初始方案',actions=[dict(type='deck_start',**deck_plan())])
  revised=copy.deepcopy(proposal['actions'][0]);revised['pages'].append(copy.deepcopy(revised['pages'][0]))
  kept=review_plan(self.studio,{'id':'J-count','payload':{}},proposal,{},'claude',lambda *a,**k:dict(reply='REVISE',actions=[revised]))
  self.assertEqual(kept['actions'],proposal['actions'])
  report=json.loads((self.studio.wb.project_dir('test')/'plan-reviews'/'J-count'/'report.json').read_text())
  self.assertEqual(report['status'],'failed-kept-draft')
  self.assertEqual(self.studio.state()['slides'],[])

 def test_sparse_plan_review_preserves_unchanged_fields_and_rejects_external_use(self):
  from ppt_workbench.deck_design import review_plan, apply_plan_patch
  from ppt_workbench.agent_bridge import _validate_task_scope
  proposal=dict(reply='草稿',actions=[dict(type='deck_start',**deck_plan())])
  change=dict(type='deck_plan_patch',changes=[dict(path=['pages',0,'composition','blocks',0,'body'],value='修订的草稿正文')])
  result=validate_plan(dict(reply='REVISE：去掉重复说明',actions=[change]))
  final=review_plan(self.studio,{'id':'J-sparse','payload':{}},proposal,{},'claude',lambda *a,**k:result)
  self.assertEqual(final['actions'][0]['pages'][1],proposal['actions'][0]['pages'][1])
  self.assertEqual(final['actions'][0]['pages'][0]['composition']['blocks'][0]['body'],'修订的草稿正文')
  self.assertEqual(final['actions'][0]['strategy'],proposal['actions'][0]['strategy'])
  with self.assertRaises(EngineError):_validate_task_scope(result,{})
  for path in (['pages'],['execution'],['pages',999,'title'],['pages',0,'missing'],['pages',-1,'title']):
   with self.assertRaises(EngineError):apply_plan_patch(proposal['actions'][0],dict(type='deck_plan_patch',changes=[dict(path=path,value='invalid')]))
  with self.assertRaises(EngineError):
   apply_plan_patch(proposal['actions'][0],dict(type='deck_plan_patch',changes=change['changes']*2))

 def test_split_text_preserves_full_source_independent_of_object_order(self):
  a=action();obj=a['scene']['objects'][2];full=obj.pop('text')
  obj.update(textRef='block.now.body',textRange=[0,4])
  tail={**obj,'id':'tail','textRange':[4,len(full)],'y':390}
  a['scene']['objects'].append(tail)
  resolved=prepare_scene(a)
  self.assertEqual(resolved['objects'][2]['text']+resolved['objects'][-1]['text'],full)
  self.assertEqual(prepare_scene({**a,'scene':resolved}),resolved)
  for span in ([5,len(full)],[3,len(full)],[4,len(full)+1]):
   bad=copy.deepcopy(a);bad['scene']['objects'][-1]['textRange']=span
   with self.assertRaises(EngineError):prepare_scene(bad)
  bad=copy.deepcopy(a);bad['scene']['objects'][-1]['opacity']=0
  with self.assertRaises(EngineError):prepare_scene(bad)

 def ready(self):
  self.studio.create_deck(deck_plan(),'完整用户需求')
  for _ in range(2):
   job=self.studio.next_job()['job']
   self.studio.apply_plan(job['id'],dict(reply='页',actions=[action()]))
  with self.studio.wb.atomic() as db:
   deck=self.studio._deck_row(db)
   row=db.execute('SELECT id FROM studio_jobs WHERE client_message_id=?',('deck-review:'+deck['id'],)).fetchone()
   db.execute("UPDATE studio_jobs SET status='running' WHERE id=?",(row['id'],))
   return self.studio.job(row['id'])

 def sheets(self,scenes,folder):
  folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);png=folder/'sheet.png';png.write_bytes(b'png')
  return [(0,len(scenes),png)],[dict(fontsReady=True,overflow=[]) for _ in scenes]

 def render(self,scene,folder):
  folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);png=folder/'page.png';png.write_bytes(b'png')
  return png,dict(fontsReady=True,overflow=[])

 def test_pages_finish_then_one_durable_review_completes_deck(self):
  job=self.ready()
  state=self.studio.deck_state();self.assertEqual(state['status'],'running');self.assertEqual(state['completedPages'],2)
  with patch('ppt_workbench.deck_review.contact_sheets',side_effect=self.sheets):
   run_review(self.studio,job,'claude',lambda *a,**k:dict(reply='PASS\n节奏清晰',actions=[]))
  state=self.studio.deck_state();self.assertEqual(state['status'],'complete')
  self.assertEqual(state['designReview']['status'],'reviewed')
  self.assertEqual(state['designReview']['reviewMode'],'structure-only')
  self.assertFalse(state['qualityAccepted'])

 def test_manual_edit_during_review_is_not_overwritten(self):
  job=self.ready();before=self.studio.get_scene('S001')
  def runner(*args,**kwargs):
   self.studio.change_scene('S001',before['sceneRevision'],[dict(objectId='title',properties={'text':'手动修改'})])
   return dict(reply='PASS',actions=[])
  with patch('ppt_workbench.deck_review.contact_sheets',side_effect=self.sheets):
   with self.assertRaises(EngineError):run_review(self.studio,job,'claude',runner)
  self.assertEqual(self.studio.get_scene('S001')['scene']['objects'][0]['text'],'手动修改')

 def test_pause_cancel_and_resume_review(self):
  job=self.ready();self.studio.control_deck('pause')
  with self.studio.wb._connection() as db:self.assertFalse(self.studio._job_available(db,job))
  self.studio.control_deck('resume')
  with self.studio.wb._connection() as db:self.assertTrue(self.studio._job_available(db,job))
  self.studio.control_deck('cancel');self.assertEqual(self.studio.job(job['id'])['status'],'cancelled')

 def test_targeted_repair_verified_once_and_original_words_preserved(self):
  job=self.ready();original=self.studio.get_scene('S001');calls=[]
  def runner(mode,prompt,context,**kwargs):
   kind=context['generationTask']['kind'];calls.append(kind)
   if kind=='deck_review':
    if context['reviewStage']=='initial':return dict(reply='REVISE\n两页位置过于雷同',actions=[dict(type='deck_feedback',edits=[dict(slide_id='S001',instruction='改善标题位置')])])
    return dict(reply='PASS\n已改善',actions=[])
   if context['reviewStage']=='critique-and-repair':
    return dict(reply='REVISE\n调整位置',actions=[dict(type='scene_patch',slide_id='S001',base_scene_revision=original['sceneRevision'],changes=[dict(objectId='title',properties={'x':70})])])
   return dict(reply='PASS\n清晰',actions=[])
  with patch('ppt_workbench.deck_review.contact_sheets',side_effect=self.sheets),patch('ppt_workbench.design_review.render_candidate',side_effect=self.render):
   run_review(self.studio,job,'claude',runner)
  after=self.studio.get_scene('S001')['scene']
  self.assertEqual(after['objects'][0]['x'],70)
  self.assertEqual([o['text'] for o in after['objects']],[o['text'] for o in original['scene']['objects']])
  self.assertEqual(len(calls),4);self.assertEqual(self.studio.deck_state()['designReview']['repairedPages'],['S001'])
  self.assertEqual(self.studio.deck_state()['revisionCount'],0)

 def test_review_cannot_be_claimed_or_applied_as_external_mutation(self):
  job=self.ready()
  with self.studio.wb._connection() as db:self.assertFalse(self.studio._job_available(db,job,external=True))
  with self.assertRaises(EngineError):self.studio.apply_plan(job['id'],dict(reply='绕过',actions=[]))

 def test_finally_discovered_relationship_gets_one_bounded_followup(self):
  job=self.ready();calls=[];revision=self.studio.get_scene('S001')['sceneRevision']
  def runner(mode,prompt,context,**kwargs):
   kind=context['generationTask']['kind'];calls.append(kind)
   if kind=='deck_review':
    if context['reviewStage'] in ('initial','verify'):
     return dict(reply='REVISE\n修正具体关系',actions=[dict(type='deck_feedback',edits=[dict(slide_id='S001',instruction='保留原文，修正位置')])])
    return dict(reply='PASS',actions=[])
   if context['reviewStage']=='critique-and-repair':
    x=70 if len(calls)<5 else 85
    return dict(reply='REVISE',actions=[dict(type='scene_patch',slide_id='S001',base_scene_revision=revision,changes=[dict(objectId='title',properties={'x':x})])])
   return dict(reply='PASS',actions=[])
  with patch('ppt_workbench.deck_review.contact_sheets',side_effect=self.sheets),patch('ppt_workbench.design_review.render_candidate',side_effect=self.render):
   run_review(self.studio,job,'claude',runner)
  self.assertEqual(len(calls),7)
  self.assertEqual(self.studio.get_scene('S001')['scene']['objects'][0]['x'],85)
  self.assertEqual(self.studio.deck_state()['designReview']['status'],'reviewed')

 def test_completed_review_is_stale_after_user_edit(self):
  job=self.ready()
  with patch('ppt_workbench.deck_review.contact_sheets',side_effect=self.sheets):
   run_review(self.studio,job,'claude',lambda *a,**k:dict(reply='PASS',actions=[]))
  current=self.studio.get_scene('S001')
  self.studio.change_scene('S001',current['sceneRevision'],[dict(objectId='title',properties={'x':80})])
  self.assertEqual(self.studio.deck_state()['designReview']['status'],'stale')

 def test_out_of_scope_suggestions_are_ignored_without_blocking_finished_deck(self):
  job=self.ready()
  def outside(mode,prompt,context,**k):
   self.assertIn('deckRhythmFindings',context);self.assertIn('visualStats',context['pages'][0])
   return dict(reply='REVISE',actions=[dict(type='deck_feedback',edits=[dict(slide_id='S999',instruction='改')])])
  with patch('ppt_workbench.deck_review.contact_sheets',side_effect=self.sheets):
   run_review(self.studio,job,'claude',outside)
  state=self.studio.deck_state()
  self.assertEqual(state['status'],'complete');self.assertEqual(state['designReview']['status'],'needs_attention')
  self.assertNotIn('S999',state['designReview']['repairedPages'])
  report=json.loads((self.studio.wb.project_dir('test')/'deck-reviews'/job['id']/'report.json').read_text())
  self.assertEqual(report['passes'][0]['rejectedSuggestions'],[{'reason':'out-of-scope','slideId':'S999'}])

 def test_repairs_beyond_budget_fix_first_pages_and_defer_the_rest(self):
  job=self.ready();revision=self.studio.get_scene('S001')['sceneRevision']
  folder=self.studio.wb.project_dir('test')/'deck-reviews'/job['id'];folder.mkdir(parents=True,exist_ok=True)
  (folder/'report.json').write_text(json.dumps({'modelCalls':0,'pageRepairCalls':2,'repairRounds':0}))
  def runner(mode,prompt,context,**kwargs):
   kind=context['generationTask']['kind']
   if kind=='deck_review':
    if context['reviewStage']=='initial':
     return dict(reply='REVISE\n两页都太平',actions=[dict(type='deck_feedback',edits=[dict(slide_id='S001',instruction='加大焦点'),dict(slide_id='S002',instruction='加色块')])])
    return dict(reply='NEEDS_ATTENTION\n第二页仍平淡',actions=[])
   if context['reviewStage']=='critique-and-repair':
    return dict(reply='REVISE',actions=[dict(type='scene_patch',slide_id='S001',base_scene_revision=revision,changes=[dict(objectId='title',properties={'x':70})])])
   return dict(reply='PASS',actions=[])
  with patch('ppt_workbench.deck_review.contact_sheets',side_effect=self.sheets),patch('ppt_workbench.design_review.render_candidate',side_effect=self.render):
   run_review(self.studio,job,'claude',runner)
  self.assertEqual(self.studio.get_scene('S001')['scene']['objects'][0]['x'],70)
  self.assertEqual(self.studio.get_scene('S002')['sceneRevision'],1)
  report=json.loads((folder/'report.json').read_text())
  self.assertEqual(report['deferredEdits'],[{'slideId':'S002','instruction':'加色块'}])
  self.assertEqual(self.studio.deck_state()['designReview']['repairedPages'],['S001'])

 def test_exhausted_restart_budget_does_not_call_or_apply(self):
  job=self.ready()
  folder=self.studio.wb.project_dir('test')/'deck-reviews'/job['id'];folder.mkdir(parents=True,exist_ok=True)
  (folder/'report.json').write_text(json.dumps({'modelCalls':100}))
  with patch('ppt_workbench.deck_review.contact_sheets',side_effect=self.sheets):
   with self.assertRaises(EngineError):run_review(self.studio,job,'claude',lambda *a,**k:self.fail('budget must stop call'))
  self.assertEqual(self.studio.get_scene('S001')['sceneRevision'],1)
