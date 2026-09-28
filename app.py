from __future__ import annotations

import base64
import json
import os
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import RLock

from flask import g, Flask, jsonify, redirect, render_template, request, url_for

from resume_app.models import PROVIDERS, selection, key_available
from resume_app import ocr
from resume_app.layout_defaults import load_defaults, validate_defaults
from resume_app.ordering import catalog, validate_order, ordered
from resume_app.drafts import normalize_spec
from resume_app.canvas import refresh_education
from resume_app.inline_styles import rebase_styles
from resume_app.evidence_view import group_evidence
from resume_app.skill_selection import skill_options, select_skills
from resume_app.rendering import ResumeRenderer
from resume_app.skill import LLMError, ResumeSkill, format_llm_error
from resume_app.storage import GenerationStore, ProfileRepository, ROOT, read_yaml, write_yaml, referenced_evidence_ids, valid_image_signature
from resume_app.validation import validate_resume_spec


def create_app(root: Path = ROOT, testing: bool = False, *, data_root: Path = None, config_path: Path = None) -> Flask:
    # root owns templates/CSS; data_root owns all user material.
    data_root = Path(data_root) if data_root is not None else root
    config_path = Path(config_path) if config_path is not None else data_root / "config.yaml"
    app = Flask(__name__, template_folder=str(root / "templates"), static_folder=str(root / "static"))
    app.config.update(TESTING=testing, MAX_CONTENT_LENGTH=8 * 1024 * 1024)
    repository = ProfileRepository(data_root)
    store = GenerationStore(data_root)
    renderer = ResumeRenderer(repository, root)
    drafts = {}
    draft_locks = {}
    drafts_guard = RLock()
    app.extensions.update(
        resume_repository=repository, resume_store=store, resume_drafts=drafts,
        resume_draft_locks=draft_locks,
    )

    def display_time(value):
        # 纯展示过滤器：容忍 ISO 字符串与 datetime 两种输入（YAML 读回类型取决于解析器）。
        if not value:
            return ''
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return value
        try:
            return value.strftime('%Y-%m-%d %H:%M')
        except AttributeError:
            return str(value)

    app.jinja_env.filters['display_time'] = display_time

    settings_lock = RLock()
    layout_defaults_path = data_root / "data" / "layout-defaults.yaml"
    layout_defaults_lock = RLock()

    @app.route("/api/layout-defaults", methods=["GET", "PUT", "DELETE"])
    def layout_defaults():
        with layout_defaults_lock:
            try:
                if request.method == "PUT":
                    value = validate_defaults(request.get_json(silent=True))
                    write_yaml(layout_defaults_path, value)
                    return jsonify(ok=True, message="已保存为默认排版，下次新生成时自动应用。")
                if request.method == "DELETE":
                    layout_defaults_path.unlink(missing_ok=True)
                    return jsonify(ok=True, message="已清除默认排版；当前草稿保持不变。")
                value, warning = load_defaults(layout_defaults_path)
                return jsonify(ok=True, saved=value is not None, message=warning or ("已保存默认排版，新生成时自动应用。" if value else "尚未保存默认排版。"))
            except ValueError as exc:
                return jsonify(ok=False, error=str(exc)), 400
            except OSError:
                return jsonify(ok=False, error="默认排版保存或清除失败，原设置保留，请重试。"), 500

    def skill(snapshot=None):
        current = read_yaml(config_path, {"llm": {}, "app": {}})
        if snapshot is not None:
            required = {"provider", "model", "thinking", "mode"}
            optional = {"base_url"}
            if (not isinstance(snapshot, dict) or not required.issubset(snapshot)
                    or set(snapshot) - required - optional):
                raise ValueError("本轮模型设置损坏，请重新分析 JD。")
            current_llm = dict(current.get("llm", {}))
            selected = selection(snapshot)
            if "base_url" in snapshot:
                # The endpoint is non-secret but belongs to the operation's
                # provider, so keep the exact endpoint used by prepare even if
                # the default provider changed while the page was open.
                current_llm["base_url"] = snapshot["base_url"]
            elif current_llm.get("provider", "deepseek") != selected["provider"]:
                current_llm.pop("base_url", None)
            current["llm"] = {**current_llm, **selected}
        return ResumeSkill(current, repository)

    def render_error(message, status=400):
        return render_template("error.html", message=message), status

    def create_draft(context, metadata, analysis, match_report, gap_report):
        identifier = store.new_id()
        context.spec["generation_id"] = identifier
        with drafts_guard:
            drafts[identifier] = {
                "context": context, "metadata": dict(metadata), "analysis": analysis,
                "match_report": match_report, "gap_report": gap_report, "revision": 0, "display_name": "",
            }
            draft_locks[identifier] = RLock()
        return identifier

    @contextmanager
    def locked_draft(identifier):
        with drafts_guard:
            draft = drafts.get(identifier)
            draft_lock = draft_locks.get(identifier)
        if draft is None or draft_lock is None:
            raise LookupError("草稿已保存或已失效，请从历史版本继续编辑。重启服务会清空未保存草稿。")
        with draft_lock:
            # A request may have waited while another request saved and retired the draft.
            with drafts_guard:
                if drafts.get(identifier) is not draft:
                    raise LookupError("草稿已保存或已失效，请从历史版本继续编辑。重启服务会清空未保存草稿。")
            yield draft

    def apply_payload(draft, identifier, payload):
        revision = payload.get('revision', draft.get('revision', 0))
        if type(revision) is not int or revision < draft.get('revision', 0):
            raise ValueError('草稿修订已过期，请保留当前内容并重新同步')
        context = draft["context"]
        spec = normalize_spec(payload.get("spec", context.spec))
        spec["generation_id"] = identifier
        draft["revision"] = revision
        context.spec = spec
        context.custom_css = str(payload.get("custom_css", context.custom_css))
        return draft

    @app.errorhandler(ValueError)
    def value_error(exc):
        if request.path.startswith("/api/"):
            return jsonify(ok=False, errors=[str(exc)]), 400
        return render_error(str(exc))

    @app.errorhandler(LookupError)
    def missing_draft(exc):
        if request.path.startswith("/api/"):
            return jsonify(ok=False, errors=[str(exc)]), 410
        return render_error(str(exc), 410)

    @app.errorhandler(413)
    def too_large(_):
        if request.path in {"/api/jd/ocr", "/api/ocr"}:
            return jsonify(ok=False, error="图片请求过大，请选择不超过 4MB 的图片。"), 413
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify(ok=False, errors=["上传或草稿请求不能超过 8 MB"]), 413
        return render_error("上传或草稿请求不能超过 8 MB", 413)

    def library_context():
        value = repository.library_snapshot()
        value["evidence"] = {e["evidence_id"]: e for exp in value["experiences"] for e in exp["evidence"]}
        value["profile"] = repository.profile()
        # v0.10.3 任务 F：回收站来源标注（只读视图注解，不动存储）。
        # 证据记录自带 source_experience_id；来源经历可能仍在库中，也可能随后被整段删除而入站。
        active = {exp["experience_id"]: exp for exp in value["experiences"]}
        trashed = {r["payload"].get("experience_id"): r["payload"] for r in value["trash"] if r.get("kind") == "experience"}
        for record in value["trash"]:
            label = ""
            if record.get("kind") == "evidence":
                origin = active.get(record.get("source_experience_id")) or trashed.get(record.get("source_experience_id"))
                if origin:
                    label = " · ".join(x for x in [origin.get("organization"), origin.get("title")] if x)
            record["origin_label"] = label
        return value

    def library_response(message="已保存", focus=None, **extra):
        if request.headers.get("X-Requested-With") != "fetch":
            return redirect(url_for("index"))
        value = library_context()
        return jsonify(ok=True, message=message, focus=focus,
            library_html=render_template("_library_body.html", **value),
            trash_html=render_template("_library_trash.html", **value),
            summary_html=render_template("_library_summary.html", **value),
            options_html=render_template("_material_options.html", **value), **extra)

    @app.post("/library/edit")
    def library_edit():
        try:
            kind = request.form.get("kind")
            identifier = request.form.get("identifier", "")
            if kind == "evidence":
                parent = repository.update_evidence_text(identifier, request.form.get("text", ""), request.form.getlist("skill_names"))
                focus = "exp:" + parent
            elif kind == "experience":
                repository.update_experience_fields(identifier, request.form)
                focus = "exp:" + identifier
            elif kind == "skill":
                repository.update_skill_description(identifier, request.form.get("description", ""))
                focus = "skill:" + identifier
            else:
                raise ValueError("对象类型不正确")
            return library_response(focus=focus)
        except (ValueError, OSError) as exc:
            if request.headers.get("X-Requested-With") == "fetch":
                return jsonify(ok=False, errors=[str(exc)]), 400
            return render_error(str(exc))

    @app.post("/library/delete")
    def library_delete():
        try:
            repository.delete_library_item(request.form.get("kind"), request.form.get("identifier", ""))
            return library_response("已移入回收站", "trash")
        except (ValueError, OSError) as exc:
            if request.headers.get("X-Requested-With") == "fetch":
                return jsonify(ok=False, errors=[str(exc)]), 400
            return render_error(str(exc))

    @app.post("/trash/<trash_id>/<action>")
    def library_trash(trash_id, action):
        try:
            if action == "restore":
                message = repository.trash_restore(trash_id)
            elif action == "purge":
                repository.trash_purge(trash_id)
                message = "已彻底删除"
            else:
                raise ValueError("操作无效")
            return library_response(message)
        except (ValueError, OSError) as exc:
            if request.headers.get("X-Requested-With") == "fetch":
                return jsonify(ok=False, errors=[str(exc)]), 400
            return render_error(str(exc))

    @app.post("/api/ocr")
    @app.post("/api/jd/ocr")
    def recognize_jd_image():
        upload = request.files.get("image")
        try:
            if upload is None:
                raise ValueError("请选择图片。")
            data = upload.read(ocr.MAX_BYTES + 1)
            ocr.validate_upload(data)
            text = app.extensions.get("resume_ocr", ocr.recognize)(data)
            if not isinstance(text, str) or not text.strip():
                raise ValueError("没有识别到文字，请换一张清晰截图。")
            return jsonify(ok=True, text=text)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @app.post("/api/model-settings")
    def save_model_settings():
        payload = request.get_json(silent=True)
        try:
            if not isinstance(payload, dict) or set(payload) != {"provider", "model", "thinking"}:
                raise ValueError("模型设置字段不完整或包含未知字段。")
            with settings_lock:
                current = read_yaml(config_path, {})
                settings = selection({**payload, "mode": current.get("llm", {}).get("mode", "demo")})
                current_llm = dict(current.get("llm", {}))
                if current_llm.get("provider", "deepseek") != settings["provider"]:
                    current_llm.pop("base_url", None)
                current["llm"] = {**current_llm, **settings}
                instance = ResumeSkill(current, repository)
                write_yaml(config_path, current)
            return jsonify(ok=True, settings=settings, runtime_label=instance.runtime_label,
                           key_missing=not instance.demo_mode and not key_available(settings["provider"]))
        except (ValueError, OSError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @app.get("/")
    def index():
        try:
            instance = skill()
        except ValueError as exc:
            return render_error(f"模型配置无效：{exc}")
        return render_template("index.html", **library_context(), runtime_label=instance.runtime_label,
            ocr_available=ocr.available() or "resume_ocr" in app.extensions,
            model_settings=instance.settings, model_catalog=PROVIDERS,
            model_keys={p: key_available(p) for p in PROVIDERS},
            key_missing=not instance.demo_mode and not key_available(instance.settings["provider"]))

    @app.get("/history")
    def history_list():
        # 历史列表与独立快照回收站；状态操作通过独立接口完成。
        return render_template("history_list.html", generations=store.list(), trash=store.trash_list())

    @app.post("/api/profile")
    def save_profile_details():
        try:
            value = repository.save_profile_details(request.get_json(silent=True))
        except OSError:
            return jsonify(ok=False, errors=["保存失败，请检查数据目录的写入权限后重试。"]), 500
        return jsonify(ok=True, profile=value)

    @app.post("/profile/import")
    def import_profile():
        # 双模端点：fetch（X-Requested-With: fetch）返回 JSON 供无刷新导入；
        # 普通表单提交保持原有 redirect / 错误页行为（multipart 时 request.is_json 恒为 False，不能用其判定）。
        fetch_mode = request.headers.get("X-Requested-With") == "fetch"

        def fail(message, status=400):
            if fetch_mode:
                return jsonify(ok=False, errors=[message]), status
            return render_error(message, status)

        upload = request.files.get("source_file")
        pasted = request.form.get("source_text", "").strip()
        if upload and upload.filename:
            if Path(upload.filename).suffix.lower() not in {".txt", ".md", ".markdown", ".yaml", ".yml"}:
                return fail("资料仅支持 TXT、Markdown 或 YAML")
            raw = upload.read()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                return fail("资料文件必须是 UTF-8 编码")
            source_ref = repository.save_source(upload.filename, raw)
        elif pasted:
            text = pasted
            source_ref = repository.save_source("pasted-profile.txt", pasted.encode("utf-8"))
        else:
            return fail("请粘贴资料或选择文件")
        try:
            target = request.form.get("target_object", "")
            current = skill()
            extra = {}
            if target.startswith("exp:"):
                identifier = target[4:]
                if identifier not in repository.experience_index():
                    raise ValueError("追加目标已不存在")
                experience = current.extract_experience(text, source_ref)
                repository.append_evidence(identifier, experience["evidence"], source_ref)
                focus = target
            elif target.startswith("skill:"):
                name = target[6:]
                item = next((x for x in repository.skills() if x["name"] == name), None)
                if item is None:
                    raise ValueError("追加目标已不存在")
                previous = item.get("description", "")
                description = current.merge_skill_description(name, previous, text)
                repository.update_skill_description(name, description, expected=previous, source_ref=source_ref)
                focus = target
            elif target:
                raise ValueError("追加目标格式不正确")
            else:
                material = current.import_new_material(text, source_ref)
                if material["kind"] == "skill":
                    name = repository.add_skill(material["name"], material["description"], source_ref)
                    focus = "skill:" + name
                else:
                    saved_path = repository.save_experience(material["experience"])
                    identifier = saved_path.stem
                    focus = "exp:" + identifier
                    # Preserve existing response fields for form/fetch clients.
                    extra = {"experience_id": identifier, "experience_html": render_template(
                        "_library_experience.html", exp=repository.experience_index()[identifier], skills=repository.skills())}
            return library_response("材料已写入履历库", focus, **extra)
        except LLMError as exc:
            return fail(f"履历整理失败：{format_llm_error(exc)}", 502)
        except (ValueError, OSError) as exc:
            return fail(str(exc), 400)

    @app.post("/profile/photo")
    def upload_photo():
        upload = request.files.get("photo")
        if not upload or not upload.filename:
            return render_error("请选择照片")
        repository.save_photo(upload.filename, upload.read())
        return redirect(url_for("index"))

    @app.post("/evidence/<evidence_id>/status")
    def evidence_status(evidence_id):
        if request.is_json:
            value = request.get_json(silent=True)
            status = value.get("status", "") if isinstance(value, dict) else ""
            try:
                repository.set_evidence_status(evidence_id, status)
            except (ValueError, KeyError, OSError):
                return jsonify(ok=False, error="更新失败，请重试并确认该证据仍存在。"), 400
            return jsonify(ok=True, status=status)
        repository.set_evidence_status(evidence_id, request.form.get("status", ""))
        return redirect(url_for("index"))

    @app.post("/prepare")
    def prepare():
        if request.form.get("language", "zh") != "zh":
            return render_error("本版仅生成中文")
        company, role = request.form.get("company", "").strip(), request.form.get("role", "").strip()
        jd_text = request.form.get("jd_text", "")
        upload = request.files.get("jd_file")
        if upload and upload.filename:
            if Path(upload.filename).suffix.lower() not in {".txt", ".md", ".markdown"}:
                return render_error("JD 文件仅支持 TXT 或 Markdown")
            try:
                jd_text = upload.read().decode("utf-8-sig")
            except UnicodeDecodeError:
                return render_error("JD 文件必须是 UTF-8 编码")
        if not company or not role or not jd_text.strip():
            return render_error("公司、岗位和 JD 均不能为空")
        current_skill = skill()
        try:
            analysis = current_skill.analyze_jd(jd_text)
        except Exception as exc:
            return render_error(f"JD 分析失败：{format_llm_error(exc)}", 502)
        try:
            match_report = current_skill.match(analysis)
        except Exception as exc:
            return render_error(f"证据匹配失败：{format_llm_error(exc)}", 502)
        snapshot = library_context()
        evidence = snapshot["evidence"]
        selected = [x["evidence_id"] for x in match_report["matches"] if x["category"] in {"strong", "partial"}]
        options = skill_options(snapshot["skills"], evidence, selected)
        descriptions, description_warning = {}, ""
        try:
            descriptions = current_skill.generate_skill_descriptions(analysis, options, evidence)
        except (LLMError, ValueError) as exc:
            description_warning = "技能描述生成失败，已使用履历库描述"
        for item in options:
            item["suggested_description"] = descriptions.get(item["name"], item.get("description", ""))
        matches = deepcopy(match_report["matches"])
        known = {x["evidence_id"] for x in matches}
        priority = max((x["priority"] for x in matches), default=0) + 1
        for eid, item in evidence.items():
            if eid not in known and item["status"] != "rejected":
                matches.append({"evidence_id": eid, "category": "not_applicable", "unassessed": True,
                                "reason": "模型未评估此证据，请人工判断是否选用", "priority": priority})
        sections = group_evidence(matches, snapshot["experiences"], snapshot["skills"])
        display_order = match_report.get('display_order')
        if display_order is not None:
            for section in sections:
                ids = display_order[section['kind']]
                rank = {value: i for i, value in enumerate(ids)}
                section['entries'].sort(key=lambda row: rank.get(row['experience']['experience_id'], len(rank)))
            options = ordered(options, display_order['skills'], 'name')
        order_label = ('已按本地规则推荐排序' if current_skill.demo_mode else '已按 JD 相关性推荐排序') if display_order is not None else '当前按原顺序展示，未取得推荐排序'
        return render_template("prepare.html", company=company, role=role, jd_text=jd_text, analysis=analysis,
            match_report=match_report, evidence=evidence,
            evidence_sections=sections, order_label=order_label,
            skill_options=options, description_warning=description_warning,
            model_snapshot={**current_skill.settings, "base_url": current_skill.base_url}, model_label=current_skill.runtime_label)

    @app.post("/generate")
    def generate():
        if request.form.get("language", "zh") != "zh":
            return render_error("本版仅生成中文")
        company = request.form.get("company", "").strip()
        role = request.form.get("role", "").strip()
        jd_text = request.form.get("jd_text", "")
        if not company or not role or not jd_text.strip():
            return render_error("公司、岗位和 JD 均不能为空")
        selected = request.form.getlist("evidence_ids")
        evidence = repository.evidence_index()
        if any(eid not in evidence or evidence[eid]["status"] == "rejected" for eid in selected):
            return render_error("选择中包含不存在或已拒绝的证据，请重新匹配")
        try:
            analysis = json.loads(request.form["analysis_json"])
            match_report = json.loads(request.form["match_json"])
        except (KeyError, json.JSONDecodeError):
            return render_error("分析结果已损坏，请重新分析 JD")
        try:
            snapshot_value = json.loads(request.form["model_snapshot"]) if "model_snapshot" in request.form else None
            current_skill = skill(snapshot_value)
        except (ValueError, TypeError) as exc:
            return render_error(str(exc))
        selected_skills = request.form.getlist("skill_names")
        try:
            select_skills(repository.skills(), evidence, selected, selected_skills)
        except ValueError as exc:
            return render_error(str(exc))
        try:
            descriptions = json.loads(request.form.get("skill_desc_payload", "{}"))
            if not isinstance(descriptions, dict) or set(descriptions) - set(selected_skills) or not all(isinstance(x, str) for x in descriptions.values()):
                raise ValueError("技能描述格式不正确，请重新选择")
            display_order = validate_order(json.loads(request.form.get('display_order', '{}')),
                                           catalog(repository.experiences(), repository.skills()))
            spec = normalize_spec(current_skill.build_spec("zh", selected, company, role, analysis,
                selected_skill_names=selected_skills, skill_descriptions=descriptions, display_order=display_order))
            with layout_defaults_lock:
                defaults, _ = load_defaults(layout_defaults_path)
            if defaults:
                spec.update(defaults)
            unselected = referenced_evidence_ids(spec) - set(selected)
            if unselected:
                return render_error("模型引用了未选择的证据：" + "、".join(sorted(unselected)))
            context = renderer.current_context(spec)
            identifier = create_draft(context, {
                "company": company, "role": role, "jd_text": jd_text, "parent_generation_id": None,
                "selected_evidence_ids": list(dict.fromkeys(selected)), "llm": current_skill.provenance(new_call=True),
            }, analysis, match_report, build_gap_report(match_report))
        except LLMError as exc:
            return render_error(f"ResumeSpec 生成失败：{format_llm_error(exc)}", 502)
        except ValueError as exc:
            return render_error(f"ResumeSpec 生成失败：网络/超时/输出不合格：{exc}", 502)
        except Exception as exc:
            return render_error(f"生成失败：{exc}", 502)
        return redirect(url_for("draft_editor", draft_id=identifier))

    @app.context_processor
    def snapshot_helpers():
        return {"source_label": store.source_label}

    @app.before_request
    def guard_snapshot_access():
        endpoints = {"preview", "snapshot", "continue_edit", "rename_generation", "generation_trash", "history_list"}
        if request.endpoint not in endpoints:
            return
        if request.endpoint == "continue_edit" and request.view_args.get("language") != "zh":
            return
        store.lock.acquire()
        g.generation_lock = True
        if request.endpoint in {"generation_trash", "history_list"}:
            return
        try:
            store.require_active(request.view_args["generation_id"])
        except (FileNotFoundError, ValueError) as exc:
            message = "未找到该快照。" if isinstance(exc, FileNotFoundError) else str(exc)
            status = 404 if isinstance(exc, FileNotFoundError) else 410
            if request.path.startswith("/api/"):
                return jsonify(ok=False, error=message), status
            return render_error(message, status)

    @app.teardown_request
    def release_snapshot_lock(_error):
        if g.pop("generation_lock", False):
            store.lock.release()

    @app.post("/api/generations/<generation_id>/trash/<action>")
    def generation_trash(generation_id, action):
        try:
            message = store.trash_action(generation_id, action)
        except (FileNotFoundError, ValueError, OSError) as exc:
            if isinstance(exc, FileNotFoundError):
                message = "未找到该快照。"
            elif isinstance(exc, ValueError):
                message = str(exc)
            else:
                message = "文件操作未完成，请重试；若快照已进入清理状态，只能继续彻底删除。"
            return jsonify(ok=False, error=message,
                html=render_template("_history_body.html", generations=store.list(), trash=store.trash_list())), 400
        return jsonify(ok=True, message=message,
            html=render_template("_history_body.html", generations=store.list(), trash=store.trash_list()),
            url=url_for("history_list"))

    @app.get("/generations/<generation_id>/<language>")
    def preview(generation_id, language):
        folder = data_root / "outputs" / generation_id
        metadata = read_yaml(folder / "metadata.yaml", {})
        if language not in metadata.get("languages", []) or not (folder / language / "resume.html").is_file():
            return render_error("未找到该语言制品", 404)
        return render_template("history.html", metadata=metadata, language=language,
                               display_name=store.display_name(generation_id))

    @app.post("/api/generations/<generation_id>/name")
    def rename_generation(generation_id):
        value = request.get_json(silent=True)
        try:
            name = store.rename(generation_id, value.get("display_name") if isinstance(value, dict) else None)
        except FileNotFoundError:
            return jsonify(ok=False, error="未找到该快照。"), 404
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        except OSError:
            return jsonify(ok=False, error="改名失败，原名称已保留，请重试。"), 400
        return jsonify(ok=True, display_name=name)

    @app.get("/generations/<generation_id>/<language>/snapshot")
    def snapshot(generation_id, language):
        path = data_root / "outputs" / generation_id / language / "resume.html"
        if not path.is_file():
            return render_error("未找到 HTML 快照", 404)
        return app.response_class(path.read_bytes(), mimetype="text/html")

    @app.post("/generations/<generation_id>/<language>/continue")
    def continue_edit(generation_id, language):
        if language != "zh":
            return render_error("英文历史仅供查看和打印；请从中文版本继续编辑")
        try:
            spec, css, metadata = store.load(generation_id, "zh")
        except FileNotFoundError:
            return render_error("该历史版本不含中文制品", 404)
        source = data_root / "outputs" / generation_id
        context = renderer.snapshot_context(
            normalize_spec(spec), css, (source / "zh" / "resume.html").read_text(encoding="utf-8")
        )
        identifier = create_draft(
            context, {
                **metadata, "parent_generation_id": generation_id,
                "selected_evidence_ids": sorted(referenced_evidence_ids(spec)),
                "llm": {**normalize_provenance(metadata.get("llm")), "new_llm_call": False},
            },
            read_yaml(source / "jd-analysis.yaml", {}), read_yaml(source / "match-report.yaml", {}),
            (source / "gap-report.md").read_text(encoding="utf-8"),
        )
        return redirect(url_for("draft_editor", draft_id=identifier))

    @app.get("/drafts/<draft_id>")
    def draft_editor(draft_id):
        with locked_draft(draft_id) as current:
            draft = deepcopy(current)
        return render_template("preview.html", draft_id=draft_id, draft=draft, spec=draft["context"].spec, custom_css=draft["context"].custom_css)

    @app.post("/api/drafts/<draft_id>/name")
    def name_draft(draft_id):
        payload = request.get_json(silent=True)
        name = store.validate_display_name(payload.get("display_name") if isinstance(payload, dict) else None)
        with locked_draft(draft_id) as draft:
            draft["display_name"] = name
        return jsonify(ok=True, display_name=name or draft_id)

    @app.post("/api/drafts/<draft_id>/preview")
    def draft_preview(draft_id):
        with locked_draft(draft_id) as draft:
            apply_payload(draft, draft_id, request.get_json(silent=True) or {})
            html = renderer.render_document(draft["context"], editable=True)
            response = dict(ok=True, html=html, spec=deepcopy(draft["context"].spec), revision=draft["revision"])
        return jsonify(response)

    @app.post("/api/drafts/<draft_id>/export")
    def export_draft(draft_id):
        with locked_draft(draft_id) as current:
            draft = apply_payload(deepcopy(current), draft_id, request.get_json(silent=True) or {})
        # Intentionally no content/evidence validation or persistent write.
        return app.response_class(
            renderer.render_document(draft["context"]), mimetype="text/html",
            headers={"Content-Disposition": f'attachment; filename="{draft_id}-draft.html"'},
        )

    @app.post("/api/drafts/<draft_id>/save")
    def save_draft(draft_id):
        # Hold the per-draft lock until publication finishes. The saved spec, HTML and
        # CSS all come from one immutable snapshot; waiting mutations see a retired draft.
        with locked_draft(draft_id) as current:
            draft = apply_payload(deepcopy(current), draft_id, request.get_json(silent=True) or {})
            context, metadata = draft["context"], draft["metadata"]
            errors = validate_resume_spec(context.spec, context.photo_data_url)
            if not metadata.get("company") or not metadata.get("role") or not metadata.get("jd_text"):
                errors.append("公司、岗位和 JD 均不能为空")
            if errors:
                return jsonify(ok=False, errors=errors), 400
            html = renderer.render_document(context)
            try:
                with store.lock:
                    store.create(
                        metadata["company"], metadata["role"], metadata["jd_text"],
                        draft["analysis"], draft["match_report"], draft["gap_report"],
                        {"zh": (context.spec, context.custom_css, html)},
                        metadata.get("parent_generation_id"), generation_id=draft_id,
                        llm_provenance=normalize_provenance(metadata.get("llm")),
                        display_name=draft.get("display_name", ""),
                    )
            except (OSError, ValueError) as exc:
                return jsonify(ok=False, errors=[f"保存失败，草稿已保留：{exc}"]), 400
            with drafts_guard:
                del drafts[draft_id]
                del draft_locks[draft_id]
        return jsonify(ok=True, generation_id=draft_id, url=url_for("preview", generation_id=draft_id, language="zh"))

    @app.post("/api/drafts/<draft_id>/refresh")
    def refresh_draft(draft_id):
        payload = request.get_json(silent=True) or {}
        with locked_draft(draft_id) as current_draft:
            draft = apply_payload(deepcopy(current_draft), draft_id, payload)
            context = draft["context"]
            part = payload.get("part")
            if part == "photo":
                context.photo_data_url = renderer.photo_data_url()
            elif part == "css":
                context.base_css = renderer.current_css()
            elif part == "profile":
                current = repository.profile()
                before_refresh = deepcopy(context.spec)
                summary = context.spec.get("profile", {}).get("summary", "")
                context.spec["profile"] = {key: value for key, value in current.get("profile", {}).items() if key != "photo_path"}
                context.spec["profile"]["summary"] = summary
                refresh_education(context.spec, current.get("education", []))
                experiences = repository.experience_index()
                for entry in context.spec["experiences"] + context.spec["projects"]:
                    current_entry = experiences.get(entry.get("experience_id"), {})
                    for key in ("organization", "title", "date", "location"):
                        if key in current_entry:
                            entry[key] = current_entry[key]
                rebase_styles(before_refresh, context.spec)
                context.spec = normalize_spec(context.spec)
            else:
                return jsonify(ok=False, errors=["未知刷新类型"]), 400
            spec = deepcopy(context.spec)
            html = renderer.render_document(context, editable=True)
            current_draft.update(draft)
        return jsonify(ok=True, spec=spec, html=html, revision=draft["revision"])

    @app.post("/api/drafts/<draft_id>/photo")
    def draft_photo(draft_id):
        upload = request.files.get("photo")
        if not upload or not upload.filename:
            raise ValueError("请选择 JPEG 或 PNG 照片")
        suffix, content = Path(upload.filename).suffix.lower(), upload.read()
        if suffix not in {".jpg", ".jpeg", ".png"} or not valid_image_signature(content, suffix):
            raise ValueError("照片内容与 JPEG/PNG 格式不符")
        mime = "image/png" if suffix == ".png" else "image/jpeg"
        with locked_draft(draft_id) as draft:
            revision = request.form.get('revision')
            if revision is not None:
                try:
                    revision = int(revision)
                except ValueError:
                    raise ValueError('照片修订号无效')
                if revision < draft['revision']:
                    raise ValueError('照片修订已过期')
                draft['revision'] = revision
            draft["context"].photo_data_url = f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"
        return jsonify(ok=True)

    return app


def build_gap_report(match_report):
    lines = ["# 缺口报告", ""]
    education = match_report.get("education_matches")
    education_requirements = {item.get("requirement", "").strip() for item in education or []}
    gaps = [item for item in match_report.get("gaps", [])
            if item.get("requirement", "").strip() not in education_requirements]
    if gaps:
        lines += ["## 通用缺口", ""]
        for gap in gaps:
            lines.append(f"- **{gap.get('requirement', '未命名要求')}**：{gap.get('suggestion', '请补充真实证据。')}")
    pending = [item for item in education or [] if item.get("status") in {"unmet", "needs_confirmation"}]
    if pending:
        lines += ["", "## 教育条件", ""]
        for item in pending:
            status = "不满足" if item["status"] == "unmet" else "待核实"
            lines.append(f"- **{item['requirement']}**（{status}）：{item.get('reason', '')}")
    if not gaps and not pending:
        lines.append("未发现明确的无证据缺口。")
    if education is None:
        lines.append("本轮未评估教育背景。")
    return "\n".join(lines) + "\n"


def normalize_provenance(value):
    value = value if isinstance(value, dict) else {}
    return {
        "service": value.get("service") or "unknown",
        "model": value.get("model") or "unknown",
        "mode": value.get("mode") or "unknown",
        "thinking": value.get("thinking", "未记录"),
        "prompt_version": value.get("prompt_version") or "unknown",
        "new_llm_call": bool(value.get("new_llm_call", False)),
    }


if __name__ == "__main__":
    application = create_app()
    settings = read_yaml(ROOT / "config.yaml", {}).get("app", {})
    application.run(host=settings.get("host", "127.0.0.1"), port=int(settings.get("port", 5000)), debug=bool(settings.get("debug", False)))
