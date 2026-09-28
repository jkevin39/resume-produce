from __future__ import annotations

import base64
import csv
import io
import json
import shutil
import tempfile
import threading
import unittest
from copy import deepcopy
from pathlib import Path
from html.parser import HTMLParser
from unittest.mock import patch, Mock

from app import create_app
from resume_app.drafts import SnapshotResources, normalize_spec
from resume_app.skill import ResumeSkill
from resume_app.storage import ProfileRepository, read_yaml, referenced_evidence_ids, write_yaml
from tests.support import FIXTURES, PROJECT, copy_test_workspace

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
JPEG = base64.b64decode("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAACAAIDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDxyiiiv3E8w//Z")
JD = '\nData Product Intern\nRequirements:\nPython and SQL required.\nLLM experience preferred.\n"feedback, insights"\n'


class MVPFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        copy_test_workspace(self.root)
        write_yaml(self.root / "config.yaml", {"llm": {"mode": "demo"}})
        self.app = create_app(self.root, testing=True)
        self.client = self.app.test_client()
        self.repo = self.app.extensions["resume_repository"]
        self.store = self.app.extensions["resume_store"]
        self.drafts = self.app.extensions["resume_drafts"]

    def tearDown(self):
        self.temp.cleanup()

    def form(self, **changes):
        form = {
            "company": "Example Co", "role": "数据产品实习生", "jd_text": JD,
            "analysis_json": json.dumps({"technical_keywords": ["Python", "SQL", "LLM"]}),
            "match_json": json.dumps({"matches": [], "gaps": [], "keyword_coverage": []}),
            "evidence_ids": ["ev_feedback_001", "ev_dashboard_001", "ev_rag_001"],
            "skill_names": ["Python", "Excel"],
        }
        form.update(changes)
        if "skill_names" not in changes:
            form["skill_names"] = [item["name"] for item in self.repo.skills()
                                   if item.get("user_confirmed") or set(item.get("evidence_ids", [])) & set(form["evidence_ids"])]
        return form

    def draft(self, **changes):
        response = self.client.post("/generate", data=self.form(**changes))
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        return response.location.split("/")[-1]

    def save(self, identifier, **payload):
        response = self.client.post(f"/api/drafts/{identifier}/save", json=payload)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return self.root / "outputs" / identifier

    def continue_draft(self, identifier):
        response = self.client.post(f"/generations/{identifier}/zh/continue")
        self.assertEqual(response.status_code, 302)
        return response.location.split("/")[-1]

    def rows(self):
        if not self.store.csv_path.exists():
            return []
        with self.store.csv_path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def tree(self, folder):
        return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}

    def test_english_jd_only_chinese_and_no_record_until_save(self):
        identifier = self.draft()
        self.assertEqual(self.rows(), [])
        self.assertFalse((self.root / "outputs" / identifier).exists())
        self.assertEqual(self.drafts[identifier]["context"].spec["language"], "zh")
        folder = self.save(identifier)
        metadata = read_yaml(folder / "metadata.yaml", {})
        self.assertEqual(metadata["languages"], ["zh"])
        self.assertEqual(metadata["jd_text"], JD)
        self.assertFalse((folder / "en").exists())
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["language"], "zh")
        self.assertEqual(self.client.post(f"/api/drafts/{identifier}/save", json={}).status_code, 410)
        self.assertEqual(len(self.rows()), 1)

    def test_backend_blocks_english_generation_edit_and_save(self):
        self.assertEqual(self.client.post("/generate", data=self.form(language="en")).status_code, 400)
        self.assertEqual(self.client.post("/generate", data=self.form(language="both")).status_code, 400)
        identifier = self.draft()
        spec = deepcopy(self.drafts[identifier]["context"].spec)
        spec["language"] = "en"
        self.assertEqual(self.client.post(f"/api/drafts/{identifier}/save", json={"spec": spec}).status_code, 400)
        self.assertEqual(self.client.post(f"/generations/{identifier}/en/continue").status_code, 400)
        self.assertFalse(self.rows())

    def test_real_llm_contract_only_zh_call_and_chinese_prompts(self):
        demo_spec = ResumeSkill({"llm": {"mode": "demo"}}, self.repo).build_spec("zh", ["ev_feedback_001"], "", "", {})
        demo_spec["profile"]["phone"] = str(demo_spec["profile"]["phone"])
        write_yaml(self.root / "config.yaml", {"llm": {"mode": "live", "base_url": "https://api.deepseek.com", "model": "deepseek-flash"}})
        client = create_app(self.root, testing=True).test_client()
        results = [
            {"required": ["掌握 Python"], "preferred": [], "responsibilities": ["分析反馈"], "technical_keywords": ["Python"], "inferred_preferences": []},
            {"matches": [], "gaps": [{"requirement": "用户研究", "suggestion": "补充真实经历"}], "keyword_coverage": [], "education_matches": []},
            {"descriptions": {"Excel": ""}},
            demo_spec,
        ]
        responses = []
        for value in results:
            response = Mock()
            response.status_code = 200
            response.json.return_value = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value, ensure_ascii=False)}}]}
            responses.append(response)
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}), patch("resume_app.skill.requests.post", side_effect=responses) as post:
            prepared = client.post("/prepare", data={"company": "公司", "role": "岗位", "jd_text": JD})
            self.assertEqual(prepared.status_code, 200)
            generated = client.post("/generate", data=self.form(evidence_ids=["ev_feedback_001"]))
            self.assertEqual(generated.status_code, 302)
            self.assertEqual(post.call_count, 4)  # analysis, match, skill descriptions, one Chinese spec
            for call in post.call_args_list:
                self.assertIn("中文", call.kwargs["json"]["messages"][0]["content"])
                self.assertEqual(call.args[0], "https://api.deepseek.com/chat/completions")
                self.assertEqual(call.kwargs["json"]["thinking"], {"type": "disabled"})
                self.assertFalse(call.kwargs["json"]["stream"])
            final_context = json.loads(post.call_args_list[-1].kwargs["json"]["messages"][1]["content"])
            self.assertEqual(final_context["language"], "zh")
            self.assertIn("selected_evidence", final_context)
            self.assertNotIn("experiences", final_context)
            self.assertNotIn("photo_path", final_context["profile"]["profile"])
            sent_ids = {item["evidence_id"] for entry in final_context["selected_evidence"] for item in entry["evidence"]}
            self.assertEqual(sent_ids, {"ev_feedback_001"})

    def test_demo_analysis_is_chinese(self):
        analysis = ResumeSkill({"llm": {"mode": "demo"}}, self.repo).analyze_jd(JD)
        for field in ("required", "preferred", "responsibilities"):
            for text in analysis[field]:
                self.assertRegex(text, r"[\u4e00-\u9fff]")
        self.assertNotIn("AI", ResumeSkill({"llm": {"mode": "demo"}}, self.repo).analyze_jd("Maintain dashboards with SQL")["technical_keywords"])

    def test_multiline_and_empty_fields_remain_editable(self):
        identifier = self.draft()
        spec = deepcopy(self.drafts[identifier]["context"].spec)
        spec["profile"]["summary"] = ""
        spec["education"][0]["details"] = ""
        html = self.client.post(f"/api/drafts/{identifier}/preview", json={"spec":spec}).get_json()["html"]
        self.assertIn('data-path="profile.summary"', html)
        self.assertIn('data-path="education.0.details"', html)
        spec["profile"]["summary"] = "第一行\n第二行"
        folder = self.save(identifier, spec=spec)
        self.assertIn("第一行\n第二行", (folder / "zh/resume.html").read_text(encoding="utf-8"))
        continued = self.continue_draft(identifier)
        self.assertEqual(self.drafts[continued]["context"].spec["profile"]["summary"], "第一行\n第二行")

    def test_edit_and_saved_layout_share_optional_nodes(self):
        identifier = self.draft()
        spec = deepcopy(self.drafts[identifier]["context"].spec)
        spec["profile"]["summary"] = ""
        spec["education"][0]["details"] = ""
        editable = self.client.post(f"/api/drafts/{identifier}/preview", json={"spec": spec}).get_json()["html"]
        exported = self.client.post(f"/api/drafts/{identifier}/export", json={"spec": spec}).get_data(as_text=True)
        for html in (editable, exported):
            self.assertIn('class="summary optional-line"', html)
            self.assertIn('class="optional-line"', html)
        self.assertRegex(editable, r'<article class="[^"]*editable-page')
        self.assertNotRegex(exported, r'<article class="[^"]*editable-page')
        self.assertIn("position: absolute", editable)
        self.assertIn("@media print", editable)

    def test_editor_exposes_delete_actions_and_removed_rejected_refs_can_save(self):
        identifier = self.draft(evidence_ids=["ev_feedback_001"])
        editable = self.client.post(f"/api/drafts/{identifier}/preview", json={}).get_json()["html"]
        self.assertNotIn('data-remove-path="experiences.0"', editable)
        self.assertNotIn('删除整段', editable)
        self.assertNotIn('data-remove-path="experiences.0.bullets.0"', editable)
        self.assertNotIn('data-remove-path="skills.0"', editable)
        spec = deepcopy(self.drafts[identifier]["context"].spec)
        self.repo.set_evidence_status("ev_feedback_001", "rejected")
        spec["experiences"] = [item for item in spec["experiences"] if "ev_feedback_001" not in referenced_evidence_ids({"experiences": [item]})]
        spec["skills"] = [item for item in spec["skills"] if "ev_feedback_001" not in item.get("evidence_ids", [])]
        spec.pop("layout")  # Exercise a legacy caller without layout.
        self.assertEqual(self.client.post(f"/api/drafts/{identifier}/save", json={"spec": spec}).status_code, 200)

    def test_all_display_fields_restore_and_yaml_unchanged(self):
        original_data = self.tree(self.root / "data")
        identifier = self.draft()
        spec = deepcopy(self.drafts[identifier]["context"].spec)
        paths = [
            "profile.name", "profile.phone", "profile.email", "profile.location", "profile.summary",
            "education.0.school", "education.0.degree", "education.0.major", "education.0.date", "education.0.details",
            "experiences.0.organization", "experiences.0.title", "experiences.0.date", "experiences.0.location", "experiences.0.bullets.0.text",
            "projects.0.organization", "projects.0.title", "projects.0.date", "projects.0.location", "projects.0.bullets.0.text",
            "skills.0.name", "section_titles.skills",
        ]
        for index, path in enumerate(paths):
            obj = spec
            keys = path.split(".")
            for key in keys[:-1]:
                obj = obj[int(key)] if isinstance(obj, list) else obj[key]
            obj[keys[-1]] = f"编辑字段{index}"
        old = self.save(identifier, spec=spec, custom_css=".resume-page { letter-spacing: .01em; }")
        old_bytes = self.tree(old)
        continued = self.continue_draft(identifier)
        restored = self.drafts[continued]["context"].spec
        for key in ("profile", "education", "experiences", "projects", "skills", "section_titles"):
            self.assertEqual(restored[key], spec[key])
        self.assertNotEqual(continued, identifier)
        self.save(continued)
        self.assertEqual(self.tree(old), old_bytes)
        self.assertEqual(self.tree(self.root / "data"), original_data)
        metadata = read_yaml(self.root / "outputs" / continued / "metadata.yaml", {})
        self.assertEqual(metadata["parent_generation_id"], identifier)
        self.assertEqual(metadata["jd_text"], JD)

    def test_resource_context_frozen_and_explicit_refresh(self):
        self.repo.save_photo("photo.png", PNG)
        identifier = self.draft()
        context = self.drafts[identifier]["context"]
        old_photo, old_css = context.photo_data_url, context.base_css
        self.assertTrue(context.spec["show_photo"])
        self.repo.save_photo("photo.jpeg", JPEG)
        (self.root / "static/css/resume.css").write_text("/* changed globally */", encoding="utf-8")
        preview = self.client.post(f"/api/drafts/{identifier}/preview", json={}).get_json()["html"]
        exported = self.client.post(f"/api/drafts/{identifier}/export", json={}).get_data(as_text=True)
        for html in (preview, exported):
            self.assertIn(old_photo, html)
            self.assertIn(old_css, html)
            self.assertNotIn("changed globally", html)
        (self.root / self.repo.profile()["profile"]["photo_path"]).unlink()
        folder = self.save(identifier)  # No dependency on now missing global image
        self.assertIn(old_photo, (folder / "zh/resume.html").read_text(encoding="utf-8"))
        continued = self.continue_draft(identifier)
        self.assertEqual(self.drafts[continued]["context"].photo_data_url, old_photo)
        refreshed = self.client.post(f"/api/drafts/{continued}/refresh", json={"part": "css"})
        self.assertIn("changed globally", refreshed.get_json()["html"])
        self.repo.save_photo("photo.png", PNG + b"new")
        self.client.post(f"/api/drafts/{continued}/refresh", json={"part": "photo"})
        self.assertNotEqual(self.drafts[continued]["context"].photo_data_url, old_photo)

    def test_profile_only_changes_on_explicit_refresh(self):
        identifier = self.draft()
        profile = self.repo.profile()
        profile["profile"]["name"] = "新全局姓名"
        write_yaml(self.root / "data/profile.yaml", profile)
        self.assertNotEqual(self.drafts[identifier]["context"].spec["profile"]["name"], "新全局姓名")
        data = self.client.post(f"/api/drafts/{identifier}/refresh", json={"part": "profile"}).get_json()
        self.assertEqual(data["spec"]["profile"]["name"], "新全局姓名")
        self.assertIn("新全局姓名", data["html"])

    def test_export_skips_content_validation_and_never_persists(self):
        identifier = self.draft()
        original_spec = deepcopy(self.drafts[identifier]["context"].spec)
        spec = deepcopy(original_spec)
        spec["profile"]["name"] = ""
        spec["experiences"][0]["bullets"][0]["evidence_ids"] = ["does-not-exist"]
        exported = self.client.post(f"/api/drafts/{identifier}/export", json={"spec": spec})
        self.assertEqual(exported.status_code, 200)
        self.assertIn("attachment", exported.headers["Content-Disposition"])
        self.assertEqual(self.drafts[identifier]["context"].spec, original_spec)
        self.assertFalse((self.root / "outputs" / identifier).exists())
        self.assertFalse(self.rows())
        saved = self.client.post(f"/api/drafts/{identifier}/save", json={"spec": spec})
        self.assertEqual(saved.status_code, 400)
        self.assertIn("姓名不能为空", saved.get_json()["errors"])
        self.assertFalse(any("证据不存在" in e for e in saved.get_json()["errors"]))

    def test_historical_html_ignores_current_evidence_photo_and_css(self):
        identifier = self.draft()
        folder = self.save(identifier)
        original = (folder / "zh/resume.html").read_bytes()
        self.repo.set_evidence_status("ev_feedback_001", "rejected")
        (self.root / "static/css/resume.css").write_text("/* new css */", encoding="utf-8")
        self.assertEqual(self.client.get(f"/generations/{identifier}/zh/snapshot").data, original)
        history = self.client.get(f"/generations/{identifier}/zh")
        self.assertEqual(history.status_code, 200)
        self.assertNotIn('contenteditable="true"', history.get_data(as_text=True))
        continued = self.continue_draft(identifier)
        self.assertEqual(self.client.post(f"/api/drafts/{continued}/save", json={}).status_code, 200)
        self.assertEqual((folder / "zh/resume.html").read_bytes(), original)

    def test_legacy_bilingual_only_clones_zh(self):
        identifier = self.draft()
        folder = self.save(identifier)
        shutil.copytree(folder / "zh", folder / "en")
        spec = json.loads((folder / "en/resume-spec.json").read_text(encoding="utf-8"))
        spec["language"] = "en"
        spec["experiences"][0]["bullets"][0]["evidence_ids"] = ["missing-english-only"]
        (folder / "en/resume-spec.json").write_text(json.dumps(spec), encoding="utf-8")
        metadata = read_yaml(folder / "metadata.yaml", {})
        metadata["languages"] = ["zh", "en"]
        write_yaml(folder / "metadata.yaml", metadata)
        english_row = {**self.rows()[0], "language": "en", "status": "已投递", "notes": "旧英文记录"}
        with self.store.csv_path.open("a", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=self.store.CSV_FIELDS).writerow(english_row)
        before = self.tree(folder)
        prior_csv = self.store.csv_path.read_bytes()
        self.assertEqual(self.client.get(f"/generations/{identifier}/en").status_code, 200)
        self.assertEqual(self.client.post(f"/generations/{identifier}/en/continue").status_code, 400)
        continued = self.continue_draft(identifier)
        new = self.save(continued)
        self.assertFalse((new / "en").exists())
        self.assertEqual(self.tree(folder), before)
        self.assertTrue(self.store.csv_path.read_bytes().startswith(prior_csv))
        self.assertEqual(len(self.rows()), 3)
        self.assertEqual(self.rows()[1]["notes"], "旧英文记录")

    def test_photos_and_no_photo_output(self):
        for filename, content, expected in [("photo.png", PNG, 302), ("photo.jpeg", JPEG, 302), ("photo.png", b"invalid", 400), ("photo.webp", PNG, 400)]:
            result = self.client.post("/profile/photo", data={"photo": (io.BytesIO(content), filename)}, content_type="multipart/form-data")
            self.assertEqual(result.status_code, expected)
        identifier = self.draft()
        spec = deepcopy(self.drafts[identifier]["context"].spec)
        spec["photo"]["width"] = "999mm"
        self.assertEqual(self.client.post(f"/api/drafts/{identifier}/save", json={"spec": spec}).status_code, 400)
        spec["show_photo"] = False
        html = self.client.post(f"/api/drafts/{identifier}/export", json={"spec": spec}).get_data(as_text=True)
        self.assertNotIn("data:image", html)
        self.assertNotIn("<img", html)
        self.assertIn('resume-header no-photo', html)
        self.assertNotIn('rel="stylesheet"', html)
        spec["photo"]["width"] = "25mm"
        spec["show_photo"] = True
        self.save(identifier, spec=spec)

    def test_draft_photo_upload_does_not_write_profile(self):
        identifier = self.draft()
        before = self.tree(self.root / "data")
        result = self.client.post(f"/api/drafts/{identifier}/photo", data={"photo": (io.BytesIO(PNG), "draft.png")}, content_type="multipart/form-data")
        self.assertEqual(result.status_code, 200)
        self.assertTrue(self.drafts[identifier]["context"].photo_data_url.startswith("data:image/png;base64,"))
        self.assertEqual(self.tree(self.root / "data"), before)

    def test_unique_ids_for_repeated_llm_ids_and_invalid_status(self):
        value = deepcopy(self.repo.experiences()[0])
        first = self.repo.save_experience(value)
        second = self.repo.save_experience(value)
        a, b = read_yaml(first, {}), read_yaml(second, {})
        self.assertNotEqual(a["experience_id"], b["experience_id"])
        self.assertTrue(set(e["evidence_id"] for e in a["evidence"]).isdisjoint(e["evidence_id"] for e in b["evidence"]))
        eid = a["evidence"][0]["evidence_id"]
        self.repo.set_evidence_status(eid, "rejected")
        self.assertEqual(read_yaml(second, {})["evidence"][0]["status"], "confirmed")
        value["evidence"][0]["status"] = "unknown"
        with self.assertRaises(ValueError):
            self.repo.save_experience(value)

    def test_existing_duplicate_ids_reported_without_mutation(self):
        original = self.repo.experiences()[0]
        write_yaml(self.root / "data/experiences/duplicate.yaml", original)
        before = self.tree(self.root / "data")
        with self.assertRaisesRegex(ValueError, "重复经历"):
            self.repo.evidence_index()
        with self.assertRaises(ValueError):
            self.repo.set_evidence_status(original["evidence"][0]["evidence_id"], "rejected")
        self.assertEqual(self.tree(self.root / "data"), before)
        original["experience_id"] = "different"
        write_yaml(self.root / "data/experiences/duplicate.yaml", original)
        with self.assertRaisesRegex(ValueError, "重复证据"):
            self.repo.evidence_index()

    def test_evidence_ownership_rejected_and_unselected(self):
        identifier = self.draft()
        spec = deepcopy(self.drafts[identifier]["context"].spec)
        spec["experiences"][0]["bullets"][0]["evidence_ids"] = ["ev_rag_001"]
        response = self.client.post(f"/api/drafts/{identifier}/save", json={"spec": spec})
        self.assertEqual(response.status_code, 200)  # Manual provenance is no longer a gate.
        self.repo.set_evidence_status("ev_rag_001", "rejected")
        self.assertEqual(self.client.post("/generate", data=self.form()).status_code, 400)
        clean = self.draft(evidence_ids=["ev_feedback_001"])
        ids = self.drafts[clean]["context"].spec["experiences"][0]["bullets"]
        self.assertEqual([b["evidence_ids"] for b in ids], [["ev_feedback_001"]])

    def test_csv_includes_skill_only_evidence_and_preserves_manual_columns(self):
        identifier = self.draft()
        spec = deepcopy(self.drafts[identifier]["context"].spec)
        spec.pop("layout")  # Legacy structural edit initializes new references.
        spec["experiences"], spec["projects"] = [], []
        spec["skills"] = [{"name": "Python", "evidence_ids": ["ev_feedback_001"]}]
        self.save(identifier, spec=spec)
        self.assertEqual(self.rows()[0]["evidence_ids"], "ev_feedback_001")
        with self.store.csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.store.CSV_FIELDS)
            writer.writeheader()
            row = dict.fromkeys(self.store.CSV_FIELDS, "")
            row.update(generation_id=identifier, language="zh", status="已投递", follow_up_date="2026-09-01", notes="手工备注")
            writer.writerow(row)
        before = self.store.csv_path.read_bytes()
        self.save(self.draft())
        self.assertTrue(self.store.csv_path.read_bytes().startswith(before))
        self.assertEqual(self.rows()[0]["notes"], "手工备注")

    def test_save_failure_leaves_no_generation_or_csv_row(self):
        identifier = self.draft()
        with patch("resume_app.storage.write_yaml", side_effect=OSError("disk full")):
            response = self.client.post(f"/api/drafts/{identifier}/save", json={})
        self.assertEqual(response.status_code, 400)
        self.assertFalse((self.root / "outputs" / identifier).exists())
        self.assertFalse(self.rows())
        self.assertIn(identifier, self.drafts)
        self.save(identifier)
        second = self.draft()
        prior = self.store.csv_path.read_bytes()
        with patch("resume_app.storage.os.replace", side_effect=OSError("CSV unavailable")):
            self.assertEqual(self.client.post(f"/api/drafts/{second}/save", json={}).status_code, 400)
        self.assertEqual(self.store.csv_path.read_bytes(), prior)
        self.assertFalse((self.root / "outputs" / second).exists())

    def test_save_uses_one_snapshot_and_retires_waiting_mutations(self):
        identifier = self.draft()
        spec = deepcopy(self.drafts[identifier]["context"].spec)
        spec["profile"]["name"] = "冻结姓名"
        entered, release = threading.Event(), threading.Event()
        original_create = self.store.create
        results = {}

        def delayed_create(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return original_create(*args, **kwargs)

        def save_request():
            with self.app.test_client() as client:
                results["save"] = client.post(
                    f"/api/drafts/{identifier}/save", json={"spec": spec, "custom_css": ".resume-page { color: navy; }"}
                )

        def preview_request():
            changed = deepcopy(spec)
            changed["profile"]["name"] = "竞争姓名"
            with self.app.test_client() as client:
                results["preview"] = client.post(
                    f"/api/drafts/{identifier}/preview", json={"spec": changed, "custom_css": ".resume-page { color: red; }"}
                )

        with patch.object(self.store, "create", side_effect=delayed_create):
            saving = threading.Thread(target=save_request)
            saving.start()
            self.assertTrue(entered.wait(2))
            previewing = threading.Thread(target=preview_request)
            previewing.start()
            previewing.join(.1)
            self.assertTrue(previewing.is_alive())
            release.set()
            saving.join(3)
            previewing.join(3)

        self.assertEqual(results["save"].status_code, 200)
        self.assertEqual(results["preview"].status_code, 410)
        folder = self.root / "outputs" / identifier / "zh"
        stored_spec = json.loads((folder / "resume-spec.json").read_text(encoding="utf-8"))
        html = (folder / "resume.html").read_text(encoding="utf-8")
        self.assertEqual(stored_spec["profile"]["name"], "冻结姓名")
        self.assertIn("冻结姓名", html)
        self.assertNotIn("竞争姓名", html)
        self.assertEqual((folder / "custom.css").read_text(encoding="utf-8"), ".resume-page { color: navy; }")

    def test_repository_rejects_malformed_records_before_write(self):
        value = deepcopy(self.repo.experiences()[0])
        value["evidence"][0]["structured_fact"] = "not-an-object"
        before = self.tree(self.root / "data/experiences")
        with self.assertRaisesRegex(ValueError, "structured_fact 必须是对象"):
            self.repo.save_experience(value)
        self.assertEqual(self.tree(self.root / "data/experiences"), before)

    def test_atomic_yaml_write_preserves_original_on_replace_failure(self):
        path = self.root / "data/profile.yaml"
        before = path.read_bytes()
        with patch("resume_app.storage.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                write_yaml(path, {"profile": {"name": "不应写入"}})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.glob(f".{path.name}.*")), [])

    def test_concurrent_evidence_updates_do_not_overwrite_each_other(self):
        target = self.root / "data/experiences/internship.yaml"
        original_read = read_yaml
        condition = threading.Condition()
        arrivals = 0
        local = threading.local()

        def coordinated_read(path, default):
            nonlocal arrivals
            value = original_read(path, default)
            if Path(path) == target:
                local.count = getattr(local, "count", 0) + 1
                if local.count == 2:
                    with condition:
                        arrivals += 1
                        if arrivals < 2:
                            condition.wait(timeout=.2)
                        else:
                            condition.notify_all()
            return value

        with patch("resume_app.storage.read_yaml", side_effect=coordinated_read):
            threads = [
                threading.Thread(target=self.repo.set_evidence_status, args=("ev_feedback_001", "rejected")),
                threading.Thread(target=self.repo.set_evidence_status, args=("ev_dashboard_001", "rejected")),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(2)
        statuses = {item["evidence_id"]: item["status"] for item in read_yaml(target, {})["evidence"]}
        self.assertEqual(statuses["ev_feedback_001"], "rejected")
        self.assertEqual(statuses["ev_dashboard_001"], "rejected")

    def test_legacy_snapshot_resource_selectors_are_stable(self):
        html = (FIXTURES / "legacy/resume-v05.html").read_text(encoding="utf-8")
        resources = SnapshotResources(html)
        self.assertEqual(resources.styles, [".resume-page { color: #123456; }"])
        self.assertEqual(resources.photo, "data:image/png;base64,legacy-photo")

    def test_multiple_draft_ids_and_different_jd_snapshots(self):
        a, b = self.draft(), self.draft(jd_text="另一份 JD")
        self.assertNotEqual(a, b)
        self.save(b)
        self.save(a)
        self.assertEqual(read_yaml(self.root / "outputs" / a / "metadata.yaml", {})["jd_text"], JD)
        self.assertEqual(read_yaml(self.root / "outputs" / b / "metadata.yaml", {})["jd_text"], "另一份 JD")

    def test_required_fields_import_and_file_only_jd(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        for field in ("company", "role", "jd_text"):
            self.assertEqual(self.client.post("/generate", data=self.form(**{field:" "})).status_code, 400)
        imported = self.client.post("/profile/import", data={"source_text": "课程项目\n使用 Python 分析 1000 条记录。"})
        self.assertEqual(imported.status_code, 302)
        self.assertTrue(any((self.root / "sources").glob("*-pasted-profile.txt")))
        prepared = self.client.post("/prepare", data={"company":"公司", "role":"实习", "jd_file": (io.BytesIO(JD.encode()), "jd.txt")}, content_type="multipart/form-data")
        self.assertEqual(prepared.status_code, 200)
        class Inputs(HTMLParser):
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "input" and attrs.get("name") == "jd_text":
                    self.jd_text = attrs["value"]
        inputs = Inputs()
        inputs.feed(prepared.get_data(as_text=True))
        self.assertEqual(inputs.jd_text, JD)
        self.assertNotIn('name="language"', self.client.get("/").get_data(as_text=True))

    def test_history_does_not_need_spec_for_view_or_print(self):
        identifier = self.draft()
        folder = self.save(identifier)
        (folder / "zh/resume-spec.json").write_text("not JSON", encoding="utf-8")
        self.assertEqual(self.client.get(f"/generations/{identifier}/zh").status_code, 200)
        self.assertEqual(self.client.get(f"/generations/{identifier}/zh/snapshot").data, (folder / "zh/resume.html").read_bytes())

    def test_section_hide_restore_and_style_persistence(self):
        identifier = self.draft()
        spec = deepcopy(self.drafts[identifier]["context"].spec)
        spec.pop("layout")  # Legacy section_order remains supported.
        spec["section_order"] = ["skills", "education"]
        spec["style"]["font_size"] = "12pt"
        spec["density"] = "compact"
        result = self.client.post(f"/api/drafts/{identifier}/preview", json={"spec":spec, "custom_css": "h1 {color:purple}"}).get_json()["html"]
        self.assertIn('data-section="experience" hidden', result)
        exported = self.client.post(f"/api/drafts/{identifier}/export", json={}).get_data(as_text=True)
        self.assertNotIn('data-section="experience"', exported)
        self.assertLess(exported.index('data-section="skills"'), exported.index('data-section="education"'))
        spec["section_order"] = ["experience", "skills", "education", "projects"]
        self.save(identifier, spec=spec)
        continued = self.continue_draft(identifier)
        self.assertEqual(self.drafts[continued]["context"].custom_css, "h1 {color:purple}")
        self.assertEqual(self.drafts[continued]["context"].spec["style"]["font_size"], "12pt")
        self.assertIn('data-section="experience"', self.client.post(f"/api/drafts/{continued}/preview", json={}).get_json()["html"])


if __name__ == "__main__":
    unittest.main()
