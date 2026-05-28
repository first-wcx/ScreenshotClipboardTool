#!/bin/bash
set -e

pip install pyinstaller pynput python-xlib

pyinstaller --onefile --windowed \
    --name IntegratedCaptureClipboard \
    --icon assets/icon.ico \
    src/run.py

echo "Build complete: dist/IntegratedCaptureClipboard"
