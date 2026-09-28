"""v0.9 regressions use only the synthetic workspace."""
import json
import os
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from app import create_app
from resume_app.evidence_view import group_evidence
from resume_app.storage import GenerationStore, read_yaml, write_yaml
from tests import test_mvp


class V09Test(unittest.TestCase):
    setUp = test_mvp.MVPFlowTest.setUp
    tearDown = test_mvp.MVPFlowTest.tearDown
    form = test_mvp.MVPFlowTest.form
    draft = test_mvp.MVPFlowTest.draft
    save = test_mvp.MVPFlowTest.save
    continue_draft = test_mvp.MVPFlowTest.continue_draft

    def preserve(self, name, response, inputs=None):
        output = os.environ.get('V09_ARTIFACT_DIR')
        if output:
            folder = Path(output) / self._testMethodName
            folder.mkdir(parents=True, exist_ok=True)
            (folder / (name + '.html')).write_bytes(response.data)
            if inputs is not None:
                (folder / (name + '-input.json')).write_text(json.dumps(inputs, ensure_ascii=False, indent=2))
        return response.get_data(as_text=True)

    def test_grouping_preserves_unique_candidates_and_default_selection(self):
        experiences = self.repo.experiences()
        duplicate = deepcopy(experiences[0])
        duplicate['experience_id'] = 'same-name-other-id'
        duplicate['evidence'] = [deepcopy(duplicate['evidence'][0])]
        duplicate['evidence'][0]['evidence_id'] = 'unique-other-evidence'
        experiences.append(duplicate)
        matches = [dict(evidence_id=e['evidence_id'], category='strong' if i % 2 else 'partial',
                        reason='合成匹配原因', priority=10-i)
                   for i, e in enumerate(e for x in experiences for e in x['evidence'])]
        skills = self.repo.skills() + [dict(name='共享能力', evidence_ids=['ev_feedback_001'])]
        grouped = group_evidence(matches, experiences, skills)
        leaves = [b for s in grouped for entry in s['entries'] for b in entry['bullets']]
        self.assertCountEqual([b['evidence']['evidence_id'] for b in leaves], [m['evidence_id'] for m in matches])
        self.assertEqual(len(leaves), len(matches))
        self.assertEqual(sum(len(s['entries']) for s in grouped), len(experiences))
        self.assertEqual(next(b for b in leaves if b['evidence']['evidence_id']=='ev_feedback_001')['skills'], ['Python', '共享能力'])
        with patch.object(type(self.repo), 'experiences', return_value=experiences), patch.object(type(self.repo), 'skills', return_value=skills), patch('resume_app.skill.ResumeSkill.match', return_value={'matches':matches,'gaps':[],'keyword_coverage':[]}):
            response = self.client.post('/prepare', data=self.form())
        self.assertEqual(response.status_code, 200)
        html = self.preserve('prepare', response, {'experiences':experiences,'matches':matches,'skills':skills})
        self.assertEqual(html.count('name="evidence_ids"'), len(matches))
        self.assertEqual(html.count('name="evidence_ids"'), len(matches))
        self.assertIn('class="skill-selection"', html)
        self.assertIn('Excel', html)
        self.assertNotIn('教育摘要', html)

    def test_empty_grouping_and_rejected_not_selectable(self):
        self.assertEqual(group_evidence([], self.repo.experiences(), self.repo.skills()), [])
        self.repo.set_evidence_status('ev_feedback_001', 'rejected')
        report={'matches':[dict(evidence_id='ev_feedback_001',priority=1,category='strong',reason='合成')], 'gaps':[], 'keyword_coverage':[]}
        with patch('resume_app.skill.ResumeSkill.match', return_value=report):
            response=self.client.post('/prepare', data=self.form())
        html=self.preserve('rejected',response,report)
        self.assertIn('value="ev_feedback_001" disabled',html)
        self.assertNotIn('value="ev_feedback_001" checked',html)
        self.assertEqual(self.client.post('/generate',data=self.form()).status_code,400)

    def test_status_json_persistence_and_write_failure(self):
        url='/evidence/ev_feedback_001/status'
        self.assertEqual(self.client.post(url,json={'status':'needs_details'}).json, {'ok':True,'status':'needs_details'})
        self.assertEqual(self.repo.evidence_index()['ev_feedback_001']['status'],'needs_details')
        before=(self.root/'data/experiences/internship.yaml').read_bytes()
        with patch('resume_app.storage.os.replace',side_effect=OSError('synthetic failure')):
            self.assertEqual(self.client.post(url,json={'status':'rejected'}).status_code,400)
        self.assertEqual((self.root/'data/experiences/internship.yaml').read_bytes(),before)
        self.assertEqual(self.client.post(url,json={'status':'invalid'}).status_code,400)
        self.assertEqual(self.client.post('/evidence/missing/status',json={'status':'confirmed'}).status_code,400)

    def test_rename_legacy_persistence_escaping_and_immutable_content(self):
        identifier=self.draft();folder=self.save(identifier)
        files={p.relative_to(folder):p.read_bytes() for p in folder.rglob('*') if p.is_file()}
        csv_before=self.store.csv_path.read_bytes()
        self.assertEqual(self.store.display_name(identifier),identifier)
        self.preserve('legacy-history',self.client.get(f'/generations/{identifier}/zh'))
        name='数据分析 <精简> & 版本'
        url=f'/api/generations/{identifier}/name'
        self.assertEqual(self.client.post(url,json={'display_name':name}).json['display_name'],name)
        new_app=create_app(self.root,testing=True)
        self.assertEqual(new_app.extensions['resume_store'].list()[0]['display_name'],name)
        html=self.preserve('renamed-history',new_app.test_client().get(f'/generations/{identifier}/zh'))
        self.assertIn('数据分析 &lt;精简&gt; &amp; 版本',html)
        self.preserve('renamed-index',new_app.test_client().get('/'))
        for relative,content in files.items():self.assertEqual((folder/relative).read_bytes(),content)
        self.assertEqual(self.store.csv_path.read_bytes(),csv_before)
        second=self.continue_draft(identifier);self.save(second)
        self.assertEqual(self.store.display_name(second),second)
        self.assertEqual(read_yaml(self.root/'outputs'/second/'metadata.yaml',{})['parent_generation_id'],identifier)
        self.store.rename(second,name)
        self.assertEqual(self.store.display_name(second),self.store.display_name(identifier))
        self.assertEqual(self.client.post(url,json={'display_name':'  '}).json['display_name'],identifier)

    def test_rename_invalid_missing_and_atomic_failure(self):
        identifier=self.draft();self.save(identifier)
        self.store.rename(identifier,'原名称')
        url=f'/api/generations/{identifier}/name'
        for name in (None, [], '多行\n名称'):
            self.assertEqual(self.client.post(url,json={'display_name':name}).status_code,400)
        self.assertEqual(self.client.post('/api/generations/gen-20000101-999/name',json={'display_name':'新名'}).status_code,404)
        with patch('resume_app.storage.os.replace',side_effect=OSError('synthetic failure')):
            self.assertEqual(self.client.post(url,json={'display_name':'新名称'}).status_code,400)
        self.assertEqual(GenerationStore(self.root).display_name(identifier),'原名称')

    def test_skill_selection_demo_empty_and_manual_save(self):
        identifier=self.draft(skill_names=[])
        spec=deepcopy(self.drafts[identifier]['context'].spec)
        self.assertEqual(spec['skills'],[])
        spec['skills']=[{'name':'人工新增技能','description':'人工说明','evidence_ids':[]}]
        spec.pop('layout',None)
        self.save(identifier,spec=spec)
        child=self.continue_draft(identifier)
        self.assertEqual(self.drafts[child]['context'].spec['skills'][0]['name'],'人工新增技能')
        selected=self.draft(skill_names=['Excel'])
        self.assertEqual([s['name'] for s in self.drafts[selected]['context'].spec['skills']],['Excel'])

    def test_skill_selection_rechecks_sources_and_unknown_names(self):
        for changes in ({'skill_names':['不存在']}, {'skill_names':['SQL'],'evidence_ids':['ev_feedback_001']}):
            response=self.client.post('/generate',data=self.form(**changes))
            self.assertEqual(response.status_code,400)
            self.preserve('unavailable-'+str(len(changes)),response)
        self.repo.set_evidence_status('ev_dashboard_001','rejected')
        response=self.client.post('/generate',data=self.form(skill_names=['SQL'],evidence_ids=['ev_feedback_001']))
        self.assertEqual(response.status_code,400)
        self.assertEqual(len(self.drafts),0)
        self.draft(skill_names=['Excel'],evidence_ids=[])

    def test_live_skills_whitelist_input_and_rejected_output(self):
        from resume_app.skill import ResumeSkill, LLMError
        demo=ResumeSkill({'llm':{'mode':'demo'}},self.repo)
        live=ResumeSkill({'llm':{'mode':'live'}},self.repo)
        selected=['ev_feedback_001','ev_dashboard_001']
        result=demo.build_spec('zh',selected,'合成公司','数据岗',{},selected_skill_names=['Python'])
        result['profile']['phone']=str(result['profile']['phone'])
        with patch.object(live,'_chat_json',return_value=result) as chat:
            value=live.build_spec('zh',selected,'合成公司','数据岗',{},selected_skill_names=['Python'])
            payload=json.loads(chat.call_args.args[1])
            self.assertEqual([s['name'] for s in payload['skills']],['Python'])
            self.assertEqual([s['name'] for s in value['skills']],['Python'])
        with patch.object(live,'_chat_json',return_value=result):
            with self.assertRaises(LLMError):live.build_spec('zh',selected,'合成公司','数据岗',{},selected_skill_names=[])
        invalid=deepcopy(result);invalid['skills'][0]['evidence_ids']=['ev_dashboard_001']
        with patch.object(live,'_chat_json',return_value=invalid):
            with self.assertRaises(LLMError):live.build_spec('zh',selected,'合成公司','数据岗',{},selected_skill_names=['Python'])
        empty=deepcopy(result);empty['skills']=[]
        with patch.object(live,'_chat_json',return_value=empty) as chat:
            self.assertEqual(live.build_spec('zh',selected,'合成公司','数据岗',{},selected_skill_names=[])['skills'],[])
            self.assertEqual(json.loads(chat.call_args.args[1])['skills'],[])

    def test_home_skill_bullets_and_prepare_skill_sources(self):
        response=self.client.get('/')
        html=self.preserve('home-skills',response,{'skills':self.repo.skills()})
        self.assertIn('id="library-skills"',html)
        response=self.client.post('/prepare',data=self.form(jd_text='Python 数据分析'))
        html=self.preserve('prepare-skills',response,{'skills':self.repo.skills()})
        self.assertIn('name="skill_names" value="Python"',html)
        self.assertIn('name="skill_names" value="Excel"',html)
        self.assertIn('data-confirmed="true"',html)
