import json
import unittest
from copy import deepcopy
from unittest.mock import patch
from resume_app.canvas import apply_layout, refresh_education
from resume_app.drafts import normalize_spec
from resume_app.llm_validation import validate_generated_spec
from tests import test_mvp


class CanvasTest(unittest.TestCase):
    def test_legacy_initialization_and_authoritative_order(self):
        spec = normalize_spec({'section_order': ['experience'], 'experiences': [
            {'organization': '先', 'bullets': [{'text': '一'}, {'text': '二'}]}, {'organization': '后'}]})
        self.assertEqual(normalize_spec(spec), spec)
        self.assertEqual([s['hidden'] for s in spec['layout']['sections']], [False, True, True, True])
        spec['section_order'] = ['skills']
        spec['layout']['sections'][0]['items'].reverse()
        spec['layout']['sections'][0]['items'][1]['bullets'].reverse()
        result = normalize_spec(spec)
        self.assertEqual(result['section_order'], ['experience'])
        self.assertEqual([x['organization'] for x in result['experiences']], ['后', '先'])
        self.assertEqual([b['text'] for b in result['experiences'][1]['bullets']], ['二', '一'])

    def test_invalid_layout_and_types_are_rejected_without_repair(self):
        base = normalize_spec({'experiences': [{'bullets': [{'text': '合成'}]}]})
        mutations = [lambda s: s['experiences'][0].pop('canvas_id'),
                     lambda s: s['experiences'][0]['bullets'][0].update(canvas_id=s['experiences'][0]['canvas_id']),
                     lambda s: s['layout']['sections'][1]['items'][0]['bullets'].append('missing'),
                     lambda s: s.update(profile=[]), lambda s: s.update(show_photo='true'),
                     lambda s: s['experiences'][0].update(bullets=[None]),
                     lambda s: s['experiences'][0]['bullets'][0].update(evidence_ids=[3]),
                     lambda s: s.update(layout=None)]
        for mutate in mutations:
            value = deepcopy(base); mutate(value)
            with self.assertRaises(ValueError): normalize_spec(value)

    def test_education_refresh_retains_identity_and_layout_order(self):
        spec = normalize_spec({'education': [{'education_id': 'a'}, {'education_id': 'b'}]})
        section = spec['layout']['sections'][0]
        section['items'].reverse(); apply_layout(spec)
        prior = deepcopy(spec['education'])
        refresh_education(spec, [{'education_id': 'a', 'school': '更新'}, {'education_id': 'b'}, {'education_id': 'c'}])
        result = normalize_spec(spec)
        self.assertEqual([e['education_id'] for e in result['education']], ['b', 'a', 'c'])
        self.assertEqual([e['canvas_id'] for e in result['education'][:2]], [e['canvas_id'] for e in prior])
        refresh_education(result, [{'education_id': 'c'}])
        self.assertEqual(len(normalize_spec(result)['education']), 1)


class CanvasFlowTest(unittest.TestCase):
    setUp = test_mvp.MVPFlowTest.setUp
    tearDown = test_mvp.MVPFlowTest.tearDown
    form = test_mvp.MVPFlowTest.form
    draft = test_mvp.MVPFlowTest.draft
    save = test_mvp.MVPFlowTest.save
    continue_draft = test_mvp.MVPFlowTest.continue_draft

    def test_manual_save_never_queries_library_and_continues_layout(self):
        identifier = self.draft()
        spec = deepcopy(self.drafts[identifier]['context'].spec)
        spec['experiences'][0]['experience_id'] = 'deleted-source'
        spec['experiences'][0]['bullets'][0]['evidence_ids'] = ['stale-source']
        spec['skills'][0].update(name='人工技能', evidence_ids=[], user_confirmed=True)
        with patch.object(self.repo, 'evidence_index', side_effect=AssertionError('must not read library')), patch.object(self.repo, 'experience_index', side_effect=AssertionError('must not read library')), patch.object(self.repo, 'skills', side_effect=AssertionError('must not read library')):
            folder = self.save(identifier, spec=spec)
            child = self.continue_draft(identifier)
            self.assertEqual(self.drafts[child]['context'].spec['layout'], spec['layout'])
            self.save(child)
        html = (folder/'zh/resume.html').read_text()
        self.assertEqual(html.count('id="canvas-css"'), 1)
        self.assertNotIn('id="editor-css"', html)
        self.assertIn('stale-source', self.store.csv_path.read_text())

    def test_skill_description_is_backward_compatible_and_survives_export_save_continue(self):
        identifier = self.draft(evidence_ids=['ev_feedback_001'])
        spec = deepcopy(self.drafts[identifier]['context'].spec)
        # The fixture starts with legacy skills without description.  A loaded
        # spec receives the optional empty field, while a manual description is
        # carried through preview, formal HTML and historical continuation.
        self.assertEqual(spec['skills'][0]['description'], '')
        spec['skills'][0]['description'] = '用于清洗和整理用户反馈数据'
        editable = self.client.post(f'/api/drafts/{identifier}/preview', json={'spec': spec}).get_json()['html']
        self.assertIn('data-path="skills.0.name"', editable)
        self.assertIn('data-path="skills.0.description"', editable)
        self.assertIn('用于清洗和整理用户反馈数据', editable)
        self.assertIn('说明（可选）', editable)  # the legacy Excel/other empty description entry remains editor-visible
        exported = self.client.post(f'/api/drafts/{identifier}/export', json={'spec': spec}).get_data(as_text=True)
        self.assertIn('用于清洗和整理用户反馈数据', exported)
        self.assertNotIn('data-placeholder=', exported)
        folder = self.save(identifier, spec=spec)
        stored = json.loads((folder / 'zh/resume-spec.json').read_text(encoding='utf-8'))
        self.assertEqual(stored['skills'][0]['description'], spec['skills'][0]['description'])
        child = self.continue_draft(identifier)
        self.assertEqual(self.drafts[child]['context'].spec['skills'][0]['description'], spec['skills'][0]['description'])

    def test_skill_description_structure_rejects_non_string(self):
        identifier = self.draft()
        spec = deepcopy(self.drafts[identifier]['context'].spec)
        spec['skills'][0]['description'] = ['not', 'text']
        response = self.client.post(f'/api/drafts/{identifier}/preview', json={'spec': spec})
        self.assertEqual(response.status_code, 400)
        self.assertIn('description', response.get_json()['errors'][0])

    def test_model_rejects_missing_evidence_even_with_user_edited_flag(self):
        from resume_app.skill import ResumeSkill
        spec = ResumeSkill({'llm': {'mode': 'demo'}}, self.repo).build_spec('zh', ['ev_feedback_001'], '', '', {})
        spec['user_edited'] = True
        spec['experiences'][0]['bullets'][0]['evidence_ids'] = []
        with self.assertRaisesRegex(ValueError, '未关联证据'):
            validate_generated_spec(spec, self.repo, {'ev_feedback_001'})

    def test_legacy_font_only_changes_on_explicit_css_refresh(self):
        identifier = self.draft()
        self.drafts[identifier]['context'].base_css = 'body {font-family: Arial, sans-serif;}'
        folder = self.save(identifier)
        original = (folder/'zh/resume.html').read_bytes()
        child = self.continue_draft(identifier)
        context = self.drafts[child]['context']
        self.assertNotIn('Songti SC', context.base_css)
        self.assertNotIn('Structural flow', context.base_css)
        refreshed = self.client.post(f'/api/drafts/{child}/refresh', json={'part': 'css'})
        self.assertIn('Songti SC', refreshed.json['html'])
        self.assertEqual((folder/'zh/resume.html').read_bytes(), original)

    def test_layout_reorders_dom_and_paths_and_bad_payload_keeps_draft(self):
        from resume_app.canvas import new_id, item_layout
        identifier = self.draft(evidence_ids=['ev_feedback_001'])
        original = deepcopy(self.drafts[identifier]['context'].spec)
        spec = deepcopy(original)
        copy = deepcopy(spec['experiences'][0])
        copy['canvas_id'] = new_id()
        copy['organization'] = '画布排在最前的合成经历'
        for bullet in copy['bullets']:
            bullet['canvas_id'] = new_id()
        spec['experiences'].append(copy)
        section = next(s for s in spec['layout']['sections'] if s['section'] == 'experience')
        section['items'].insert(0, item_layout(copy))
        result = self.client.post(f'/api/drafts/{identifier}/preview', json={'spec': spec})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['spec']['experiences'][0]['canvas_id'], copy['canvas_id'])
        self.assertIn('data-path="experiences.0.organization" data-multiline="false">画布排在最前的合成经历', result.json['html'])
        accepted = deepcopy(self.drafts[identifier]['context'].spec)
        spec['layout']['sections'][0]['items'].append({'canvas_id': 'dangling'})
        self.assertEqual(self.client.post(f'/api/drafts/{identifier}/preview', json={'spec': spec}).status_code, 400)
        self.assertEqual(self.drafts[identifier]['context'].spec, accepted)

    def test_old_spec_without_layout_initializes_once_on_history_continue(self):
        identifier = self.draft()
        folder = self.save(identifier)
        spec_path = folder/'zh/resume-spec.json'
        spec = json.loads(spec_path.read_text())
        spec.pop('layout')
        spec['section_order'] = ['skills', 'experience']
        for key in ('education', 'experiences', 'projects', 'skills'):
            for item in spec[key]:
                item.pop('canvas_id')
                for bullet in item.get('bullets', []):
                    bullet.pop('canvas_id')
        spec_path.write_text(json.dumps(spec))  # Synthetic legacy fixture only.
        original_html = (folder/'zh/resume.html').read_bytes()
        child = self.continue_draft(identifier)
        baseline = deepcopy(self.drafts[child]['context'].spec)
        self.assertEqual(baseline['section_order'], ['skills', 'experience'])
        self.client.post(f'/api/drafts/{child}/preview', json={})
        self.assertEqual(self.drafts[child]['context'].spec, baseline)
        self.save(child)
        continued = self.continue_draft(child)
        self.assertEqual(self.drafts[continued]['context'].spec['layout'], baseline['layout'])
        self.assertEqual((folder/'zh/resume.html').read_bytes(), original_html)

    def test_width_constraints_and_roundtrip(self):
        identifier = self.draft()
        spec = deepcopy(self.drafts[identifier]['context'].spec)
        section = spec['layout']['sections'][0]
        section['span'] = 6
        section['items'][0]['span'] = 7
        for width in (5, 13, 6.5, '6', True):
            bad = deepcopy(spec)
            bad['layout']['sections'][0]['span'] = width
            self.assertEqual(self.client.post(f'/api/drafts/{identifier}/save', json={'spec':bad}).status_code, 400)
        self.save(identifier, spec=spec)
        child = self.continue_draft(identifier)
        self.assertEqual(self.drafts[child]['context'].spec['layout'], spec['layout'])

    def test_stale_preview_refresh_save_and_photo_cannot_replace_new_revision(self):
        import io
        from tests.test_mvp import PNG
        identifier = self.draft()
        spec = deepcopy(self.drafts[identifier]['context'].spec)
        spec['profile']['name'] = '较新合成内容'
        result = self.client.post(f'/api/drafts/{identifier}/preview', json={'spec':spec,'revision':4})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json['revision'],4)
        old = deepcopy(spec);old['profile']['name']='过期内容'
        for action in ('preview','refresh','save','export'):
            result=self.client.post(f'/api/drafts/{identifier}/{action}',json={'spec':old,'revision':3,'part':'profile'})
            self.assertEqual(result.status_code,400)
        result=self.client.post(f'/api/drafts/{identifier}/photo',data={'revision':'3','photo':(io.BytesIO(PNG),'synthetic.png')})
        self.assertEqual(result.status_code,400)
        self.assertEqual(self.drafts[identifier]['context'].spec,spec)
        self.save(identifier,spec=spec,revision=5)
