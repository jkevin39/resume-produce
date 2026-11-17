from unittest.mock import patch
import unittest
from tests import test_v0111_fgh as fgh
from resume_app.layout_defaults import load_formats
from resume_app.llm_validation import validate_skill_name
from resume_app.storage import write_yaml, read_yaml


class V0112Test(unittest.TestCase):
    setUp = fgh.FGHTest.setUp
    tearDown = fgh.FGHTest.tearDown
    form = fgh.FGHTest.form
    draft = fgh.FGHTest.draft
    save = fgh.FGHTest.save
    continue_draft = fgh.FGHTest.continue_draft
    defaults = fgh.FGHTest.defaults

    def test_named_formats_migration_update_default_delete_history(self):
        path=self.root/'data/layout-defaults.yaml'
        write_yaml(path,self.defaults())
        initial=load_formats(path)
        self.assertEqual(initial,load_formats(path))
        self.assertEqual(len(initial['items']),1)
        legacy=initial['items'][0]['id']
        def change(**payload):return self.client.post('/api/layout-formats',json=payload)
        settings=self.defaults();settings['style']['line_height']='1.21'
        response=change(action='create',name='紧凑',settings=settings,make_default=True)
        self.assertEqual(response.status_code,200)
        new=response.json['selected_id']
        self.assertNotEqual(new,legacy)
        identifier=self.draft()
        self.assertEqual(self.drafts[identifier]['context'].spec['style']['line_height'],'1.21')
        self.save(identifier)
        before=path.read_bytes()
        self.assertEqual(change(action='create',name='紧凑',settings=settings).status_code,400)
        self.assertEqual(path.read_bytes(),before)
        with patch('resume_app.storage.write_yaml',side_effect=OSError('synthetic')):
            self.assertEqual(change(action='delete',id=new).status_code,500)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(change(action='delete',id=new).status_code,200)
        self.assertIsNone(load_formats(path)['default_id'])
        continued=self.continue_draft(identifier)
        self.assertEqual(self.drafts[continued]['context'].spec['style']['line_height'],'1.21')
        self.assertEqual(change(action='update',id=new,name='removed',settings=settings).status_code,400)

    def test_skill_labels_and_explicit_type(self):
        for name in ['Python','Microsoft Power BI','数据清洗','C++']:
            self.assertEqual(validate_skill_name(name),name)
        for name in ['负责分析报表，降低成本10%。','任期内月均运输总费用下降3%','SQL\n负责报表']:
            with self.assertRaises(ValueError):validate_skill_name(name)
        response=self.client.post('/profile/import',data={'source_text':'合成公司\n分析：使用 SQL 整理30份报表。','material_type':'project'},headers={'X-Requested-With':'fetch'})
        self.assertEqual(response.status_code,200)
        self.assertTrue(any(x['type']=='project' and x['organization']=='合成公司' for x in self.repo.experiences()))

    def test_qwen_address_survives_provider_switch(self):
        path=self.root/'config.yaml';c=read_yaml(path,{})
        url='https://synthetic.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'
        c['llm'].update(provider='qwen',model='qwen-plus',base_url=url)
        write_yaml(path,c)
        for provider,model in [('deepseek','deepseek-flash'),('qwen','qwen-plus')]:
            self.assertEqual(self.client.post('/api/model-settings',json={'provider':provider,'model':model,'thinking':False}).status_code,200)
        self.assertEqual(read_yaml(path,{})['llm']['base_url'],url)

    def test_legacy_client_cannot_erase_named_formats_and_migration_failure(self):
        path=self.root/'data/layout-defaults.yaml'
        write_yaml(path,self.defaults()); before=path.read_bytes()
        with patch('resume_app.storage.write_yaml',side_effect=OSError('synthetic')):
            self.assertEqual(self.client.get('/api/layout-formats').status_code,500)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(self.client.get('/api/layout-formats').status_code,200)
        before=path.read_bytes()
        self.assertEqual(self.client.put('/api/layout-defaults',json=self.defaults()).status_code,400)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(self.client.delete('/api/layout-defaults').status_code,200)
        self.assertEqual(len(load_formats(path)['items']),1)
        self.assertIsNone(load_formats(path)['default_id'])

    def test_explicit_skill_invalid_output_does_not_write(self):
        from resume_app.skill import ResumeSkill
        skill=ResumeSkill({'llm':{'provider':'qwen','model':'qwen-plus','mode':'live'}},self.repo)
        before=self.repo.skills()
        with patch.object(skill,'_chat_json',return_value={'kind':'experience'}):
            with self.assertRaises(ValueError):
                skill.import_new_material('SQL 查询报表','synthetic','skill')
        self.assertEqual(self.repo.skills(),before)

    def test_qwen_thinking_budget_preserves_enabled_mode(self):
        from resume_app.models import request_body
        for enabled in (False,True):
            body=request_body({'provider':'qwen','model':'qwen-plus','thinking':enabled},8192,[])
            self.assertEqual(body['enable_thinking'],enabled)
            if enabled:
                self.assertEqual(body['thinking_budget'],1024)
                self.assertNotIn('response_format',body)
            else:
                self.assertNotIn('thinking_budget',body)
                self.assertEqual(body['response_format'],{'type':'json_object'})
