"""Synthetic v0.11.1 contracts; live language quality is a separate Gate."""
import io
import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from app import build_gap_report
from resume_app.drafts import normalize_spec
from resume_app.education_match import demo_education_matches
from resume_app.llm_validation import validate_match_report
from resume_app.skill import ResumeSkill, LLMError
from resume_app.storage import write_yaml
from tests import test_mvp


class V0111Test(unittest.TestCase):
    setUp = test_mvp.MVPFlowTest.setUp
    tearDown = test_mvp.MVPFlowTest.tearDown
    form = test_mvp.MVPFlowTest.form
    draft = test_mvp.MVPFlowTest.draft
    save = test_mvp.MVPFlowTest.save
    continue_draft = test_mvp.MVPFlowTest.continue_draft

    def skill(self, live=False):
        return ResumeSkill({'llm': {'mode': 'live' if live else 'demo'}}, self.repo)

    def test_education_multiple_records_missing_and_ambiguous(self):
        education = self.repo.profile()['education']
        check = lambda text, rows: demo_education_matches({'required': [text]}, rows)[0]
        self.assertEqual(check('本科及以上', education)['status'], 'met')
        self.assertEqual(check('硕士及以上', education)['status'], 'unmet')
        self.assertEqual(check('本科及以上', [])['status'], 'needs_confirmation')
        self.assertEqual(check('本科及以上', [{'education_id': 'unknown', 'degree': ''}])['status'], 'needs_confirmation')
        second = {**education[0], 'education_id': 'edu_two', 'degree': '硕士'}
        self.assertEqual(check('硕士及以上', education + [second])['education_ids'], ['edu_two'])
        self.assertEqual(check('本科、相关专业、应届毕业', education)['status'], 'needs_confirmation')
        self.assertEqual(demo_education_matches({'required': ['掌握 Python']}, education), [])
        english = self.skill().match(self.skill().analyze_jd("Bachelor's degree required"))
        self.assertEqual(english['education_matches'][0]['status'], 'needs_confirmation')

    def test_live_match_education_input_and_invalid_contract(self):
        base = {'matches': [], 'gaps': [], 'keyword_coverage': [], 'education_matches': []}
        live = self.skill(True)
        with patch.object(live, '_chat_json', return_value=base) as call:
            live.match({'required': ['本科及以上']})
        sent = json.loads(call.call_args.args[1])
        self.assertEqual(sent['education'], self.repo.profile()['education'])
        self.assertNotIn('profile', sent)
        item = {'requirement': '本科及以上', 'reason': '已提供本科记录', 'status': 'met', 'education_ids': ['edu_test_001']}
        good = {**base, 'education_matches': [item], 'gaps': [{'requirement': '本科及以上', 'suggestion': '重复项'}]}
        self.assertEqual(validate_match_report(deepcopy(good), set(), {'edu_test_001'})['gaps'], [])
        for changes in ({'education_ids': ['unknown']}, {'education_ids': []}, {'status': 'guessed'}, {'reason': ''}):
            with self.assertRaises(ValueError):
                validate_match_report({**base, 'education_matches': [{**item, **changes}]}, set(), {'edu_test_001'})
        with patch.object(live, '_chat_json', return_value={k: v for k, v in base.items() if k != 'education_matches'}):
            with self.assertRaises(LLMError):
                live.match({})

    def test_education_gap_saved_report_and_legacy_panels(self):
        report = self.skill().match({'required': ['硕士及以上', '计算机专业']})
        text = build_gap_report(report)
        self.assertIn('不满足', text)
        self.assertIn('待核实', text)
        self.assertNotIn('未发现明确', text)
        identifier = self.draft(match_json=json.dumps(report))
        self.assertIn('教育背景匹配', self.client.get('/drafts/' + identifier).text)
        folder = self.save(identifier)
        gap_files = list(folder.rglob('gap-report.md'))
        self.assertEqual(len(gap_files), 1)
        self.assertEqual(gap_files[0].read_text(), text)
        old = self.draft()
        self.assertIn('本轮未评估教育背景', self.client.get('/drafts/' + old).text)
        page = self.client.post('/prepare', data={'company': '测试公司', 'role': '分析岗位', 'jd_text': '硕士及以上'})
        self.assertEqual(page.status_code, 200)
        self.assertIn('不满足', page.text)
        self.assertIn('本轮未评估教育背景', build_gap_report({'gaps': []}))
        self.assertIn('未发现明确', build_gap_report({'gaps': [], 'education_matches': []}))

    def test_final_skill_descriptions_shared_with_single_generation(self):
        write_yaml(self.root / 'data/skills.yaml', {'skills': [{'name': 'Excel', 'description': '旧技能描述', 'user_confirmed': True}]})
        baseline = self.skill().build_spec('zh', [], '测试公司', '数据分析', {}, ['Excel'])
        baseline['profile']['phone'] = str(baseline['profile']['phone'])
        baseline['section_titles']['experience'] = '实习与经历'
        for override, expected in (({'Excel': '使用表格核对数据'}, '使用表格核对数据'), ({'Excel': ''}, ''), ({}, '旧技能描述'), (None, '旧技能描述')):
            live = self.skill(True)
            with patch.object(live, '_chat_json', return_value=deepcopy(baseline)) as call:
                result = live.build_spec('zh', [], '测试公司', '数据分析', {}, ['Excel'], override)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(result['section_titles']['experience'], '实习经历')
            sent = json.loads(call.call_args.args[1])
            self.assertEqual(sent['skills'][0]['description'], expected)
            self.assertNotIn('summary', sent['profile']['profile'])
            self.assertEqual(result['skills'][0]['description'], expected)
            demo = self.skill().build_spec('zh', [], '测试公司', '数据分析', {}, ['Excel'], override)
            if expected:
                self.assertIn(expected, demo['profile']['summary'])
            else:
                self.assertNotIn('旧技能描述', demo['profile']['summary'])
        with self.assertRaises(ValueError):
            self.skill().build_spec('zh', [], '', '', {}, ['Excel'], {'未知技能': ''})
        malformed = {**baseline, 'section_titles': []}
        live = self.skill(True)
        with patch.object(live, '_chat_json', return_value=malformed):
            with self.assertRaises(LLMError):
                live.build_spec('zh', [], '', '', {}, ['Excel'])

    def test_summary_refresh_save_continue_including_empty(self):
        profile_before = (self.root / 'data/profile.yaml').read_bytes()
        for summary in ('岗位简介：数据分析方向。', '我修改过的简介。', ''):
            identifier = self.draft(evidence_ids=['ev_feedback_001'])
            spec = deepcopy(self.drafts[identifier]['context'].spec)
            spec['profile']['summary'] = summary
            profile = self.repo.profile()
            profile['profile']['name'] = '已更新姓名'
            profile['profile']['summary'] = '工作台旧简介'
            profile['education'][0]['major'] = '更新后的专业'
            write_yaml(self.root / 'data/profile.yaml', profile)
            refreshed = self.client.post(f'/api/drafts/{identifier}/refresh', json={'part': 'profile', 'spec': spec})
            self.assertEqual(refreshed.status_code, 200, refreshed.text)
            self.assertEqual(refreshed.json['spec']['profile']['summary'], summary)
            self.assertEqual(refreshed.json['spec']['profile']['name'], '已更新姓名')
            self.assertEqual(refreshed.json['spec']['education'][0]['major'], '更新后的专业')
            self.save(identifier)
            continued = self.continue_draft(identifier)
            self.assertEqual(self.drafts[continued]['context'].spec['profile']['summary'], summary)
        (self.root / 'data/profile.yaml').write_bytes(profile_before)
        a = self.draft(role='数据分析', evidence_ids=[], skill_names=[])
        b = self.draft(role='产品助理', evidence_ids=[], skill_names=[])
        summaries = [self.drafts[x]['context'].spec['profile']['summary'] for x in (a, b)]
        self.assertNotEqual(*summaries)
        self.assertNotIn('Python', summaries[0])
        self.assertEqual((self.root / 'data/profile.yaml').read_bytes(), profile_before)

    def test_titles_import_generate_and_custom_title_roundtrip(self):
        text = '合成公司 分析实习生\n账单复核：完成 120 条账单核对。\n指标整理：完成 20 项指标整理。\n整理日报并汇总结果。'
        imported = self.client.post('/profile/import', data={'source_text': text}, headers={'X-Requested-With': 'fetch'})
        self.assertEqual(imported.status_code, 200, imported.text)
        items = [x for x in self.repo.experiences() if x['organization'] == '合成公司 分析实习生']
        ids = [x['evidence_id'] for x in items[0]['evidence']]
        identifier = self.draft(evidence_ids=ids, skill_names=[])
        spec = self.drafts[identifier]['context'].spec
        bullets = spec['experiences'][0]['bullets']
        self.assertEqual([x['text'] for x in bullets], text.splitlines()[1:])
        self.assertEqual(spec['section_titles']['experience'], '实习经历')
        spec = deepcopy(spec)
        spec['section_titles']['experience'] = '我的自定义标题'
        for section in spec['layout']['sections']:
            if section['kind'] == 'experience':
                section['title'] = '我的自定义标题'
        self.save(identifier, spec=spec)
        continued = self.continue_draft(identifier)
        self.assertEqual(self.drafts[continued]['context'].spec['section_titles']['experience'], '我的自定义标题')
        legacy = self.skill().build_spec('zh', [], '', '', {})
        legacy['section_titles']['experience'] = '实习与经历'
        self.assertEqual(normalize_spec(legacy)['section_titles']['experience'], '实习与经历')

    def test_ocr_common_route_retains_jd_alias_and_limits(self):
        self.app.extensions['resume_ocr'] = lambda data: '合成材料：完成 120 条数据核对。'
        for route in ('/api/ocr', '/api/jd/ocr'):
            result = self.client.post(route, data={'image': (io.BytesIO(test_mvp.PNG), 'synthetic.png')})
            self.assertEqual(result.status_code, 200)
            self.assertIn('合成材料', result.json['text'])
            self.assertEqual(self.client.post(route, data={'image': (io.BytesIO(b'invalid'), 'invalid.png')}).status_code, 400)
            oversized = self.client.post(route, data=b'x' * (8 * 1024 * 1024 + 1), content_type='application/octet-stream')
            self.assertEqual(oversized.status_code, 413)
            self.assertFalse(oversized.json['ok'])
