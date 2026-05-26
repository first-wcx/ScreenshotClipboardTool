#!/bin/bash
# macOS 构建脚本 — 使用 py2app 打包为 .app
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${PROJECT_DIR}/dist/macos"
APP_NAME="IntegratedCaptureClipboard"

echo "=== macOS 构建脚本 ==="
echo "项目目录: ${PROJECT_DIR}"

# 检查依赖
echo ""
echo "[1/4] 检查 Python 依赖..."
pip install --quiet Pillow pystray pyobjc-framework-Cocoa pyobjc-framework-Quartz pynput

# 运行自检
echo ""
echo "[2/4] 运行组件自检..."
cd "${PROJECT_DIR}"
python -m integrated_tool.app --self-test-components
echo "自检通过 ✓"

# 创建 py2app setup 脚本
echo ""
echo "[3/4] 生成 py2app 配置..."
SETUP_PY="${BUILD_DIR}/setup_py2app.py"
mkdir -p "${BUILD_DIR}"

cat > "${SETUP_PY}" << 'SETUP_EOF'
from setuptools import setup

APP = ["src/integrated_tool/app.py"]
DATA_FILES = []
OPTIONS = {
    "argv_emulation": False,
    "iconfile": None,
    "packages": ["screenshot_tool", "integrated_tool", "clipboard_viewer", "platform_adapter"],
    "includes": [
        "PIL",
        "pystray",
        "AppKit",
        "Foundation",
        "CoreGraphics",
        "Quartz",
        "pynput",
    ],
    "excludes": [
        "winreg",
        "ctypes.wintypes",
    ],
}

setup(
    name="IntegratedCaptureClipboard",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
SETUP_EOF

# 执行打包
echo ""
echo "[4/4] 执行 py2app 打包..."
cd "${BUILD_DIR}"
python setup_py2app.py py2app

echo ""
echo "=== 构建完成 ==="
echo "应用位置: ${BUILD_DIR}/dist/${APP_NAME}.app"
echo ""
echo "如需安装到 /Applications，执行："
echo "  cp -r ${BUILD_DIR}/dist/${APP_NAME}.app /Applications/"
