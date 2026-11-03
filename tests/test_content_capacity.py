import copy
import unittest
from ppt_workbench.content_capacity import page_capacity, plan_capacity


class ContentCapacityTests(unittest.TestCase):
    def page(self, bodies):
        return {'composition': {'blocks': [dict(id=str(i), heading='步骤', body=body)
                                           for i, body in enumerate(bodies)]}}

    def test_long_five_step_explanations_warn_without_changing_content(self):
        page = self.page(['这是需要保留的完整说明。' * 8] * 5)
        before = copy.deepcopy(page)
        result = page_capacity(page)
        self.assertTrue(result['equalColumnScenario']['narrowColumnPressure'])
        self.assertEqual(page, before)
        self.assertEqual(result['groups'][0]['bodyCharacters'], len(page['composition']['blocks'][0]['body']))

    def test_short_nodes_and_wide_explanations_do_not_force_new_layout(self):
        for page in (self.page(['输入', '分析', '组织', '生成', '检查']), self.page(['完整说明' * 20] * 2)):
            self.assertFalse(page_capacity(page)['equalColumnScenario']['narrowColumnPressure'])

    def test_empty_and_explicit_lines_are_supported(self):
        self.assertEqual(page_capacity({})['blockCount'], 0)
        result = plan_capacity({'pages': [self.page(['甲\n乙\n丙']), self.page([''])]})
        self.assertEqual(result[0]['groups'][0]['estimatedBodyLinesIfEqualColumns'], 3)
        self.assertEqual(result[1]['groups'][0]['estimatedBodyLinesIfEqualColumns'], 0)


if __name__ == '__main__':
    unittest.main()
