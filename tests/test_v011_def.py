"""Synthetic snapshot trash lifecycle, failure recovery and ID migration."""
import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_mvp
from resume_app.storage import GenerationStore
from resume_app.local import initialize

class SnapshotTrashTest(unittest.TestCase):
    setUp=test_mvp.MVPFlowTest.setUp
    tearDown=test_mvp.MVPFlowTest.tearDown
    form=test_mvp.MVPFlowTest.form
    draft=test_mvp.MVPFlowTest.draft
    save=test_mvp.MVPFlowTest.save

    def test_lifecycle_routes_and_child(self):
        identifier=self.draft(); folder=self.save(identifier)
        self.store.rename(identifier,'合成父版本')
        child=self.client.post(f'/generations/{identifier}/zh/continue').location.rsplit('/',1)[-1]
        before={p.relative_to(folder):p.read_bytes() for p in folder.rglob('*') if p.is_file()}
        csv=self.store.csv_path.read_bytes()
        self.store.trash_action(identifier,'move')
        self.assertEqual(self.store.list(),[])
        self.assertEqual(GenerationStore(self.root).trash_list()[0]['generation_id'],identifier)
        for method,url in [('get',f'/generations/{identifier}/zh'),('get',f'/generations/{identifier}/zh/snapshot'),('post',f'/generations/{identifier}/zh/continue'),('post',f'/api/generations/{identifier}/name')]:
            self.assertEqual(getattr(self.client,method)(url).status_code,410,url)
        with self.assertRaises(ValueError):self.store.load(identifier,'zh')
        self.store.trash_action(identifier,'restore')
        self.assertEqual(before,{p.relative_to(folder):p.read_bytes() for p in folder.rglob('*') if p.is_file()})
        self.assertEqual(self.store.csv_path.read_bytes(),csv)
        self.store.trash_action(identifier,'move');self.store.trash_action(identifier,'purge')
        self.assertEqual(self.client.get(f'/generations/{identifier}/zh').status_code,404)
        self.assertIn('已删除',self.client.get(f'/drafts/{child}').text)
        self.save(child)
        self.assertEqual(self.store.load(child,'zh')[2]['parent_generation_id'],identifier)

    def test_partial_purge_retry(self):
        identifier=self.draft();self.save(identifier);self.store.trash_action(identifier,'move')
        def fail(folder):
            (folder/'metadata.yaml').unlink()
            raise OSError('synthetic partial deletion')
        with patch('resume_app.storage.shutil.rmtree',side_effect=fail):
            response=self.client.post(f'/api/generations/{identifier}/trash/purge')
        self.assertEqual(response.status_code,400)
        self.assertTrue(self.store.trash_list()[0]['pending'])
        with self.assertRaises(ValueError):self.store.trash_action(identifier,'restore')
        self.store.trash_action(identifier,'purge')
        self.assertEqual(self.store.trash_list(),[])

    def test_record_failure_preserves_files(self):
        identifier=self.draft();folder=self.save(identifier);self.store.trash_action(identifier,'move')
        with patch('resume_app.storage.os.fsync',side_effect=OSError('synthetic disk error')):
            with self.assertRaises(OSError):self.store.trash_action(identifier,'purge')
        self.assertTrue((folder/'metadata.yaml').exists())
        self.store.trash_action(identifier,'purge')
        self.assertFalse(folder.exists())

    def test_no_reuse_after_csv_removal_and_migration(self):
        identifier=self.draft();self.save(identifier)
        with self.assertRaises(ValueError):self.store.trash_action(identifier,'purge')
        self.store.trash_action(identifier,'move');self.store.trash_action(identifier,'purge')
        self.store.csv_path.unlink()
        self.assertGreater(GenerationStore(self.root).new_id(),identifier)
        destination=self.root/'migrated'
        # initialize forbids nesting under source; sibling temporary directory instead.
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            destination=Path(temp)/'migrated'
            initialize(destination,self.root)
            self.assertGreater(GenerationStore(destination).new_id(),identifier)
