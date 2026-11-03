import copy
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from ppt_workbench.core import EngineError
from ppt_workbench.rendering import validate_scene, render_html, patch_scene, export_pptx


class LineArrowTests(unittest.TestCase):
    def scene(self):
        return {'schema':'ppt-scene','schemaVersion':1,'slideId':'S001','width':1280,'height':720,
                'background':'#FFFFFF','title':'四向箭头', 'objects':[
                    {'id':name,'type':'line','x':x,'y':y,'w':w,'h':h,'stroke':'#142D50',
                     'strokeWidth':3,arrow:True}
                    for name,x,y,w,h,arrow in [('right',100,200,250,0,'endArrow'),
                        ('left',500,200,250,0,'startArrow'),('down',100,350,0,200,'endArrow'),
                        ('up',500,350,0,200,'startArrow')]]}

    def test_preview_arrows_belong_to_line_and_move_with_it(self):
        scene=validate_scene(self.scene())
        moved=patch_scene(scene,[{'objectId':'left','properties':{'x':600,'w':300}}])
        markup=render_html(moved,interactive=False)
        self.assertEqual(markup.count('data-arrow="start"'),2)
        self.assertEqual(markup.count('data-arrow="end"'),2)
        self.assertIn('left:600px;top:200px;width:300.0px',markup)
        self.assertNotIn('→',markup)
        self.assertEqual(scene['objects'][1]['x'],500)

    def test_optional_flags_preserve_legacy_scene_and_reject_bad_types(self):
        s=self.scene();s['objects'][0].pop('endArrow')
        self.assertNotIn('endArrow',validate_scene(s)['objects'][0])
        for value in [1,'true',None,[],{}]:
            s['objects'][0]['endArrow']=value
            with self.assertRaises(EngineError):validate_scene(s)

    def test_direction_survives_editable_pptx_export(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'arrows.pptx';export_pptx([self.scene()],target)
            with zipfile.ZipFile(target) as z:
                root=ET.fromstring(z.read('ppt/slides/slide1.xml'))
                ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main',
                    'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
                self.assertEqual(root.findall('.//p:pic',ns),[])
                for shape in root.findall('.//p:sp',ns):
                    name=shape.find('p:nvSpPr/p:cNvPr',ns).attrib['name']
                    if name not in {'right','left','down','up'}:continue
                    line=shape.find('p:spPr/a:ln',ns)
                    head=line.find('a:headEnd',ns).attrib['type']
                    tail=line.find('a:tailEnd',ns).attrib['type']
                    self.assertEqual((head,tail),('triangle','none') if name in {'left','up'} else ('none','triangle'))

    def test_scene_patch_allows_native_arrow_without_changing_words(self):
        s=validate_scene(self.scene());before=copy.deepcopy(s)
        revised=patch_scene(s,[{'objectId':'right','properties':{'endArrow':False,'startArrow':True}}])
        self.assertTrue(revised['objects'][0]['startArrow'])
        self.assertFalse(revised['objects'][0]['endArrow'])
        self.assertEqual(s,before)


if __name__=='__main__':unittest.main()
