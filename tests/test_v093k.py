"""v0.9.3k regressions: draft-page analysis panels, no-refresh material import; synthetic workspace only."""
import io
import json
import unittest

from tests import test_mvp


class V093kTest(unittest.TestCase):
    setUp = test_mvp.MVPFlowTest.setUp
    tearDown = test_mvp.MVPFlowTest.tearDown
    form = test_mvp.MVPFlowTest.form
    draft = test_mvp.MVPFlowTest.draft
    save = test_mvp.MVPFlowTest.save
    continue_draft = test_mvp.MVPFlowTest.continue_draft

    def test_draft_editor_shows_analysis_panels(self):
        # 首次生成草稿：编辑器页含 JD 分析双卡片（默认折叠的 details）
        draft_id = self.draft()
        html = self.client.get(f'/drafts/{draft_id}').get_data(as_text=True)
        self.assertIn('id="jd-analysis-panel"', html)
        self.assertIn('JD 四类分析', html)
        self.assertIn('缺口与关键词覆盖', html)
        # 续编草稿同样显示（分析数据从快照 jd-analysis.yaml / match-report.yaml 恢复）
        self.save(draft_id)
        continued = self.continue_draft(draft_id)
        continued_html = self.client.get(f'/drafts/{continued}').get_data(as_text=True)
        self.assertIn('id="jd-analysis-panel"', continued_html)
        self.assertIn('JD 四类分析', continued_html)

    def test_draft_editor_analysis_panels_empty_fallback(self):
        # 分析数据缺失（{}）时以既有空态兜底渲染，不报错
        draft_id = self.draft(analysis_json=json.dumps({}), match_json=json.dumps({}))
        html = self.client.get(f'/drafts/{draft_id}').get_data(as_text=True)
        self.assertIn('id="jd-analysis-panel"', html)
        self.assertIn('无明确内容', html)

    def test_prepare_panels_unchanged_after_extraction(self):
        # partial 抽取后 prepare 页渲染等价（结构断言保持）
        response = self.client.post('/prepare', data={'company': '公司', 'role': '岗位', 'jd_text': test_mvp.JD})
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('JD 四类分析', html)
        self.assertIn('缺口与关键词覆盖', html)
        self.assertIn('必备条件', html)

    def test_import_fetch_mode_returns_json_fragments(self):
        response = self.client.post('/profile/import', data={'source_text': '课程项目\n使用 Python 分析 1000 条记录。'},
                                    headers={'X-Requested-With': 'fetch'})
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertTrue(result['ok'])
        # 经历片段与首页整页渲染同源（折叠块结构、证据表单、服务端分配的 ID）
        self.assertIn('data-collapsible="exp:', result['experience_html'])
        self.assertIn(result['experience_id'], result['experience_html'])
        self.assertIn('data-evidence-form', result['experience_html'])
        # 摘要片段含改名联动标记与计数
        self.assertIn('data-profile-name', result['summary_html'])
        self.assertIn('段经历', result['summary_html'])
        # 首页整页渲染与片段一致（同一 partial）
        index_html = self.client.get('/').get_data(as_text=True)
        self.assertIn(result['experience_id'], index_html)

    def test_import_fetch_mode_errors_are_json(self):
        # 空输入
        response = self.client.post('/profile/import', data={}, headers={'X-Requested-With': 'fetch'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()['ok'])
        self.assertIn('请粘贴资料或选择文件', response.get_json()['errors'][0])
        # 文件类型不允许
        response = self.client.post('/profile/import', data={'source_file': (io.BytesIO(b'x'), 'bad.exe')},
                                    content_type='multipart/form-data', headers={'X-Requested-With': 'fetch'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()['ok'])
        # 非 UTF-8 文件
        response = self.client.post('/profile/import', data={'source_file': (io.BytesIO(b'\xff\xfe\x00'), 'bad.txt')},
                                    content_type='multipart/form-data', headers={'X-Requested-With': 'fetch'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('UTF-8', response.get_json()['errors'][0])

    def test_import_form_mode_still_redirects(self):
        # 兼容路径：无 fetch 头的表单提交仍 302 回首页（现有用例行为不变）
        response = self.client.post('/profile/import', data={'source_text': '另一段经历\n使用 SQL 汇总数据。'})
        self.assertEqual(response.status_code, 302)
        # 空输入仍渲染错误页而非 JSON
        response = self.client.post('/profile/import', data={})
        self.assertEqual(response.status_code, 400)
        self.assertIn('text/html', response.content_type)


if __name__ == '__main__':
    unittest.main()
