"""Single-field font sizes. Offsets count Unicode code points, not UTF-16 units."""
from markupsafe import Markup, escape

FONT_STACKS = {
    'songti': '"Times New Roman", "Songti SC", "STSong", "SimSun", serif',
    'heiti': '"Times New Roman", "Heiti SC", "STHeiti", "SimHei", sans-serif',
    'kaiti': '"Times New Roman", "Kaiti SC", "STKaiti", "KaiTi", serif',
}

FIELDS = {'profile': ('name', 'phone', 'email', 'location', 'summary'),
          'education': ('school', 'degree', 'major', 'date', 'details'),
          'experiences': ('organization', 'title', 'date', 'location'),
          'projects': ('organization', 'title', 'date', 'location'),
          'skills': ('name', 'description'), 'custom_bullets': ('text',)}


def field_index(spec):
    result = {}
    for key, fields in FIELDS.items():
        rows = [spec['profile']] if key == 'profile' else spec[key]
        for i, row in enumerate(rows):
            identifier = 'profile' if key == 'profile' else row['canvas_id']
            for field in fields:
                path = f'profile.{field}' if key == 'profile' else f'{key}.{i}.{field}'
                result[path] = (identifier, field, row.get(field, ''))
            for j, bullet in enumerate(row.get('bullets', [])):
                result[f'{key}.{i}.bullets.{j}.text'] = (bullet['canvas_id'], 'text', bullet['text'])
    for i, section in enumerate(spec['layout']['sections']):
        result[f'layout.sections.{i}.title'] = (section['canvas_id'], 'title', section['title'])
    return result


def validate_inline_styles(spec):
    if spec['style'].get('cjk_font', 'songti') not in FONT_STACKS:
        raise ValueError('中文字体须为 songti、heiti 或 kaiti')
    styles = spec.get('inline_styles', [])
    if not isinstance(styles, list):
        raise ValueError('inline_styles 必须是数组')
    fields = {(identifier, field): text for identifier, field, text in field_index(spec).values()}
    ends = {}
    for style in styles:
        if not isinstance(style, dict) or not {'object_id', 'field', 'start', 'end'} <= set(style) or set(style) - {'object_id', 'field', 'start', 'end', 'font_size', 'cjk_font'} or not ({'font_size', 'cjk_font'} & set(style)):
            raise ValueError('行内字号仅接受字段锚点、范围和 font_size')
        identifier, field = style['object_id'], style['field']
        if not isinstance(identifier, str) or not isinstance(field, str) or (identifier, field) not in fields:
            raise ValueError('行内字号字段锚点无效')
        start, end, size = style['start'], style['end'], style.get('font_size')
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(fields[(identifier, field)]):
            raise ValueError('行内字号 Unicode 范围无效')
        if 'cjk_font' in style and (not isinstance(style['cjk_font'], str) or style['cjk_font'] not in FONT_STACKS):
            raise ValueError('中文字体须为 songti、heiti 或 kaiti')
        if 'font_size' in style and (type(size) not in (int, float) or not 8 <= size <= 24 or size * 2 != int(size * 2)):
            raise ValueError('行内字号须为 8–24 pt，步长 0.5')
        key = (identifier, field)
        for a, b in ends.setdefault(key, []):
            if start < b and end > a:
                raise ValueError('同字段行内字号范围不能重叠')
        ends[key].append((start, end))


def render_field(spec, path):
    identifier, field, text = field_index(spec)[path]
    styles = sorted((s for s in spec.get('inline_styles', []) if s['object_id'] == identifier and s['field'] == field), key=lambda s: s['start'])
    parts, offset = [], 0
    for style in styles:
        css = []
        if 'font_size' in style:
            css.append('font-size: ' + format(style['font_size'], 'g') + 'pt')
        if 'cjk_font' in style:
            css.append('font-family: ' + FONT_STACKS[style['cjk_font']])
        parts.extend([escape(text[offset:style['start']]), Markup('<span style="%s">') % '; '.join(css), escape(text[style['start']:style['end']]), Markup('</span>')])
        offset = style['end']
    parts.append(escape(text[offset:]))
    return Markup('').join(parts)


def rebase_styles(before, after):
    old = {(i, f): text for i, f, text in field_index(before).values()}
    current = {(i, f): text for i, f, text in field_index(after).values()}
    result = []
    for style in before.get('inline_styles', []):
        key = (style['object_id'], style['field'])
        if key not in current:
            continue
        a, b = old[key], current[key]
        start = 0
        while start < min(len(a), len(b)) and a[start] == b[start]:
            start += 1
        suffix = 0
        while suffix < min(len(a), len(b)) - start and a[-1-suffix] == b[-1-suffix]:
            suffix += 1
        end, delta = len(a) - suffix, len(b) - len(a)
        if style['end'] <= start:
            result.append(dict(style))
        elif style['start'] >= end:
            result.append(dict(style, start=style['start']+delta, end=style['end']+delta))
        else:
            if style['start'] < start:
                result.append(dict(style, end=start))
            if style['end'] > end:
                result.append(dict(style, start=end+delta, end=style['end']+delta))
    after['inline_styles'] = result
