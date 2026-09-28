from __future__ import annotations

from typing import Any
import base64

from .storage import valid_image_signature
from .drafts import normalize_spec


ALLOWED_TEMPLATES = {"classic"}
ALLOWED_THEMES = {"blue", "charcoal", "green"}
ALLOWED_DENSITIES = {"normal", "compact"}
ALLOWED_SECTIONS = {"education", "experience", "projects", "skills"}
ALLOWED_PHOTO_POSITIONS = {"center top", "center", "center bottom", "left top", "right top"}
ALLOWED_PHOTO_SIZES = {"22mm", "25mm", "28mm", "30mm", "32mm", "35mm", "38mm", "40mm"}


def validate_resume_spec(spec: dict[str, Any], photo_data_url: str = "") -> list[str]:
    try:
        spec = normalize_spec(spec)
    except ValueError as exc:
        return [str(exc)]
    errors: list[str] = []
    for field in ("generation_id", "language", "template", "theme", "density", "profile", "section_order"):
        if field not in spec:
            errors.append(f"缺少必填字段：{field}")
    profile = spec.get("profile", {})
    if not str(profile.get("name", "")).strip():
        errors.append("姓名不能为空")
    if not str(profile.get("phone", "")).strip() and not str(profile.get("email", "")).strip():
        errors.append("电话和邮箱至少填写一项")
    if spec.get("template") not in ALLOWED_TEMPLATES:
        errors.append("模板不在允许范围内")
    if spec.get("theme") not in ALLOWED_THEMES:
        errors.append("主题不在允许范围内")
    if spec.get("density") not in ALLOWED_DENSITIES:
        errors.append("排版密度不在允许范围内")
    if spec.get("language") != "zh":
        errors.append("当前仅允许保存中文简历")
    sections = spec.get("section_order", [])
    if len(sections) != len(set(sections)) or any(item not in ALLOWED_SECTIONS for item in sections):
        errors.append("板块顺序包含重复或未知板块")
    if spec.get("show_photo"):
        try:
            header, data = photo_data_url.split(",", 1)
            suffix = {"data:image/jpeg;base64": ".jpg", "data:image/png;base64": ".png"}.get(header)
            if not suffix or not valid_image_signature(base64.b64decode(data, validate=True), suffix):
                raise ValueError()
        except (ValueError, TypeError):
            errors.append("草稿中缺少有效 JPEG 或 PNG 照片，请更新照片后重试")
        photo = spec.get("photo", {})
        if photo.get("width") not in ALLOWED_PHOTO_SIZES or photo.get("height") not in ALLOWED_PHOTO_SIZES:
            errors.append("照片尺寸不在允许范围内")
        if photo.get("position") not in ALLOWED_PHOTO_POSITIONS:
            errors.append("照片裁切位置不在允许范围内")
    return list(dict.fromkeys(errors))
