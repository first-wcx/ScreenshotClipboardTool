from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path
from typing import Optional


RUN_VALUE_NAME = "ScreenshotTool"
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def current_startup_command() -> str:
    if getattr(sys, "frozen", False):
        return _quote(Path(sys.executable).resolve())

    script = _source_run_script()
    executable = _pythonw_executable()
    return f"{_quote(executable)} {_quote(script)}"


def is_startup_enabled() -> bool:
    if sys.platform != "win32":
        return False
    return _read_run_value() is not None


def set_startup_enabled(enabled: bool) -> Optional[str]:
    if sys.platform != "win32":
        raise RuntimeError("开机自启只支持 Windows。")

    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            command = current_startup_command()
            winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, command)
            return command
        try:
            winreg.DeleteValue(key, RUN_VALUE_NAME)
        except FileNotFoundError:
            pass
        return None


def _read_run_value() -> Optional[str]:
    if sys.platform != "win32":
        return None

    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            value, _value_type = winreg.QueryValueEx(key, RUN_VALUE_NAME)
            return str(value)
    except FileNotFoundError:
        return None
    except OSError:
        return None


def _source_run_script() -> Path:
    argv0 = Path(sys.argv[0]).resolve()
    if argv0.name.lower() == "run.py" and argv0.exists():
        return argv0

    package_root = Path(__file__).resolve().parent
    project_root = package_root.parents[1]
    candidate = project_root / "run.py"
    if candidate.exists():
        return candidate
    return argv0


def _pythonw_executable() -> Path:
    executable = Path(sys.executable).resolve()
    if os.name == "nt" and executable.name.lower() == "python.exe":
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            return pythonw
    return executable


def _quote(path: Path) -> str:
    return shlex.quote(str(path)) if os.name != "nt" else f'"{path}"'
