"""v0.9.2k regressions: read-only /history list page, synthetic workspace only."""
import unittest

from tests import test_mvp


class V092kTest(unittest.TestCase):
    setUp = test_mvp.MVPFlowTest.setUp
    tearDown = test_mvp.MVPFlowTest.tearDown
    form = test_mvp.MVPFlowTest.form
    draft = test_mvp.MVPFlowTest.draft
    save = test_mvp.MVPFlowTest.save

    def test_history_list_page_renders_generations_and_filter(self):
        generation_id = self.draft()
        self.save(generation_id)
        response = self.client.get('/history')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="history-filter"', html)
        self.assertIn(generation_id, html)
        self.assertIn('历史记录 · 简历生成 Agent', html)
        # 列表行带有筛选用的数据文本（名称 + 公司 + 岗位）
        self.assertIn('data-filter-text', html)
        # 首页不再含历史区块，导航指向 /history
        index_html = self.client.get('/').get_data(as_text=True)
        self.assertNotIn('id="history"', index_html)
        self.assertIn('/history', index_html)
        # 快照详情页的返回入口指向历史列表
        detail = self.client.get(f'/generations/{generation_id}/zh').get_data(as_text=True)
        self.assertIn('返回历史记录', detail)

    def test_prepare_experience_selection_badge(self):
        # 经历折叠块摘要渲染“已选 N”标识：每段经历一枚，默认勾选由服务端计入
        response = self.client.post('/prepare', data=self.form())
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertEqual(html.count('data-selection-badge'), html.count('data-experience-id='))
        self.assertIn('selection-badge.js', html)
        # JD 含 Python/SQL，demo 匹配至少一段经历有默认勾选（strong/partial）
        self.assertIn('evidence-experience has-selection', html)
        self.assertRegex(html, r'已选 [1-9]')


if __name__ == '__main__':
    unittest.main()
