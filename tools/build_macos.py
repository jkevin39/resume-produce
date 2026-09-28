"""Build the local app in this checkout; no installer or data migration."""
import plistlib
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
bundle = root / "简历工作台.app"
contents = bundle / "Contents"
(contents / "MacOS").mkdir(parents=True, exist_ok=True)
(contents / "Resources").mkdir(exist_ok=True)
with (contents / "Info.plist").open("wb") as handle:
    plistlib.dump({"CFBundleExecutable": "ResumeLauncher", "CFBundleIdentifier": "local.resume-produce",
                  "CFBundleName": "简历工作台", "CFBundleDisplayName": "简历工作台",
                  "CFBundlePackageType": "APPL", "CFBundleIconFile": "Resume", "CFBundleVersion": "0.11",
                  "NSHighResolutionCapable": True, "ResumeProjectPath": str(root)}, handle)
subprocess.run(["xcrun", "swiftc", str(root / "macos/Launcher.swift"), "-o",
                str(contents / "MacOS/ResumeLauncher"), "-module-cache-path", "/tmp/resume-swift-cache"], check=True)
print(bundle)
binary = root / ".local-bin" / "resume-ocr"
binary.parent.mkdir(exist_ok=True)
subprocess.run(["xcrun", "swiftc", str(root / "macos/OCR.swift"), "-o", str(binary),
                "-module-cache-path", "/tmp/resume-swift-cache"], check=True)
print(binary)

import tempfile
with tempfile.TemporaryDirectory(prefix="resume-icon-") as temp:
    iconset = Path(temp) / "Resume.iconset"
    subprocess.run(["xcrun", "swift", "-module-cache-path", "/tmp/resume-swift-cache",
                    str(root / "macos/Icon.swift"), str(iconset)], check=True)
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o",
                    str(contents / "Resources/Resume.icns")], check=True)
