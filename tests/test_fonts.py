from copy import deepcopy
import unittest
from resume_app.drafts import normalize_spec
from resume_app.inline_styles import render_field

class FontTest(unittest.TestCase):
    def test_default_whitelist_and_independent_inline_styles(self):
        base=normalize_spec({'profile':{'summary':'中文ABC123'}})
        self.assertEqual(base['style']['cjk_font'],'songti')
        for font in ['songti','heiti','kaiti']:
            spec=deepcopy(base);spec['style']['cjk_font']=font
            for props in [{'cjk_font':font},{'font_size':12,'cjk_font':font},{'font_size':12}]:
                spec['inline_styles']=[dict(object_id='profile',field='summary',start=0,end=5,**props)]
                normalize_spec(spec)
                html=str(render_field(spec,'profile.summary'))
                if 'cjk_font' in props:self.assertIn('Times New Roman',html)
                if 'font_size' in props:self.assertIn('font-size: 12pt',html)
        for props in [{},{'cjk_font':'Arial'},{'cjk_font':[]},{'cjk_font':'songti','font-family':'evil'},{'cjk_font':'\";color:red'}]:
            spec=deepcopy(base);spec['inline_styles']=[dict(object_id='profile',field='summary',start=0,end=2,**props)]
            with self.assertRaises(ValueError):normalize_spec(spec)
        for font in ['Arial',[],None]:
            spec=deepcopy(base);spec['style']['cjk_font']=font
            with self.assertRaises(ValueError):normalize_spec(spec)
