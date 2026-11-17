"""Named global typography preferences, independent of resume content."""
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
    if not re.fullmatch(length + r'|0', style['font_size']):
        raise ValueError('当前格式的字号无效，应为正长度，例如 10.5pt')
    # These fields render as CSS margins, which may legitimately be negative
    # in compact historical resumes. Preserve the actual layout on save.
    for key, label in (('section_gap', '板块间距'), ('bullet_gap', 'Bullet 间距')):
        if not re.fullmatch(r'-?(?:' + length + r'|0)', style[key]):
            raise ValueError(f'当前格式的{label}无效，应为长度，例如 4mm 或 -0.2mm')
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
        value = load_formats(path)
        item = next((x for x in value['items'] if x['id'] == value['default_id']), None)
        return (item['settings'] if item else None), ''
    except (ValueError, TypeError, OSError, yaml.YAMLError):
        return None, '已存默认排版无法读取，本次未应用；可重新保存或清除默认排版。'


def automatic_name(settings):
    s = settings['style']
    return f"字号：{s['font_size']} · 行距：{s['line_height']} · 板块间距：{s['section_gap']}"



def custom_name(item):
    """Legacy automatic names have no prefix; other legacy names remain literal."""
    if 'custom_name' in item:
        return item['custom_name']
    return '' if item['name'] == automatic_name(item['settings']) else item['name']


def present_formats(value):
    result = deepcopy(value)
    for item in result['items']:
        item['custom_name'] = custom_name(item)
    return result


def load_formats(path):
    """Upgrade the legacy file in place, atomically; never maintain two sources."""
    from .storage import write_yaml
    if not path.exists():
        return {'version': 2, 'default_id': None, 'items': []}
    try:
        value = read_yaml(path, {})
        if isinstance(value, dict) and set(value) == {'theme', 'density', 'style'}:
            settings = validate_defaults(value)
            value = {'version': 2, 'default_id': 'legacy', 'items': [
                {'id': 'legacy', 'name': automatic_name(settings), 'settings': settings}]}
            write_yaml(path, value)
        if not isinstance(value, dict) or value.get('version') != 2 or not isinstance(value.get('items'), list):
            raise ValueError()
        ids, names = set(), set()
        for item in value['items']:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'] or item['id'] in ids:
                raise ValueError()
            if not isinstance(item.get('name'), str) or not item['name'].strip() or item['name'] in names:
                raise ValueError()
            validate_defaults(item.get('settings'))
            if 'custom_name' in item and not isinstance(item['custom_name'], str):
                raise ValueError()
            ids.add(item['id']); names.add(item['name'])
        if value.get('default_id') is not None and value['default_id'] not in ids:
            raise ValueError()
        return value
    except (ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
        raise ValueError('排版格式文件无法读取，请从备份恢复后重试；原文件已保留。') from exc


def change_formats(path, payload):
    from uuid import uuid4
    from .storage import write_yaml
    if not isinstance(payload, dict):
        raise ValueError('排版格式请求无效')
    value = load_formats(path)
    action = payload.get('action')
    item = None if action == 'create' else next((x for x in value['items'] if x['id'] == payload.get('id')), None)
    if action in ('update', 'delete', 'default') and item is None:
        raise ValueError('请选择仍存在的排版格式')
    if action in ('create', 'update'):
        settings = validate_defaults(payload.get('settings'))
        prefix = payload.get('custom_name', payload.get('name', ''))
        if 'custom_name' not in payload:
            reference = next((x for x in value['items'] if x['id'] == payload.get('id')), None)
            if reference and prefix == reference['name']:
                prefix = custom_name(reference)
            elif reference and 'custom_name' in reference:
                raise ValueError('命名方式已更新，请刷新页面后保存自定义名称')
        if not isinstance(prefix, str):
            raise ValueError('格式名称必须是文字')
        prefix = prefix.strip()
        name = (prefix + ' · ' if prefix else '') + automatic_name(settings)
        if any(x['name'] == name and x is not item for x in value['items']):
            raise ValueError('已有同名格式，请改名或选择该格式后更新')
        if action == 'create':
            item = {'id': uuid4().hex}; value['items'].append(item)
        item.update(name=name, custom_name=prefix, settings=settings)
        if payload.get('make_default') is True:
            value['default_id'] = item['id']
    elif action == 'delete':
        value['items'].remove(item)
        if value['default_id'] == item['id']:
            value['default_id'] = None
    elif action == 'default':
        value['default_id'] = item['id']
    elif action == 'clear_default':
        value['default_id'] = None
    else:
        raise ValueError('未知排版操作')
    write_yaml(path, value)
    return value, item['id'] if item else None
