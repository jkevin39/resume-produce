"""Read-only grouping for the existing evidence selection protocol."""


def group_evidence(matches, experiences, skills):
    tags = {}
    for skill in skills:
        for eid in skill.get("evidence_ids", []):
            names = tags.setdefault(eid, [])
            if skill["name"] not in names:
                names.append(skill["name"])
    candidates = {}
    for match in sorted(matches, key=lambda item: item["priority"]):
        candidates.setdefault(match["evidence_id"], match)
    sections = []
    for kind, title in (("experience", "实习与经历"), ("project", "项目经历")):
        entries = []
        for experience in experiences:
            if ("project" if experience.get("type") == "project" else "experience") != kind:
                continue
            bullets = [
                {"evidence": item, "match": candidates[item["evidence_id"]],
                 "skills": tags.get(item["evidence_id"], [])}
                for item in experience["evidence"] if item["evidence_id"] in candidates
            ]
            bullets.sort(key=lambda item: item["match"]["priority"])
            if bullets:
                entries.append({"experience": experience, "bullets": bullets})
        entries.sort(key=lambda item: item["bullets"][0]["match"]["priority"])
        if entries:
            sections.append({"kind": kind, "title": title, "entries": entries})
    return sections
