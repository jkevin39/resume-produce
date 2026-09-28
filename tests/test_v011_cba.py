"""v0.11 contracts and state boundaries, using synthetic data and mocked APIs."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_mvp
from tests.test_v06_llm import response
from resume_app.models import PROVIDERS, selection
from resume_app.skill import ResumeSkill, LLMError
from resume_app.storage import write_yaml, read_yaml
from resume_app.local import initialize, load_key, existing_service
from resume_app.ocr import validate_upload, recognize


class CBATest(unittest.TestCase):
    setUp = test_mvp.MVPFlowTest.setUp
    tearDown = test_mvp.MVPFlowTest.tearDown
    form = test_mvp.MVPFlowTest.form

    def test_deepseek_flash_legacy_ids_normalize_to_current_api_id(self):
        for legacy in ("deepseek-v4-flash", "deepseek-v4.1-flash"):
            settings = selection({"mode": "live", "model": legacy})
            self.assertEqual(settings["model"], "deepseek-flash")

    def test_each_provider_request_and_thinking(self):
        for provider, info in PROVIDERS.items():
            for model in info["models"]:
                for thinking in (False, True):
                    skill = ResumeSkill({"llm": {"mode": "live", "provider": provider, "model": model, "thinking": thinking}}, self.repo)
                    with patch.dict(os.environ, {info["env"]: "synthetic"}, clear=True), patch("resume_app.skill.requests.post", return_value=response('{"answer": 1}')) as post:
                        self.assertEqual(skill._chat_json("JSON", "synthetic", "contract"), {"answer": 1})
                    self.assertEqual(post.call_args.args[0], info["url"] + "/chat/completions")
                    body = post.call_args.kwargs["json"]
                    self.assertEqual(body["model"], model)
                    if provider == "openai":
                        self.assertEqual(body["reasoning_effort"], "medium" if thinking else "none")
                        self.assertIn("max_completion_tokens", body)
                        self.assertNotIn("temperature", body)
                    elif provider == "qwen":
                        self.assertEqual(body["enable_thinking"], thinking)
                        self.assertEqual("response_format" in body, not thinking)
                    else:
                        self.assertEqual(body["thinking"]["type"], "enabled" if thinking else "disabled")
                    self.assertEqual(skill.provenance(True)["thinking"], thinking)

    def test_keys_are_isolated_and_missing_does_not_fallback(self):
        with patch.dict(os.environ, {}, clear=True), patch("resume_app.keychain.read_key", side_effect=lambda p: "synthetic-" + p):
            for p, info in PROVIDERS.items():
                self.assertTrue(load_key(p))
                self.assertEqual(os.environ[info["env"]], "synthetic-" + p)
        skill = ResumeSkill({"llm": {"mode": "live", "provider": "kimi"}}, self.repo)
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "synthetic"}, clear=True), patch("resume_app.skill.requests.post") as post:
            with self.assertRaises(LLMError):
                skill._chat_json("JSON", "test", "test")
            post.assert_not_called()

    def test_settings_persist_without_restart_and_reject_invalid(self):
        settings = {"provider": "kimi", "model": next(iter(PROVIDERS["kimi"]["models"])), "thinking": True}
        result = self.client.post("/api/model-settings", json=settings)
        self.assertEqual(result.status_code, 200)
        self.assertIn("本地规则", result.json["runtime_label"])
        self.assertEqual(read_yaml(self.root / "config.yaml", {})["llm"]["provider"], "kimi")
        self.assertIn(next(iter(PROVIDERS["kimi"]["models"])), self.client.get("/").text)
        before = (self.root / "config.yaml").read_bytes()
        for bad in ({**settings, "provider": []}, {**settings, "model": []}, {**settings, "model": "unknown"}, {**settings, "thinking": "false"}, {**settings, "base_url": "https://untrusted.invalid"}):
            self.assertEqual(self.client.post("/api/model-settings", json=bad).status_code, 400)
            self.assertEqual((self.root / "config.yaml").read_bytes(), before)

    def test_prepare_snapshot_survives_changed_defaults(self):
        self.client.post("/api/model-settings", json={"provider": "kimi", "model": next(iter(PROVIDERS["kimi"]["models"])), "thinking": True})
        page = self.client.post("/prepare", data={"company": "合成公司", "role": "分析", "jd_text": "Python"})
        self.assertEqual(page.status_code, 200)
        import re, html
        snapshot = html.unescape(re.search(r'name="model_snapshot" value=\'(.*?)\'', page.text).group(1))
        self.client.post("/api/model-settings", json={"provider": "openai", "model": "gpt-5.4", "thinking": False})
        form = self.form()
        form["model_snapshot"] = snapshot
        seen = []
        original = ResumeSkill.build_spec
        def build(skill, *args, **kwargs):
            seen.append(skill.settings)
            return original(skill, *args, **kwargs)
        with patch.object(ResumeSkill, "build_spec", build):
            result = self.client.post("/generate", data=form)
        self.assertEqual(result.status_code, 302)
        self.assertEqual(seen[0]["provider"], "kimi")
        self.assertTrue(seen[0]["thinking"])
        form["model_snapshot"] = '{"provider":"unknown"}'
        self.assertEqual(self.client.post("/generate", data=form).status_code, 400)

    def test_model_settings_migrate(self):
        write_yaml(self.root / "config.yaml", {"llm": {"mode": "demo", "provider": "qwen", "model": "qwen-plus", "thinking": True}})
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "copy"
            initialize(dest, self.root)
            migrated = read_yaml(dest / "config.yaml", {})["llm"]
            self.assertEqual(migrated["provider"], "qwen")
            self.assertTrue(migrated["thinking"])
            ResumeSkill({"llm": migrated}, None)

    def test_ready_identity_rejects_other_data(self):
        from unittest.mock import Mock
        ready = Mock(ok=True)
        ready.json.return_value = {"application": "resume-produce", "data_directory": str(self.root.resolve())}
        with patch("requests.Session.get", return_value=ready):
            self.assertTrue(existing_service(self.root, 5000))
            with self.assertRaises(ValueError):
                existing_service(self.root / "other", 5000)

    def test_ocr_endpoint_and_error_paths(self):
        import io
        from tests.test_mvp import PNG
        # PNG constant is a synthetic fixture, never a user screenshot.
        self.app.extensions["resume_ocr"] = lambda data: "Synthetic Python SQL"
        result = self.client.post("/api/jd/ocr", data={"image": (io.BytesIO(PNG), "jd.png")})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["text"], "Synthetic Python SQL")
        for data in (b"", b"invalid", b"x" * (4 * 1024 * 1024 + 1)):
            result = self.client.post("/api/jd/ocr", data={"image": (io.BytesIO(data), "jd.png")})
            self.assertEqual(result.status_code, 400)
        with patch.dict(self.app.extensions, {"resume_ocr": lambda data: ""}):
            self.assertEqual(self.client.post("/api/jd/ocr", data={"image": (io.BytesIO(PNG), "jd.png")}).status_code, 400)
        result = self.client.post("/api/jd/ocr", data=b"x" * (8 * 1024 * 1024 + 1), content_type="application/octet-stream")
        self.assertEqual(result.status_code, 413)
        self.assertFalse(result.json["ok"])
        def fail(data):
            raise ValueError("合成识别失败")
        with patch.dict(self.app.extensions, {"resume_ocr": fail}):
            self.assertEqual(self.client.post("/api/jd/ocr", data={"image": (io.BytesIO(PNG), "jd.png")}).status_code, 400)
        with patch("resume_app.ocr.available", return_value=False):
            with self.assertRaisesRegex(ValueError, "尚未就绪"):
                recognize(PNG)
