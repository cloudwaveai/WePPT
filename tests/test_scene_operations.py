import copy
import unittest

from ppt_workbench.core import EngineError
from ppt_workbench.rendering import edit_scene_objects, render_html, validate_scene, MAX_OBJECTS


class SceneOperationsTest(unittest.TestCase):
    def setUp(self):
        self.scene = validate_scene({
            "schema": "ppt-scene", "schemaVersion": 1, "slideId": "S001",
            "objects": [
                {"id": "title", "type": "text", "x": 0, "y": 0, "w": 200, "h": 50,
                 "text": "Title", "binding": "title"},
                {"id": "box", "type": "rect", "x": 0, "y": 60, "w": 100, "h": 100},
            ],
        })

    def assert_code(self, code, operations, scene=None):
        original = copy.deepcopy(self.scene if scene is None else scene)
        source = self.scene if scene is None else scene
        with self.assertRaises(EngineError) as error:
            edit_scene_objects(source, operations)
        self.assertEqual(error.exception.code, code)
        self.assertEqual(source, original)

    def test_add_reorder_delete_and_render_order(self):
        original = copy.deepcopy(self.scene)
        obj = {"id": "new", "type": "text", "x": 10, "y": 10, "w": 100, "h": 30, "text": "Hello"}
        result = edit_scene_objects(self.scene, [
            {"op": "add", "object": obj, "index": 1},
            {"op": "reorder", "objectId": "title", "index": 2},
            {"op": "delete", "objectId": "box"},
        ])
        self.assertEqual([o["id"] for o in result["objects"]], ["new", "title"])
        self.assertEqual(result["objects"][1], original["objects"][0])
        self.assertEqual(self.scene, original)
        self.assertNotIn("fontSize", obj)
        markup = render_html(result)
        self.assertLess(markup.index('data-object-id="new"'), markup.index('data-object-id="title"'))

    def test_scope_and_atomicity(self):
        self.assert_code("SCENE_SCOPE_VIOLATION", [{"op": "delete", "objectId": "title"}])
        self.assert_code("SCENE_SCOPE_VIOLATION", [{"op": "add", "object": {"binding": "title"}}])
        self.assert_code("SCENE_OBJECT_NOT_FOUND", [
            {"op": "delete", "objectId": "box"}, {"op": "delete", "objectId": "missing"}])
        self.assert_code("INVALID_SCENE", [{"op": "delete", "objectId": "box"},
                                           {"op": "delete", "objectId": "title"}],
                         scene={**self.scene, "objects": [{"id": "box", "type": "rect", "x": 0, "y": 0, "w": 2, "h": 2},
                                                         {"id": "title", "type": "text", "x": 0, "y": 0, "w": 2, "h": 2}]})

    def test_validation_and_operation_shape(self):
        duplicate = copy.deepcopy(self.scene["objects"][1])
        self.assert_code("INVALID_SCENE", [{"op": "add", "object": duplicate}])
        self.assert_code("SCENE_OUT_OF_BOUNDS", [{"op": "add", "object":
            {"id": "bad", "type": "rect", "x": 1279, "y": 0, "w": 10, "h": 10}}])
        self.assert_code("INVALID_SCENE_IMAGE", [{"op": "add", "object":
            {"id": "img", "type": "image", "x": 0, "y": 0, "w": 10, "h": 10, "src": "https://example.com/x"}}])
        for op in [{"op": "reorder", "objectId": "box", "index": True},
                   {"op": "reorder", "objectId": "box", "index": 2},
                   {"op": "delete", "objectId": "box", "extra": 1}, {"op": []}]:
            self.assert_code("INVALID_SCENE_OPERATION", [op])
        full = copy.deepcopy(self.scene)
        full["objects"] = [dict(self.scene["objects"][1], id=f"box{i}") for i in range(MAX_OBJECTS)]
        self.assert_code("INVALID_SCENE", [{"op": "add", "object":
            {"id": "extra", "type": "rect", "x": 0, "y": 0, "w": 1, "h": 1}}], scene=full)


if __name__ == "__main__":
    unittest.main()
