import base64
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ppt_workbench.pptx_opening import DATA_DIR, NS, OpeningImporter, REVIEWED
from ppt_workbench.rendering import validate_scene


class BundledOpeningTests(unittest.TestCase):
    def test_only_reviewed_first_three_opening_pages_are_bundled(self):
        manifest = json.loads((DATA_DIR / "manifest.json").read_text())
        self.assertEqual(len(manifest["inspectedPages"]), 15)
        expected = {(f, p, role) for f, roles in REVIEWED.items() for p, role in enumerate(roles, 1) if role != "body"}
        self.assertEqual({(t["sourceFile"], t["sourcePage"], t["role"]) for t in manifest["templates"]}, expected)
        self.assertEqual(len(expected), 7)
        for t in manifest["templates"]:
            scene = validate_scene(json.loads((DATA_DIR / t["scene"]).read_text()))
            self.assertTrue(any(o.get("binding") == "title" for o in scene["objects"]))
            self.assertTrue(any(o["type"] == "image" for o in scene["objects"]))
            self.assertTrue(any(o["type"] == "text" for o in scene["objects"]))
            for obj in scene["objects"]:
                if obj["type"] == "text" and "\n" in obj["text"]:
                    self.assertLessEqual(obj["fontSize"] * obj["lineHeight"] * len(obj["text"].split("\n")), obj["h"] + .001)
            if t["role"] == "toc":
                self.assertEqual([o["binding"] for o in scene["objects"] if o.get("binding", "").startswith("keyPoints:")],
                                 [f"keyPoints:{i}" for i in range(5)])
            by_id = {o["id"]: o for o in scene["objects"]}
            for meta in t["objects"]:
                self.assertIn(meta["objectId"], by_id)
                if "sourceAsset" in meta:
                    raw = (DATA_DIR / meta["sourceAsset"]).read_bytes()
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), meta["sourceSha256"])
                    scene_raw = (DATA_DIR / meta["sceneAsset"]).read_bytes()
                    self.assertEqual(scene_raw, base64.b64decode(by_id[meta["objectId"]]["src"].split(",")[1]))

    def test_theme_background_group_transform_and_text_insets(self):
        a, p, r = NS["a"], NS["p"], NS["r"]
        def rels(rows):
            return '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(
                f'<Relationship Id="{rid}" Type="{r}/{kind}" Target="{target}"/>' for rid, kind, target in rows) + '</Relationships>'
        slide = f'''<p:sld xmlns:p="{p}" xmlns:a="{a}"><p:cSld><p:spTree><p:grpSp><p:nvGrpSpPr><p:cNvPr id="2"/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="1000000" y="500000"/><a:ext cx="4000000" cy="2000000"/><a:chOff x="100" y="200"/><a:chExt cx="400" cy="200"/></a:xfrm></p:grpSpPr><p:sp><p:nvSpPr><p:cNvPr id="3"/></p:nvSpPr><p:spPr><a:xfrm><a:off x="200" y="250"/><a:ext cx="200" cy="100"/></a:xfrm><a:prstGeom prst="rect"/><a:solidFill><a:schemeClr val="accent1"><a:lumMod val="50000"/></a:schemeClr></a:solidFill></p:spPr><p:txBody><a:bodyPr lIns="0" rIns="0" tIns="0" bIns="0"/><a:lstStyle/><a:p><a:r><a:rPr sz="2000"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill><a:latin typeface="+mn-lt"/></a:rPr><a:t>Editable grouped title</a:t></a:r></a:p></p:txBody></p:sp></p:grpSp></p:spTree></p:cSld></p:sld>'''
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.pptx"
            with zipfile.ZipFile(source, "w") as z:
                z.writestr("ppt/presentation.xml", f'<p:presentation xmlns:p="{p}" xmlns:r="{r}"><p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst><p:sldSz cx="12800000" cy="7200000"/></p:presentation>')
                z.writestr("ppt/_rels/presentation.xml.rels", rels([("rId1", "slide", "slides/slide1.xml")]))
                z.writestr("ppt/slides/slide1.xml", slide)
                z.writestr("ppt/slides/_rels/slide1.xml.rels", rels([("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml")]))
                z.writestr("ppt/slideLayouts/slideLayout1.xml", f'<p:sldLayout xmlns:p="{p}"><p:cSld><p:spTree/></p:cSld></p:sldLayout>')
                z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", rels([("rId1", "slideMaster", "../slideMasters/slideMaster1.xml")]))
                z.writestr("ppt/slideMasters/slideMaster1.xml", f'<p:sldMaster xmlns:p="{p}" xmlns:a="{a}"><p:cSld><p:bg><p:bgPr><a:solidFill><a:schemeClr val="bg1"/></a:solidFill></p:bgPr></p:bg><p:spTree/></p:cSld><p:clrMap bg1="lt1" tx1="dk1"/></p:sldMaster>')
                z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", rels([("rId1", "theme", "../theme/theme1.xml")]))
                z.writestr("ppt/theme/theme1.xml", f'<a:theme xmlns:a="{a}"><a:themeElements><a:clrScheme><a:lt1><a:srgbClr val="F0F0F0"/></a:lt1><a:dk1><a:srgbClr val="123456"/></a:dk1><a:accent1><a:srgbClr val="4F81BD"/></a:accent1></a:clrScheme><a:fontScheme><a:minorFont><a:latin typeface="Calibri"/></a:minorFont></a:fontScheme></a:themeElements></a:theme>')
            importer = OpeningImporter(source)
            try:
                scene, meta = importer.extract(1, "cover")
                self.assertEqual(scene["background"], "#F0F0F0")
                shape, text = scene["objects"]
                self.assertEqual([shape[k] for k in ("x", "y", "w", "h")], [200, 100, 200, 100])
                self.assertEqual(shape["fill"], "#254061")
                self.assertEqual(text["fontFamily"], "Calibri")
                self.assertEqual(text["color"], "#123456")
                self.assertEqual(text["binding"], "title")
                self.assertFalse(meta["limitations"])
                with self.assertRaises(ValueError): importer.extract(4, "cover")
                with self.assertRaises(ValueError): importer.extract(1, "body")
            finally:
                importer.close()


if __name__ == "__main__":
    unittest.main()
