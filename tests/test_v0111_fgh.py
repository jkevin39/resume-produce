"""Default typography and prepare-owned order; all data are synthetic."""
import json
import unittest
from copy import deepcopy
from unittest.mock import patch
from app import create_app
from resume_app.drafts import STYLE_DEFAULTS, normalize_spec
from resume_app.ordering import catalog, validate_order, demo_order
from resume_app.skill import ResumeSkill, LLMError
from resume_app.storage import write_yaml
from resume_app.prompts import PROFILE_SUMMARY_PROMPT, BUILD_RESUME_SPEC_PROMPT
from tests import test_mvp


class FGHTest(unittest.TestCase):
    setUp = test_mvp.MVPFlowTest.setUp
    tearDown = test_mvp.MVPFlowTest.tearDown
    form = test_mvp.MVPFlowTest.form
    draft = test_mvp.MVPFlowTest.draft
    save = test_mvp.MVPFlowTest.save
    continue_draft = test_mvp.MVPFlowTest.continue_draft

    def defaults(self):
        return {'theme':'green', 'density':'compact', 'style':{**STYLE_DEFAULTS, 'line_height':'1.25', 'page_padding':'10mm 12mm', 'title_color':''}}

    def test_defaults_save_restart_clear_and_history_isolation(self):
        original = self.draft()
        self.save(original)
        settings = self.defaults()
        self.assertEqual(self.client.put('/api/layout-defaults', json=settings).status_code, 200)
        resumed = self.continue_draft(original)
        self.assertNotEqual(self.drafts[resumed]['context'].spec['theme'], 'green')
        newer = self.draft()
        self.assertEqual(self.drafts[newer]['context'].spec['style'], settings['style'])
        restarted = create_app(self.root, testing=True)
        self.assertTrue(restarted.test_client().get('/api/layout-defaults').json['saved'])
        response = restarted.test_client().post('/generate', data=self.form())
        self.assertEqual(restarted.extensions['resume_drafts'][response.location.split('/')[-1]]['context'].spec['theme'], 'green')
        self.client.delete('/api/layout-defaults')
        self.assertFalse(self.client.get('/api/layout-defaults').json['saved'])
        self.assertEqual(self.drafts[newer]['context'].spec['theme'], 'green')
        self.assertEqual(self.drafts[self.draft()]['context'].spec['theme'], 'blue')

    def test_defaults_validation_atomic_failure_and_corrupt_file(self):
        good = self.defaults()
        self.client.put('/api/layout-defaults', json=good)
        path = self.root / 'data/layout-defaults.yaml'; before = path.read_bytes()
        for bad in ({**good,'profile':{}}, {**good,'style':{**good['style'],'line_height':'bad'}}, {**good,'style':{**good['style'],'font_size':'0pt'}}, {**good,'style':{**good['style'],'page_padding':'-1mm'}}):
            self.assertEqual(self.client.put('/api/layout-defaults', json=bad).status_code, 400)
            self.assertEqual(path.read_bytes(), before)
        with patch('app.write_yaml', side_effect=OSError('synthetic')):
            self.assertEqual(self.client.put('/api/layout-defaults', json=good).status_code, 500)
        self.assertEqual(path.read_bytes(), before)
        path.write_text('style: [broken')
        self.assertIn('无法读取', self.client.get('/api/layout-defaults').json['message'])
        self.assertEqual(self.drafts[self.draft()]['context'].spec['theme'], 'blue')
        self.assertEqual(self.client.delete('/api/layout-defaults').status_code, 200)

    def test_order_validation_stable_completion_and_exclusion(self):
        allowed = catalog(self.repo.experiences(), self.repo.skills())
        self.assertEqual(validate_order({}, allowed), allowed)
        for bad in ([], {'other':[]}, {'experience':['project_001']}, {'skills':['Python','Python']}, {'skills':['unknown']}):
            with self.assertRaises(ValueError): validate_order(bad, allowed)
        order = {**allowed,'skills':['Excel','SQL','Python']}
        identifier = self.draft(evidence_ids=['ev_feedback_001'], skill_names=['Python','Excel'], display_order=json.dumps(order), skill_desc_payload=json.dumps({'Python':'', 'Excel':'当次描述'}))
        spec = self.drafts[identifier]['context'].spec
        self.assertEqual([x['name'] for x in spec['skills']], ['Excel','Python'])
        self.assertEqual([x['description'] for x in spec['skills']], ['当次描述',''])
        self.save(identifier)
        continued = self.continue_draft(identifier)
        self.assertEqual([x['name'] for x in self.drafts[continued]['context'].spec['skills']], ['Excel','Python'])

    def test_prepare_order_beats_model_and_layout(self):
        experience = deepcopy(self.repo.experiences()[0])
        experience['experience_id'] = 'internship_second'
        for item in experience['evidence']: item['evidence_id'] += '_second'
        write_yaml(self.root/'data/experiences/second.yaml',experience)
        ids = ['ev_feedback_001','ev_feedback_001_second']
        demo = ResumeSkill({'llm':{'mode':'demo'}},self.repo)
        value = demo.build_spec('zh',ids,'合成公司','分析',{},['Python','Excel'])
        value['profile']['phone'] = str(value['profile']['phone'])
        value = normalize_spec(value)
        order = {'experience':['internship_second','internship_001'],'project':[], 'skills':['Excel','Python']}
        live = ResumeSkill({'llm':{'mode':'live'}},self.repo)
        with patch.object(live,'_chat_json',return_value=value) as call:
            spec = normalize_spec(live.build_spec('zh',ids,'合成公司','分析',{},['Python','Excel'],{'Python':'','Excel':'已确认描述'},order))
        self.assertEqual(call.call_count,1)
        self.assertEqual([x['experience_id'] for x in spec['experiences']],order['experience'])
        self.assertEqual([x['name'] for x in spec['skills']],order['skills'])
        section = next(x for x in spec['layout']['sections'] if x['kind']=='experience')
        self.assertEqual([x['canvas_id'] for x in section['items']],[x['canvas_id'] for x in spec['experiences']])
        sent = json.loads(call.call_args.args[1])
        self.assertEqual(sent['display_order']['skills'],['Excel','Python'])
        self.assertNotIn('SQL',sent['display_order']['skills'])

    def test_matching_order_contract_and_demo_relevance(self):
        demo = ResumeSkill({'llm':{'mode':'demo'}},self.repo)
        sql = demo.match({'technical_keywords':['SQL']})
        python = demo.match({'technical_keywords':['Python']})
        self.assertEqual(sql['display_order']['skills'][0],'SQL')
        self.assertEqual(python['display_order']['skills'][0],'Python')
        live = ResumeSkill({'llm':{'mode':'live'}},self.repo)
        with patch.object(live,'_chat_json',return_value=sql) as call:
            live.match({'technical_keywords':['SQL']})
        sent = json.loads(call.call_args.args[1])
        self.assertTrue(all(x.get('experience_id') for x in sent['evidence']))
        with patch.object(live,'_chat_json',return_value={**sql,'display_order':{'skills':['missing']}}):
            with self.assertRaises(LLMError): live.match({})
        page = self.client.post('/prepare',data={'company':'合成公司','role':'分析','jd_text':'SQL'}).text
        self.assertIn('已按本地规则推荐排序',page)
        self.assertIn('生成草稿将沿用当前顺序',page)

    def test_summary_template_is_shared_once_and_sparse_data(self):
        self.assertEqual(BUILD_RESUME_SPEC_PROMPT.count(PROFILE_SUMMARY_PROMPT),1)
        # Final-input behavior and sparse evidence are exercised rather than exact prose.
        skill = ResumeSkill({'llm':{'mode':'demo'}},self.repo)
        spec = skill.build_spec('zh',[],'合成公司','数据分析',{},[],{}, {'skills':[]})
        self.assertNotIn('Python',spec['profile']['summary'])
        self.assertNotIn('[',spec['profile']['summary'])
