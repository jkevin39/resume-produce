from __future__ import annotations

import json
from copy import deepcopy
import os
import re
import time
from datetime import datetime
from typing import Any

import requests

from .ordering import catalog, validate_order, ordered, demo_order
from .education_match import demo_education_matches, demo_summary
from .models import PROVIDERS, selection, request_body, resolve_base_url
from .llm_validation import validate_extraction, validate_generated_spec, validate_jd_analysis, validate_match_report, validate_skill_descriptions
from .skill_selection import select_skills
from .prompts import ANALYZE_JD_PROMPT, BUILD_RESUME_SPEC_PROMPT, EXTRACT_EXPERIENCE_PROMPT, MATCH_EVIDENCE_PROMPT, PROMPT_VERSION, IMPORT_MATERIAL_PROMPT, MERGE_SKILL_PROMPT, SKILL_DESCRIPTION_PROMPT


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-flash"


class LLMError(RuntimeError):
    """A safe, user-facing DeepSeek failure without request or response contents."""

    def __init__(self, category: str, detail: str):
        super().__init__(detail)
        self.category = category


def format_llm_error(exc: Exception) -> str:
    if isinstance(exc, LLMError):
        labels = {
            "credentials": "密钥/余额错误",
            "configuration": "请求配置错误",
            "busy": "限流/服务拥堵",
            "output": "网络/超时/输出不合格",
        }
        return f"{labels[exc.category]}：{exc}"
    return f"网络/超时/输出不合格：{exc}"


class ResumeSkill:
    """LLM workflow with a deterministic local demo fallback."""

    def __init__(self, config: dict[str, Any], repository):
        self.config = config.get("llm", {})
        self.repository = repository
        if not self.config.get("mode"):
            raise ValueError("缺少 llm.mode；请显式设置为 demo 或 live")
        self.mode = str(self.config["mode"]).strip().lower()
        if self.mode not in {"demo", "live"}:
            raise ValueError("llm.mode 必须是 demo 或 live")
        self.settings = selection(self.config)
        self.provider = PROVIDERS[self.settings["provider"]]
        self.base_url = resolve_base_url(self.settings["provider"], self.config)
        self.call_metrics: list[dict[str, Any]] = []

    @property
    def demo_mode(self) -> bool:
        return self.mode == "demo"

    @property
    def runtime_label(self) -> str:
        return "demo（本地规则）" if self.demo_mode else f"live（{self.provider['name']} / {self.settings['model']} / 思考{'开启' if self.settings['thinking'] else '关闭'}）"

    def provenance(self, new_call: bool) -> dict[str, Any]:
        return {
            "service": "local-demo" if self.demo_mode else self.provider["name"],
            "model": "deterministic-demo" if self.demo_mode else self.settings["model"],
            "thinking": "not-applicable" if self.demo_mode else self.settings["thinking"],
            "mode": self.mode,
            "prompt_version": PROMPT_VERSION,
            "new_llm_call": bool(new_call and not self.demo_mode),
        }

    def extract_experience(self, text: str, source_ref: str) -> dict[str, Any]:
        if self.demo_mode:
            return self._demo_extract(text, source_ref)
        value = self._validate(validate_extraction, self._chat_json(EXTRACT_EXPERIENCE_PROMPT, text, "履历拆解"))
        value["source_refs"] = [source_ref]
        return value

    def import_new_material(self, text, source_ref):
        if self.demo_mode:
            lines = [x.strip() for x in text.splitlines() if x.strip()]
            if any(re.match(r"技能[：:]", x) for x in lines[1:]):
                raise ValueError("请拆分后分次导入，一次只导入一个对象")
            if lines and re.match(r"技能[：:]", lines[0]):
                value = lines[0].split(":" if ":" in lines[0] else "：", 1)[1].strip()
                parts = re.split(r"[，,:：\s]", value, maxsplit=1)
                return {"kind": "skill", "name": parts[0], "description": "，".join(parts[1:] + lines[1:])}
            return {"kind": "experience", "experience": self.extract_experience(text, source_ref)}
        value = self._chat_json(IMPORT_MATERIAL_PROMPT, text, "材料识别与整理")
        if value.get("kind") == "experience":
            experience = self._validate(validate_extraction, value.get("experience"))
            experience["source_refs"] = [source_ref]
            return {"kind": "experience", "experience": experience}
        if value.get("kind") == "skill":
            if not isinstance(value.get("name"), str) or not value["name"].strip() or not isinstance(value.get("description"), str):
                raise LLMError("output", "技能名称或描述格式不正确")
            return value
        raise ValueError("请拆分后分次导入；技能材料请明确已经掌握的能力")

    def merge_skill_description(self, name, description, text):
        if self.demo_mode:
            return "；".join(x.strip().rstrip("。；") for x in (description, text) if x.strip())
        value = self._chat_json(MERGE_SKILL_PROMPT, json.dumps(
            {"name": name, "description": description, "material": text}, ensure_ascii=False), "技能描述整合")
        if not isinstance(value.get("description"), str):
            raise LLMError("output", "技能描述格式不正确")
        return value["description"]

    def generate_skill_descriptions(self, analysis, options, evidence):
        available = [x for x in options if x["eligible"]]
        if not available:
            return {}
        sources = {x["name"]: "\n".join([x.get("description", "")] +
            [evidence[eid]["original_fact"] for eid in x.get("available_evidence_ids", [])]) for x in available}
        if self.demo_mode:
            return {name: source.split("\n")[0] or next((line for line in source.split("\n") if line), "")
                    for name, source in sources.items()}
        value = self._chat_json(SKILL_DESCRIPTION_PROMPT, json.dumps(
            {"analysis": analysis, "skills": [{"name": n, "sources": v} for n, v in sources.items()]}, ensure_ascii=False), "技能描述生成")
        return self._validate(validate_skill_descriptions, value, sources)

    def analyze_jd(self, jd_text: str) -> dict[str, Any]:
        if self.demo_mode:
            return self._demo_analyze(jd_text)
        return self._validate(validate_jd_analysis, self._chat_json(ANALYZE_JD_PROMPT, jd_text, "JD 分析"))

    def match(self, analysis: dict[str, Any]) -> dict[str, Any]:
        evidence = [
            {"evidence_id": item["evidence_id"], "experience_id": item.get("experience_id"), "status": item.get("status"),
             "original_fact": item.get("original_fact"), "structured_fact": item.get("structured_fact")}
            for item in self.repository.evidence_index().values() if item.get("status") != "rejected"
        ]
        education = [{key: row.get(key, "") for key in ("education_id", "school", "degree", "major", "date", "details")}
                     for row in self.repository.profile().get("education", [])]
        experiences = [{key: row.get(key, '') for key in ('experience_id', 'type', 'organization', 'title')}
                       for row in self.repository.experiences()]
        available_skills = select_skills(self.repository.skills(), self.repository.evidence_index(),
                                        [x['evidence_id'] for x in evidence], None)
        if self.demo_mode:
            value = self._demo_match(analysis, evidence)
            value['display_order'] = demo_order(analysis, self.repository.experiences(), available_skills)
            value["education_matches"] = demo_education_matches(analysis, education)
        else:
            value = self._chat_json(MATCH_EVIDENCE_PROMPT, json.dumps(
                {"analysis": analysis, "evidence": evidence, "education": education, "experiences": experiences, "skills": available_skills}, ensure_ascii=False), "证据匹配")
        if 'display_order' in value:
            value['display_order'] = self._validate(validate_order, value['display_order'], catalog(experiences, available_skills))
        return self._validate(validate_match_report, value, {item["evidence_id"] for item in evidence},
                              {row["education_id"] for row in education if row["education_id"]})

    def build_spec(self, language: str, selected_ids: list[str], company: str, role: str, analysis: dict[str, Any],
                   selected_skill_names: list[str] | None = None, skill_descriptions=None, display_order=None) -> dict[str, Any]:
        if language != "zh":
            raise ValueError("本版仅生成中文 ResumeSpec")
        selected = set(selected_ids)
        profile_data = self.repository.profile()
        experiences = self.repository.experiences()
        skills = select_skills(self.repository.skills(), self.repository.evidence_index(), selected,
                               selected_skill_names)
        if display_order is not None:
            display_order = validate_order(display_order, catalog(experiences, self.repository.skills()))
            experiences = ordered(experiences, display_order['experience'] + display_order['project'], 'experience_id')
            skills = ordered(skills, display_order['skills'], 'name')
        # Build the final selection before either the model or demo sees it.
        skills = deepcopy(skills)
        if skill_descriptions is not None:
            if (not isinstance(skill_descriptions, dict) or
                set(skill_descriptions) - {item["name"] for item in skills} or
                not all(isinstance(text, str) for text in skill_descriptions.values())):
                raise ValueError("技能描述格式不正确")
            for item in skills:
                if item["name"] in skill_descriptions:
                    item["description"] = skill_descriptions[item["name"]]
        def assemble(value):
            if skill_descriptions is not None or display_order is not None:
                value["skills"] = [{"name": item["name"], "description": item.get("description", ""),
                    "evidence_ids": [eid for eid in item.get("evidence_ids", []) if eid in selected],
                    "user_confirmed": item.get("user_confirmed") is True} for item in skills]
            if "section_titles" in value:
                if not isinstance(value["section_titles"], dict):
                    raise ValueError("ResumeSpec.section_titles 必须是 JSON 对象")
                value["section_titles"]["experience"] = "实习经历"
            if display_order is not None:
                for field, kind in (('experiences', 'experience'), ('projects', 'project')):
                    if field in value:
                        value[field] = ordered(value[field], display_order[kind], 'experience_id')
                # New generation owns its initial layout; ignore model-invented layout references.
                value.pop('layout', None)
            return value
        if self.demo_mode:
            value = self._demo_spec(selected, profile_data, experiences, skills)
            value["profile"]["summary"] = demo_summary(role, profile_data.get("education", []),
                                                       value["experiences"] + value["projects"], skills, analysis)
            return assemble(value)
        selected_evidence = []
        for experience in experiences:
            items = [item for item in experience.get("evidence", []) if item.get("evidence_id") in selected]
            if items:
                selected_evidence.append({
                    "experience_id": experience.get("experience_id"), "type": experience.get("type"),
                    "organization": experience.get("organization"), "title": experience.get("title"),
                    "date": experience.get("date"), "location": experience.get("location"), "evidence": items,
                })
        safe_profile = {"profile": {key: value for key, value in profile_data.get("profile", {}).items() if key not in {"photo_path", "summary"}}, "education": profile_data.get("education", [])}
        safe_skills = []
        for item in skills:
            ids = [eid for eid in item.get("evidence_ids", []) if eid in selected]
            if ids or item.get("user_confirmed") is True:
                safe_skills.append({
                    "name": item.get("name", ""),
                    "description": item.get("description", ""),
                    "evidence_ids": ids,
                    "user_confirmed": item.get("user_confirmed") is True,
                })
        context = {
            "language": language, "company": company, "role": role, "jd_analysis": analysis,
            "profile": safe_profile, "selected_evidence": selected_evidence, "skills": safe_skills,
            "display_order": ({
                'experience': [x['experience_id'] for x in selected_evidence if x.get('type') != 'project'],
                'project': [x['experience_id'] for x in selected_evidence if x.get('type') == 'project'],
                'skills': [x['name'] for x in safe_skills],
            } if display_order is not None else None),
        }
        value = self._chat_json(BUILD_RESUME_SPEC_PROMPT, json.dumps(context, ensure_ascii=False), "ResumeSpec 生成")
        return self._validate(validate_generated_spec, self._validate(assemble, value), self.repository, selected,
                              {item["name"] for item in skills})

    @staticmethod
    def _validate(validator, value, *args):
        try:
            return validator(value, *args)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise LLMError("output", str(exc)) from exc

    def _chat_json(self, system_prompt: str, user_text: str, stage: str) -> dict[str, Any]:
        key = os.environ.get(self.provider["env"], "").strip()
        if not key:
            raise LLMError("credentials", f"未配置 {self.provider['name']} 密钥（{self.provider['env']}），请配置后重启服务。")
        started = time.monotonic()
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
                json=request_body(self.settings, int(self.config.get("max_tokens", 8192)),
                    [{"role": "system", "content": system_prompt + "\n请只输出 JSON 对象。"},
                     {"role": "user", "content": user_text}]),
                timeout=int(self.config.get("timeout_seconds", 90)),
            )
        except requests.Timeout as exc:
            raise LLMError("output", "请求超时，请手工重试") from exc
        except requests.RequestException as exc:
            raise LLMError("output", "网络请求失败，请手工重试") from exc
        elapsed = round(time.monotonic() - started, 3)
        status = response.status_code
        if status in {401, 402}:
            raise LLMError("credentials", f"{self.provider['name']} 返回 HTTP {status}")
        if status in {429, 500, 502, 503, 504}:
            raise LLMError("busy", f"{self.provider['name']} 返回 HTTP {status}，请稍后手工重试")
        if status >= 400:
            raise LLMError("configuration", f"{self.provider['name']} 返回 HTTP {status}")
        try:
            payload = response.json()
            choice = payload["choices"][0]
            finish_reason = choice["finish_reason"]
            content = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("output", "响应结构缺失必要字段") from exc
        if finish_reason != "stop":
            raise LLMError("output", f"模型未正常完成（finish_reason={finish_reason}）")
        if not isinstance(content, str) or not content.strip():
            raise LLMError("output", "模型返回空内容")
        try:
            value = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError("output", "模型返回内容不是合法 JSON") from exc
        if not isinstance(value, dict):
            raise LLMError("output", "模型 JSON 顶层必须是对象")
        usage = payload.get("usage", {}) if isinstance(payload, dict) else {}
        self.call_metrics.append({"stage": stage, "elapsed_seconds": elapsed, "usage": usage if isinstance(usage, dict) else {}})
        return value

    def _demo_extract(self, text: str, source_ref: str) -> dict[str, Any]:
        stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")[-14:]
        lines = [line.strip(" -•\t") for line in text.splitlines() if line.strip()]
        heading = lines[0] if lines else "待补充经历"
        facts = lines[1:] or lines
        evidence = []
        for index, fact in enumerate(facts[:8], 1):
            has_detail = bool(re.search(r"\d|%|万|千|用户|提升|降低|完成|上线", fact))
            skills = [word for word in ("Python", "SQL", "Excel", "Java", "Docker", "Figma", "AI", "LLM") if word.lower() in fact.lower()]
            evidence.append({
                "evidence_id": f"ev_{stamp}_{index:02d}", "original_fact": fact,
                "structured_fact": {"action": fact, "method": "", "scale": "", "result": "", "skills": skills},
                "candidate_zh": fact,
                "status": "confirmed" if has_detail else "needs_details",
            })
        return {
            "experience_id": f"exp_{stamp}", "type": "project" if "项目" in heading else "experience",
            "organization": heading, "title": "", "date": "", "location": "",
            "source_refs": [source_ref], "evidence": evidence,
        }

    def _demo_analyze(self, jd_text: str) -> dict[str, Any]:
        lines = [line.strip(" -•\t") for line in jd_text.splitlines() if line.strip()]
        keywords = []
        for word in ("Python", "SQL", "Excel", "Java", "Docker", "Figma", "AI", "LLM", "数据分析", "产品", "英语"):
            if self._has_keyword(jd_text, word):
                keywords.append(word)
        required, preferred, responsibilities = [], [], []
        category = responsibilities
        for line in lines:
            lower = line.lower()
            if lower.rstrip(":") in {"requirements", "qualifications", "要求", "必备条件"}:
                category = required
                continue
            if lower.rstrip(":") in {"responsibilities", "职责", "工作职责"}:
                category = responsibilities
                continue
            target = preferred if any(k in lower for k in ("优先", "加分", "preferred", "plus")) else required if any(k in lower for k in ("必须", "要求", "学历", "学位", "本科", "硕士", "博士", "专科", "专业", "毕业", "在读", "bachelor", "master", "degree", "phd", "熟悉", "掌握", "required", "requirements")) else category
            if re.search(r"[\u4e00-\u9fff]", line):
                translated = line
            else:
                # Demo-only summaries for recognizable clauses; never invent a translation.
                terms = [word for word in keywords if word.lower() in lower]
                if re.search(r"bachelor|master|degree|phd|graduate", lower):
                    translated = "教育条件需核实：演示模式未完整解读英文教育要求，请配置模型或人工核对原 JD。"
                elif "dashboard" in lower:
                    translated = "构建指标看板并向产品团队沟通洞察。"
                elif "analy" in lower and ("feedback" in lower or "usage" in lower):
                    translated = "分析产品使用数据和用户反馈，识别改进机会。"
                elif "communication" in lower:
                    translated = "具备书面和口头沟通能力。"
                elif terms:
                    translated = "相关技术能力或经验：" + "、".join(terms)
                else:
                    translated = "演示模式未完整解读此条英文信息；请配置模型获取中文分析。"
            target.append(translated)
        return {
            "required": required[:8], "preferred": preferred[:8],
            "responsibilities": responsibilities[:12], "technical_keywords": keywords,
            "inferred_preferences": [],
        }

    def _demo_match(self, analysis: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        jd_words = {word.lower() for word in analysis.get("technical_keywords", [])}
        matches = []
        covered = set()
        for index, item in enumerate(evidence):
            fact = item.get("structured_fact", {})
            searchable = " ".join([
                str(item.get("original_fact", "")), str(fact.get("action", "")),
                str(fact.get("method", "")), str(fact.get("scale", "")),
                str(fact.get("result", "")), *map(str, fact.get("skills", [])),
            ])
            overlap = sorted(word for word in jd_words if self._has_keyword(searchable, word))
            category = "strong" if len(overlap) >= 2 else "partial" if overlap else "needs_details" if item.get("status") == "needs_details" else "not_applicable"
            if category != "not_applicable":
                covered.update(overlap)
            matches.append({
                "evidence_id": item["evidence_id"], "category": category,
                "reason": f"覆盖关键词：{', '.join(overlap[:5])}" if overlap else "演示模式未发现直接关键词重合",
                "priority": index + 1,
            })
        gaps = [{"requirement": "相关技能：" + word, "suggestion": "如有相关真实经历，请补充到履历库。"} for word in sorted(jd_words - covered)[:8]]
        return {"matches": matches, "gaps": gaps, "keyword_coverage": sorted(covered)}

    @staticmethod
    def _has_keyword(text: str, keyword: str) -> bool:
        if keyword.isascii():
            return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(keyword)}(?![A-Za-z0-9])", text, re.I))
        return keyword.lower() in text.lower()

    def _demo_spec(self, selected: set[str], profile_data: dict[str, Any], experiences: list[dict[str, Any]], skills: list[dict[str, Any]]) -> dict[str, Any]:
        result_experiences, result_projects = [], []
        for experience in experiences:
            bullets = []
            for evidence in experience.get("evidence", []):
                if evidence.get("evidence_id") in selected and evidence.get("status") != "rejected":
                    text = evidence.get("candidate_zh") or evidence.get("original_fact", "")
                    bullets.append({"text": text, "evidence_ids": [evidence["evidence_id"]]})
            if bullets:
                item = {
                    "experience_id": experience["experience_id"], "organization": experience.get("organization", ""),
                    "title": experience.get("title", ""), "date": experience.get("date", ""),
                    "location": experience.get("location", ""), "bullets": bullets,
                }
                (result_projects if experience.get("type") == "project" else result_experiences).append(item)
        usable_skills = []
        evidence_index = self.repository.evidence_index()
        for skill in skills:
            ids = [item for item in skill.get("evidence_ids", []) if item in selected and evidence_index.get(item, {}).get("status") != "rejected"]
            if ids or skill.get("user_confirmed"):
                usable_skills.append({
                    "name": skill.get("name", ""),
                    "description": skill.get("description", ""),
                    "evidence_ids": ids,
                    "user_confirmed": bool(skill.get("user_confirmed")),
                })
        profile = dict(profile_data.get("profile", {}))
        profile.pop("photo_path", None)
        return {
            "generation_id": "draft", "language": "zh", "template": "classic", "theme": "blue",
            "density": "normal", "show_photo": bool(profile_data.get("profile", {}).get("photo_path")),
            "photo": {"width": "25mm", "height": "32mm", "position": "center top"},
            "style": {"font_size": "10.5pt", "line_height": "1.42", "page_padding": "14mm 16mm", "section_gap": "4.2mm", "bullet_gap": ".7mm", "title_color": ""},
            "profile": {key: profile.get(key, "") for key in ("name", "phone", "email", "location", "summary")},
            "section_titles": {"education": "教育经历", "experience": "实习经历", "projects": "项目经历", "skills": "技能"},
            "section_order": ["education", "experience", "projects", "skills"],
            "education": profile_data.get("education", []), "experiences": result_experiences,
            "projects": result_projects, "skills": usable_skills,
        }
