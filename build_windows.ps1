$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
..\.venv\Scripts\python.exe -m PyInstaller .\IntegratedTool.spec --clean --noconfirm
