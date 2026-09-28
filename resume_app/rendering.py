from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .storage import ROOT
from .inline_styles import render_field, FONT_STACKS
from .drafts import RenderContext, SnapshotResources, normalize_spec


class ResumeRenderer:
    def __init__(self, repository, root: Path = ROOT):
        self.root = root
        self.repository = repository
        self.templates = root / "templates"
        self.env = Environment(
            loader=FileSystemLoader(self.templates),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self.env.globals["render_field"] = render_field
        self.env.globals["font_stacks"] = FONT_STACKS

    def photo_data_url(self) -> str:
        relative = self.repository.profile().get("profile", {}).get("photo_path", "")
        path = self.repository.root / relative
        if not relative or not path.is_file():
            return ""
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"

    def current_context(self, spec: dict, css: str = "") -> RenderContext:
        return RenderContext(spec, self.photo_data_url(), self.current_css(), css)

    def current_css(self) -> str:
        return (self.root / "static" / "css" / "resume.css").read_text(encoding="utf-8")

    def snapshot_context(self, spec: dict, css: str, html: str) -> RenderContext:
        resources = SnapshotResources(html)
        return RenderContext(spec, resources.photo, "\n".join(resources.styles), css)

    def render_fragment(self, context: RenderContext, editable: bool = False) -> str:
        return self.env.get_template("resume_page.html").render(
            resume=normalize_spec(context.spec), editable=editable,
            photo_data_url=context.photo_data_url if context.spec.get("show_photo") else "",
        )

    def render_document(self, context: RenderContext, editable: bool = False) -> str:
        page = self.render_fragment(context, editable=editable)
        return self.env.get_template("resume_document.html").render(
            resume=context.spec, page=page, base_css=context.base_css, custom_css=context.custom_css,
            canvas_css=(self.root / "static/css/canvas.css").read_text(encoding="utf-8"),
            editor_css=(self.root / "static/css/canvas-editor.css").read_text(encoding="utf-8") if editable else ""
        )
