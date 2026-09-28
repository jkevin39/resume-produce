"""Flow-grid canvas contract. Content IDs are independent of provenance IDs."""
from copy import deepcopy
from uuid import uuid4

SECTIONS = {'education': 'education', 'experience': 'experiences', 'projects': 'projects', 'skills': 'skills', 'custom': 'custom_bullets'}


def new_id():
    return 'canvas_' + uuid4().hex


def item_layout(item):
    node = {'canvas_id': item['canvas_id']}
    if 'bullets' in item:
        node['bullets'] = [bullet['canvas_id'] for bullet in item['bullets']]
    return node


def initialize_layout(spec):
    """Only missing layout is legacy; never silently repair an existing layout."""
    if 'layout' in spec:
        migrate_layout(spec)
        return
    sections = spec['section_order']
    if len(set(sections)) != len(sections) or any(s not in SECTIONS for s in sections):
        raise ValueError('板块顺序包含重复或未知板块')
    for key in SECTIONS.values():
        for item in spec[key]:
            item.setdefault('canvas_id', new_id())
            for bullet in item.get('bullets', []):
                bullet.setdefault('canvas_id', new_id())
    spec['layout'] = {'version': 1, 'sections': [
        {'canvas_id': new_id(), 'section': section, 'hidden': section not in sections,
         'items': [item_layout(item) for item in spec[SECTIONS[section]]]}
        for section in sections + [s for s in SECTIONS if s not in sections and s != 'custom']
    ]}
    migrate_layout(spec)


def migrate_layout(spec):
    layout = spec['layout']
    if isinstance(layout, dict) and type(layout.get('version')) is int and layout['version'] == 1:
        sections = layout.get('sections', [])
        if len(sections) != 4 or {s.get('section') for s in sections} != set(SECTIONS) - {'custom'}:
            raise ValueError('旧画布必须包含四个固定板块')
        for section in sections:
            section['kind'] = section['section']
            section['title'] = spec['section_titles'][section['kind']]
            section.setdefault('span', 12)
        layout['version'] = 2


def apply_layout(spec):
    """Validate total, unique, parent-correct references and materialize DOM paths."""
    layout = spec['layout']
    if not isinstance(layout, dict) or type(layout.get('version')) is not int or layout['version'] != 2:
        raise ValueError('不支持的画布布局版本')
    sections = layout.get('sections')
    if not isinstance(sections, list):
        raise ValueError('画布板块必须是数组')
    used = set()
    def identity(item):
        identifier = item.get('canvas_id') if isinstance(item, dict) else None
        if not isinstance(identifier, str) or not identifier.strip() or identifier in used:
            raise ValueError('画布对象 ID 缺失、类型错误或重复')
        used.add(identifier)
        return identifier
    def width(node, allowed=True):
        if 'span' in node and (not allowed or type(node['span']) is not int or not 6 <= node['span'] <= 12):
            raise ValueError('画布宽度须为 6–12 格；技能和 bullet 随父容器')
    indexes = {}
    for kind, key in SECTIONS.items():
        indexes[kind] = {identity(item): item for item in spec[key]}
        for item in spec[key]:
            for bullet in item.get('bullets', []):
                identity(bullet)
    references = {kind: [] for kind in SECTIONS}
    for section in sections:
        identity(section)
        width(section)
        kind = section.get('kind')
        if not isinstance(kind, str) or kind not in SECTIONS or type(section.get('hidden')) is not bool or not isinstance(section.get('title'), str):
            raise ValueError('画布板块类型、标题或显隐无效')
        # Legacy alias is a projection, never an alternative authority.
        section['section'] = kind
        nodes = section.get('items')
        if not isinstance(nodes, list) or any(not isinstance(n, dict) for n in nodes):
            raise ValueError('画布条目必须是对象数组')
        for node in nodes:
            identifier = node.get('canvas_id')
            if not isinstance(identifier, str) or identifier not in indexes[kind] or identifier in references[kind]:
                raise ValueError('画布引用缺失、重复或不属于当前父对象')
            references[kind].append(identifier)
            width(node, kind not in ('skills', 'custom'))
            item = indexes[kind][identifier]
            if kind in ('experience', 'projects'):
                refs = node.get('bullets')
                bullets = {b['canvas_id']: b for b in item['bullets']}
                if not isinstance(refs, list) or any(not isinstance(r, str) for r in refs) or len(set(refs)) != len(refs) or set(refs) != set(bullets):
                    raise ValueError('bullet 引用缺失、重复或不属于当前父对象')
                item['bullets'] = [bullets[r] for r in refs]
            elif 'bullets' in node:
                raise ValueError('此画布对象不能包含 bullet')
    for kind, key in SECTIONS.items():
        if set(references[kind]) != set(indexes[kind]):
            raise ValueError('画布对象必须恰好归属一个板块')
        spec[key] = [indexes[kind][r] for r in references[kind]]
    spec['section_order'] = list(dict.fromkeys(s['kind'] for s in sections if not s['hidden'] and s['kind'] != 'custom'))


def refresh_education(spec, education):
    """Preserve layout order and IDs for surviving education_id; append new rows."""
    old = {}
    for e in spec['education']:
        if e.get('education_id'):
            old.setdefault(e['education_id'], e)
    rows = deepcopy(education)
    for row in rows:
        row['canvas_id'] = old.get(row.get('education_id'), {}).get('canvas_id') or new_id()
    sections = [s for s in spec['layout']['sections'] if s['kind'] == 'education']
    if not sections:
        sections = [{'canvas_id': new_id(), 'kind': 'education', 'section': 'education', 'title': '教育经历', 'hidden': False, 'span': 12, 'items': []}]
        spec['layout']['sections'].extend(sections)
    section = sections[0]
    for extra in sections[1:]:
        extra['items'] = []
    by_id = {r['canvas_id']: r for r in rows}
    ids = [n['canvas_id'] for n in section['items'] if n['canvas_id'] in by_id]
    ids += [r['canvas_id'] for r in rows if r['canvas_id'] not in ids]
    spec['education'] = [by_id[i] for i in ids]
    prior_nodes = {n['canvas_id']: n for n in section['items']}
    section['items'] = [prior_nodes.get(r['canvas_id'], item_layout(r)) for r in spec['education']]
