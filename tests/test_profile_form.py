"""Basic profile editing uses isolated synthetic data and no model requests."""
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from app import create_app
from resume_app.storage import write_yaml
from tests.support import copy_test_workspace


class ProfileFormTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        copy_test_workspace(self.root)
        write_yaml(self.root / 'config.yaml', {'llm': {'mode': 'demo'}})
        self.app = create_app(self.root, testing=True)
        self.client = self.app.test_client()
        self.repo = self.app.extensions['resume_repository']

    def payload(self):
        value = self.repo.profile()
        return {
            'profile': {key: value['profile'].get(key, '') for key in ('name', 'phone', 'email', 'location', 'summary')},
            'education': [dict(original_index=index, **{key: item.get(key, '') for key in ('school', 'degree', 'major', 'date', 'details')}) for index, item in enumerate(value['education'])],
        }

    def test_save_without_key_preserves_extras_and_survives_restart(self):
        value = self.repo.profile()
        value['profile'].update(photo_path='sources/profile/photo.png', website='https://example.com')
        value['education'][0]['honors'] = ['合成奖项']
        value['custom'] = {'note': '保留'}
        write_yaml(self.repo.data / 'profile.yaml', value)
        payload = self.payload()
        payload['profile'].update(name=' 合成新姓名 ', location='杭州、上海', phone='13900000000', email='new@example.com')
        payload['education'][0]['major'] = '计算机'
        write_yaml(self.root / 'config.yaml', {'llm': {'mode': 'live'}})
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': ''}), patch('requests.post', side_effect=AssertionError('must not call model')):
            client = create_app(self.root, testing=True).test_client()
            response = client.post('/api/profile', json=payload)
        self.assertEqual(response.status_code, 200)
        saved = response.json['profile']
        self.assertEqual(saved['profile']['name'], '合成新姓名')
        self.assertEqual(saved['profile']['photo_path'], value['profile']['photo_path'])
        self.assertEqual(saved['profile']['website'], value['profile']['website'])
        self.assertEqual(saved['custom'], value['custom'])
        self.assertEqual(saved['education'][0]['honors'], ['合成奖项'])
        self.assertEqual(saved['education'][0]['education_id'], 'edu_test_001')
        restarted = create_app(self.root, testing=True)
        self.assertEqual(restarted.extensions['resume_repository'].profile(), saved)
        page = restarted.test_client().get('/').get_data(as_text=True)
        self.assertIn('我的基本信息', page)
        self.assertIn('合成新姓名', page)

    def test_add_delete_education_and_assign_legacy_ids(self):
        value = self.repo.profile()
        del value['education'][0]['education_id']
        write_yaml(self.repo.data / 'profile.yaml', value)
        payload = self.payload()
        blank = dict.fromkeys(('school', 'degree', 'major', 'date', 'details'), '')
        payload['education'].extend([dict(blank, school='合成研究院', degree='硕士'), blank])
        saved = self.client.post('/api/profile', json=payload).json['profile']
        self.assertEqual(len(saved['education']), 2)
        ids = [item['education_id'] for item in saved['education']]
        self.assertEqual(len(set(ids)), 2)
        payload = self.payload()
        payload['education'].pop(0)
        saved = self.client.post('/api/profile', json=payload).json['profile']
        self.assertEqual(saved['education'][0]['education_id'], ids[1])
        payload['education'] = []
        self.assertEqual(self.client.post('/api/profile', json=payload).json['profile']['education'], [])

    def test_bad_input_and_disk_failure_leave_original_intact(self):
        path = self.repo.data / 'profile.yaml'
        original = path.read_bytes()
        bad = [None, {}, {'profile': {}, 'education': []}]
        for field, value in [('education', {}), ('education', [None]), ('profile', {'name': 123})]:
            payload = self.payload()
            payload[field] = value
            bad.append(payload)
        for index in (-1, 42, True, '0'):
            payload = self.payload()
            payload['education'][0]['original_index'] = index
            bad.append(payload)
        payload = self.payload()
        payload['education'] *= 2
        bad.append(payload)
        for payload in bad:
            with self.subTest(payload=payload):
                response = self.client.post('/api/profile', data=json.dumps(payload), content_type='application/json')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(path.read_bytes(), original)
        with patch('resume_app.storage.os.replace', side_effect=OSError('synthetic failure')):
            response = self.client.post('/api/profile', json=self.payload())
        self.assertEqual(response.status_code, 500)
        self.assertIn('保存失败', response.json['errors'][0])
        self.assertEqual(path.read_bytes(), original)

    def test_new_resume_uses_profile_without_changing_drafts_or_history(self):
        form = {'company': '合成公司', 'role': '数据实习生', 'jd_text': 'Python SQL',
                'analysis_json': '{}', 'match_json': '{}', 'evidence_ids': ['ev_feedback_001']}
        def generate():
            response = self.client.post('/generate', data=form)
            self.assertEqual(response.status_code, 302)
            return response.location.rsplit('/', 1)[-1]
        old = generate()
        drafts = self.app.extensions['resume_drafts']
        original_spec = deepcopy(drafts[old]['context'].spec)
        historical = generate()
        self.assertEqual(self.client.post(f'/api/drafts/{historical}/save', json={}).status_code, 200)
        folder = self.root / 'outputs' / historical
        files = {path: path.read_bytes() for path in folder.rglob('*') if path.is_file()}
        payload = self.payload()
        payload['profile'].update(name='更新合成姓名', location='杭州', email='updated@example.com', phone='13900000000')
        payload['education'][0].update(school='合成新大学', degree='硕士')
        self.assertEqual(self.client.post('/api/profile', json=payload).status_code, 200)
        new = generate()
        self.assertEqual(drafts[new]['context'].spec['profile']['name'], '更新合成姓名')
        self.assertEqual(drafts[new]['context'].spec['education'][0]['school'], '合成新大学')
        self.assertEqual(drafts[old]['context'].spec, original_spec)
        self.assertEqual({path: path.read_bytes() for path in files}, files)
        response = self.client.post(f'/api/drafts/{old}/refresh', json={'part': 'profile'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(drafts[old]['context'].spec['profile']['name'], '更新合成姓名')
