from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict


APP_NAME = "ScreenshotTool"


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def default_save_dir() -> Path:
    pictures = Path.home() / "Pictures"
    return pictures / "Screenshots"


@dataclass
class Settings:
    save_dir: str
    auto_copy_after_capture: bool = True
    auto_save_after_capture: bool = False
    filename_pattern: str = "screenshot_%Y%m%d_%H%M%S.png"
    show_capture_magnifier: bool = True
    keep_editor_on_top: bool = False
    float_after_capture: bool = False
    minimize_to_background: bool = True
    close_action: str = "ask"
    toolbar_mode: str = "mini"
    ocr_language: str = "zh-Hans"
    scroll_max_frames: int = 12
    scroll_wheel_delta: int = 650
    scroll_pause_ms: int = 420
    enable_global_hotkeys: bool = True
    start_with_windows: bool = False


def default_settings() -> Settings:
    return Settings(save_dir=str(default_save_dir()))


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def load_settings() -> Settings:
    path = settings_path()
    if not path.exists():
        return default_settings()

    try:
        payload: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_settings()

    base = asdict(default_settings())
    base.update({key: value for key, value in payload.items() if key in base})
    return Settings(**base)


def save_settings(settings: Settings) -> None:
    directory = app_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def ensure_runtime_dirs(settings: Settings) -> None:
    app_data_dir().mkdir(parents=True, exist_ok=True)
    Path(settings.save_dir).mkdir(parents=True, exist_ok=True)
