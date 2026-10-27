import tempfile
import unittest

from ppt_workbench.core import EngineError
from ppt_workbench.studio import Studio
from ppt_workbench import guide_store


class GuideStoreTests(unittest.TestCase):
    def test_persists_across_reopen_without_mutating_slides_or_chat(self):
        with tempfile.TemporaryDirectory() as root:
            studio = Studio(root, 'guide', agent='manual')
            before = studio.state()
            doc = {'pages': [{'title': '业务情况', 'role': 'content', 'answers': {'evidence': '客户原始材料'}}]}
            guide_store.save(studio, 'draft', 0, doc)
            experience = {'qa': [{'question': '为何不用具体内容', 'answer': '模板需要复用', 'rule': '使用内容槽位'}],
                          'curated': [{'templateId': 'cover', 'reason': '标题层次清晰'}]}
            guide_store.save(studio, 'experience', 0, experience)
            reopened = Studio(root, 'guide', agent='manual')
            self.assertEqual(guide_store.load(reopened, 'draft')['document'], doc)
            self.assertEqual(guide_store.load(reopened, 'experience')['document'], experience)
            self.assertEqual(reopened.state()['slides'], before['slides'])
            self.assertEqual(reopened.state()['messages'], before['messages'])
            with self.assertRaises(EngineError) as error:
                guide_store.save(reopened, 'draft', 0, {})
            self.assertEqual(error.exception.code, 'STALE_REVISION')
            self.assertEqual(guide_store.load(reopened, 'draft')['document'], doc)
