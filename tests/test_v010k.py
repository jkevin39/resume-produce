"""Synthetic library write / restore and deterministic generation contracts."""
import json
import os
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from tests import test_mvp
from resume_app.storage import write_yaml, ProfileRepository
from resume_app.skill import ResumeSkill, LLMError
from resume_app.llm_validation import validate_skill_descriptions, validate_extraction


class V010kTest(unittest.TestCase):
    setUp = test_mvp.MVPFlowTest.setUp
    tearDown = test_mvp.MVPFlowTest.tearDown
    form = test_mvp.MVPFlowTest.form
    draft = test_mvp.MVPFlowTest.draft
    save = test_mvp.MVPFlowTest.save

    def preserve(self, name, response, inputs):
        folder = Path(os.environ.get('V010K_ARTIFACT_DIR', '/tmp/resume-v010k-pages')) / self._testMethodName
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (name + '.html')).write_bytes(response.data)
        (folder / (name + '-input.json')).write_text(json.dumps(inputs, ensure_ascii=False, indent=2))

    def test_edit_fact_and_links_together(self):
        response = self.client.post('/library/edit', data={'kind':'evidence','identifier':'ev_feedback_001',
            'text':'协助整理访谈资料。', 'skill_names':['SQL']}, headers={'X-Requested-With':'fetch'})
        self.assertEqual(response.status_code, 200)
        item = ProfileRepository(self.root).evidence_index()['ev_feedback_001']
        self.assertEqual(item['candidate_zh'], '协助整理访谈资料。')
        self.assertEqual(item['structured_fact'], {'action':'协助整理访谈资料。','method':'','scale':'','result':'','skills':['SQL']})
        skills = {x['name']: x for x in self.repo.skills()}
        self.assertNotIn('ev_feedback_001', skills['Python']['evidence_ids'])
        self.assertIn('ev_feedback_001', skills['SQL']['evidence_ids'])

    def test_multifile_failure_rolls_back(self):
        before = {p:p.read_bytes() for p in (self.root/'data').rglob('*.yaml')}
        original = write_yaml
        counter = 0
        def fail_second(path, value):
            nonlocal counter
            counter += 1
            if counter == 2:
                raise OSError('synthetic disk failure')
            original(path, value)
        with patch('resume_app.storage.write_yaml', side_effect=fail_second), self.assertRaises(OSError):
            self.repo.delete_library_item('evidence', 'ev_feedback_001')
        self.assertEqual({p:p.read_bytes() for p in (self.root/'data').rglob('*.yaml')}, before)
        with patch('resume_app.storage.write_yaml', side_effect=fail_second):
            counter = 0
            with self.assertRaises(OSError):
                self.repo.update_evidence_text('ev_feedback_001', '新事实', ['SQL'])
        self.assertEqual({p:p.read_bytes() for p in (self.root/'data').rglob('*.yaml')}, before)

    def test_empty_experience_and_parent_restore(self):
        evidence_trash = self.repo.delete_library_item('evidence', 'ev_rag_001')
        self.assertEqual(self.repo.experience_index()['project_001']['evidence'], [])
        exp = self.repo.experience_index()['project_001']
        with self.assertRaises(ValueError):
            validate_extraction(exp)
        self.preserve('index', self.client.get('/'), self.repo.library_snapshot())
        parent_trash = self.repo.delete_library_item('experience', 'project_001')
        with self.assertRaisesRegex(ValueError, '所属经历'):
            self.repo.trash_restore(evidence_trash)
        self.repo.trash_restore(parent_trash)
        self.repo.trash_restore(evidence_trash)
        self.assertEqual(len(self.repo.experience_index()['project_001']['evidence']), 1)

    def test_cross_delete_both_restore_orders(self):
        for skill_first in (True, False):
            with self.subTest(skill_first=skill_first):
                eid = self.repo.delete_library_item('evidence','ev_feedback_001')
                sid = self.repo.delete_library_item('skill','Python')
                with self.assertRaisesRegex(ValueError, '回收站'):
                    self.repo.add_skill('Python','用于测试','source')
                for tid in ([sid,eid] if skill_first else [eid,sid]):
                    self.repo.trash_restore(tid)
                self.assertIn('ev_feedback_001', next(x for x in self.repo.skills() if x['name']=='Python')['evidence_ids'])
                self.assertIn('Python', self.repo.evidence_index()['ev_feedback_001']['structured_fact']['skills'])
                self.assertEqual(self.repo.trash_list(), [])

    def test_whole_experience_restores_exact_skill_mapping(self):
        tid = self.repo.delete_library_item('experience','internship_001')
        self.repo.trash_restore(tid)
        skills = {x['name']:x for x in self.repo.skills()}
        self.assertEqual(skills['Python']['evidence_ids'], ['ev_feedback_001'])
        self.assertEqual(skills['SQL']['evidence_ids'], ['ev_dashboard_001'])

    def test_trash_origin_label(self):
        # v0.10.3 任务 F：回收站证据行显示来源经历；来源随后整段入站时仍能标注。
        self.client.post('/library/delete', data={'kind':'evidence','identifier':'ev_feedback_001'}, headers={'X-Requested-With':'fetch'})
        self.assertIn('来自 测试科技有限公司 · 数据产品实习生', self.client.get('/').get_data(as_text=True))
        self.client.post('/library/delete', data={'kind':'experience','identifier':'internship_001'}, headers={'X-Requested-With':'fetch'})
        self.assertIn('来自 测试科技有限公司 · 数据产品实习生', self.client.get('/').get_data(as_text=True))

    def test_new_skill_append_conflict_and_special_name(self):
        response = self.client.post('/profile/import', data={'source_text':'技能：C++\n用于课程开发。'}, headers={'X-Requested-With':'fetch'})
        self.assertEqual(response.status_code, 200)
        response = self.client.post('/profile/import', data={'source_text':'完成数据处理。','target_object':'skill:C++'}, headers={'X-Requested-With':'fetch'})
        self.assertEqual(response.status_code, 200)
        item = next(x for x in self.repo.skills() if x['name']=='C++')
        self.assertEqual(len(item['source_refs']),2)
        with self.assertRaisesRegex(ValueError,'已被修改'):
            self.repo.update_skill_description('C++','过时结果',expected='旧描述')
        tid = self.repo.delete_library_item('skill','C++')
        self.repo.trash_purge(tid)
        self.assertEqual(self.repo.trash_list(), [])

    def test_append_uses_latest_experience_and_sources(self):
        self.repo.update_experience_fields('internship_001', {'title':'更新岗位'})
        response = self.client.post('/profile/import', data={'source_text':'补充材料\n使用 SQL 汇总记录。','target_object':'exp:internship_001'})
        self.assertEqual(response.status_code,302)
        exp=self.repo.experience_index()['internship_001']
        self.assertEqual(exp['title'],'更新岗位')
        self.assertEqual(len(exp['evidence']),4)
        self.assertEqual(len(exp['source_refs']),2)

    def test_prepare_union_and_fallback_keeps_raw_report(self):
        report={'matches':[], 'gaps':[], 'keyword_coverage':[]}
        inputs=self.form()
        with patch.object(ResumeSkill,'match',return_value=report), patch.object(ResumeSkill,'generate_skill_descriptions',side_effect=LLMError('output','synthetic')):
            response=self.client.post('/prepare',data=inputs)
        self.assertEqual(response.status_code,200)
        self.preserve('prepare',response,{'form':inputs,'library':self.repo.library_snapshot(),'report':report})
        html=response.get_data(as_text=True)
        self.assertIn('value="ev_rag_001"',html)
        self.assertIn('未评估',html)
        self.assertIn('已使用履历库描述',html)
        did=self.draft(match_json=json.dumps(report))
        self.assertEqual(self.drafts[did]['match_report'],report)

    def test_descriptions_and_selected_evidence_are_deterministic(self):
        skills=self.repo.skills()
        skills[0]['evidence_ids'].append('ev_rag_001')
        write_yaml(self.root/'data/skills.yaml',{'skills':skills})
        did=self.draft(evidence_ids=['ev_feedback_001'],skill_names=['Python'],skill_desc_payload=json.dumps({'Python':'我的当次描述'}))
        generated=self.drafts[did]['context'].spec['skills']
        self.assertEqual(generated[0]['description'],'我的当次描述')
        self.assertEqual(generated[0]['evidence_ids'],['ev_feedback_001'])
        self.assertNotIn('description',self.repo.skills()[0])
        did=self.draft(skill_names=['Excel'],skill_desc_payload=json.dumps({'Excel':''}))
        self.assertEqual(self.drafts[did]['context'].spec['skills'][0]['description'], '')  # Editor normalizes missing optional text to empty.

    def test_live_skill_replacement_precedes_validation(self):
        selected=['ev_feedback_001']
        result=ResumeSkill({'llm':{'mode':'demo'}},self.repo).build_spec('zh',selected,'','',{})
        result['skills']=[{'name':'错误技能','evidence_ids':['bad']}]
        live=ResumeSkill({'llm':{'mode':'live'}},self.repo)
        with patch.object(live,'_chat_json',return_value=result):
            spec=live.build_spec('zh',selected,'','',{},['Python'],{'Python':'人工描述'})
        self.assertEqual([x['name'] for x in spec['skills']],['Python'])
        self.assertEqual(spec['skills'][0]['description'],'人工描述')

    def test_description_guard_rejects_jd_only_tools(self):
        with self.assertRaises(ValueError):
            validate_skill_descriptions({'descriptions':{'Python':'使用 Python 和 PySpark 清洗数据'}},{'Python':'使用 Python 清洗数据'})
        self.assertEqual(validate_skill_descriptions({'descriptions':{'Python':'使用 Python 清洗数据'}},{'Python':'使用 Python 清洗数据'})['Python'],'使用 Python 清洗数据')
