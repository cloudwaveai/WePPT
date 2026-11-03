import unittest

from ppt_workbench.semantic_planning import plan_page_expression
from ppt_workbench.templates import recommend_templates


class SemanticPlanningTests(unittest.TestCase):
    def test_relationships_derived_from_page_content(self):
        for content, relation in [
            ("甲方案相比乙方案成本更低", "compare"),
            ("由于交付延迟导致客户流失", "cause"),
            ("首先调研，然后试点，最后推广", "process"),
            ("客户案例证明方案有效", "evidence"),
            ("组织架构与层级", "structure"),
            ("收入趋势及指标", "data"),
        ]:
            with self.subTest(content=content):
                self.assertEqual(plan_page_expression({"takeaway": content})["relationship"], relation)
        self.assertEqual(plan_page_expression({"keyPoints": "速度快\n覆盖广\n成本低"})["relationship"], "parallel")
        self.assertEqual(plan_page_expression({"evidence": [{"id": "e1"}]})["relationship"], "evidence")
        self.assertEqual(plan_page_expression({"title": "市场概况"})["relationship"], "general")

    def test_number_of_points_selects_parallel_variant(self):
        for count, expected in [(2, "parallel-two"), (3, "parallel-three"), (4, "parallel-four")]:
            page = {"keyPoints": ["独立观点" + str(i) for i in range(count)]}
            self.assertEqual(recommend_templates("content", page=page)[0]["id"], expected)

    def test_real_assets_and_density_change_ranking(self):
        no_image = {"title": "产品演示", "assets": []}
        with_image = {"title": "产品演示", "assets": [{"reference": "screen.png"}]}
        no_ids = [x["id"] for x in recommend_templates("content", page=no_image, limit=60)]
        image_ids = [x["id"] for x in recommend_templates("content", page=with_image, limit=60)]
        self.assertLess(image_ids.index("demo"), no_ids.index("demo"))
        self.assertIsNone(plan_page_expression(text="产品演示")["assets"]["imageCount"])
        self.assertEqual(plan_page_expression(no_image)["assets"]["imageCount"], 0)
        dense = {"keyPoints": ["观点" * 100] * 3}
        self.assertEqual(plan_page_expression(dense)["content"]["density"], "high")
        self.assertNotEqual(recommend_templates("content", page=dense)[0]["id"], "parallel-three")

    def test_legacy_text_api_and_role_filter(self):
        self.assertIn("compare", [t["family"] for t in recommend_templates("content", "竞品对比", 3)])
        self.assertTrue(all("cover" in t["roles"] for t in recommend_templates("cover", "产品对比")))
        self.assertEqual(len(recommend_templates("content", "", 2)), 2)


if __name__ == "__main__":
    unittest.main()
