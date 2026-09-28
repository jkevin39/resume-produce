"""Local Vision OCR; the image travels through stdin and is never archived."""
import json
import os
import subprocess
import sys
from .storage import ROOT, valid_image_signature

MAX_BYTES = 4 * 1024 * 1024
BINARY = ROOT / ".local-bin" / "resume-ocr"


def available():
    return sys.platform == "darwin" and os.access(BINARY, os.X_OK)


def recognize(data):
    if not available():
        raise ValueError("本机 OCR 尚未就绪，请运行 tools/build_macos.py 构建识别组件。")
    try:
        result = subprocess.run([str(BINARY)], input=data, capture_output=True, timeout=60)
        value = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise ValueError("本机识别失败或超时，请重试。")
    if result.returncode or "error" in value:
        raise ValueError(value.get("error", "图片识别失败。"))
    if not value.get("text", "").strip():
        raise ValueError("没有识别到文字，请换一张清晰截图。")
    return value["text"]


def validate_upload(data):
    if not data or len(data) > MAX_BYTES:
        raise ValueError("请选择一张不超过 4MB 的 PNG/JPEG 图片。")
    if not (valid_image_signature(data, ".png") or valid_image_signature(data, ".jpg")):
        raise ValueError("仅支持有效的 PNG/JPEG 图片。")
