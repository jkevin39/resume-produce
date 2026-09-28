import unittest
from copy import deepcopy
from resume_app.drafts import normalize_spec
from resume_app.canvas import new_id, item_layout
from tests import test_mvp


class V081StructureTest(unittest.TestCase):
    def test_v1_migration_is_once_and_does_not_mutate_input(self):
        spec = normalize_spec({'skills': [{'name': '旧技能'}]})
        legacy = deepcopy(spec)
        legacy['layout']['version'] = 1
        for section in legacy['layout']['sections']:
            section.pop('kind'); section.pop('title')
        before = deepcopy(legacy)
        migrated = normalize_spec(legacy)
        self.assertEqual(legacy, before)
        self.assertEqual(migrated, normalize_spec(migrated))
        self.assertEqual(migrated['layout'], spec['layout'])

    def test_duplicate_kind_and_custom_have_exactly_one_owner(self):
        spec = normalize_spec({'skills': [{'name': 'SQL'}, {'name': 'Python'}]})
        original = spec['layout']['sections'][3]
        duplicate = deepcopy(original); duplicate.update(canvas_id=new_id(), title='第二技能板块')
        duplicate['items'] = [original['items'].pop()]
        spec['layout']['sections'].append(duplicate)
        custom = {'canvas_id': new_id(), 'text': '合成自定义内容'}
        spec['custom_bullets'].append(custom)
        spec['layout']['sections'].append({'canvas_id':new_id(),'kind':'custom','title':'补充','hidden':False,'span':6,'items':[item_layout(custom)]})
        result = normalize_spec(spec)
        self.assertEqual(result['section_order'].count('skills'), 1)
        self.assertEqual(len(result['skills']), 2)
        for mutate in (lambda s:s['layout']['sections'][3]['items'].extend(s['layout']['sections'][4]['items']), lambda s:s['layout']['sections'][4]['items'].clear()):
            bad=deepcopy(spec);mutate(bad)
            with self.assertRaises(ValueError):normalize_spec(bad)

    def test_unicode_inline_validation_and_hostile_fields(self):
        spec=normalize_spec({'profile':{'summary':'甲😀乙<script>'}})
        style={'object_id':'profile','field':'summary','start':1,'end':2,'font_size':12.5}
        spec['inline_styles']=[style]
        self.assertEqual(normalize_spec(spec)['inline_styles'], [style])
        for change in ({'start':True},{'start':-1},{'end':100},{'end':1},{'font_size':7},{'font_size':24.5},{'font_size':12.2},{'font_size':True},{'field':'photo_path'},{'object_id':'missing'},{'html':'<script>'}):
            bad=deepcopy(spec);bad['inline_styles'][0].update(change)
            with self.assertRaises(ValueError):normalize_spec(bad)
        spec['inline_styles'].append(deepcopy(style))
        with self.assertRaisesRegex(ValueError,'重叠'):normalize_spec(spec)


class V081FlowTest(unittest.TestCase):
    setUp=test_mvp.MVPFlowTest.setUp
    tearDown=test_mvp.MVPFlowTest.tearDown
    form=test_mvp.MVPFlowTest.form
    draft=test_mvp.MVPFlowTest.draft
    save=test_mvp.MVPFlowTest.save
    continue_draft=test_mvp.MVPFlowTest.continue_draft

    def test_inline_custom_roundtrip_escaping_and_failed_save_keeps_state(self):
        draft=self.draft();spec=deepcopy(self.drafts[draft]['context'].spec)
        spec['profile']['summary']='甲😀乙<script>alert(1)</script>'
        spec['inline_styles']=[{'object_id':'profile','field':'summary','start':1,'end':2,'font_size':15.5}]
        item={'canvas_id':new_id(),'text':'自定义😀内容','evidence_ids':[]}
        spec['custom_bullets']=[item]
        spec['layout']['sections'].append({'canvas_id':new_id(),'kind':'custom','title':'补充 <内容>','hidden':False,'span':12,'items':[item_layout(item)]})
        preview=self.client.post(f'/api/drafts/{draft}/preview',json={'spec':spec})
        self.assertEqual(preview.status_code,200)
        self.assertIn('<span style="font-size: 15.5pt">😀</span>',preview.json['html'])
        self.assertIn('&lt;script&gt;',preview.json['html'])
        self.assertNotIn('<script>alert',preview.json['html'])
        bad=deepcopy(spec);bad['inline_styles'][0]['end']=10000
        self.assertEqual(self.client.post(f'/api/drafts/{draft}/save',json={'spec':bad}).status_code,400)
        self.assertEqual(self.drafts[draft]['context'].spec,preview.json['spec'])
        exported=self.client.post(f'/api/drafts/{draft}/export',json={'spec':spec}).text
        folder=self.save(draft,spec=spec)
        self.assertEqual(exported,(folder/'zh/resume.html').read_text())
        child=self.continue_draft(draft)
        self.assertEqual(self.drafts[child]['context'].spec['inline_styles'],spec['inline_styles'])
        self.assertEqual(self.drafts[child]['context'].spec['custom_bullets'],spec['custom_bullets'])
