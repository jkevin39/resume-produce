"""Ephemeral render context. No persistent resource-version store."""
from copy import deepcopy
from dataclasses import dataclass
from html.parser import HTMLParser
import json
from .canvas import initialize_layout, apply_layout
from .inline_styles import validate_inline_styles


STYLE_DEFAULTS = {"cjk_font": "songti", "font_size": "10.5pt", "line_height": "1.42", "page_padding": "14mm 16mm", "section_gap": "4.2mm", "bullet_gap": ".7mm", "title_color": ""}
SECTION_TITLES = {"education": "教育经历", "experience": "实习经历", "projects": "项目经历", "skills": "技能"}
# Saved HTML is a historical data source. These selectors are compatibility APIs.
SNAPSHOT_BASE_CSS_ID = "base-css"
SNAPSHOT_CUSTOM_CSS_ID = "custom-css"
SNAPSHOT_PHOTO_CLASS = "profile-photo"


def normalize_spec(value):
    """Supply renderable empty fields, not facts or evidence. Export may be incomplete."""
    if not isinstance(value, dict):
        raise ValueError("ResumeSpec 必须是 JSON 对象")
    validate_structure(value)
    spec = deepcopy(value)
    if spec.get("language", "zh") != "zh":
        raise ValueError("本版仅生成和编辑中文，英文历史仅供查看")
    for key, default in {"generation_id": "draft", "language": "zh", "template": "classic", "theme": "blue", "density": "normal", "show_photo": False}.items():
        spec.setdefault(key, default)
    spec["photo"] = {"width": "25mm", "height": "32mm", "position": "center top", **spec.get("photo", {})}
    spec["style"] = {**STYLE_DEFAULTS, **spec.get("style", {})}
    spec["profile"] = {**dict.fromkeys(("name", "phone", "email", "location", "summary"), ""), **spec.get("profile", {})}
    spec["section_titles"] = {**SECTION_TITLES, **spec.get("section_titles", {})}
    spec.setdefault("section_order", list(SECTION_TITLES))
    for key in ("education", "experiences", "projects", "skills", "custom_bullets"):
        spec.setdefault(key, [])
        if not isinstance(spec[key], list):
            raise ValueError(f"{key} 必须是数组")
    for education in spec["education"]:
        for key in ("school", "degree", "major", "date", "details"):
            education.setdefault(key, "")
    for entry in spec["experiences"] + spec["projects"]:
        for key in ("organization", "title", "date", "location"):
            entry.setdefault(key, "")
        entry.setdefault("bullets", [])
    for skill in spec["skills"]:
        # `description` was added after the first ResumeSpec versions.  Keep
        # the field optional on input while giving the editor/rendering layer a
        # stable empty string to work with.
        skill.setdefault("description", "")
    initialize_layout(spec)
    apply_layout(spec)
    validate_inline_styles(spec)
    return spec


@dataclass
class RenderContext:
    spec: dict
    photo_data_url: str
    base_css: str
    custom_css: str = ""


class SnapshotResources(HTMLParser):
    """Recover existing embedded resources when continuing a saved HTML snapshot."""
    def __init__(self, html):
        super().__init__()
        self.styles = []
        self.photo = ""
        self.current_style = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "style" and attrs.get("id") not in {SNAPSHOT_CUSTOM_CSS_ID, "canvas-css", "editor-css"}:
            self.current_style = []
        if tag == "img" and SNAPSHOT_PHOTO_CLASS in attrs.get("class", "").split():
            self.photo = attrs.get("src", "")

    def handle_data(self, data):
        if self.current_style is not None:
            self.current_style.append(data)

    def handle_endtag(self, tag):
        if tag == "style" and self.current_style is not None:
            self.styles.append("".join(self.current_style))
            self.current_style = None


def validate_structure(spec):
    """Check provided fields before defaulting; provenance is optional typed metadata."""
    try:
        json.dumps(spec, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('ResumeSpec 必须可序列化为 JSON') from exc
    def fields(obj, strings=(), arrays=(), booleans=()):
        if not isinstance(obj, dict):
            raise ValueError('ResumeSpec 字段必须是对象')
        for key in strings:
            if key in obj and not isinstance(obj[key], str):
                raise ValueError(f'{key} 必须是字符串')
        for key in arrays:
            if key in obj and (not isinstance(obj[key], list) or any(not isinstance(v, str) for v in obj[key])):
                raise ValueError(f'{key} 必须是字符串数组')
        for key in booleans:
            if key in obj and type(obj[key]) is not bool:
                raise ValueError(f'{key} 必须是布尔值')
    fields(spec, ('generation_id','language','template','theme','density'), ('section_order',), ('show_photo',))
    for key, names in {'profile': ('name','phone','email','location','summary'),
                       'photo': ('width','height','position'), 'style': tuple(STYLE_DEFAULTS),
                       'section_titles': tuple(SECTION_TITLES)}.items():
        fields(spec.get(key, {}), names)
    for key in ('education','experiences','projects','skills','custom_bullets'):
        rows = spec.get(key, [])
        if not isinstance(rows, list):
            raise ValueError(f'{key} 必须是数组')
        for row in rows:
            fields(row, ('canvas_id','experience_id','education_id','school','degree','major','date','details','organization','title','location','name','description','text'), ('evidence_ids','source_refs'), ('user_confirmed',))
            if key in ('experiences','projects'):
                bullets = row.get('bullets', [])
                if not isinstance(bullets, list):
                    raise ValueError('bullets 必须是数组')
                for bullet in bullets:
                    fields(bullet, ('canvas_id','text'), ('evidence_ids','source_refs'))
