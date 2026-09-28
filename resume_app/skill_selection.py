"""Skill names follow the existing library identity; evidence remains separate."""


def skill_options(skills, evidence, selected_ids):
    selected = set(selected_ids)
    options = []
    for skill in skills:
        usable = [eid for eid in skill.get("evidence_ids", [])
                  if eid in evidence and evidence[eid].get("status") != "rejected"]
        confirmed = skill.get("user_confirmed") is True
        options.append({**skill, "available_evidence_ids": usable,
                        "eligible": confirmed or bool(selected.intersection(usable))})
    return options


def select_skills(skills, evidence, selected_ids, names):
    options = skill_options(skills, evidence, selected_ids)
    if names is None:  # Direct callers without an explicit selection retain their existing defaults.
        return [item for item in options if item["eligible"]]
    requested = set(names)
    available = {item["name"] for item in options if item["eligible"]}
    if requested - available:
        raise ValueError("所选技能不存在或缺少已选证据/用户确认，请重新选择技能。")
    return [item for item in options if item["name"] in requested]
