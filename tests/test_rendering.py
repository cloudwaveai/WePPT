import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from ppt_workbench.core import EngineError
from ppt_workbench.rendering import (
    validate_scene, render_html, scene_from_slide, patch_scene,
    export_html_deck, export_pptx,
)


class RenderingTests(unittest.TestCase):
    def setUp(self):
        self.slide = {"id": "S001", "title": "用户提供的标题", "role": "content",
                      "templateId": "compare", "takeaway": "用户拟用的主张", "keyPoints": "方案甲：完整描述\n方案乙：另一项描述"}
        self.scene = scene_from_slide(self.slide, {"title": "测试材料"})

    def assert_code(self, code, fn, *args):
        with self.assertRaises(EngineError) as caught:
            fn(*args)
        self.assertEqual(caught.exception.code, code)

    def test_supplied_content_is_preserved_and_stable_ids_are_clickable(self):
        text = "\n".join(o.get("text", "") for o in self.scene["objects"])
        for value in [self.slide["title"], self.slide["takeaway"], *self.slide["keyPoints"].splitlines()]:
            self.assertIn(value, text)
        ids = {o["id"] for o in self.scene["objects"]}
        self.assertTrue({"title", "takeaway", "body-1", "body-2"} <= ids)
        markup = render_html(self.scene)
        self.assertIn('data-object-id="body-2"', markup)
        self.assertIn("ppt-select", markup)
        self.assertIn("ppt-overflow", markup)

    def test_all_basic_roles_and_long_content_keep_user_words(self):
        for role, tid in [("cover", "cover"), ("chapter", "chapter"), ("toc", "toc"),
                          ("content", "process"), ("ending", "ending")]:
            slide = self.slide | {"role": role, "templateId": tid, "keyPoints": "一步\n二步\n三步"}
            scene = scene_from_slide(slide, {})
            words = "\n".join(o.get("text", "") for o in scene["objects"])
            for word in ["一步", "二步", "三步"]:
                self.assertIn(word, words)
        long_outline = "\n".join(f"第{i}条完整原话" for i in range(25))
        scene = scene_from_slide(self.slide | {"role": "toc", "templateId": "toc", "keyPoints": long_outline}, {})
        self.assertIn(long_outline, "\n".join(o.get("text", "") for o in scene["objects"]))

    def test_content_bindings_preserve_fields_and_grouped_comparison(self):
        for role in ["cover", "chapter", "content", "ending", "toc"]:
            page = self.slide | {"role": role, "templateId": role, "keyPoints": "正文第一行\n正文第二行"}
            scene = scene_from_slide(page, {})
            bound = {o["binding"]: o["text"] for o in scene["objects"] if "binding" in o}
            self.assertEqual(bound["title"], page["title"])
            self.assertEqual(bound["takeaway"], page["takeaway"])
            points = sorted((int(k.split(":")[1]), v) for k, v in bound.items() if k.startswith("keyPoints:"))
            self.assertEqual(scene["bindingSeparator"].join(v for _, v in points), page["keyPoints"])
        page = self.slide | {"keyPoints": "方案甲\n甲的完整说明\n\n方案乙\n乙的完整说明"}
        scene = scene_from_slide(page, {})
        self.assertEqual(scene["bindingSeparator"], "\n\n")
        self.assertEqual([o["text"] for o in scene["objects"] if o.get("binding", "").startswith("keyPoints:")],
                         ["方案甲\n甲的完整说明", "方案乙\n乙的完整说明"])
        self.assert_code("SCENE_SCOPE_VIOLATION", patch_scene, scene,
                         [{"objectId":"body-1", "properties":{"binding":"keyPoints:1"}}])

    def test_text_cannot_inject_html_or_script_or_style(self):
        malicious = '</script><img src=x onerror="alert(1)"><script>alert(2)</script>'
        scene = patch_scene(self.scene, [{"objectId": "title", "properties": {"text": malicious}}])
        markup = render_html(scene)
        self.assertNotIn(malicious, markup)
        self.assertIn("&lt;/script&gt;", markup)
        self.assertIn("&lt;img", markup)
        self.assertEqual(markup.count("<script>"), 1)
        self.assert_code("INVALID_SCENE", patch_scene, self.scene,
                         [{"objectId": "title", "properties": {"fontFamily": "Arial';background:url(x)"}}])
        self.assert_code("INVALID_SCENE", patch_scene, self.scene,
                         [{"objectId": "title", "properties": {"color": "red;position:fixed"}}])

    def test_object_patch_preserves_every_other_object_and_original_scene(self):
        before = copy.deepcopy(self.scene)
        changed = patch_scene(self.scene, [{"objectId": "title", "properties": {"text": "新标题", "fontSize": 54}}])
        self.assertEqual(self.scene, before)
        for old, new in zip(before["objects"], changed["objects"]):
            if old["id"] != "title":
                self.assertEqual(old, new)
        self.assertEqual([o for o in changed["objects"] if o["id"] == "title"][0]["text"], "新标题")
        self.assert_code("SCENE_SCOPE_VIOLATION", patch_scene, self.scene,
                         [{"objectId": "title", "properties": {"id": "different"}}])
        self.assert_code("SCENE_OBJECT_NOT_FOUND", patch_scene, self.scene,
                         [{"objectId": "unknown", "properties": {"text": "x"}}])

    def test_invalid_geometry_duplicate_ids_and_remote_images_are_rejected(self):
        self.assert_code("SCENE_OUT_OF_BOUNDS", patch_scene, self.scene,
                         [{"objectId": "title", "properties": {"x": 1200}}])
        self.assert_code("INVALID_SCENE", patch_scene, self.scene,
                         [{"objectId": "title", "properties": {"fontSize": float("nan")}}])
        dup = copy.deepcopy(self.scene)
        dup["objects"].append(copy.deepcopy(dup["objects"][0]))
        self.assert_code("INVALID_SCENE", validate_scene, dup)
        img = copy.deepcopy(self.scene)
        img["objects"].append({"id":"image", "type":"image", "x":0, "y":0, "w":100, "h":100, "src":"https://example.com/a.png"})
        self.assert_code("INVALID_SCENE_IMAGE", validate_scene, img)

    def test_html_deck_is_self_contained_and_keeps_each_page(self):
        second = scene_from_slide(self.slide | {"id": "S002", "title": "第二页"}, {})
        deck = export_html_deck([self.scene, second], "演示稿 <安全>")
        self.assertEqual(deck.count('<section class="page'), 2)
        self.assertIn("第二页", deck)
        self.assertIn("演示稿 &lt;安全&gt;", deck)
        self.assertNotIn('src="https:', deck)
        self.assertIn("ArrowRight", deck)
        self.assertIn("@media print", deck)

    def test_editable_pptx_contains_native_text_geometry_and_object_names(self):
        if not shutil.which("node"):
            self.skipTest("Node.js not installed")
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "editable.pptx"
            try:
                result = export_pptx([self.scene], target, "测试演示稿")
            except EngineError as exc:
                if exc.code == "PPTX_DEPENDENCY_MISSING":
                    self.skipTest("Install npm dependency pptxgenjs to run PPTX test")
                raise
            self.assertGreater(result["bytes"], 1000)
            self.assertTrue(result["editable"])
            with zipfile.ZipFile(target) as deck:
                self.assertIsNone(deck.testzip())
                xml = deck.read("ppt/slides/slide1.xml")
                root = ET.fromstring(xml)
                ns = {"a":"http://schemas.openxmlformats.org/drawingml/2006/main",
                      "p":"http://schemas.openxmlformats.org/presentationml/2006/main"}
                actual = [e.text for e in root.findall(".//a:t", ns)]
                self.assertIn("用户提供的标题", actual)
                self.assertIn("方案甲：完整描述", actual)
                names = [e.attrib.get("name") for e in root.findall(".//p:cNvPr", ns)]
                self.assertIn("title", names)
                self.assertIn("body-2", names)
                self.assertGreater(len(root.findall(".//p:sp", ns)), 4)
                self.assertEqual(len(root.findall(".//p:pic", ns)), 0)

    def test_image_pptx_keeps_actual_bytes_and_alt_object_id(self):
        if not shutil.which("node"):
            self.skipTest("Node.js not installed")
        import base64
        png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aM1sAAAAASUVORK5CYII="
        image_scene = copy.deepcopy(self.scene)
        image_scene["objects"].append({"id":"logo.original", "type":"image", "x":1100, "y":20, "w":50, "h":50,
                                       "src":"data:image/png;base64,"+png, "alt":"实际测试原图", "fit":"contain"})
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "image.pptx"
            try:
                export_pptx([image_scene], output)
            except EngineError as exc:
                if exc.code == "PPTX_DEPENDENCY_MISSING":
                    self.skipTest("Install npm dependency pptxgenjs to run PPTX test")
                raise
            with zipfile.ZipFile(output) as deck:
                images = [deck.read(name) for name in deck.namelist() if name.startswith("ppt/media/")]
                self.assertIn(base64.b64decode(png), images)
                slide = deck.read("ppt/slides/slide1.xml").decode()
                self.assertIn("logo.original", slide)
                self.assertIn("实际测试原图", slide)

    def test_image_pptx_contain_keeps_intrinsic_aspect_and_original_bytes(self):
        import base64, struct, zlib
        import xml.etree.ElementTree as ET
        # Real 4:2 PNG with original encoding, displayed in a square slot.
        def chunk(t,d):return struct.pack('>I',len(d))+t+d+struct.pack('>I',zlib.crc32(t+d)&0xffffffff)
        raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',4,2,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\x00'+b'\xff\x00\x00'*4)*2))+chunk(b'IEND',b'')
        scene=copy.deepcopy(self.scene)
        scene['objects'].append(dict(id='original',type='image',x=100,y=100,w=200,h=200,src='data:image/png;base64,'+base64.b64encode(raw).decode(),fit='contain'))
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'fit.pptx';export_pptx([scene],out)
            with zipfile.ZipFile(out) as z:
                self.assertIn(raw,[z.read(n) for n in z.namelist() if n.startswith('ppt/media/')])
                xml=ET.fromstring(z.read('ppt/slides/slide1.xml'))
                ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
                size=xml.find('.//p:pic/p:spPr/a:xfrm/a:ext',ns)
                self.assertAlmostEqual(int(size.get('cx'))/int(size.get('cy')),2,places=4)
                off=xml.find('.//p:pic/p:spPr/a:xfrm/a:off',ns)
                self.assertGreater(int(off.get('y')),int(off.get('x')))


if __name__ == "__main__":
    unittest.main()
