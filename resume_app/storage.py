from __future__ import annotations

import csv
import io
import json
import re
import shutil
import tempfile
import os
from copy import deepcopy
from threading import RLock
from uuid import uuid4
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parent.parent


def read_yaml(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or default


def write_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            yaml.safe_dump(value, temporary, allow_unicode=True, sort_keys=False)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def validate_experience_record(value: Any, source: str = "履历记录") -> dict[str, Any]:
    """Validate the schema consumed by matching before a record reaches the library."""
    if not isinstance(value, dict):
        raise ValueError(f"{source}必须是对象")
    if value.get("type") not in {"experience", "project"}:
        raise ValueError(f"{source}包含无效经历类型")
    for key in ("experience_id", "organization", "title", "date", "location"):
        if not isinstance(value.get(key), str):
            raise ValueError(f"{source}.{key} 必须是字符串")
    if not isinstance(value.get("source_refs"), list) or not all(isinstance(item, str) for item in value["source_refs"]):
        raise ValueError(f"{source}.source_refs 必须是字符串数组")
    evidence_items = value.get("evidence")
    if not isinstance(evidence_items, list):
        raise ValueError(f"{source}.evidence 必须是数组")
    for index, evidence in enumerate(evidence_items):
        label = f"{source}.evidence[{index}]"
        if not isinstance(evidence, dict):
            raise ValueError(f"{label} 必须是对象")
        for key in ("evidence_id", "original_fact", "candidate_zh"):
            if not isinstance(evidence.get(key), str) or not evidence[key].strip():
                raise ValueError(f"{label}.{key} 必须是非空字符串")
        if evidence.get("status") not in {"confirmed", "needs_details", "rejected"}:
            raise ValueError(f"{label}.status 无效")
        fact = evidence.get("structured_fact")
        if not isinstance(fact, dict):
            raise ValueError(f"{label}.structured_fact 必须是对象")
        for key in ("action", "method", "scale", "result"):
            if not isinstance(fact.get(key), str):
                raise ValueError(f"{label}.structured_fact.{key} 必须是字符串")
        if not isinstance(fact.get("skills"), list) or not all(isinstance(item, str) for item in fact["skills"]):
            raise ValueError(f"{label}.structured_fact.skills 必须是字符串数组")
    return value


class ProfileRepository:
    def __init__(self, root: Path = ROOT):
        self.root = root
        self.data = root / "data"
        self.experiences_dir = self.data / "experiences"
        self.sources = root / "sources"
        self.experiences_dir.mkdir(parents=True, exist_ok=True)
        self.sources.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()

    def profile(self) -> dict[str, Any]:
        with self.lock:
            return read_yaml(self.data / "profile.yaml", {"profile": {}, "education": []})

    def save_profile_details(self, payload: dict) -> dict:
        """Update form-owned fields without replacing photos or other profile data."""
        fields = ("name", "phone", "email", "location", "summary")
        education_fields = ("school", "degree", "major", "date", "details")
        if not isinstance(payload, dict) or not isinstance(payload.get("profile"), dict):
            raise ValueError("基本信息格式不正确，请刷新后重试。")
        profile = payload["profile"]
        if any(not isinstance(profile.get(key), str) for key in fields):
            raise ValueError("姓名、联系方式、意向城市和简介必须是文字。")
        rows = payload.get("education")
        if not isinstance(rows, list):
            raise ValueError("教育经历必须是列表。")
        with self.lock:
            value = self.profile()
            existing = value.get("education", [])
            updated, used = [], set()
            for row in rows:
                if not isinstance(row, dict) or any(not isinstance(row.get(key), str) for key in education_fields):
                    raise ValueError("教育经历的学校、学历、专业、时间和说明必须是文字。")
                index = row.get("original_index")
                if index is not None:
                    if type(index) is not int or index < 0 or index >= len(existing) or index in used:
                        raise ValueError("教育经历已发生变化，请刷新页面后重新编辑。")
                    used.add(index)
                    entry = deepcopy(existing[index])
                else:
                    if not any(row[key].strip() for key in education_fields):
                        continue
                    entry = {}
                entry.update({key: row[key].strip() for key in education_fields})
                if not entry.get("education_id"):
                    entry["education_id"] = "edu_" + uuid4().hex
                updated.append(entry)
            value.setdefault("profile", {}).update({key: profile[key].strip() for key in fields})
            value["education"] = updated
            write_yaml(self.data / "profile.yaml", value)
            return value

    def skills(self) -> list[dict[str, Any]]:
        with self.lock:
            return read_yaml(self.data / "skills.yaml", {"skills": []}).get("skills", [])

    def experiences(self) -> list[dict[str, Any]]:
        with self.lock:
            items = []
            experience_ids, evidence_ids = set(), set()
            for path in sorted(self.experiences_dir.glob("*.yaml")):
                value = read_yaml(path, {})
                if value:
                    validate_experience_record(value, path.name)
                    identifier = value.get("experience_id")
                    if not identifier or identifier in experience_ids:
                        raise ValueError(f"履历库存在缺失或重复经历 ID：{identifier}（{path.name}）")
                    experience_ids.add(identifier)
                    for evidence in value["evidence"]:
                        eid = evidence.get("evidence_id")
                        if not eid or eid in evidence_ids:
                            raise ValueError(f"履历库存在缺失或重复证据 ID：{eid}（{path.name}）")
                        if evidence.get("status") not in {"confirmed", "needs_details", "rejected"}:
                            raise ValueError(f"无效证据状态：{eid}")
                        evidence_ids.add(eid)
                    items.append(value)
            return items

    def evidence_index(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for experience in self.experiences():
            for evidence in experience.get("evidence", []):
                result[evidence["evidence_id"]] = {**evidence, "experience_id": experience["experience_id"]}
        return result

    def experience_index(self) -> dict[str, dict[str, Any]]:
        return {item["experience_id"]: item for item in self.experiences()}

    def save_experience(self, experience: dict[str, Any]) -> Path:
        value = deepcopy(experience)
        validate_experience_record(value, "提取结果")
        with self.lock:
            existing = self.experiences()  # Surface corrupt existing IDs before any write.
            used = {e["experience_id"] for e in existing}
            used.update(e["evidence_id"] for x in existing for e in x["evidence"])

            def allocate(prefix):
                identifier = prefix + uuid4().hex
                while identifier in used:
                    identifier = prefix + uuid4().hex
                used.add(identifier)
                return identifier

            value["experience_id"] = allocate("exp_")
            for evidence in value["evidence"]:
                evidence["evidence_id"] = allocate("ev_")
            path = self.experiences_dir / f"{value['experience_id']}.yaml"
            write_yaml(path, value)
        return path

    def set_evidence_status(self, evidence_id: str, status: str) -> None:
        if status not in {"confirmed", "needs_details", "rejected"}:
            raise ValueError("无效证据状态")
        with self.lock:
            self.experiences()  # Do not update an ambiguous duplicate ID.
            for path in self.experiences_dir.glob("*.yaml"):
                item = read_yaml(path, {})
                for evidence in item.get("evidence", []):
                    if evidence.get("evidence_id") == evidence_id:
                        evidence["status"] = status
                        write_yaml(path, item)
                        return
        raise KeyError(evidence_id)

    def library_snapshot(self):
        with self.lock:
            return {"experiences": self.experiences(), "skills": self.skills(), "trash": self.trash_list()}

    def _library_files(self):
        self.experiences()  # Validate IDs before mutating any file.
        return {path: read_yaml(path, {}) for path in self.experiences_dir.glob("*.yaml")}

    def _commit_library(self, changes):
        """Small multi-file update: rollback ordinary failures; no recovery journal."""
        changes = {path: value for path, value in changes.items()
                   if (value is None and path.exists()) or (value is not None and
                       (not path.exists() or read_yaml(path, {}) != value))}
        before = {path: path.read_bytes() if path.exists() else None for path in changes}
        written = []
        try:
            for path, value in changes.items():
                if value is not None and path.parent == self.experiences_dir:
                    validate_experience_record(value)
            for path, value in changes.items():
                if value is None:
                    path.unlink(missing_ok=True)
                else:
                    write_yaml(path, value)
                written.append(path)
        except OSError as exc:
            failed = False
            for path in reversed(written):
                try:
                    if before[path] is None:
                        path.unlink(missing_ok=True)
                    else:
                        # The original YAML bytes are retained for an ordinary rollback.
                        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                            temporary = Path(handle.name)
                            handle.write(before[path]); handle.flush(); os.fsync(handle.fileno())
                        try:
                            os.replace(temporary, path)
                        finally:
                            temporary.unlink(missing_ok=True)
                except OSError:
                    failed = True
            if failed:
                raise OSError("部分写入未能回滚，请检查履历库与回收站后再操作。") from exc
            raise

    @staticmethod
    def _validate_skills(skills):
        names = set()
        for item in skills:
            name = item.get("name") if isinstance(item, dict) else None
            if not isinstance(name, str) or not name.strip() or name != name.strip() or name in names:
                raise ValueError("技能名称不能为空或重复")
            names.add(name)
            if not isinstance(item.get("description", ""), str):
                raise ValueError("技能描述必须是文字")
            for field in ("evidence_ids", "source_refs"):
                if not isinstance(item.get(field, []), list) or not all(isinstance(x, str) for x in item.get(field, [])):
                    raise ValueError(f"技能 {field} 必须是字符串数组")
            if "user_confirmed" in item and type(item["user_confirmed"]) is not bool:
                raise ValueError("技能确认标记必须是布尔值")

    def add_skill(self, name, description, source_ref):
        with self.lock:
            skills = self.skills()
            name = name.strip()
            if any(x["name"] == name for x in skills):
                raise ValueError("该技能已存在，请在对象下拉中选择它进行追加")
            if any(x["kind"] == "skill" and x["payload"]["name"] == name for x in self.trash_list()):
                raise ValueError("该技能在回收站中，请先恢复")
            skills.append({"name": name, "description": description, "user_confirmed": True,
                           "evidence_ids": [], "source_refs": [source_ref]})
            self._validate_skills(skills)
            write_yaml(self.data / "skills.yaml", {"skills": skills})
            return name

    def update_skill_description(self, name, description, *, expected=None, source_ref=None):
        if not isinstance(description, str):
            raise ValueError("技能描述必须是文字")
        with self.lock:
            skills = self.skills()
            item = next((x for x in skills if x["name"] == name), None)
            if item is None:
                raise ValueError("技能已不存在，请刷新后重试")
            if expected is not None and item.get("description", "") != expected:
                raise ValueError("描述已被修改，请核对后重试")
            item["description"] = description.strip()
            if source_ref:
                item["source_refs"] = list(dict.fromkeys(item.get("source_refs", []) + [source_ref]))
            self._validate_skills(skills)
            write_yaml(self.data / "skills.yaml", {"skills": skills})

    def update_evidence_text(self, evidence_id, text, skill_names=None):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("事实文字不能为空")
        with self.lock:
            files, skills = self._library_files(), self.skills()
            if skill_names is not None and (not isinstance(skill_names, list) or
                    not all(isinstance(x, str) for x in skill_names) or
                    set(skill_names) - {x["name"] for x in skills}):
                raise ValueError("技能关联包含不存在的技能")
            for path, exp in files.items():
                for item in exp["evidence"]:
                    if item["evidence_id"] != evidence_id:
                        continue
                    item["original_fact"] = item["candidate_zh"] = text.strip()
                    item["structured_fact"].update(action=text.strip(), method="", scale="", result="")
                    changes = {path: exp}
                    if skill_names is not None:
                        item["structured_fact"]["skills"] = list(dict.fromkeys(skill_names))
                        for skill in skills:
                            ids = [x for x in skill.get("evidence_ids", []) if x != evidence_id]
                            if skill["name"] in skill_names:
                                ids.append(evidence_id)
                            skill["evidence_ids"] = ids
                        changes[self.data / "skills.yaml"] = {"skills": skills}
                    self._commit_library(changes)
                    return exp["experience_id"]
            raise ValueError("证据已不存在，请刷新后重试")

    def update_experience_fields(self, experience_id, fields):
        with self.lock:
            for path, exp in self._library_files().items():
                if exp["experience_id"] == experience_id:
                    for key in ("organization", "title", "date", "location", "type"):
                        if key in fields:
                            if not isinstance(fields[key], str):
                                raise ValueError("经历字段必须是文字")
                            exp[key] = fields[key].strip()
                    validate_experience_record(exp)
                    write_yaml(path, exp)
                    return
            raise ValueError("经历已不存在，请刷新后重试")

    def append_evidence(self, experience_id, items, source_ref):
        with self.lock:
            for path, exp in self._library_files().items():
                if exp["experience_id"] == experience_id:
                    for item in deepcopy(items):
                        item["evidence_id"] = "ev_" + uuid4().hex
                        exp["evidence"].append(item)
                    exp["source_refs"] = list(dict.fromkeys(exp["source_refs"] + [source_ref]))
                    validate_experience_record(exp)
                    write_yaml(path, exp)
                    return
            raise ValueError("追加目标已被删除，请刷新后重新选择")

    def trash_list(self):
        with self.lock:
            return read_yaml(self.data / "trash.yaml", {"items": []})["items"]

    def delete_library_item(self, kind, identifier):
        with self.lock:
            files, skills, trash = self._library_files(), self.skills(), self.trash_list()
            record = {"trash_id": "trash_" + uuid4().hex, "kind": kind,
                      "deleted_at": datetime.now().isoformat(timespec="seconds"), "reference_snapshot": {}}
            changes = {}
            if kind == "skill":
                item = next((x for x in skills if x["name"] == identifier), None)
                if item is None:
                    raise ValueError("技能已不存在")
                record["payload"] = deepcopy(item)
                for path, exp in files.items():
                    for evidence in exp["evidence"]:
                        tags = evidence["structured_fact"]["skills"]
                        if identifier in tags:
                            record["reference_snapshot"][evidence["evidence_id"]] = [identifier]
                            evidence["structured_fact"]["skills"] = [x for x in tags if x != identifier]
                            changes[path] = exp
                skills.remove(item)
            elif kind in {"evidence", "experience"}:
                found = False
                for path, exp in files.items():
                    if kind == "experience" and exp["experience_id"] == identifier:
                        record["payload"] = deepcopy(exp)
                        record["source_filename"] = path.name
                        ids = {x["evidence_id"] for x in exp["evidence"]}
                        changes[path] = None
                    elif kind == "evidence":
                        index = next((i for i, x in enumerate(exp["evidence"]) if x["evidence_id"] == identifier), None)
                        if index is None:
                            continue
                        record.update(payload=deepcopy(exp["evidence"].pop(index)),
                                      source_experience_id=exp["experience_id"], original_index=index)
                        ids = {identifier}
                        changes[path] = exp
                    else:
                        continue
                    for eid in ids:
                        record["reference_snapshot"][eid] = [x["name"] for x in skills if eid in x.get("evidence_ids", [])]
                    for skill in skills:
                        skill["evidence_ids"] = [x for x in skill.get("evidence_ids", []) if x not in ids]
                    found = True
                    break
                if not found:
                    raise ValueError("对象已不存在")
            else:
                raise ValueError("无效对象类型")
            trash.append(record)
            # Preserve deleted content first. Interrupted writes may require manual reconciliation.
            self._commit_library({self.data / "trash.yaml": {"items": trash},
                                  **changes, self.data / "skills.yaml": {"skills": skills}})
            return record["trash_id"]

    def trash_purge(self, trash_id):
        with self.lock:
            items = self.trash_list()
            if not any(x["trash_id"] == trash_id for x in items):
                raise ValueError("回收站记录已不存在")
            write_yaml(self.data / "trash.yaml", {"items": [x for x in items if x["trash_id"] != trash_id]})

    def trash_restore(self, trash_id):
        with self.lock:
            files, skills, trash = self._library_files(), self.skills(), self.trash_list()
            record = next((x for x in trash if x["trash_id"] == trash_id), None)
            if record is None:
                raise ValueError("回收站记录已不存在")
            payload, kind = deepcopy(record["payload"]), record["kind"]
            if kind == "skill":
                if any(x["name"] == payload["name"] for x in skills):
                    raise ValueError("同名技能已存在，未覆盖；可核对后清理回收站副本")
                skills.append(payload)
            elif kind == "experience":
                ids = {e["evidence_id"] for exp in files.values() for e in exp["evidence"]}
                if any(x["experience_id"] == payload["experience_id"] for x in files.values()) or ids.intersection(e["evidence_id"] for e in payload["evidence"]):
                    raise ValueError("同 ID 对象已存在，未覆盖；可核对后清理回收站副本")
                path = self.experiences_dir / Path(record["source_filename"]).name
                if path in files:
                    raise ValueError("原文件已存在，未覆盖")
                files[path] = payload
            else:
                if any(e["evidence_id"] == payload["evidence_id"] for x in files.values() for e in x["evidence"]):
                    raise ValueError("同 ID 证据已存在，未覆盖；可核对后清理回收站副本")
                parent = next((x for x in files.values() if x["experience_id"] == record["source_experience_id"]), None)
                if parent is None:
                    raise ValueError("请先恢复所属经历")
                parent["evidence"].insert(min(record["original_index"], len(parent["evidence"])), payload)
            evidence = {x["evidence_id"]: x for exp in files.values() for x in exp["evidence"]}
            skill_map = {x["name"]: x for x in skills}
            pending = []
            for eid, names in record["reference_snapshot"].items():
                for name in names:
                    if eid in evidence and name in skill_map:
                        item = skill_map[name]
                        item["evidence_ids"] = list(dict.fromkeys(item.get("evidence_ids", []) + [eid]))
                        tags = evidence[eid]["structured_fact"]["skills"]
                        if name not in tags:
                            tags.append(name)
                    else:
                        # Move deferred relations to the still-deleted counterpart, not a global queue.
                        other = None
                        for candidate in trash:
                            if candidate is record:
                                continue
                            missing_skill = (name not in skill_map and candidate["kind"] == "skill"
                                             and candidate["payload"]["name"] == name)
                            candidate_ids = ([candidate["payload"]["evidence_id"]] if candidate["kind"] == "evidence"
                                             else [e["evidence_id"] for e in candidate["payload"]["evidence"]]
                                             if candidate["kind"] == "experience" else [])
                            if missing_skill or (eid not in evidence and eid in candidate_ids):
                                other = candidate
                                break
                        if other:
                            names = other["reference_snapshot"].setdefault(eid, [])
                            if name not in names:
                                names.append(name)
                            pending.append(name)
            # A restored skill must not retain active dangling references.
            for item in skills:
                item["evidence_ids"] = [eid for eid in item.get("evidence_ids", []) if eid in evidence]
            self._validate_skills(skills)
            trash.remove(record)
            self._commit_library({**files, self.data / "skills.yaml": {"skills": skills},
                                  self.data / "trash.yaml": {"items": trash}})
            return "已恢复；关联对象也在回收站，恢复后自动重建关联" if pending else "已恢复"

    def save_source(self, filename: str, content: bytes) -> str:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = self.sources / f"{stamp}-{safe_name(filename)}"
        path.write_bytes(content)
        return path.relative_to(self.root).as_posix()

    def save_photo(self, filename: str, content: bytes) -> str:
        suffix = Path(filename).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png"}:
            raise ValueError("照片仅支持 JPEG 或 PNG")
        if not valid_image_signature(content, suffix):
            raise ValueError("照片内容与 JPEG/PNG 格式不符")
        with self.lock:
            folder = self.sources / "profile"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"photo{suffix}"
            path.write_bytes(content)
            profile = self.profile()
            profile.setdefault("profile", {})["photo_path"] = path.relative_to(self.root).as_posix()
            write_yaml(self.data / "profile.yaml", profile)
        return profile["profile"]["photo_path"]


def valid_image_signature(content: bytes, suffix: str) -> bool:
    if suffix == ".png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    return content.startswith(b"\xff\xd8\xff")


def safe_name(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    return result or "item"


class GenerationStore:
    CSV_FIELDS = [
        "company", "role", "generation_id", "language", "jd_reference",
        "html_version", "evidence_ids", "generated_at", "status", "follow_up_date", "notes",
    ]

    def __init__(self, root: Path = ROOT):
        self.root = root
        self.outputs = root / "outputs"
        self.outputs.mkdir(parents=True, exist_ok=True)
        self.csv_path = root / "applications.csv"
        self.reserved_ids: set[str] = set()
        self.lock = RLock()

    def generation_folder(self, identifier):
        if not re.fullmatch(r"gen-\d{8}-\d+", identifier):
            raise FileNotFoundError(identifier)
        return self.outputs / identifier

    def purged_ids(self):
        path = self.root / "data" / "purged-generations.txt"
        return set(path.read_text(encoding="utf-8").splitlines()) if path.exists() else set()

    def require_active(self, identifier):
        folder = self.generation_folder(identifier)
        if (self.outputs / (".purging-" + identifier)).exists():
            raise ValueError("快照正在清理，请到快照回收站重试彻底删除。")
        if (folder / "trash.yaml").exists():
            raise ValueError("快照已移入回收站，请先在历史页恢复。")
        if not (folder / "metadata.yaml").is_file():
            raise FileNotFoundError(identifier)
        return folder

    def source_label(self, identifier):
        if not identifier:
            return "首次生成"
        folder = self.generation_folder(identifier)
        if (self.outputs / (".purging-" + identifier)).exists():
            return identifier + "（清理未完成）"
        if (folder / "trash.yaml").exists():
            return identifier + "（已移入回收站）"
        if not (folder / "metadata.yaml").exists():
            return identifier + "（已删除或不可用）"
        return self.display_name(identifier)

    def trash_list(self):
        with self.lock:
            result = []
            for folder in list(self.outputs.glob("gen-*")) + list(self.outputs.glob(".purging-gen-*")):
                pending = folder.name.startswith(".purging-")
                if not pending and not (folder / "trash.yaml").is_file():
                    continue
                identifier = folder.name.removeprefix(".purging-")
                metadata = read_yaml(folder / "metadata.yaml", {})
                result.append({**metadata, "generation_id": identifier,
                    "display_name": read_yaml(folder / "display.yaml", {}).get("display_name") or identifier,
                    "deleted_at": read_yaml(folder / "trash.yaml", {}).get("deleted_at", ""), "pending": pending})
            return sorted(result, key=lambda item: item["generation_id"], reverse=True)

    def trash_action(self, identifier, action):
        with self.lock:
            folder = self.generation_folder(identifier)
            pending = self.outputs / (".purging-" + identifier)
            if action == "move":
                self.require_active(identifier)
                write_yaml(folder / "trash.yaml", {"deleted_at": datetime.now().astimezone().isoformat(timespec="seconds")})
                return "已移入快照回收站"
            if action == "restore":
                if pending.exists():
                    raise ValueError("快照清理未完成，不能恢复残缺制品，请重试彻底删除。")
                if not (folder / "trash.yaml").is_file():
                    raise ValueError("该快照不在回收站中。")
                (folder / "trash.yaml").unlink()
                return "快照已恢复；若列表未显示，请检查筛选条件"
            if action != "purge":
                raise ValueError("未知回收站操作。")
            if not pending.exists() and not (folder / "trash.yaml").is_file():
                raise ValueError("只允许彻底删除回收站中的快照。")
            record = self.root / "data" / "purged-generations.txt"
            record.parent.mkdir(parents=True, exist_ok=True)
            if identifier not in self.purged_ids():
                with record.open("a", encoding="utf-8") as handle:
                    handle.write(identifier + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            # Pending directories remain discoverable even if rmtree removes metadata first.
            if not pending.exists():
                folder.rename(pending)
            shutil.rmtree(pending)
            return "快照已彻底删除"

    def new_id(self) -> str:
        with self.lock:
            prefix = datetime.now().strftime("gen-%Y%m%d-")
            used = [p.name for p in self.outputs.glob(f"{prefix}*") if p.is_dir()]
            used += [name for name in self.reserved_ids if name.startswith(prefix)]
            used += [name for name in self.purged_ids() if name.startswith(prefix)]
            numbers = [int(name.rsplit("-", 1)[-1]) for name in used if name.rsplit("-", 1)[-1].isdigit()]
            identifier = f"{prefix}{max(numbers, default=0) + 1:03d}"
            self.reserved_ids.add(identifier)
            return identifier

    def create(
        self,
        company: str,
        role: str,
        jd_text: str,
        analysis: dict[str, Any],
        match_report: dict[str, Any],
        gap_report: str,
        artifacts: dict[str, tuple[dict[str, Any], str, str]],
        parent_generation_id: str | None = None,
        generation_id: str | None = None,
        llm_provenance: dict[str, Any] | None = None,
        display_name: str = "",
    ) -> str:
        if set(artifacts) != {"zh"}:
            raise ValueError("当前版本仅允许保存中文制品")
        display_name = self.validate_display_name(display_name)
        generation_id = generation_id or self.new_id()
        folder = self.outputs / generation_id
        if folder.exists():
            raise ValueError("已保存 generation 不可覆盖")
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        metadata = {
            "generation_id": generation_id,
            "parent_generation_id": parent_generation_id,
            "company": company,
            "role": role,
            "jd_text": jd_text,
            "generated_at": now,
            "languages": list(artifacts),
            "llm": deepcopy(llm_provenance) if isinstance(llm_provenance, dict) else {
                "service": "unknown", "model": "unknown", "mode": "unknown",
                "prompt_version": "unknown", "new_llm_call": False,
            },
        }
        # Stage complete artifacts before publishing; failed saves must not appear as history.
        with self.lock, tempfile.TemporaryDirectory(prefix=".saving-", dir=self.outputs) as temporary:
            staged = Path(temporary) / generation_id
            staged.mkdir()
            write_yaml(staged / "metadata.yaml", metadata)
            if display_name:
                write_yaml(staged / "display.yaml", {"display_name": display_name})
            write_yaml(staged / "jd-analysis.yaml", analysis)
            write_yaml(staged / "match-report.yaml", match_report)
            (staged / "gap-report.md").write_text(gap_report, encoding="utf-8")
            for language, (spec, css, html) in artifacts.items():
                lang_dir = staged / language
                lang_dir.mkdir()
                spec = {**spec, "generation_id": generation_id, "language": language}
                (lang_dir / "resume-spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
                (lang_dir / "custom.css").write_text(css, encoding="utf-8")
                (lang_dir / "resume.html").write_text(html, encoding="utf-8")
            if folder.exists():
                raise ValueError("已保存 generation 不可覆盖")
            staged.rename(folder)
            try:
                self._record(metadata, artifacts)
            except Exception:
                shutil.rmtree(folder)  # Only the new directory published by this save.
                raise
        return generation_id

    def load(self, generation_id: str, language: str) -> tuple[dict[str, Any], str, dict[str, Any]]:
        folder = self.require_active(generation_id)
        metadata = read_yaml(folder / "metadata.yaml", {})
        if language not in metadata.get("languages", []):
            raise FileNotFoundError(f"{generation_id}/{language}")
        lang_dir = folder / language
        spec = json.loads((lang_dir / "resume-spec.json").read_text(encoding="utf-8"))
        css = (lang_dir / "custom.css").read_text(encoding="utf-8")
        return spec, css, metadata

    def list(self) -> list[dict[str, Any]]:
        result = []
        for folder in self.outputs.glob("gen-*"):
            if (folder / "trash.yaml").exists():
                continue
            metadata = read_yaml(folder / "metadata.yaml", {})
            if metadata:
                metadata["display_name"] = self.display_name(folder.name)
                result.append(metadata)
        return sorted(result, key=lambda item: item["generation_id"], reverse=True)

    def display_name(self, generation_id: str) -> str:
        value = read_yaml(self.outputs / generation_id / "display.yaml", {})
        return value.get("display_name") or generation_id

    @staticmethod
    def validate_display_name(name: str) -> str:
        if not isinstance(name, str) or any(char in name for char in "\r\n"):
            raise ValueError("名称须为单行文字。")
        return name.strip()

    def rename(self, generation_id: str, name: str) -> str:
        name = self.validate_display_name(name)
        if not re.fullmatch(r"gen-\d{8}-\d+", generation_id):
            raise FileNotFoundError(generation_id)
        with self.lock:
            folder = self.require_active(generation_id)
            if not (folder / "metadata.yaml").is_file():
                raise FileNotFoundError(generation_id)
            name = name.strip()
            write_yaml(folder / "display.yaml", {"display_name": name})
            return name or generation_id

    def _record(self, metadata: dict[str, Any], artifacts: dict[str, tuple[dict[str, Any], str, str]]) -> None:
        existing: set[tuple[str, str]] = set()
        if self.csv_path.exists():
            with self.csv_path.open(newline="", encoding="utf-8-sig") as handle:
                existing = {(row["generation_id"], row["language"]) for row in csv.DictReader(handle)}
        original = self.csv_path.read_bytes() if self.csv_path.exists() else b"\xef\xbb\xbf"
        needs_header = not self.csv_path.exists() or not self.csv_path.stat().st_size
        with io.StringIO(newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.CSV_FIELDS)
            if needs_header:
                writer.writeheader()
            for language, (spec, _, _) in artifacts.items():
                key = (metadata["generation_id"], language)
                if key in existing:
                    continue
                evidence = sorted(referenced_evidence_ids(spec))
                writer.writerow({
                    "company": metadata["company"], "role": metadata["role"],
                    "generation_id": metadata["generation_id"], "language": language,
                    "jd_reference": f"outputs/{metadata['generation_id']}/metadata.yaml",
                    "html_version": f"outputs/{metadata['generation_id']}/{language}/resume.html",
                    "evidence_ids": "|".join(evidence), "generated_at": metadata["generated_at"],
                    "status": "未投递", "follow_up_date": "", "notes": "",
                })
            content = original + handle.getvalue().encode("utf-8")
        with tempfile.NamedTemporaryFile(dir=self.root, prefix=".applications-", delete=False) as temporary:
            temp_path = Path(temporary.name)
            temporary.write(content)
        try:
            os.replace(temp_path, self.csv_path)
        finally:
            temp_path.unlink(missing_ok=True)


def referenced_evidence_ids(spec: dict) -> set[str]:
    result = set()
    for item in spec.get("experiences", []) + spec.get("projects", []):
        for bullet in item.get("bullets", []):
            result.update(bullet.get("evidence_ids", []))
    for skill in spec.get("skills", []):
        result.update(skill.get("evidence_ids", []))
    return result
