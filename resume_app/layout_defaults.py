"""One set of global typography preferences, independent of any resume content."""
from copy import deepcopy
import re
import yaml
from .drafts import STYLE_DEFAULTS, validate_structure
from .storage import read_yaml
from .validation import ALLOWED_THEMES, ALLOWED_DENSITIES


def validate_defaults(value):
    if not isinstance(value, dict) or set(value) != {'theme', 'density', 'style'}:
        raise ValueError('默认排版只接受主题、密度和全局样式')
    validate_structure(value)
    if value['theme'] not in ALLOWED_THEMES or value['density'] not in ALLOWED_DENSITIES:
        raise ValueError('主题或密度无效')
    style = value['style']
    if set(style) != set(STYLE_DEFAULTS):
        raise ValueError('全局排版字段不完整或含未知字段')
    if style['cjk_font'] not in {'songti', 'heiti', 'kaiti'}:
        raise ValueError('中文字体无效')
    length = r'(?:\d+(?:\.\d+)?|\.\d+)(?:mm|cm|pt|px|em|rem)'
    for key in ('font_size', 'section_gap', 'bullet_gap'):
        if not re.fullmatch(length + r'|0', style[key]):
            raise ValueError('字号和间距请输入非负长度，例如 10.5pt、4mm')
    if float(re.match(r'[\d.]+', style['font_size']).group()) <= 0:
        raise ValueError('字号必须大于零')
    if not re.fullmatch(r'(?:\d+(?:\.\d+)?|\.\d+)', style['line_height']) or float(style['line_height']) <= 0:
        raise ValueError('行距请输入正数，例如 1.42')
    parts = style['page_padding'].split()
    if not 1 <= len(parts) <= 4 or any(not re.fullmatch(length + r'|0', x) for x in parts):
        raise ValueError('页边距请输入 1–4 个非负长度，例如 14mm 16mm')
    if style['title_color'] and not re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?', style['title_color']):
        raise ValueError('标题色请输入十六进制颜色，或留空跟随主题')
    return deepcopy(value)


def load_defaults(path):
    try:
        if not path.exists():
            return None, ''
        return validate_defaults(read_yaml(path, {})), ''
    except (ValueError, TypeError, OSError, yaml.YAMLError):
        return None, '已存默认排版无法读取，本次未应用；可重新保存或清除默认排版。'
