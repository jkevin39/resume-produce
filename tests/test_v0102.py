"""Draft display-name lifecycle and staged publication, using synthetic fixtures."""
import unittest
from copy import deepcopy
from unittest.mock import patch
from tests import test_mvp
from resume_app.storage import write_yaml

class DraftNameTest(unittest.TestCase):
    setUp = test_mvp.MVPFlowTest.setUp
    tearDown = test_mvp.MVPFlowTest.tearDown
    form = test_mvp.MVPFlowTest.form
    draft = test_mvp.MVPFlowTest.draft
    save = test_mvp.MVPFlowTest.save

    def test_name_lifecycle(self):
        identifier = self.draft()
        before = deepcopy(self.drafts[identifier]['context'].spec)
        url = f'/api/drafts/{identifier}/name'
        for invalid in [None, 42, 'a\nb']:
            self.assertEqual(self.client.post(url,json={'display_name':invalid}).status_code,400)
        name = '合成 <产品> & 简历'
        self.assertEqual(self.client.post(url,json={'display_name':' '+name+' '}).json['display_name'],name)
        self.assertIn('&lt;产品&gt;', self.client.get(f'/drafts/{identifier}').text)
        self.assertEqual(self.drafts[identifier]['context'].spec,before)
        self.assertEqual(self.drafts[identifier]['revision'],0)
        self.assertFalse((self.root/'outputs'/identifier).exists())
        self.assertEqual(self.client.post(url,json={'display_name':'   '}).json['display_name'],identifier)
        self.client.post(url,json={'display_name':name})
        self.save(identifier)
        self.assertEqual(self.store.display_name(identifier),name)
        continued=self.client.post(f'/generations/{identifier}/zh/continue').location.split('/')[-1]
        self.assertEqual(self.drafts[continued]['display_name'],'')
        self.assertEqual(self.client.post(url,json={'display_name':'x'}).status_code,410)
        self.assertIn(name.replace('<','&lt;').replace('>','&gt;').replace('& ', '&amp; '),self.client.get('/history').text)

    def test_name_write_failure_keeps_draft(self):
        identifier=self.draft()
        self.client.post(f'/api/drafts/{identifier}/name',json={'display_name':'合成名称'})
        def fail_name(path,value):
            if path.name=='display.yaml':raise OSError('synthetic name write failure')
            return write_yaml(path,value)
        with patch('resume_app.storage.write_yaml',side_effect=fail_name):
            response=self.client.post(f'/api/drafts/{identifier}/save',json={})
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.drafts[identifier]['display_name'],'合成名称')
        self.assertFalse((self.root/'outputs'/identifier).exists())
        self.assertFalse((self.root/'applications.csv').exists())
        self.save(identifier)
        self.assertEqual(self.store.display_name(identifier),'合成名称')
