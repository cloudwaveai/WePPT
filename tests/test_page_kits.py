import copy
import unittest
from ppt_workbench import page_kits
from ppt_workbench.templates import catalog, recommend_templates, sample_scene
from ppt_workbench.rendering import validate_scene
from ppt_workbench.core import EngineError
from test_studio import PNG

class PageKitTests(unittest.TestCase):
    def source(self,count=3):
        return validate_scene(dict(schema='ppt-scene',schemaVersion=1,slideId='S001',width=1280,height=720,background='#FFFFFF',notes='开发中，待核验',objects=[dict(id='title',type='text',binding='title',text='产品能力（开发中）',x=64,y=40,w=1100,h=90,fontSize=48)]+[dict(id=f'body.{i}',type='text',binding=f'keyPoints:{i}',text='能力'+str(i)+'（开发中）\n保留范围与条件。',x=64,y=160+i*min(110,480/count),w=1100,h=90,fontSize=24) for i in range(count)]))

    def test_all_styles_preserve_content_ids_bindings_notes_and_source(self):
        source=self.source();source['objects'].append(dict(id='original',type='image',src='data:image/png;base64,'+PNG,alt='原图',fit='contain',opacity=.8,x=900,y=200,w=200,h=200))
        source=validate_scene(source);snapshot=copy.deepcopy(source)
        for card in page_kits.catalog():
            with self.subTest(card=card['id']):
                out=page_kits.apply(source,card['id']);objects={o['id']:o for o in out['objects']}
                for old in source['objects']:
                    for key in ('type','text','binding','src','fit','alt','opacity'):
                        self.assertEqual(old.get(key),objects[old['id']].get(key))
                self.assertEqual(out['notes'],source['notes'])
        self.assertEqual(source,snapshot)

    def test_reapply_removes_only_unchanged_decoration(self):
        out=page_kits.apply(self.source(),'pagekit-editorial-v1')
        same=page_kits.apply(out,'pagekit-editorial-v1')
        self.assertEqual(len(out['objects']),len(same['objects']))
        shape=next(o for o in out['objects'] if page_kits._owned(o) and o['type']=='rect')
        shape.update(fill='#AA0033',x=900,y=180,w=80,h=80);old=copy.deepcopy(shape)
        changed=page_kits.apply(out,'pagekit-window-v1')
        obj=next(o for o in changed['objects'] if o['id']==old['id'])
        self.assertEqual(obj['fill'],old['fill'])
        self.assertEqual(obj['type'],old['type'])

    def test_authored_chart_composition_is_preserved(self):
        source=self.source(2);source['objects'] += [dict(id='bar.a',type='rect',x=300,y=450,w=70,h=80,fill='#223344'),dict(id='bar.b',type='rect',x=420,y=410,w=70,h=120,fill='#445566')]
        source=validate_scene(source)
        out=page_kits.apply(source,'pagekit-data-v1');byid={o['id']:o for o in out['objects']}
        a,b=byid['bar.a'],byid['bar.b']
        self.assertAlmostEqual(b['h']/a['h'],1.5)
        self.assertAlmostEqual((b['x']-a['x'])/a['w'],120/70)
        self.assertEqual(a['fill'],'#223344')
        self.assertEqual([o['text'] for o in source['objects'] if o['type']=='text'],[o['text'] for o in out['objects'] if o['type']=='text'])

    def test_capacity_refusal_is_atomic_and_edited_decoration_is_not_discarded(self):
        source=self.source(7);snapshot=copy.deepcopy(source)
        with self.assertRaises(EngineError) as err:page_kits.apply(source,'pagekit-compare-v1')
        self.assertEqual(err.exception.code,'TEMPLATE_CAPACITY');self.assertEqual(source,snapshot)

    def test_parallel_count_adapts_actual_geometry(self):
        layouts=[]
        for n in (2,3,4):
            out=page_kits.apply(self.source(n),'pagekit-compare-v1')
            bodies=[o for o in out['objects'] if o['id'].startswith('body.')]
            self.assertEqual(len(bodies),n);layouts.append(tuple((o['x'],o['y'],o['w'],o['h']) for o in bodies))
        self.assertEqual(len(set(layouts)),3)

    def test_current_defaults_cover_all_roles_and_old_ids_resolve(self):
        for role in ('cover','toc','chapter','content','ending','appendix'):
            self.assertTrue(all(c.get('current') for c in recommend_templates(role)))
        self.assertTrue(next(c for c in catalog() if c['id']=='editorial')['archived'])
        self.assertEqual(sample_scene('editorial')['templateId'],'editorial')
        for key in ('product','case','gallery'):
            sample=page_kits.sample('pagekit-'+key+'-v1')
            self.assertTrue(any(o['type']=='image' for o in sample['objects']))
