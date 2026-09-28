from __future__ import annotations

import re
from typing import Any


STATUSES = {"confirmed", "needs_details"}
MATCH_CATEGORIES = {"strong", "partial", "needs_details", "not_applicable"}


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} 必须是 JSON 对象")
    return value


def _list(value: dict, key: str, name: str) -> list:
    result = value.get(key)
    if not isinstance(result, list):
        raise ValueError(f"{name} 缺少数组字段 {key}")
    return result


def _text(value: Any, field: str, allow_empty: bool = True) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"字段 {field} 必须是字符串")
    return value


def _chinese(value: str, field: str) -> None:
    if value.strip() and not re.search(r"[\u4e00-\u9fff]", value):
        raise ValueError(f"字段 {field} 必须使用中文说明")


def _chinese_or_technical(value: str, field: str) -> None:
    stripped = value.strip()
    technical_only = bool(re.fullmatch(r"[A-Za-z0-9+#./ -]+", stripped)) and len(stripped.split()) <= 2
    if stripped and not re.search(r"[\u4e00-\u9fff]", stripped) and not technical_only:
        raise ValueError(f"字段 {field} 必须使用中文说明")


def validate_extraction(value: Any) -> dict[str, Any]:
    data = _object(value, "履历拆解结果")
    if data.get("type") not in {"experience", "project"}:
        raise ValueError("履历拆解结果 type 无效")
    for key in ("experience_id", "organization", "title", "date", "location"):
        _text(data.get(key), key)
    _list(data, "source_refs", "履历拆解结果")
    evidence = _list(data, "evidence", "履历拆解结果")
    if not evidence:
        raise ValueError("履历拆解结果 evidence 不能为空")
    for index, item in enumerate(evidence):
        item = _object(item, f"evidence[{index}]")
        for key in ("evidence_id", "original_fact", "candidate_zh"):
            _text(item.get(key), f"evidence[{index}].{key}", allow_empty=False)
        if item.get("status") not in STATUSES:
            raise ValueError(f"evidence[{index}].status 无效")
        _chinese(item["candidate_zh"], f"evidence[{index}].candidate_zh")
        fact = _object(item.get("structured_fact"), f"evidence[{index}].structured_fact")
        for key in ("action", "method", "scale", "result"):
            _text(fact.get(key), f"structured_fact.{key}")
        if not all(isinstance(x, str) for x in _list(fact, "skills", "structured_fact")):
            raise ValueError("structured_fact.skills 必须是字符串数组")
    return data


def validate_jd_analysis(value: Any) -> dict[str, Any]:
    data = _object(value, "JD 分析结果")
    for key in ("required", "preferred", "responsibilities", "technical_keywords"):
        items = _list(data, key, "JD 分析结果")
        if not all(isinstance(x, str) for x in items):
            raise ValueError(f"{key} 必须是字符串数组")
        if key != "technical_keywords":
            for item in items:
                _chinese_or_technical(item, key)
    for item in _list(data, "inferred_preferences", "JD 分析结果"):
        item = _object(item, "inferred_preferences 项")
        if item.get("inferred") is not True:
            raise ValueError("推测偏好必须标记 inferred=true")
        _chinese(_text(item.get("text"), "inferred_preferences.text", False), "inferred_preferences.text")
    return data


def validate_match_report(value: Any, allowed_evidence_ids: set[str], allowed_education_ids=None) -> dict[str, Any]:
    data = _object(value, "证据匹配结果")
    for item in _list(data, "matches", "证据匹配结果"):
        item = _object(item, "matches 项")
        if item.get("evidence_id") not in allowed_evidence_ids:
            raise ValueError(f"匹配结果引用未知证据：{item.get('evidence_id')}")
        if item.get("category") not in MATCH_CATEGORIES or not isinstance(item.get("priority"), int):
            raise ValueError("匹配结果 category 或 priority 无效")
        _chinese(_text(item.get("reason"), "matches.reason", False), "matches.reason")
    for item in _list(data, "gaps", "证据匹配结果"):
        item = _object(item, "gaps 项")
        _chinese_or_technical(_text(item.get("requirement"), "gaps.requirement", False), "gaps.requirement")
        _chinese(_text(item.get("suggestion"), "gaps.suggestion", False), "gaps.suggestion")
    if not all(isinstance(x, str) for x in _list(data, "keyword_coverage", "证据匹配结果")):
        raise ValueError("keyword_coverage 必须是字符串数组")
    if allowed_education_ids is not None:
        for item in _list(data, "education_matches", "教育匹配结果"):
            item = _object(item, "education_matches 项")
            _chinese(_text(item.get("requirement"), "教育条件", False), "教育条件")
            _chinese(_text(item.get("reason"), "教育匹配依据", False), "教育匹配依据")
            if item.get("status") not in {"met", "unmet", "needs_confirmation"}:
                raise ValueError("教育匹配状态无效")
            ids = _list(item, "education_ids", "教育匹配项")
            if not all(isinstance(eid, str) and eid in allowed_education_ids for eid in ids):
                raise ValueError("教育匹配引用未知教育记录")
            if item["status"] != "needs_confirmation" and not ids:
                raise ValueError("教育匹配缺少判断依据")
        # Same requirement should not also be rendered as a general gap.
        education_requirements = {item["requirement"].strip() for item in data["education_matches"]}
        data["gaps"] = [item for item in data["gaps"] if item["requirement"].strip() not in education_requirements]
    return data


def validate_generated_spec(value: Any, repository, selected_ids: set[str], selected_skill_names=None) -> dict[str, Any]:
    data = _object(value, "ResumeSpec")
    required = {"generation_id", "language", "template", "theme", "density", "show_photo", "photo", "profile", "section_titles", "section_order", "education", "experiences", "projects", "skills"}
    missing = sorted(required - set(data))
    if missing:
        raise ValueError("ResumeSpec 缺少字段：" + "、".join(missing))
    if data.get("language") != "zh" or data.get("generation_id") != "draft":
        raise ValueError("ResumeSpec 的 language 或 generation_id 无效")
    if data.get("template") != "classic" or data.get("theme") not in {"blue", "charcoal", "green"} or data.get("density") not in {"normal", "compact"}:
        raise ValueError("ResumeSpec 的模板、主题或密度枚举无效")
    if not isinstance(data.get("show_photo"), bool):
        raise ValueError("ResumeSpec.show_photo 必须是布尔值")
    for key in ("photo", "profile", "section_titles"):
        _object(data.get(key), f"ResumeSpec.{key}")
    for key in ("width", "height", "position"):
        _text(data["photo"].get(key), f"photo.{key}", False)
    for key in ("education", "experiences", "projects", "skills", "section_order"):
        _list(data, key, "ResumeSpec")
    sections = data["section_order"]
    if not all(isinstance(item, str) for item in sections) or len(sections) != len(set(sections)) or any(item not in {"education", "experience", "projects", "skills"} for item in sections):
        raise ValueError("ResumeSpec.section_order 包含重复或未知板块")
    for key in ("name", "phone", "email", "location", "summary"):
        _text(data["profile"].get(key), f"profile.{key}")
    _chinese(data["profile"].get("summary", ""), "profile.summary")
    for key in ("education", "experience", "projects", "skills"):
        _chinese(_text(data["section_titles"].get(key), f"section_titles.{key}", False), f"section_titles.{key}")
    for index, item in enumerate(data["education"]):
        item = _object(item, f"education[{index}]")
        for key in ("education_id", "school", "degree", "major", "date", "details"):
            _text(item.get(key), f"education[{index}].{key}")
    evidence = repository.evidence_index()
    experiences = repository.experience_index()
    for entry in data["experiences"] + data["projects"]:
        entry = _object(entry, "经历项")
        experience_id = entry.get("experience_id")
        if experience_id not in experiences:
            raise ValueError(f"ResumeSpec 引用未知经历：{experience_id}")
        for key in ("organization", "title", "date", "location"):
            _text(entry.get(key), f"经历项.{key}")
        for bullet in _list(entry, "bullets", "经历项"):
            bullet = _object(bullet, "bullet")
            _chinese(_text(bullet.get("text"), "bullet.text", False), "bullet.text")
            ids = _list(bullet, "evidence_ids", "bullet")
            if not ids or not all(isinstance(eid, str) for eid in ids):
                raise ValueError("ResumeSpec bullet 未关联证据")
            for eid in ids:
                if eid not in selected_ids or eid not in evidence:
                    raise ValueError(f"ResumeSpec 引用未选择证据：{eid}")
                if evidence[eid].get("status") == "rejected" or evidence[eid].get("experience_id") != experience_id:
                    raise ValueError(f"ResumeSpec 证据不可用或归属错误：{eid}")
    confirmed_skills = {str(x.get("name", "")).strip() for x in repository.skills() if x.get("user_confirmed") is True}
    for skill in data["skills"]:
        skill = _object(skill, "技能项")
        name = _text(skill.get("name"), "skills.name", False).strip()
        if selected_skill_names is not None and name not in selected_skill_names:
            raise ValueError(f"模型加入了未选择技能：{name}")
        description = _text(skill.get("description", ""), "skills.description").strip()
        ids = skill.get("evidence_ids", [])
        if not isinstance(ids, list) or not all(isinstance(eid, str) for eid in ids):
            raise ValueError("skills.evidence_ids 必须是数组")
        flag = skill.get("user_confirmed")
        if "user_confirmed" in skill and (not isinstance(flag, bool) or flag != (name in confirmed_skills)):
            raise ValueError(f"技能 user_confirmed 不能由模型新增或修改：{name}")
        if not ids and not (skill.get("user_confirmed") is True and name in confirmed_skills):
            raise ValueError(f"技能缺少合法证据：{name}")
        # A generated explanation is part of the model output contract.  It
        # may be omitted, but when present it must belong to a skill that has
        # the same evidence/user-confirmed support as the skill name.  Manual
        # editing is validated by the lighter ResumeSpec structure check.
        if description and not ids and not (skill.get("user_confirmed") is True and name in confirmed_skills):
            raise ValueError(f"技能说明缺少合法证据：{name}")
        for eid in ids:
            if selected_skill_names is not None and not any(
                item.get("name") == name and eid in item.get("evidence_ids", [])
                for item in repository.skills()
            ):
                raise ValueError(f"技能引用了不属于该技能的证据：{name}")
            if eid not in selected_ids or eid not in evidence or evidence[eid].get("status") == "rejected":
                raise ValueError(f"技能引用未选择或不可用证据：{eid}")
    return data


def validate_skill_descriptions(value, sources):
    data = _object(value, "技能描述结果")
    descriptions = _object(data.get("descriptions"), "descriptions")
    if set(descriptions) - set(sources):
        raise ValueError("模型返回了未知技能")
    result = {}
    for name, source in sources.items():
        text = _text(descriptions.get(name, ""), "技能描述").strip()
        _chinese_or_technical(text, "技能描述")
        # Lightweight lexical guard, not a claim of general semantic verification.
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_+#./-]*|\d+(?:\.\d+)?%?", text)
        unsupported = [token for token in tokens if not re.search(
            r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])", source, re.I)]
        levels = ("熟练", "精通", "熟悉", "掌握")
        if unsupported or any(level in text and level not in source for level in levels):
            raise ValueError("技能描述包含来源未支持的工具、数字或熟练度")
        result[name] = text
    return result
