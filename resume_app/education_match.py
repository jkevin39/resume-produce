"""Conservative local demo: ambiguous education requirements remain unverified."""
import re


def demo_education_matches(analysis, education):
    results = []
    degrees = ("专科", "本科", "硕士", "博士")
    for requirement in dict.fromkeys(analysis.get("required", []) + analysis.get("preferred", [])):
        if not re.search(r"教育|学历|学位|本科|硕士|博士|专科|学士|专业|毕业|在读|应届", requirement):
            continue
        ids = [row["education_id"] for row in education if row.get("education_id")]
        status, reason = "needs_confirmation", "演示模式仅比较明确学历字段；专业、毕业状态或其他条件请人工核实。"
        targets = [i for i, degree in enumerate(degrees) if degree in requirement]
        known = [(row["education_id"], next((i for i, degree in reversed(list(enumerate(degrees)))
                  if degree in row.get("degree", "")), None)) for row in education if row.get("education_id")]
        if not education:
            reason = "尚未提供教育记录，请在工作台补充后重新分析。"
        elif len(targets) == 1 and re.fullmatch(r"(?:要求|学历要求|学历|学位|需|具备|具有|至少|最低)?[：: ]*"
                                                r"(?:专科|本科|硕士|博士)(?:学历|学位)?(?:及以上|以上)?[。！ ]*", requirement):
            ranks = [rank for _, rank in known if rank is not None]
            if ranks:
                minimum = "以上" in requirement or "至少" in requirement or "最低" in requirement
                matched = [eid for eid, rank in known if rank is not None and
                           (rank >= targets[0] if minimum else rank == targets[0])]
                if matched:
                    status, ids, reason = "met", matched, "已提供的学历字段符合该条件；不额外推断毕业状态。"
                elif len(ranks) == len(education):
                    status, reason = "unmet", "已提供的学历字段不符合该条件。"
        results.append({"requirement": requirement, "status": status, "reason": reason, "education_ids": ids})
    return results


def demo_summary(role, education, entries, skills, analysis):
    """Short sourced sentences; never pad sparse materials or reuse old summary."""
    sentences = []
    if role:
        sentences.append(f"求职方向为{role}。")
    if education:
        row = education[0]
        background = "、".join(row.get(k, "") for k in ("degree", "major") if row.get(k))
        if background:
            sentences.append(f"教育背景：{background}。")
    for skill in skills:
        text = skill.get("description", "").strip()
        sentence = f"{skill['name']}：{text}。" if text else f"已选技能包括{skill['name']}。"
        if len("".join(sentences)) + len(sentence) <= 120:
            sentences.append(sentence)
    keywords = analysis.get("technical_keywords", [])
    facts = [bullet["text"] for entry in entries for bullet in entry.get("bullets", [])]
    facts.sort(key=lambda text: -sum(word.lower() in text.lower() for word in keywords))
    for fact in facts:
        sentence = re.split(r"[。；]", fact, maxsplit=1)[0].strip() + "。"
        if len("".join(sentences)) + len(sentence) <= 120:
            sentences.append(sentence)
        if len("".join(sentences)) >= 80:
            break
    return "".join(sentences)
