"""Names are user text; suffixes come exclusively from saved settings."""
import unittest
from copy import deepcopy
from tests import test_v0111_fgh as fgh
from resume_app.layout_defaults import automatic_name
from resume_app.storage import write_yaml, read_yaml


class FormatNamesTest(unittest.TestCase):
    setUp=fgh.FGHTest.setUp
    tearDown=fgh.FGHTest.tearDown
    defaults=fgh.FGHTest.defaults
    form=fgh.FGHTest.form
    draft=fgh.FGHTest.draft
    save=fgh.FGHTest.save
    continue_draft=fgh.FGHTest.continue_draft

    def test_historical_negative_margins_save_and_reuse_without_typography_input(self):
        identifier=self.draft()
        spec=deepcopy(self.drafts[identifier]['context'].spec)
        spec['style'].update(section_gap='-0.5mm', bullet_gap='-0.2mm')
        folder=self.save(identifier,spec=spec)
        before={str(p):p.read_bytes() for p in folder.rglob('*') if p.is_file()}
        continued=self.continue_draft(identifier)
        resumed=self.drafts[continued]['context'].spec
        settings={k:resumed[k] for k in ('theme','density','style')}
        result=self.change(action='create',custom_name='我的',settings=settings,make_default=True)
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['items'][0]['name'],'我的 · '+automatic_name(settings))
        self.assertEqual(self.client.get('/api/layout-formats').json['items'][0]['settings'],settings)
        newer=self.draft()
        self.assertEqual(self.drafts[newer]['context'].spec['style'],spec['style'])
        self.assertEqual(before,{str(p):p.read_bytes() for p in folder.rglob('*') if p.is_file()})

    def test_signed_margins_do_not_allow_invalid_font_padding_or_css(self):
        settings=self.defaults()
        for margin in ('-0.5mm','-.2mm','0','0mm','4.2mm'):
            settings['style'].update(section_gap=margin,bullet_gap=margin)
            self.assertEqual(self.change(action='create',custom_name=margin,settings=settings).status_code,200)
        path=self.root/'data/layout-defaults.yaml';before=path.read_bytes()
        for key,value in (('font_size','-1pt'),('font_size','0'),('page_padding','-1mm'),('section_gap','auto'),('bullet_gap','1mm; color:red')):
            invalid=deepcopy(settings);invalid['style'][key]=value
            self.assertEqual(self.change(action='create',custom_name='invalid',settings=invalid).status_code,400)
            self.assertEqual(path.read_bytes(),before)

    def change(self, **payload):
        return self.client.post('/api/layout-formats', json=payload)

    def test_free_name_latest_suffix_roundtrip_and_duplicate(self):
        settings=self.defaults()
        prefix='中文 English 123 / : · <img src=x onerror="alert(1)"> & '+ '长名称'*70
        result=self.change(action='create',custom_name=prefix,settings=settings,make_default=True)
        self.assertEqual(result.status_code,200)
        identifier=result.json['selected_id']
        item=result.json['items'][0]
        self.assertEqual(item['custom_name'],prefix)
        self.assertEqual(item['name'],prefix+' · '+automatic_name(settings))
        settings['style']['font_size']='11pt';settings['style']['line_height']='1.11'
        for _ in range(3):
            result=self.change(action='update',id=identifier,custom_name=item['custom_name'],settings=settings)
            item=result.json['items'][0]
            self.assertEqual(item['name'],prefix+' · '+automatic_name(settings))
            self.assertEqual(result.json['default_id'],identifier)
        self.assertEqual(self.change(action='create',custom_name=prefix,settings=settings).status_code,400)
        settings['style']['section_gap']='3mm'
        self.assertEqual(self.change(action='create',custom_name=prefix,settings=settings).status_code,200)
        self.assertEqual(len(self.client.get('/api/layout-formats').json['items']),2)

    def test_legacy_read_only_and_update_auto_or_literal_prefix(self):
        path=self.root/'data/layout-defaults.yaml';settings=self.defaults()
        old={'version':2,'default_id':'a','items':[
            {'id':'a','name':automatic_name(settings),'settings':settings},
            {'id':'b','name':'旧名称 · 包含标点 <测试>','settings':settings}]}
        write_yaml(path,old);before=path.read_bytes()
        items=self.client.get('/api/layout-formats').json['items']
        self.assertEqual(items[0]['custom_name'],'')
        self.assertEqual(items[1]['custom_name'],old['items'][1]['name'])
        self.assertEqual(path.read_bytes(),before)
        result=self.change(action='update',id='a',custom_name='',settings=settings)
        self.assertEqual(result.json['items'][0]['name'],automatic_name(settings))
        self.assertNotIn('custom_name',read_yaml(path,{})['items'][1])
        settings=deepcopy(settings);settings['style']['line_height']='1.13'
        result=self.change(action='update',id='b',custom_name=items[1]['custom_name'],settings=settings)
        self.assertEqual(result.json['items'][1]['name'],items[1]['custom_name']+' · '+automatic_name(settings))
        self.assertEqual(result.json['default_id'],'a')

    def test_blank_and_literal_suffix_like_custom_text(self):
        settings=self.defaults();suffix=automatic_name(settings)
        result=self.change(action='create',custom_name='   ',settings=settings)
        self.assertEqual(result.json['items'][0]['name'],suffix)
        result=self.change(action='create',custom_name='我的 '+suffix,settings=settings)
        self.assertEqual(result.json['items'][-1]['custom_name'],'我的 '+suffix)
        before=(self.root/'data/layout-defaults.yaml').read_bytes()
        self.assertEqual(self.change(action='create',custom_name=['invalid'],settings=settings).status_code,400)
        self.assertEqual((self.root/'data/layout-defaults.yaml').read_bytes(),before)

    def test_old_page_full_name_uses_selected_prefix_or_requests_refresh(self):
        settings=self.defaults()
        result=self.change(action='create',custom_name='旧页面续用',settings=settings)
        item=result.json['items'][0]
        settings['style']['line_height']='1.19'
        result=self.change(action='update',id=item['id'],name=item['name'],settings=settings)
        updated=result.json['items'][0]
        self.assertEqual(updated['name'],'旧页面续用 · '+automatic_name(settings))
        settings['style']['line_height']='1.18'
        result=self.change(action='create',id=updated['id'],name=updated['name'],settings=settings)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json['items'][-1]['custom_name'],'旧页面续用')
        before=(self.root/'data/layout-defaults.yaml').read_bytes()
        result=self.change(action='update',id=item['id'],name='旧页面无法辨明的新值',settings=settings)
        self.assertEqual(result.status_code,400)
        self.assertIn('刷新',result.json['error'])
        self.assertEqual((self.root/'data/layout-defaults.yaml').read_bytes(),before)
