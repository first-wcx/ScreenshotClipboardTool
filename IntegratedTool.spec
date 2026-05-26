# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


SPEC_PATH = Path(SPECPATH).resolve()
APP_ROOT = SPEC_PATH if SPEC_PATH.is_dir() else SPEC_PATH.parent
APP_SRC = APP_ROOT / "src"

for path in (APP_SRC,):
    sys.path.insert(0, str(path))

hiddenimports = []
hiddenimports += collect_submodules("pystray")
hiddenimports += [
    "clipboard_viewer",
    "screenshot_tool.app",
    "screenshot_tool.clipboard",
    "screenshot_tool.config",
    "screenshot_tool.history",
    "screenshot_tool.hotkeys",
]

datas = []


a = Analysis(
    ["run.py"],
    pathex=[str(APP_SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "cv2",
        "easyocr",
        "matplotlib",
        "numpy",
        "pandas",
        "pytesseract",
        "screenshot_tool.ocr",
        "screenshot_tool.scrolling",
        "scipy",
        "torch",
        "transformers",
        "winocr",
        "winrt",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="IntegratedCaptureClipboard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
