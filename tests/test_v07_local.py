from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

import requests
from app import create_app
from resume_app.local import check_configuration, initialize, load_key, open_in_chrome, single_instance
from resume_app.rendering import ResumeRenderer
from resume_app.skill import ResumeSkill
from resume_app.storage import ProfileRepository, read_yaml, write_yaml
from tests.support import PROJECT, FIXTURES
from tests.test_mvp import PNG, JD


class LocalUseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='resume-v07-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.data = self.base / 'daily'
        initialize(self.data)
        shutil.copytree(FIXTURES / 'data', self.data / 'data', dirs_exist_ok=True)
        self.configure('demo')

    def configure(self, mode, port=5000):
        cfg = read_yaml(self.data / 'config.yaml', {})
        cfg['llm']['mode'] = mode
        cfg['app']['port'] = port
        write_yaml(self.data / 'config.yaml', cfg)

    def app(self, resource=PROJECT):
        return create_app(resource, data_root=self.data, testing=True)

    def generate(self, client):
        result = client.post('/generate', data={
            'company':'合成公司', 'role':'数据分析', 'jd_text':JD,
            'analysis_json':json.dumps({'technical_keywords':['Python','SQL']}),
            'match_json':json.dumps({'matches':[], 'gaps':[], 'keyword_coverage':[]}),
            'evidence_ids':['ev_feedback_001'],
        })
        self.assertEqual(result.status_code, 302, result.get_data(as_text=True))
        return result.location.split('/')[-1]

    def test_separate_resources_photo_restart_restore_and_no_key(self):
        application = self.app()
        repo = application.extensions['resume_repository']
        repo.save_photo('test.png', PNG)
        client = application.test_client()
        identifier = self.generate(client)
        drafts = application.extensions['resume_drafts']
        drafts[identifier]['context'].spec['show_photo'] = True
        drafts[identifier]['context'].photo_data_url = ResumeRenderer(repo).photo_data_url()
        self.assertTrue(drafts[identifier]['context'].photo_data_url.startswith('data:image/png'))
        self.assertEqual(client.post(f'/api/drafts/{identifier}/save', json={}).status_code, 200)
        html = (self.data / 'outputs' / identifier / 'zh/resume.html').read_bytes()
        self.assertIn(b'data:image/png', html)
        self.assertFalse((self.data / 'templates').exists())
        self.configure('live')
        # A new checkout supplies only resources; all history remains in daily data.
        resources = self.base / 'other-checkout'
        for name in ('templates','static'):
            shutil.copytree(PROJECT / name, resources / name)
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY':''}), patch('resume_app.skill.requests.post') as post:
            restarted = self.app(resources).test_client()
            self.assertEqual(restarted.get('/').status_code, 200)
            self.assertEqual(restarted.get(f'/generations/{identifier}/zh/snapshot').data, html)
            self.assertEqual(restarted.get(f'/drafts/{identifier}').status_code, 410)
            resumed = restarted.post(f'/generations/{identifier}/zh/continue')
            self.assertEqual(resumed.status_code, 302)
            new_id = resumed.location.split('/')[-1]
            self.assertEqual(restarted.post(f'/api/drafts/{new_id}/export', json={}).status_code, 200)
            self.assertEqual(restarted.post(f'/api/drafts/{new_id}/save', json={}).status_code, 200)
            self.assertEqual(restarted.post('/prepare', data={'company':'合成公司','role':'岗位','jd_text':'Python'}).status_code, 502)
            post.assert_not_called()
        restored = self.base / 'restored'
        initialize(restored, self.data)  # stopped-server backup/restore model
        self.assertEqual((restored/'applications.csv').read_bytes(), (self.data/'applications.csv').read_bytes())
        restored_client = create_app(PROJECT, data_root=restored, testing=True).test_client()
        self.assertEqual(restored_client.get(f'/generations/{identifier}/zh/snapshot').data, html)
        self.assertEqual(restored_client.post(f'/generations/{identifier}/zh/continue').status_code, 302)
        self.assertEqual(read_yaml(restored/'outputs'/identifier/'metadata.yaml', {})['jd_text'], JD)

    def test_initialize_refuses_existing_and_preserves_source(self):
        original = (self.data/'data/profile.yaml').read_bytes()
        with self.assertRaisesRegex(ValueError, '目标已存在'):
            initialize(self.data)
        self.assertEqual((self.data/'data/profile.yaml').read_bytes(), original)
        cfg = read_yaml(self.data/'config.yaml', {})
        cfg['llm']['api_key'] = 'synthetic-secret'
        write_yaml(self.data/'config.yaml',cfg)
        destination = self.base/'copy'
        initialize(destination,self.data)
        self.assertNotIn('api_key', read_yaml(destination/'config.yaml', {})['llm'])
        self.assertEqual((self.data/'data/profile.yaml').read_bytes(), original)
        with self.assertRaisesRegex(ValueError,'之外'):
            initialize(self.data/'nested',self.data)

    def test_configuration_rejects_nonlocal_invalid_mode_and_bad_port(self):
        original = read_yaml(self.data/'config.yaml', {})
        for section, name, value in [('app','host','0.0.0.0'),('app','debug',True),('app','port','auto'),('llm','mode','broken'),('llm','timeout_seconds',0)]:
            cfg = json.loads(json.dumps(original)); cfg[section][name] = value
            write_yaml(self.data/'config.yaml',cfg)
            with self.assertRaises(ValueError): check_configuration(self.data)
        with self.assertRaisesRegex(ValueError, '尚未初始化'):
            check_configuration(self.base/'missing')

    def test_same_data_lock_rejects_other_process_and_releases(self):
        code = 'from pathlib import Path; from resume_app.local import single_instance; import sys\nwith single_instance(Path(sys.argv[1])): pass'
        with single_instance(self.data):
            p = subprocess.run([sys.executable,'-c',code,str(self.data)],cwd=PROJECT,capture_output=True)
            self.assertNotEqual(p.returncode,0)
            self.assertIn('已有服务',p.stderr.decode())
        with single_instance(self.data): pass

    def test_key_boundary_environment_missing_and_denied(self):
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY':'synthetic-key'}), patch('resume_app.keychain.read_key') as read:
            self.assertTrue(load_key());read.assert_not_called()
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY':''}), patch('resume_app.keychain.read_key',return_value=None):
            self.assertFalse(load_key())
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY':''}), patch('resume_app.keychain.read_key',side_effect=RuntimeError('denied')):
            self.assertFalse(load_key())
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY':''}), patch('resume_app.keychain.read_key',return_value='synthetic-key'):
            self.assertTrue(load_key()); self.assertEqual(os.environ['DEEPSEEK_API_KEY'],'synthetic-key')

    def test_waitress_slow_failure_preserves_draft_and_accepts_retry(self):
        from waitress import create_server
        application=self.app();client=application.test_client();identifier=self.generate(client)
        # Switch only the model configuration by recreating app in live mode;
        # create the draft from an existing saved snapshot with no model call.
        client.post(f'/api/drafts/{identifier}/save',json={})
        self.configure('live');application=self.app()
        client=application.test_client();draft=client.post(f'/generations/{identifier}/zh/continue').location.split('/')[-1]
        server=create_server(application,host='127.0.0.1',port=0,threads=4,channel_timeout=1,cleanup_interval=1)
        halt=threading.Event()
        def run_loop():
            while not halt.is_set():
                server.asyncore.loop(timeout=.1,map=server._map,count=1)
        thread=threading.Thread(target=run_loop,daemon=True);thread.start()
        url=f'http://127.0.0.1:{server.effective_port}'
        session=requests.Session();session.trust_env=False
        analysis={'required':['掌握 Python'],'preferred':[],'responsibilities':['分析数据'],'technical_keywords':['Python'],'inferred_preferences':[]}
        match={'matches':[],'gaps':[],'keyword_coverage':[],'education_matches':[]}
        entered=threading.Event()
        def slow_fail(*args,**kwargs):
            entered.set();time.sleep(2.2);raise requests.Timeout()
        def response(value):
            obj=Mock(status_code=200);obj.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]};return obj
        try:
            with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'synthetic-key'}),patch('resume_app.skill.requests.post',side_effect=slow_fail):
                result=[]
                worker=threading.Thread(target=lambda:result.append(session.post(url+'/prepare',data={'company':'公司','role':'岗位','jd_text':'Python'},timeout=8)))
                worker.start();self.assertTrue(entered.wait(3))
                self.assertEqual(session.get(url+f'/drafts/{draft}',timeout=3).status_code,200)
                worker.join(8);self.assertFalse(worker.is_alive());self.assertEqual(result[0].status_code,502)
            with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'synthetic-key'}),patch('resume_app.skill.requests.post',side_effect=[response(analysis),response(match),response({"descriptions":{"Excel":""}})]) as post:
                self.assertEqual(session.post(url+'/prepare',data={'company':'公司','role':'岗位','jd_text':'Python'},timeout=4).status_code,200)
                self.assertEqual(post.call_count,3)
            self.assertIn(draft,application.extensions['resume_drafts'])
        finally:
            session.close();halt.set();thread.join(3);server.close();server.task_dispatcher.shutdown()

    def test_launcher_ready_repeat_port_conflict_and_restart(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        self.configure('demo',port)
        launch_code="import sys; from resume_app import local; local.open_in_chrome=lambda url: print('BROWSER_READY '+url, flush=True) or True; raise SystemExit(local.main(sys.argv[1:]))"
        command=[sys.executable,'-c',launch_code,'start','--data-dir',str(self.data),'--no-keychain']
        session=requests.Session();session.trust_env=False
        def start():
            process=subprocess.Popen(command,cwd=PROJECT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            for _ in range(60):
                if process.poll() is not None: self.fail(process.stdout.read())
                try:
                    if session.get(f'http://127.0.0.1:{port}/_local/ready',timeout=.2).status_code==200:return process
                except requests.RequestException: pass
                time.sleep(.1)
            process.terminate();process.wait();self.fail('launcher not ready')
        process=start()
        try:
            reused=subprocess.run(command+['--reuse'],cwd=PROJECT,capture_output=True,text=True,timeout=8)
            self.assertEqual(reused.returncode,0);self.assertIn('已打开现有服务',reused.stdout)
            self.assertIsNone(process.poll())
            second=subprocess.run(command,cwd=PROJECT,capture_output=True,text=True,timeout=8)
            self.assertEqual(second.returncode,1);self.assertIn('已有服务',second.stderr)
        finally:
            process.terminate();output=process.communicate(timeout=10)[0];self.assertIn('服务已停止',output);self.assertIn(f'BROWSER_READY http://127.0.0.1:{port}',output)
        process=start();process.terminate();process.communicate(timeout=10)
        # An unrelated wildcard responder must not prevent a valid loopback bind.
        original_command = command
        command = [sys.executable, '-c',
            "import sys; from resume_app import local; "
            "local.existing_service=lambda *args: (_ for _ in ()).throw(ValueError('synthetic wildcard listener')); "
            "local.open_in_chrome=lambda url: True; raise SystemExit(local.main(sys.argv[1:]))",
            'start', '--reuse', '--data-dir', str(self.data), '--no-keychain', '--no-browser']
        process=start()
        process.terminate();process.communicate(timeout=10)
        command=original_command
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1',0));occupied.listen();self.configure('demo',occupied.getsockname()[1])
            conflict=subprocess.run(command,cwd=PROJECT,capture_output=True,text=True,timeout=8)
            self.assertEqual(conflict.returncode,1);self.assertIn('不会自动换端口',conflict.stderr)
        session.close()

    def test_browser_opener_uses_google_chrome(self):
        with patch('resume_app.local.subprocess.run') as run:
            run.return_value.returncode = 0
            self.assertTrue(open_in_chrome('http://127.0.0.1:5000'))
            run.assert_called_once_with(
                ['open', '-a', 'Google Chrome', 'http://127.0.0.1:5000'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


if __name__=='__main__':unittest.main()
