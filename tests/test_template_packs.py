import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ppt_workbench import template_packs as packs
from ppt_workbench.studio import Studio
from ppt_workbench.core import EngineError
from ppt_workbench.page_design import prepare_scene
from ppt_workbench.outline import validate_deck_plan
from test_deck_design import STRATEGY


def page(role='content', relationship='parallel', count=3, body='完整正文和适用边界。'):
    return {'title':'内容与设计适配','role':role,'user_intent':'保留全部内容',
            'composition':{'purpose':'展示适配规则','relationship':relationship,
                           'blocks':[{'id':f'b{i}','heading':f'能力 {i+1}','body':body} for i in range(count)]}}


class TemplatePacksTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.studio=Studio(self.tmp.name,'test',agent='manual')
    def test_role_routing_and_family_consistency(self):
        for pid in packs._catalog():
            for role,master in [('cover','cover'),('chapter','chapter'),('content','body-columns'),('ending','ending')]:
                p=page(role,count=1 if role!='content' else 3)
                scene,evidence=packs.compile_page(p,pid)
                self.assertEqual(scene['templateId'],pid+':'+master)
                self.assertEqual(prepare_scene(dict(type='slide_add',scene=scene,**p))['title'],p['title'])
                self.assertTrue(evidence['sources']);self.assertEqual(len(evidence['packSHA256']),64)
    def test_long_columns_fall_back_losslessly_to_wide_rows(self):
        p=page(count=4,body='这是原稿给出的完整说明，需要逐项保留对象、适用范围和所有限定条件，不能为填进模板而删掉。'*2+'保留全部适用条件。')
        scene,e=packs.compile_page(p)
        self.assertEqual(e['masterId'],'body-rows');self.assertTrue(e['adaptation'])
        self.assertEqual([o['text'] for o in scene['objects'] if o['id'].endswith('.body')],[b['body'] for b in p['composition']['blocks']])
    def test_repeated_status_and_anchors_preserved(self):
        p=page(count=2)
        for b in p['composition']['blocks']:b.update(kicker='开发中',metric='3',body='尚未实测，不承诺效果。')
        scene,_=packs.compile_page(p)
        text='\n'.join(o['text'] for o in scene['objects'] if o['type']=='text')
        self.assertEqual(text.count('开发中'),2);self.assertEqual(text.count('尚未实测'),2)
    def test_process_has_ordered_connector_channel(self):
        p=page(relationship='process',count=4)
        scene,e=packs.compile_page(p)
        self.assertEqual(e['masterId'],'body-process')
        self.assertEqual(sum(o.get('endArrow',False) for o in scene['objects']),3)
    def test_capacity_fails_without_mutating_input(self):
        p=page(count=6,body='完整内容不应丢失。'*200);original=copy.deepcopy(p)
        with self.assertRaises(EngineError) as e:packs.compile_page(p)
        self.assertEqual(e.exception.code,'TEMPLATE_CAPACITY');self.assertEqual(p,original)
    def test_true_image_no_reference_photo_no_blank_placeholder(self):
        from test_diagram_design import PNG
        raw=PNG;src='data:image/png;base64,'+base64.b64encode(raw).decode()
        p=page(count=1)
        scene,e=packs.compile_page(p,images=[src])
        self.assertEqual(e['masterId'],'body-photo')
        self.assertEqual([o['src'] for o in scene['objects'] if o['type']=='image'],[src])
        self.assertEqual(next(o['fit'] for o in scene['objects'] if o['type']=='image'),'contain')
        plain,_=packs.compile_page(p)
        self.assertFalse(any(o['type']=='image' for o in plain['objects']))
    def test_select_revision_and_whole_deck_preference(self):
        rev=self.studio.state()['projectRevision']
        packs.select(self.studio,'forest-editorial-v1',rev)
        plan={'title':'示例','execution':'agent','strategy':copy.deepcopy(STRATEGY),'pages':[
            dict(page('cover',count=1),template_id='forest-editorial-v1:cover'),
            dict(page(),template_id='forest-editorial-v1:body-columns')]}
        self.studio.create_deck(plan,'原始内容')
        with self.studio.wb._connection() as db:stored=json.loads(self.studio._deck_row(db)['plan'])
        self.assertTrue(all(p['template_id'].startswith('forest-editorial-v1:') for p in stored['pages']))
        with self.assertRaises(EngineError):packs.select(self.studio,'crimson-grid-v1',rev)
    def test_template_pages_compile_locally_without_runner(self):
        packs.select(self.studio,packs.DEFAULT,self.studio.state()['projectRevision'])
        self.studio.create_deck({'title':'两页','pages':[
            dict(page('cover',count=1),template_id=packs.DEFAULT+':cover'),
            dict(page(),template_id=packs.DEFAULT+':body-columns')]},'历史绑定任务')
        with patch('ppt_workbench.agent_bridge.run_turn',side_effect=AssertionError('no page model call')), \
             patch('ppt_workbench.design_review.render_candidate',return_value=(Path('/unused'),{'overflow':[],'imageFailures':[],'fontsReady':True})):
            self.assertTrue(self.studio.run_pending());self.assertTrue(self.studio.run_pending())
        self.assertEqual(len(self.studio.state()['slides']),2)
        self.assertEqual(self.studio.deck_state()['status'],'complete')
    def test_attachment_must_belong_to_project(self):
        packs.select(self.studio,packs.DEFAULT,self.studio.state()['projectRevision'])
        p=page();p['template_images']=['A-not-owned'];p['template_id']=packs.DEFAULT+':body-columns'
        with self.assertRaises(EngineError) as e:self.studio.create_deck({'title':'两页','pages':[p,page()]},'源内容')
        self.assertEqual(e.exception.code,'ASSET_NOT_FOUND')
        self.assertIsNone(self.studio.deck_state())
    def test_image_schema_rejects_non_ids(self):
        p=page();p['template_images']=[{'id':'bad'}]
        with self.assertRaises(EngineError):validate_deck_plan({'title':'两页','execution':'agent','pages':[p,page()]})

    def test_default_contract_routes_families_and_keeps_old_workflow(self):
        proposal={'reply':'ok','actions':[{'type':'deck_start','title':'整稿','execution':'agent','pages':[page('cover',count=1),page(relationship='process')]}]}
        self.assertEqual(packs.default_plan(proposal,{}),proposal)
        routed=packs.default_plan(proposal,{'templateContract':packs.contract(self.studio),'creationContract':'content-led-v1'})
        self.assertEqual(routed['actions'][0]['pages'][1]['template_id'],packs.DEFAULT+':body-process')
        self.assertNotIn('template_id',proposal['actions'][0]['pages'][1])

    def test_template_change_and_external_redraw_rejected(self):
        packs.select(self.studio,packs.DEFAULT,self.studio.state()['projectRevision'])
        self.studio.create_deck({'title':'两页','pages':[
            dict(page('cover',count=1),template_id=packs.DEFAULT+':cover'),
            dict(page(),template_id=packs.DEFAULT+':body-columns')]},'历史绑定任务')
        with self.studio.wb._connection() as db:
            row=db.execute('SELECT id,payload FROM studio_jobs WHERE project_id=? ORDER BY created_at',(self.studio.project_id,)).fetchone()
        payload=json.loads(row['payload'])
        with patch('ppt_workbench.design_review.render_candidate',return_value=(Path('/unused'),{'overflow':[],'imageFailures':[],'fontsReady':True})):
            plan=packs.page_job(self.studio,payload)
        plan['actions'][0]['scene']['objects'][-1]['x']+=1
        with self.assertRaises(EngineError) as e:self.studio.apply_plan(row['id'],plan)
        self.assertEqual(e.exception.code,'TEMPLATE_LAYOUT_CHANGED')
        self.assertFalse(self.studio.state()['slides'])
        with self.studio.wb.atomic() as db:db.execute("UPDATE studio_pack_bindings SET sha256='changed'")
        with self.assertRaises(EngineError) as e:packs.page_job(self.studio,payload)
        self.assertEqual(e.exception.code,'TEMPLATE_PACK_CHANGED')

    def test_template_copy_preserves_source_notes_image_occurrences_and_owner(self):
        from ppt_workbench import owners
        from ppt_workbench.derived import derive
        from test_diagram_design import PNG
        token=owners.set_current(owners.new_token());self.addCleanup(owners.reset,token)
        owners.claim_project(self.studio.wb,self.studio.project_id)
        self.studio.demo();self.studio.set_agent_mode('codex')
        current=self.studio.get_scene('S002');scene=current['scene'];scene['notes']='原始讲者备注'
        src='data:image/png;base64,'+base64.b64encode(PNG).decode()
        for i in range(2):scene['objects'].append(dict(id=f'photo{i}',type='image',x=60+200*i,y=560,w=120,h=80,src=src,fit='contain'))
        self.studio.put_scene('S002',current['contentRevision'],scene)
        before=self.studio.wb.get_project(self.studio.project_id)
        result=derive(self.studio,'template',style_id='blue-editorial-v1',source_revision=before['revision'])
        target=Studio(self.tmp.name,result['projectId'])
        self.assertEqual(owners.project_owner(target.wb,target.project_id),owners.current())
        self.assertEqual(packs.selected(target),'blue-editorial-v1')
        folder=target.wb.project_dir(target.project_id)
        images=json.loads((folder/'template-source-images.json').read_text())
        self.assertEqual(len(images[1]),2);self.assertEqual(images[1][0],images[1][1])
        self.assertEqual((folder/target.asset(images[1][0])['path']).read_bytes(),PNG)
        self.assertEqual(json.loads((folder/'restyle-source.json').read_text())[1]['notes'],'原始讲者备注')
        self.assertEqual(self.studio.wb.get_project(self.studio.project_id),before)

    def test_layers_and_hub_use_relational_variants(self):
        for rel in ('layers','hub'):
            scene,e=packs.compile_page(page(relationship=rel))
            self.assertEqual(e['masterId'],'body-'+rel)
            if rel=='hub':self.assertTrue(any(o['id']=='hub.root' for o in scene['objects']))
            else:self.assertEqual(sum(o['id'].endswith('.layer') for o in scene['objects']),3)

    def test_spatial_gallery_contract_and_legacy_preference(self):
        cards=packs.cards(self.studio)
        self.assertEqual(len(cards['packs']),4)
        self.assertTrue(all(p['spatialMethod'] for p in cards['packs']))
        self.assertEqual({p['id'] for p in packs.contract(self.studio)['packs']},{p['id'] for p in cards['packs']})
        packs.select(self.studio,'forest-editorial-v1',self.studio.state()['projectRevision'])
        self.assertEqual(packs.cards(self.studio)['selectedPack'],'forest-editorial-v1')
        self.assertEqual(len(packs.cards(self.studio)['packs']),5)

    def test_spatial_dense_reflow_and_relational_content_preserved(self):
        for pid,pack in packs._catalog().items():
            if not pack.get('spatialMethod'):continue
            for rel in ('parallel','process','layers','hub'):
                p=page(relationship=rel,count=4)
                for b in p['composition']['blocks']:b.update(kicker='开发中',metric='3',body='尚未实测，不承诺效果。')
                scene,e=packs.compile_page(p,pid)
                prepare_scene(dict(type='slide_add',scene=scene,**p))
                text='\n'.join(o['text'] for o in scene['objects'] if o['type']=='text')
                self.assertEqual(text.count('开发中'),4,(pid,rel))
                self.assertEqual(text.count('尚未实测'),4,(pid,rel))
                self.assertEqual(e['packId'],pid)
                if rel=='parallel':self.assertFalse(any(o['id'].startswith('hub.') for o in scene['objects']))
            dense=page(count=4,body='这是原稿给出的完整说明，需要逐项保留对象、适用范围和所有限定条件，不能为填进模板而删掉。'*2+'保留全部适用条件。')
            scene,e=packs.compile_page(dense,pid)
            self.assertIn(e['masterId'],('body-columns','body-rows'),pid)
            self.assertEqual([o['text'] for o in scene['objects'] if o['id'].endswith('.body')],[b['body'] for b in dense['composition']['blocks']])
            self.assertTrue(all(o['fontSize']>=24 for o in scene['objects'] if o['type']=='text'))

    def test_spatial_renderer_version_guard(self):
        from ppt_workbench import spatial_templates
        pack=packs.get(packs.DEFAULT);pack['rendererSHA256']='changed'
        with self.assertRaises(EngineError) as e:spatial_templates.render(page(),pack,'body-columns')
        self.assertEqual(e.exception.code,'TEMPLATE_PACK_CHANGED')

if __name__=='__main__':unittest.main()
