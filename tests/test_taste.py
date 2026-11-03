"""Cross-project taste aggregation and recommendation ranking."""
import json
import tempfile
import unittest

from ppt_workbench.studio import Studio
from ppt_workbench.taste import taste_profile
from ppt_workbench.templates import recommend_templates


class TasteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_empty(self):
        s = Studio(self.temp.name, "t1")
        profile = taste_profile(s)
        self.assertEqual(profile["signals"], 0)
        self.assertIsNone(profile["summary"])

    def test_aggregation_across_projects(self):
        a = Studio(self.temp.name, "a")
        a.set_palette({"primary": "#1F4E9E", "secondary": ["#2BB3C0"]})
        a.demo()
        b = Studio(self.temp.name, "b")
        b.demo()
        with b.wb.atomic() as db:
            db.execute("INSERT INTO studio_template_preferences VALUES ('b','claim-proof')")
        before = taste_profile(b)["signals"]
        with b.wb.atomic() as db:
            db.execute("INSERT INTO studio_template_preferences VALUES ('ghost','no-such-template')")
        profile = taste_profile(b)
        self.assertEqual(profile["signals"], before)
        self.assertGreaterEqual(profile["signals"], 2)
        self.assertIn("features", profile)

    def test_bonus_reorders_but_never_crosses_roles(self):
        taste = {"features": {"browseCategory": {"cover": 1.0}}, "signals": 10}
        ranked = recommend_templates("cover", taste=taste, limit=50)
        self.assertTrue(all("cover" in t["roles"] for t in ranked))
        self.assertTrue(any(t.get("tasteMatch") for t in ranked))
        self.assertIn("；接近你常用的风格",
                      "".join(t["recommendationReason"] for t in ranked))
        content = recommend_templates("ending", taste=taste, limit=10)
        self.assertTrue(all("ending" in t["roles"] for t in content))

    def test_context_and_recommendations_threshold(self):
        s = Studio(self.temp.name, "a")
        self.assertIsNone(s.context({"scope": "deck"})["userTasteProfile"])
        s.set_palette({"primary": "#1F4E9E", "secondary": ["#2BB3C0"]})
        with s.wb.atomic() as db:
            db.execute("INSERT INTO studio_template_preferences VALUES ('a','claim-proof')")
            db.execute("INSERT INTO studio_template_preferences VALUES ('x','compare')")
        s.demo()
        profile = taste_profile(s)
        self.assertGreaterEqual(profile["signals"], 3)
        rec = s.template_recommendations(s.state()["slides"][0]["id"])
        self.assertIsNotNone(rec["tasteSummary"])
        ctx = s.context({"scope": "deck"})
        self.assertIn("审美参考", ctx["userTasteProfile"]["instruction"])


if __name__ == "__main__":
    unittest.main()
