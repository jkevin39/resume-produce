"""Per-generation display order, using existing library identities."""

def catalog(experiences, skills):
    return {
        'experience': [x['experience_id'] for x in experiences if x.get('type') != 'project'],
        'project': [x['experience_id'] for x in experiences if x.get('type') == 'project'],
        'skills': [x['name'] for x in skills],
    }


def validate_order(value, allowed):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError('排序格式或类别不正确')
    result = {}
    for key, known in allowed.items():
        ids = value.get(key, [])
        if (not isinstance(ids, list) or not all(isinstance(x, str) for x in ids)
                or len(ids) != len(set(ids)) or set(ids) - set(known)):
            raise ValueError('排序包含重复、未知或跨类别对象')
        result[key] = ids + [x for x in known if x not in ids]
    return result


def ordered(rows, ids, key):
    rank = {value: i for i, value in enumerate(ids)}
    return sorted(rows, key=lambda row: rank.get(row[key], len(rank)))


def demo_order(analysis, experiences, skills):
    words = analysis.get('technical_keywords', [])
    def score(text):
        return -sum(word.lower() in text.lower() for word in words)
    result = {}
    for kind in ('experience', 'project'):
        rows = [x for x in experiences if ('project' if x.get('type') == 'project' else 'experience') == kind]
        rows.sort(key=lambda x: score(' '.join(e.get('original_fact', '') for e in x.get('evidence', []) if e.get('status') != 'rejected')))
        result[kind] = [x['experience_id'] for x in rows]
    result['skills'] = [x['name'] for x in sorted(skills, key=lambda x: score(x['name'] + ' ' + x.get('description', '')))]
    return result
