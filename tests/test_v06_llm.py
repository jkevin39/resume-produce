from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from app import create_app
from resume_app.prompts import (
    ANALYZE_JD_PROMPT, BUILD_RESUME_SPEC_PROMPT, EXTRACT_EXPERIENCE_PROMPT,
    MATCH_EVIDENCE_PROMPT, PROMPT_VERSION,
)
from resume_app.skill import LLMError, ResumeSkill
from resume_app.rendering import ResumeRenderer
from resume_app.storage import ProfileRepository, read_yaml, write_yaml
from tests.live_deepseek_acceptance import save_html_artifact
from tests.support import copy_test_workspace



def response(content, finish_reason="stop", status=200, usage=None):
    result = Mock()
    result.status_code = status
    result.json.return_value = {
        "choices": [{"finish_reason": finish_reason, "message": {"content": content}}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    return result


class V06LLMTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        copy_test_workspace(self.root)
        self.live = {"llm": {"mode": "live", "base_url": "https://api.deepseek.com", "model": "deepseek-flash", "timeout_seconds": 7, "max_tokens": 4096}}
        write_yaml(self.root / "config.yaml", self.live)
        self.repo = ProfileRepository(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_four_versioned_prompts_have_json_examples(self):
        self.assertEqual(PROMPT_VERSION, "v0.11.1-fgh")
        for prompt in (EXTRACT_EXPERIENCE_PROMPT, ANALYZE_JD_PROMPT, MATCH_EVIDENCE_PROMPT, BUILD_RESUME_SPEC_PROMPT):
            self.assertIn("JSON", prompt)
            self.assertIn("示例", prompt)
            json.loads(prompt[prompt.index("{"):])

    def test_four_entry_points_use_their_prompts(self):
        skill = ResumeSkill(self.live, self.repo)
        spec = ResumeSkill({"llm": {"mode": "demo"}}, self.repo).build_spec("zh", ["ev_feedback_001"], "公司", "岗位", {})
        spec["profile"]["phone"] = str(spec["profile"]["phone"])
        outputs = [
            {"experience_id": "draft", "type": "project", "organization": "项目", "title": "", "date": "", "location": "", "source_refs": [], "evidence": [{"evidence_id": "draft", "original_fact": "使用 Python", "structured_fact": {"action": "使用 Python", "method": "Python", "scale": "", "result": "", "skills": ["Python"]}, "candidate_zh": "使用 Python 完成数据处理。", "status": "needs_details"}]},
            {"required": ["掌握 Python"], "preferred": [], "responsibilities": [], "technical_keywords": ["Python"], "inferred_preferences": []},
            {"matches": [], "gaps": [], "keyword_coverage": [], "education_matches": []},
            spec,
        ]
        with patch.object(skill, "_chat_json", side_effect=outputs) as chat:
            skill.extract_experience("材料", "synthetic")
            analysis = skill.analyze_jd("JD")
            skill.match(analysis)
            skill.build_spec("zh", ["ev_feedback_001"], "公司", "岗位", analysis)
        self.assertEqual([call.args[0] for call in chat.call_args_list], [
            EXTRACT_EXPERIENCE_PROMPT, ANALYZE_JD_PROMPT, MATCH_EVIDENCE_PROMPT, BUILD_RESUME_SPEC_PROMPT,
        ])

    def test_live_config_key_and_request_contract(self):
        with self.assertRaisesRegex(ValueError, "llm.mode"):
            ResumeSkill({"llm": {}}, self.repo)
        skill = ResumeSkill(self.live, self.repo)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(LLMError, "DEEPSEEK_API_KEY"):
                skill.analyze_jd("中文 JD")
        valid = {"required": ["掌握 Python"], "preferred": [], "responsibilities": [], "technical_keywords": ["Python"], "inferred_preferences": []}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret"}), patch("resume_app.skill.requests.post", return_value=response(json.dumps(valid, ensure_ascii=False))) as post:
            self.assertEqual(skill.analyze_jd("JD"), valid)
        call = post.call_args
        self.assertEqual(call.kwargs["timeout"], 7)
        self.assertEqual(call.kwargs["json"]["max_tokens"], 4096)
        self.assertEqual(call.kwargs["json"]["thinking"], {"type": "disabled"})
        self.assertEqual(call.kwargs["json"]["response_format"], {"type": "json_object"})
        self.assertNotIn("secret", json.dumps(call.kwargs["json"]))

    def test_response_failures_and_http_categories(self):
        skill = ResumeSkill(self.live, self.repo)
        cases = [
            (response("{}", "length"), "output"),
            (response("{}", "content_filter"), "output"),
            (response("{}", "insufficient_system_resource"), "output"),
            (response("not json"), "output"),
            (response(""), "output"),
            (response("{}", status=401), "credentials"),
            (response("{}", status=402), "credentials"),
            (response("{}", status=400), "configuration"),
            (response("{}", status=429), "busy"),
            (response("{}", status=503), "busy"),
        ]
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret"}):
            for mocked, category in cases:
                with self.subTest(category=category, status=mocked.status_code):
                    with patch("resume_app.skill.requests.post", return_value=mocked), self.assertRaises(LLMError) as caught:
                        skill.analyze_jd("JD")
                    self.assertEqual(caught.exception.category, category)
            for exception in (requests.Timeout(), requests.ConnectionError()):
                with patch("resume_app.skill.requests.post", side_effect=exception), self.assertRaises(LLMError) as caught:
                    skill.analyze_jd("JD")
                self.assertEqual(caught.exception.category, "output")

    def test_structural_language_and_evidence_validation(self):
        skill = ResumeSkill(self.live, self.repo)
        bad_analysis = {"required": ["Python"], "preferred": [], "responsibilities": ["Analyze customer data"], "technical_keywords": ["Python"], "inferred_preferences": []}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret"}), patch("resume_app.skill.requests.post", return_value=response(json.dumps(bad_analysis))):
            with self.assertRaisesRegex(LLMError, "中文"):
                skill.analyze_jd("JD")
        bad_match = {"matches": [{"evidence_id": "unknown", "category": "strong", "reason": "匹配", "priority": 1}], "gaps": [], "keyword_coverage": []}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret"}), patch("resume_app.skill.requests.post", return_value=response(json.dumps(bad_match, ensure_ascii=False))):
            with self.assertRaisesRegex(LLMError, "未知证据"):
                skill.match({"required": [], "preferred": [], "responsibilities": [], "technical_keywords": [], "inferred_preferences": []})
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret"}), patch("resume_app.skill.requests.post", return_value=response("{}")):
            with self.assertRaisesRegex(LLMError, "ResumeSpec 缺少字段"):
                skill.build_spec("zh", ["ev_feedback_001"], "公司", "岗位", {})

    def test_failure_does_not_create_generation_or_csv(self):
        app = create_app(self.root, testing=True)
        client = app.test_client()
        before = {p.relative_to(self.root / "data").as_posix(): p.read_bytes() for p in (self.root / "data").rglob("*") if p.is_file()}
        bad = response("not json")
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret"}), patch("resume_app.skill.requests.post", return_value=bad):
            result = client.post("/prepare", data={"company": "公司", "role": "岗位", "jd_text": "JD"})
        self.assertEqual(result.status_code, 502)
        self.assertIn("JD 分析失败", result.get_data(as_text=True))
        self.assertFalse((self.root / "applications.csv").exists())
        self.assertEqual(list((self.root / "outputs").glob("gen-*")), [])
        after = {p.relative_to(self.root / "data").as_posix(): p.read_bytes() for p in (self.root / "data").rglob("*") if p.is_file()}
        self.assertEqual(after, before)

        valid_analysis = {"required": ["掌握 Python"], "preferred": [], "responsibilities": [], "technical_keywords": ["Python"], "inferred_preferences": []}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret"}), patch("resume_app.skill.requests.post", side_effect=[response(json.dumps(valid_analysis, ensure_ascii=False)), response("not json")]):
            matched = client.post("/prepare", data={"company": "公司", "role": "岗位", "jd_text": "JD"})
        self.assertEqual(matched.status_code, 502)
        self.assertIn("证据匹配失败", matched.get_data(as_text=True))

        generation_form = {
            "company": "公司", "role": "岗位", "jd_text": "JD",
            "analysis_json": json.dumps(valid_analysis, ensure_ascii=False),
            "match_json": json.dumps({"matches": [], "gaps": [], "keyword_coverage": [], "education_matches": []}),
            "evidence_ids": ["ev_feedback_001"],
        }
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret"}), patch("resume_app.skill.requests.post", return_value=response("{}")):
            generated = client.post("/generate", data=generation_form)
        self.assertEqual(generated.status_code, 502)
        self.assertIn("ResumeSpec 生成失败", generated.get_data(as_text=True))
        self.assertEqual(app.extensions["resume_drafts"], {})
        self.assertFalse((self.root / "applications.csv").exists())
        self.assertEqual(list((self.root / "outputs").glob("gen-*")), [])

        extraction = {
            "experience_id": "draft", "type": "project", "organization": "项目", "title": "", "date": "", "location": "", "source_refs": [],
            "evidence": [{"evidence_id": "draft", "original_fact": "fact", "structured_fact": {"action": "", "method": "", "scale": "", "result": "", "skills": []}, "candidate_zh": "English only", "status": "confirmed"}],
        }
        before_experiences = sorted((self.root / "data/experiences").glob("*.yaml"))
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret"}), patch("resume_app.skill.requests.post", return_value=response(json.dumps({"kind": "experience", "experience": extraction}))):
            imported = client.post("/profile/import", data={"source_text": "synthetic input"})
        self.assertEqual(imported.status_code, 502)
        self.assertEqual(sorted((self.root / "data/experiences").glob("*.yaml")), before_experiences)

    def test_selected_evidence_rechecked_and_provenance_inherited(self):
        write_yaml(self.root / "config.yaml", {"llm": {"mode": "demo"}})
        app = create_app(self.root, testing=True)
        client = app.test_client()
        form = {
            "company": "公司", "role": "岗位", "jd_text": "需要 Python",
            "analysis_json": json.dumps({"technical_keywords": ["Python"]}),
            "match_json": json.dumps({"matches": [], "gaps": [], "keyword_coverage": [], "education_matches": []}),
            "evidence_ids": ["ev_feedback_001"],
        }
        made = client.post("/generate", data=form)
        identifier = made.location.rsplit("/", 1)[-1]
        drafts = app.extensions["resume_drafts"]
        spec = deepcopy(drafts[identifier]["context"].spec)
        spec.pop("layout")  # Legacy input gains a layout once.
        spec["skills"] = [{"name": "人工新增技能", "evidence_ids": [], "user_confirmed": "true"}]
        rejected_type = client.post(f"/api/drafts/{identifier}/save", json={"spec": spec})
        self.assertIn("必须是布尔值", " ".join(rejected_type.get_json()["errors"]))
        spec["skills"][0]["user_confirmed"] = True
        saved = client.post(f"/api/drafts/{identifier}/save", json={"spec": spec})
        self.assertEqual(saved.status_code, 200)
        metadata = read_yaml(self.root / "outputs" / identifier / "metadata.yaml", {})
        self.assertEqual(metadata["llm"]["prompt_version"], PROMPT_VERSION)
        continued = client.post(f"/generations/{identifier}/zh/continue")
        child = continued.location.rsplit("/", 1)[-1]
        child_metadata = drafts[child]["metadata"]
        self.assertFalse(child_metadata["llm"]["new_llm_call"])
        self.assertEqual(child_metadata["llm"]["model"], metadata["llm"]["model"])

    def test_legacy_provenance_is_unknown(self):
        self.assertEqual(
            __import__("app").normalize_provenance(None),
            {"service": "unknown", "model": "unknown", "mode": "unknown", "thinking": "未记录", "prompt_version": "unknown", "new_llm_call": False},
        )

    def test_acceptance_artifact_preserves_exact_html_and_spec(self):
        spec = ResumeSkill({"llm": {"mode": "demo"}}, self.repo).build_spec(
            "zh", ["ev_feedback_001"], "公司", "岗位", {}
        )
        target = self.root / "acceptance-artifact" / "01-中文-JD"
        save_html_artifact(ResumeRenderer(self.repo, self.root), spec, target)
        self.assertEqual(json.loads((target / "resume-spec.json").read_text(encoding="utf-8")), spec)
        html = (target / "resume.html").read_text(encoding="utf-8")
        self.assertIn(spec["profile"]["name"], html)
        self.assertIn('<style id="base-css">', html)
        self.assertIn('<style id="custom-css">', html)


if __name__ == "__main__":
    unittest.main()
