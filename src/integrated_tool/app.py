from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw


Point = Tuple[int, int]
BBox = Tuple[int, int, int, int]
APP_NAME = "IntegratedCaptureClipboard"


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def add_legacy_import_paths() -> None:
    candidates = [project_root() / "src"]
    for path in candidates:
        text = str(path)
        if path.exists() and text not in sys.path:
            sys.path.insert(0, text)


add_legacy_import_paths()

import clipboard_viewer as clip  # noqa: E402
import pystray  # noqa: E402
from platform_adapter import HotkeyDef, get_adapter  # noqa: E402
from screenshot_tool.clipboard import copy_image_to_clipboard  # noqa: E402
from screenshot_tool.config import Settings as ScreenshotSettings  # noqa: E402
from screenshot_tool.hotkeys import (  # noqa: E402
    GlobalHotkeyManager,
    Hotkey,
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
)


SCREENSHOT_COMPONENTS = None
DEFAULT_HOTKEYS = {
    "copy": "Alt+A",
    "edit": "Alt+S",
    "pin": "Alt+D",
    "show": "Ctrl+Shift+M",
}


def app_data_dir() -> Path:
    """获取应用数据目录（跨平台）。"""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
        return Path(base) / APP_NAME
    # Linux 或其他平台
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / APP_NAME.lower()
    return Path.home() / f".{APP_NAME.lower()}"


def runtime_dir() -> Path:
    directory = app_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def integrated_settings_path() -> Path:
    return runtime_dir() / "settings.json"


def current_startup_command() -> str:
    """获取当前平台的启动命令。"""
    if getattr(sys, "frozen", False):
        return quote_path(Path(sys.executable).resolve())
    executable = Path(sys.executable).resolve()
    if sys.platform == "win32" and executable.name.lower() == "python.exe":
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            executable = pythonw
    return f"{quote_path(executable)} {quote_path(project_root() / 'run.py')}"


def quote_path(path: Path) -> str:
    """给路径加引号（跨平台）。"""
    return f'"{path}"'


# 保留旧名以兼容
def quote_windows_path(path: Path) -> str:
    """已弃用：保留签名以兼容，委托给 quote_path。"""
    return quote_path(path)


def read_startup_value() -> Optional[str]:
    """读取开机自启注册值（兼容层，委托给适配器）。"""
    # Windows 上可通过适配器获取，其他平台返回 None
    if sys.platform == "win32":
        import winreg
        try:
            from windows_adapter import RUN_KEY_PATH, RUN_VALUE_NAME
        except ImportError:
            RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
            RUN_VALUE_NAME = APP_NAME
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
                value, _value_type = winreg.QueryValueEx(key, RUN_VALUE_NAME)
                return str(value)
        except (FileNotFoundError, OSError):
            return None
    return None


def is_integrated_startup_enabled() -> bool:
    """检查开机自启是否已启用，委托给适配器。"""
    return get_adapter().is_startup_enabled()


def set_integrated_startup_enabled(enabled: bool) -> Optional[str]:
    """设置开机自启，委托给适配器。"""
    return get_adapter().set_startup_enabled(enabled)


def configure_clipboard_module() -> None:
    data_dir = runtime_dir()
    clip.APP_DIR = data_dir
    clip.HISTORY_FILE = data_dir / "clipboard_history.json"
    clip.IMAGE_DIR = data_dir / "images"
    clip.SYNC_CONFIG_FILE = data_dir / "clipboard_sync.json"
    clip.IMAGE_DIR.mkdir(parents=True, exist_ok=True)


def install_disabled_screenshot_feature_stubs() -> None:
    import types

    if "screenshot_tool.ocr" not in sys.modules:
        ocr_stub = types.ModuleType("screenshot_tool.ocr")

        class OcrResult:
            def __init__(
                self,
                text: str = "",
                engine: str = "disabled",
                language: str = "",
                lines: Optional[List[str]] = None,
                line_items: Optional[List[object]] = None,
            ) -> None:
                self.text = text
                self.engine = engine
                self.language = language
                self.lines = lines or []
                self.line_items = line_items or []

        def recognize_text(*_args, **_kwargs):
            raise RuntimeError("OCR 已在整合版轻量模式中禁用。")

        def format_ocr_text(result, _mode: str = "clean") -> str:
            return getattr(result, "text", "")

        ocr_stub.OcrResult = OcrResult
        ocr_stub.recognize_text = recognize_text
        ocr_stub.format_ocr_text = format_ocr_text
        sys.modules["screenshot_tool.ocr"] = ocr_stub

    if "screenshot_tool.scrolling" not in sys.modules:
        scrolling_stub = types.ModuleType("screenshot_tool.scrolling")

        def disabled_scrolling(*_args, **_kwargs):
            raise RuntimeError("滚动长截图已在整合版轻量模式中禁用。")

        scrolling_stub.collect_scrolling_frames = disabled_scrolling
        scrolling_stub.stitch_vertical = disabled_scrolling
        sys.modules["screenshot_tool.scrolling"] = scrolling_stub


def patch_screenshot_components(module) -> None:
    if getattr(module, "_integrated_light_patch", False):
        return

    if hasattr(module, "TOOLBAR_ACTIONS"):
        module.TOOLBAR_ACTIONS = tuple(
            action for action in module.TOOLBAR_ACTIONS if action[0] not in {"ocr", "scroll"}
        )

    def build_editor_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(10, 8), style="Toolbar.TFrame")
        toolbar.pack(fill=tk.X)

        ttk.Label(toolbar, text="工具").pack(side=tk.LEFT, padx=(0, 4))
        for key, label in module.TOOL_LABELS.items():
            ttk.Radiobutton(
                toolbar,
                text=label,
                value=key,
                variable=self.tool_var,
                command=self.update_status,
            ).pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(toolbar, text="颜色").pack(side=tk.LEFT, padx=(0, 4))
        for color in module.PALETTE:
            swatch = tk.Button(
                toolbar,
                width=2,
                height=1,
                bg=color,
                activebackground=color,
                relief=tk.RIDGE,
                command=lambda value=color: self.set_color(value),
            )
            swatch.pack(side=tk.LEFT, padx=1)

        ttk.Label(toolbar, text="粗细").pack(side=tk.LEFT, padx=(10, 2))
        ttk.Spinbox(toolbar, from_=1, to=30, width=4, textvariable=self.width_var, command=self.update_status).pack(
            side=tk.LEFT
        )

        actionbar = ttk.Frame(self, padding=(10, 0, 10, 8), style="Toolbar.TFrame")
        actionbar.pack(fill=tk.X)
        actions = [
            ("撤销", self.undo),
            ("重做", self.redo),
            ("适应", self.fit_to_window),
            ("100%", self.zoom_actual),
            ("-", lambda: self.change_zoom(0.85)),
            ("+", lambda: self.change_zoom(1.15)),
            ("复制", self.copy_to_clipboard),
            ("保存", self.quick_save),
            ("另存", self.save_as),
            ("贴图", self.pin_current),
        ]
        for label, command in actions:
            ttk.Button(actionbar, text=label, command=command).pack(side=tk.LEFT, padx=(0, 6))

        if self.source_bbox:
            source = f"屏幕区域：{self.source_bbox[0]}, {self.source_bbox[1]}"
        else:
            source = "导入图片"
        ttk.Label(actionbar, text=source, foreground="#667085").pack(side=tk.RIGHT)

        canvas_frame = ttk.Frame(self, padding=(10, 0, 10, 8))
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(canvas_frame, bg="#111827", highlightthickness=0, cursor="crosshair")
        self.hbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.vbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.hbar.set, yscrollcommand=self.vbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        statusbar = ttk.Frame(self, padding=(10, 2, 10, 8))
        statusbar.pack(fill=tk.X)
        ttk.Label(statusbar, textvariable=self.status_var, foreground="#475467").pack(side=tk.LEFT)

    def floating_menu(self, event: tk.Event) -> None:
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="编辑", command=self.edit)
        menu.add_command(label="保存", command=self.quick_save)
        menu.add_command(label="另存", command=self.save_as)
        menu.add_separator()
        menu.add_command(label="复制图片", command=self.copy_current)
        menu.add_separator()
        menu.add_command(label="切换置顶", command=self.toggle_topmost)
        menu.add_command(label="显示主窗口", command=self.show_main_window)
        menu.add_command(label="关闭", command=self.destroy)
        menu.tk_popup(event.x_root, event.y_root)

    def disabled_ocr(self) -> None:
        messagebox.showinfo("OCR 已禁用", "整合版轻量模式暂时不启用 OCR。", parent=self)

    module.EditorWindow._build_ui = build_editor_ui
    module.EditorWindow.run_ocr = disabled_ocr
    module.FloatingCaptureWindow._menu = floating_menu
    module.FloatingCaptureWindow.run_ocr = disabled_ocr
    module._integrated_light_patch = True


def load_screenshot_components():
    global SCREENSHOT_COMPONENTS
    if SCREENSHOT_COMPONENTS is not None:
        return SCREENSHOT_COMPONENTS
    install_disabled_screenshot_feature_stubs()
    import screenshot_tool.app as screenshot_app

    SCREENSHOT_COMPONENTS = {
        "CaptureOverlay": screenshot_app.CaptureOverlay,
        "FloatingCaptureWindow": screenshot_app.FloatingCaptureWindow,
        "open_image_editor": screenshot_app.open_image_editor,
        "virtual_screen_bounds": screenshot_app.virtual_screen_bounds,
    }
    patch_screenshot_components(screenshot_app)
    return SCREENSHOT_COMPONENTS


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def save_image_file(image: Image.Image, path: Path) -> None:
    image_to_save = image.convert("RGBA")
    if path.suffix.lower() in {".jpg", ".jpeg", ".bmp"}:
        background = Image.new("RGB", image_to_save.size, "white")
        background.paste(image_to_save, mask=image_to_save.getchannel("A"))
        image_to_save = background
    path.parent.mkdir(parents=True, exist_ok=True)
    image_to_save.save(path)


def default_screenshot_settings() -> ScreenshotSettings:
    data_dir = runtime_dir()
    save_dir = data_dir / "captures"
    save_dir.mkdir(parents=True, exist_ok=True)
    settings = ScreenshotSettings(
        save_dir=str(save_dir),
        auto_copy_after_capture=True,
        auto_save_after_capture=False,
        filename_pattern="capture_%Y%m%d_%H%M%S.png",
        show_capture_magnifier=True,
        keep_editor_on_top=False,
        float_after_capture=False,
        minimize_to_background=True,
        close_action="background",
        toolbar_mode="mini",
        enable_global_hotkeys=True,
        start_with_windows=False,
    )
    settings.hide_main_during_capture = True
    path = integrated_settings_path()
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for key, value in payload.items():
                if hasattr(settings, key):
                    setattr(settings, key, value)
        except (OSError, json.JSONDecodeError):
            pass
    Path(settings.save_dir).mkdir(parents=True, exist_ok=True)
    return settings


def load_hotkeys() -> Dict[str, str]:
    hotkeys = dict(DEFAULT_HOTKEYS)
    path = integrated_settings_path()
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            configured = payload.get("hotkeys", {})
            if isinstance(configured, dict):
                for key in hotkeys:
                    value = configured.get(key)
                    if isinstance(value, str) and value.strip():
                        hotkeys[key] = value.strip()
        except (OSError, json.JSONDecodeError):
            pass
    return hotkeys


def save_integrated_config(settings: ScreenshotSettings, hotkeys: Dict[str, str]) -> None:
    payload = dict(settings.__dict__)
    payload["hotkeys"] = hotkeys
    integrated_settings_path().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_hotkey(value: str, callback: Callable[[], None]) -> Optional[HotkeyDef]:
    """将 "Alt+A" 风格的热键字符串解析为跨平台 HotkeyDef。"""
    parts = [part.strip() for part in value.replace(" ", "").split("+") if part.strip()]
    if not parts:
        return None
    # 验证格式有效性
    key = parts[-1].upper()
    for part in parts[:-1]:
        name = part.upper()
        if name not in {"CTRL", "CONTROL", "SHIFT", "ALT", "WIN", "WINDOWS"}:
            raise ValueError(f"不支持的修饰键: {part}")
    if not (len(key) == 1 and key.isalnum()) and not (key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12):
        raise ValueError(f"不支持的按键: {key}")
    return HotkeyDef(name=value, key=value, callback=callback)


@dataclass
class CaptureHistoryItem:
    id: str
    path: str
    created_at: str
    width: int
    height: int
    thumbnail: str


class IntegratedScreenshotHistory:
    def __init__(self) -> None:
        self.directory = runtime_dir()
        self.captures_dir = self.directory / "captures"
        self.thumbnails_dir = self.directory / "thumbnails"
        self.path = self.directory / "capture_history.json"
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnails_dir.mkdir(parents=True, exist_ok=True)
        self.items: List[CaptureHistoryItem] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.items = []
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.items = []
            return
        items: List[CaptureHistoryItem] = []
        for item in payload:
            if isinstance(item, dict):
                try:
                    items.append(CaptureHistoryItem(**item))
                except TypeError:
                    continue
        self.items = items

    def save(self) -> None:
        self.path.write_text(
            json.dumps([asdict(item) for item in self.items], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, image_path: Path, width: int, height: int) -> CaptureHistoryItem:
        item_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
        thumbnail = self.thumbnails_dir / f"{item_id}.png"
        self._make_thumbnail(image_path, thumbnail)
        item = CaptureHistoryItem(
            id=item_id,
            path=str(image_path),
            created_at=datetime.now().isoformat(timespec="seconds"),
            width=width,
            height=height,
            thumbnail=str(thumbnail),
        )
        self.items.insert(0, item)
        overflow = self.items[200:]
        self.items = self.items[:200]
        for stale in overflow:
            self._delete_item_files(stale)
        self.save()
        return item

    def add_image(self, image: Image.Image) -> CaptureHistoryItem:
        filename = datetime.now().strftime("capture_%Y%m%d_%H%M%S.png")
        path = unique_path(self.captures_dir / filename)
        save_image_file(image, path)
        return self.add(path, image.width, image.height)

    def recent(self, limit: int = 80) -> List[CaptureHistoryItem]:
        return self.items[:limit]

    def get(self, item_id: str) -> Optional[CaptureHistoryItem]:
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def remove(self, item_id: str) -> None:
        item = self.get(item_id)
        self.items = [existing for existing in self.items if existing.id != item_id]
        if item:
            self._delete_item_files(item)
        self.save()

    def clear_cache(self) -> int:
        removed = 0
        for item in list(self.items):
            removed += self._delete_item_files(item)
        self.items = []
        self.save()
        return removed

    def _make_thumbnail(self, image_path: Path, thumbnail_path: Path) -> None:
        try:
            with Image.open(image_path) as image:
                image.thumbnail((360, 220))
                image.convert("RGB").save(thumbnail_path, "PNG")
        except OSError:
            pass

    def _delete_item_files(self, item: CaptureHistoryItem) -> int:
        removed = 0
        for value, owned in ((item.thumbnail, True), (item.path, False)):
            try:
                path = Path(value)
                if not owned:
                    try:
                        owned = path.parent.resolve() == self.captures_dir.resolve()
                    except OSError:
                        owned = False
                if owned and path.exists():
                    path.unlink()
                    removed += 1
            except OSError:
                pass
        return removed


class IntegratedTrayIcon:
    def __init__(self, command_queue: "queue.Queue[str]") -> None:
        self.command_queue = command_queue
        self.icon = pystray.Icon(
            "integrated_capture_clipboard",
            self._create_icon_image(),
            "截图剪切板工具",
            menu=pystray.Menu(
                pystray.MenuItem("剪切板", self._show_clipboard, default=True),
                pystray.MenuItem("历史截图", self._show_captures),
                pystray.MenuItem("设置", self._show_settings),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", self._quit),
            ),
        )
        self.thread = threading.Thread(target=self.icon.run, name="IntegratedTray", daemon=True)
        self.thread.start()

    def _create_icon_image(self) -> Image.Image:
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=10, fill=(20, 82, 120, 255))
        draw.rectangle((18, 16, 46, 36), outline=(255, 255, 255, 255), width=4)
        draw.line((22, 46, 42, 46), fill=(125, 211, 252, 255), width=5)
        draw.line((44, 40, 52, 48), fill=(45, 212, 191, 255), width=4)
        return image

    def _put(self, command: str):
        self.command_queue.put(command)

    def _show_clipboard(self, _icon=None, _item=None):
        self._put("show_clipboard")

    def _show_captures(self, _icon=None, _item=None):
        self._put("show_captures")

    def _show_settings(self, _icon=None, _item=None):
        self._put("show_settings")

    def _quit(self, _icon=None, _item=None):
        self._put("quit")

    def remove(self) -> None:
        self.icon.stop()


class IntegratedApp(clip.ClipboardViewer):
    def __init__(self) -> None:
        configure_clipboard_module()
        clip.TrayIcon = IntegratedTrayIcon
        self.screenshot_settings = default_screenshot_settings()
        self.screenshot_history = IntegratedScreenshotHistory()
        self.capture_mode = "editor"
        self._restore_main_after_capture = False
        self.recent_preview_image: Optional[ImageTk.PhotoImage] = None
        self.hotkey_manager: Optional[GlobalHotkeyManager] = None
        self.hotkeys = load_hotkeys()
        self.hotkey_vars: Dict[str, tk.StringVar] = {}
        self.sync_device_count_var: Optional[tk.StringVar] = None
        self.sync_device_list_var: Optional[tk.StringVar] = None
        super().__init__()
        self.title("截图剪切板工具")
        self.hotkey_manager = GlobalHotkeyManager(self)
        self._apply_hotkeys()

    def _build_ui(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.clipboard_tab = ttk.Frame(self.notebook, padding=8)
        self.capture_tab = ttk.Frame(self.notebook, padding=8)
        self.settings_tab = ttk.Frame(self.notebook, padding=8)
        self.devices_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.clipboard_tab, text="剪切板")
        self.notebook.add(self.capture_tab, text="截图")
        self.notebook.add(self.devices_tab, text="设备同步")
        self.notebook.add(self.settings_tab, text="设置")

        self._build_clipboard_tab(self.clipboard_tab)
        self._build_capture_tab(self.capture_tab)
        self._build_devices_tab(self.devices_tab)
        self._build_settings_tab(self.settings_tab)

        # Sync status bar at the bottom
        sync_status_frame = ttk.Frame(root)
        sync_status_frame.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        sync_status_frame.columnconfigure(1, weight=1)
        self.sync_indicator_var = tk.StringVar(value="● 同步未启用")
        ttk.Label(
            sync_status_frame,
            textvariable=self.sync_indicator_var,
            foreground="#888888",
            font=("", 9),
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))
        status = ttk.Label(sync_status_frame, textvariable=self.status_var, anchor="w", font=("", 9))
        status.grid(row=0, column=1, sticky="ew")

    def _build_clipboard_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(parent)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure(1, weight=1)
        ttk.Label(toolbar, text="搜索").grid(row=0, column=0, padx=(0, 6))
        ttk.Entry(toolbar, textvariable=self.search_var).grid(row=0, column=1, sticky="ew")

        # Sync status indicator in clipboard toolbar
        if self.sync_device_count_var is None:
            self.sync_device_count_var = tk.StringVar(value="0")
        sync_ind = ttk.Frame(toolbar)
        sync_ind.grid(row=0, column=2, padx=(8, 0))
        ttk.Label(sync_ind, text="同步:").pack(side=tk.LEFT, padx=(0, 2))
        ttk.Label(sync_ind, textvariable=self.sync_device_count_var, foreground="#2196F3").pack(side=tk.LEFT)

        actions = ttk.Frame(parent)
        actions.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for column in range(3):
            actions.columnconfigure(column, weight=1)
        ttk.Button(actions, text="复制", command=self.copy_selected).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(actions, text="打开", command=self.open_selected).grid(row=0, column=1, sticky="ew", padx=2)
        ttk.Button(actions, text="编辑", command=self.edit_selected_image).grid(row=0, column=2, sticky="ew", padx=(4, 0))

        main = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        main.grid(row=2, column=0, sticky="nsew")

        left = ttk.Frame(main)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        main.add(left, weight=2)

        columns = ("time", "type", "preview")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse", height=8)
        self.tree.heading("time", text="时间")
        self.tree.heading("type", text="类型")
        self.tree.heading("preview", text="内容预览")
        self.tree.column("time", width=int(142 * self.ui_scale), anchor="w", stretch=False)
        self.tree.column("type", width=int(54 * self.ui_scale), anchor="center", stretch=False)
        self.tree.column("preview", width=int(260 * self.ui_scale), anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.show_selected())
        self.tree.bind("<Button-3>", self.show_tree_context_menu)
        scrollbar = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        right = ttk.Frame(main, padding=(0, 8, 0, 0))
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        main.add(right, weight=3)
        self.detail_title = ttk.Label(right, text="详情", font=("", 11, "bold"))
        self.detail_title.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.detail = tk.Text(right, wrap=tk.WORD, undo=False, height=8)
        self.detail.grid(row=1, column=0, sticky="nsew")
        detail_scrollbar = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.detail.yview)
        detail_scrollbar.grid(row=1, column=1, sticky="ns")
        self.detail.configure(yscrollcommand=detail_scrollbar.set, state=tk.DISABLED)

    def _build_capture_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        capture_buttons = ttk.Frame(parent)
        capture_buttons.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        for column in range(4):
            capture_buttons.columnconfigure(column, weight=1)
        ttk.Button(capture_buttons, text="编辑", command=self.open_recent_capture).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(capture_buttons, text="复制", command=self.copy_recent_capture).grid(row=0, column=1, sticky="ew", padx=2)
        ttk.Button(capture_buttons, text="定位", command=self.reveal_recent_capture).grid(row=0, column=2, sticky="ew", padx=2)
        ttk.Button(capture_buttons, text="移除", command=self.remove_recent_capture).grid(row=0, column=3, sticky="ew", padx=(4, 0))

        search_frame = ttk.Frame(parent)
        search_frame.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        search_frame.columnconfigure(1, weight=1)
        ttk.Label(search_frame, text="搜索").grid(row=0, column=0, padx=(0, 6))
        self.recent_search_var = tk.StringVar()
        self.recent_search_var.trace_add("write", lambda *_: self.refresh_recent())
        ttk.Entry(search_frame, textvariable=self.recent_search_var).grid(row=0, column=1, sticky="ew")

        content = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        content.grid(row=2, column=0, sticky="nsew")

        preview_frame = ttk.Frame(content)
        preview_frame.rowconfigure(0, weight=1)
        preview_frame.columnconfigure(0, weight=1)
        content.add(preview_frame, weight=5)
        self.recent_preview = tk.Label(
            preview_frame,
            text="暂无截图\n点击「编辑截图」开始截取",
            anchor="center",
            bg="#f0f0f0",
            fg="#888888",
            font=("", 11),
        )
        self.recent_preview.grid(row=0, column=0, sticky="nsew")
        self.recent_preview.bind("<Configure>", lambda _event: self.update_recent_preview())

        list_frame = ttk.Frame(content)
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        content.add(list_frame, weight=1)

        self.recent_tree = ttk.Treeview(
            list_frame,
            columns=("time", "name"),
            show="headings",
            selectmode="browse",
            height=4,
        )
        self.recent_tree.heading("time", text="时间")
        self.recent_tree.heading("name", text="文件名")
        self.recent_tree.column("time", width=int(180 * self.ui_scale), anchor="w", stretch=False)
        self.recent_tree.column("name", width=int(260 * self.ui_scale), anchor="w")
        self.recent_tree.grid(row=0, column=0, sticky="nsew")
        self.recent_tree.bind("<<TreeviewSelect>>", lambda _event: self.update_recent_preview())
        recent_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.recent_tree.yview)
        recent_scroll.grid(row=0, column=1, sticky="ns")
        self.recent_tree.configure(yscrollcommand=recent_scroll.set)
        self.refresh_recent()

    def _build_devices_tab(self, parent: ttk.Frame) -> None:
        """Build the device sync management tab."""
        parent.columnconfigure(0, weight=1)

        # Sync enable section
        sync_enable_frame = ttk.LabelFrame(parent, text="同步功能", padding=8)
        sync_enable_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        sync_enable_frame.columnconfigure(1, weight=1)

        ttk.Checkbutton(
            sync_enable_frame,
            text="启用网络同步",
            variable=self.sync_enabled_var,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        ttk.Label(sync_enable_frame, text="对端地址").grid(row=1, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(sync_enable_frame, textvariable=self.sync_peer_host_var).grid(
            row=1, column=1, sticky="ew", padx=(0, 6)
        )
        ttk.Label(sync_enable_frame, text="端口").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(4, 0))
        ttk.Entry(sync_enable_frame, textvariable=self.sync_port_var, width=8).grid(
            row=2, column=1, sticky="w", padx=(0, 6), pady=(4, 0)
        )
        ttk.Label(sync_enable_frame, text="密钥").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=(4, 0))
        ttk.Entry(sync_enable_frame, textvariable=self.sync_secret_var, show="*").grid(
            row=3, column=1, sticky="ew", padx=(0, 6), pady=(4, 0)
        )
        ttk.Checkbutton(sync_enable_frame, text="同步图片", variable=self.sync_images_var).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        ttk.Button(sync_enable_frame, text="应用同步设置", command=self.apply_sync_settings).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )
        ttk.Label(sync_enable_frame, textvariable=self.sync_status_var).grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )

        # Connected devices section
        devices_frame = ttk.LabelFrame(parent, text="已连接设备", padding=8)
        devices_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        devices_frame.columnconfigure(0, weight=1)
        devices_frame.rowconfigure(1, weight=1)

        if self.sync_device_count_var is None:
            self.sync_device_count_var = tk.StringVar(value="0")
        ttk.Label(devices_frame, textvariable=self.sync_device_count_var).grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )

        # Device list with details
        self.device_list_text = tk.Text(
            devices_frame, wrap=tk.WORD, height=6, state=tk.DISABLED, font=("", 9)
        )
        self.device_list_text.grid(row=1, column=0, sticky="nsew")
        device_scroll = ttk.Scrollbar(devices_frame, orient=tk.VERTICAL, command=self.device_list_text.yview)
        device_scroll.grid(row=1, column=1, sticky="ns")
        self.device_list_text.configure(yscrollcommand=device_scroll.set)

        ttk.Button(devices_frame, text="刷新设备列表", command=self.refresh_device_list).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )

        parent.rowconfigure(1, weight=1)

    def refresh_device_list(self) -> None:
        """Refresh the connected device list display."""
        if not hasattr(self, "device_list_text"):
            return

        self.device_list_text.configure(state=tk.NORMAL)
        self.device_list_text.delete("1.0", tk.END)

        if self.sync_manager is None:
            self.device_list_text.insert("1.0", "同步未启用")
            self.device_list_text.configure(state=tk.DISABLED)
            return

        # Check if V2 sync manager (has get_connected_devices)
        if hasattr(self.sync_manager, "get_connected_devices"):
            devices = self.sync_manager.get_connected_devices()
            count = self.sync_manager.get_device_count()
            if self.sync_device_count_var:
                self.sync_device_count_var.set(str(count))
            if not devices:
                self.device_list_text.insert("1.0", "暂无连接设备\n\n启用同步后，局域网内的其他设备可以连接到此电脑。")
            else:
                lines = []
                for i, device in enumerate(devices, 1):
                    name = device.get("device_name", "Unknown")
                    dtype = device.get("device_type", "unknown")
                    platform = device.get("platform", "")
                    label = device.get("label", "")
                    auth = "已认证" if device.get("authenticated") else "未认证"
                    lines.append(
                        f"{i}. {name} ({dtype})\n"
                        f"   平台: {platform}  地址: {label}\n"
                        f"   状态: {auth}"
                    )
                self.device_list_text.insert("1.0", "\n\n".join(lines))
        else:
            # Legacy ClipboardSyncManager — just show client count
            with getattr(self.sync_manager, "clients_lock", threading.Lock()):
                count = len(getattr(self.sync_manager, "clients", []))
            if self.sync_device_count_var:
                self.sync_device_count_var.set(str(count))
            self.device_list_text.insert("1.0", f"已连接 {count} 个设备（旧版同步协议）")

        self.device_list_text.configure(state=tk.DISABLED)

    def _build_settings_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        # Save directory
        dir_frame = ttk.LabelFrame(parent, text="保存目录", padding=8)
        dir_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        dir_frame.columnconfigure(0, weight=1)
        self.capture_save_dir_var = tk.StringVar(value=self.screenshot_settings.save_dir)
        dir_row = ttk.Frame(dir_frame)
        dir_row.grid(row=0, column=0, sticky="ew")
        dir_row.columnconfigure(0, weight=1)
        ttk.Entry(dir_row, textvariable=self.capture_save_dir_var).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(dir_row, text="选择", command=self.choose_capture_save_dir).grid(row=0, column=1)

        # General settings
        general_frame = ttk.LabelFrame(parent, text="常规", padding=8)
        general_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        general_frame.columnconfigure(2, weight=1)
        self.hide_main_during_capture_var = tk.BooleanVar(
            value=bool(getattr(self.screenshot_settings, "hide_main_during_capture", True))
        )
        self.start_with_windows_var = tk.BooleanVar(
            value=bool(getattr(self.screenshot_settings, "start_with_windows", False) or is_integrated_startup_enabled())
        )
        ttk.Checkbutton(general_frame, text="截图前隐藏主窗口", variable=self.hide_main_during_capture_var).grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        ttk.Checkbutton(general_frame, text="开机自启", variable=self.start_with_windows_var).grid(
            row=0, column=1, sticky="w", padx=(0, 10)
        )
        ttk.Button(general_frame, text="应用", command=self.apply_general_settings).grid(row=0, column=2, sticky="e")

        # Network sync
        sync_frame = ttk.LabelFrame(parent, text="网络同步", padding=8)
        sync_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        sync_frame.columnconfigure(1, weight=1)

        ttk.Checkbutton(sync_frame, text="启用同步", variable=self.sync_enabled_var).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 6)
        )
        ttk.Label(sync_frame, text="对端地址").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(0, 6))
        ttk.Entry(sync_frame, textvariable=self.sync_peer_host_var).grid(row=1, column=1, sticky="ew", padx=(0, 6), pady=(0, 6))
        ttk.Label(sync_frame, text="端口").grid(row=1, column=2, sticky="w", padx=(0, 6), pady=(0, 6))
        ttk.Entry(sync_frame, textvariable=self.sync_port_var, width=8).grid(row=1, column=3, sticky="w", pady=(0, 6))
        ttk.Label(sync_frame, text="密钥").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(0, 6))
        ttk.Entry(sync_frame, textvariable=self.sync_secret_var, show="*").grid(row=2, column=1, sticky="ew", padx=(0, 6), pady=(0, 6))
        ttk.Checkbutton(sync_frame, text="同步图片", variable=self.sync_images_var).grid(
            row=2, column=2, columnspan=2, sticky="w", pady=(0, 6)
        )
        ttk.Button(sync_frame, text="应用同步设置", command=self.apply_sync_settings).grid(
            row=3, column=0, columnspan=4, sticky="ew", pady=(4, 0)
        )
        ttk.Label(sync_frame, textvariable=self.sync_status_var).grid(row=4, column=0, columnspan=4, sticky="ew", pady=(4, 0))

        # Hotkeys
        hotkey_frame = ttk.LabelFrame(parent, text="热键", padding=8)
        hotkey_frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        hotkey_frame.columnconfigure(1, weight=1)
        hotkey_frame.columnconfigure(3, weight=1)
        labels = [
            ("截图复制", "copy", 0, 0),
            ("截图编辑", "edit", 0, 2),
            ("截图贴图", "pin", 1, 0),
            ("显示窗口", "show", 1, 2),
        ]
        for label, key, row, column in labels:
            ttk.Label(hotkey_frame, text=label).grid(row=row, column=column, sticky="w", padx=(0, 6), pady=(0, 6))
            self.hotkey_vars[key] = tk.StringVar(value=self.hotkeys.get(key, DEFAULT_HOTKEYS[key]))
            ttk.Entry(hotkey_frame, textvariable=self.hotkey_vars[key], width=16).grid(
                row=row,
                column=column + 1,
                sticky="ew",
                padx=(0, 12),
                pady=(0, 6),
            )
        ttk.Button(hotkey_frame, text="应用热键", command=self.apply_hotkey_settings).grid(
            row=2, column=0, columnspan=4, sticky="ew", pady=(4, 0)
        )

        # Cache clearing
        cache_frame = ttk.LabelFrame(parent, text="缓存清理", padding=8)
        cache_frame.grid(row=4, column=0, sticky="ew")
        for column in range(3):
            cache_frame.columnconfigure(column, weight=1)
        ttk.Button(cache_frame, text="清理剪切板历史", command=self.clear_clipboard_history_cache).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ttk.Button(cache_frame, text="清理截图历史缓存", command=self.clear_screenshot_cache).grid(
            row=0, column=1, sticky="ew", padx=2
        )
        ttk.Button(cache_frame, text="清理同步文件缓存", command=self.clear_synced_files_cache).grid(
            row=0, column=2, sticky="ew", padx=(4, 0)
        )

    def restart_sync(self) -> None:
        """Override to use V2 sync manager and update sync indicator."""
        if self.sync_manager:
            self.sync_manager.stop()
            self.sync_manager = None

        if not self.sync_config.get("enabled"):
            self.sync_status_var.set("网络同步未启用")
            if hasattr(self, "sync_indicator_var") and self.sync_indicator_var:
                self.sync_indicator_var.set("● 同步未启用")
            if hasattr(self, "sync_device_count_var") and self.sync_device_count_var:
                self.sync_device_count_var.set("0")
            return

        # Always use V2 sync manager (WebSocket + binary frame protocol)
        self.sync_manager = clip.SyncManagerV2(self.sync_config, self.sync_events)
        self.sync_manager.start()
        if self.sync_config.get("peer_host"):
            self.sync_status_var.set("V2同步启动，正在连接对端。")
        else:
            self.sync_status_var.set("V2同步启动，等待设备连接。")
        if hasattr(self, "sync_indicator_var") and self.sync_indicator_var:
            self.sync_indicator_var.set("● 同步已启用")
        self.refresh_device_list()

    def process_sync_events(self) -> None:
        """Override to also update sync indicator and device list on status changes."""
        import queue as _queue

        had_device_event = False
        while True:
            try:
                event_type, payload = self.sync_events.get_nowait()
            except _queue.Empty:
                break

            if event_type == "status":
                self.sync_status_var.set(payload)
                # Update sync indicator based on status
                if hasattr(self, "sync_indicator_var") and self.sync_indicator_var:
                    if "已认证" in payload or "connected" in payload.lower():
                        self.sync_indicator_var.set("● 同步已连接")
                    elif "启动" in payload:
                        self.sync_indicator_var.set("● 同步已启用")
                had_device_event = True
            elif event_type == "clipboard":
                self.apply_synced_clipboard_item(payload)

        if had_device_event:
            self.refresh_device_list()

        if not self._quitting:
            self.after(150, self.process_sync_events)

    def apply_general_settings(self) -> None:
        self.screenshot_settings.hide_main_during_capture = bool(self.hide_main_during_capture_var.get())
        self.screenshot_settings.start_with_windows = bool(self.start_with_windows_var.get())
        try:
            set_integrated_startup_enabled(self.screenshot_settings.start_with_windows)
        except Exception as exc:
            messagebox.showerror("开机自启", str(exc), parent=self)
            return
        save_integrated_config(self.screenshot_settings, self.hotkeys)
        self.status_var.set("常规设置已保存")

    def _apply_hotkeys(self) -> None:
        if not self.hotkey_manager:
            return
        callbacks = {
            "copy": self.start_clipboard_capture,
            "edit": self.start_edit_capture,
            "pin": self.start_pin_capture,
            "show": self.show_main_window,
        }
        entries = []
        for key, callback in callbacks.items():
            value = self.hotkeys.get(key, DEFAULT_HOTKEYS[key])
            try:
                entries.append(parse_hotkey(value, callback))
            except ValueError as exc:
                self.status_var.set(f"热键设置无效: {exc}")
                return
        registered, failures = self.hotkey_manager.register_many([entry for entry in entries if entry is not None])
        if failures:
            self.status_var.set(f"已注册 {registered} 个热键；冲突：{', '.join(failures)}")
        else:
            self.status_var.set(f"已注册 {registered} 个热键")

    def apply_hotkey_settings(self) -> None:
        try:
            updated = {
                key: variable.get().strip() or DEFAULT_HOTKEYS[key]
                for key, variable in self.hotkey_vars.items()
            }
            callbacks = {
                "copy": self.start_clipboard_capture,
                "edit": self.start_edit_capture,
                "pin": self.start_pin_capture,
                "show": self.show_main_window,
            }
            for key, value in updated.items():
                parse_hotkey(value, callbacks[key])
        except ValueError as exc:
            messagebox.showerror("热键设置", str(exc), parent=self)
            return
        self.hotkeys.update(updated)
        save_integrated_config(self.screenshot_settings, self.hotkeys)
        self._apply_hotkeys()

    def show_page(self, tab: ttk.Frame) -> None:
        self.show_main_window()
        self.notebook.select(tab)

    def show_clipboard_page(self) -> None:
        self.show_page(self.clipboard_tab)

    def show_capture_page(self) -> None:
        self.show_page(self.capture_tab)

    def show_devices_page(self) -> None:
        """Navigate to the device sync tab and refresh device list."""
        self.show_page(self.devices_tab)
        self.refresh_device_list()

    def show_settings_page(self) -> None:
        self.show_page(self.settings_tab)

    def show_from_background(self) -> None:
        self.show_main_window()

    def process_tray_commands(self):
        while True:
            try:
                command = self.tray_commands.get_nowait()
            except queue.Empty:
                break
            if command == "show_clipboard":
                self.show_clipboard_page()
            elif command == "show_captures":
                self.show_capture_page()
            elif command == "show_settings":
                self.show_settings_page()
            elif command == "show":
                self.show_main_window()
            elif command == "quit":
                self.quit_app()
                return
        if not self._quitting:
            self.after(120, self.process_tray_commands)

    def choose_capture_save_dir(self) -> None:
        directory = filedialog.askdirectory(parent=self, initialdir=self.screenshot_settings.save_dir)
        if not directory:
            return
        self.screenshot_settings.save_dir = directory
        self.capture_save_dir_var.set(directory)
        Path(directory).mkdir(parents=True, exist_ok=True)
        save_integrated_config(self.screenshot_settings, self.hotkeys)

    def start_capture(self, mode: str) -> None:
        self.capture_mode = mode
        hide_main = bool(getattr(self.screenshot_settings, "hide_main_during_capture", True))
        self._restore_main_after_capture = hide_main and self.state() != "withdrawn"
        if hide_main:
            self.withdraw()
            self.after(220, self._capture_screen)
        else:
            self.after(60, self._capture_screen)

    def start_clipboard_capture(self) -> None:
        self.start_capture("clipboard")

    def start_edit_capture(self) -> None:
        self.start_capture("editor")

    def start_pin_capture(self) -> None:
        self.start_capture("pin")

    def _capture_screen(self) -> None:
        try:
            components = load_screenshot_components()
            virtual_screen_bounds = components["virtual_screen_bounds"]
            CaptureOverlay = components["CaptureOverlay"]
            from PIL import ImageGrab

            bounds = virtual_screen_bounds()
            try:
                screenshot = ImageGrab.grab(all_screens=True)
            except TypeError:
                screenshot = ImageGrab.grab()
            image = screenshot.convert("RGB")
            CaptureOverlay(
                self,
                image,
                bounds,
                self._handle_capture_selection,
                self._handle_capture_cancel,
                show_magnifier=self.screenshot_settings.show_capture_magnifier,
            )
        except Exception as exc:
            self._restore_main_after_capture_if_needed(lift=True)
            messagebox.showerror("截图失败", str(exc), parent=self)

    def _handle_capture_selection(self, image: Image.Image, screen_bbox: BBox) -> None:
        mode = self.capture_mode
        if mode == "clipboard":
            self.record_screenshot(image)
            self.copy_capture_to_clipboard(image, force=True)
            self.status_var.set(f"已复制截图 {image.width} x {image.height}")
            self._restore_main_after_capture_if_needed(lift=False)
        elif mode == "pin":
            self.record_screenshot(image)
            self.copy_capture_to_clipboard(image)
            FloatingCaptureWindow = load_screenshot_components()["FloatingCaptureWindow"]
            FloatingCaptureWindow(
                self,
                image,
                self.screenshot_settings,
                self.screenshot_history,
                on_history_change=self.refresh_recent,
                source_bbox=screen_bbox,
            )
            self.status_var.set(f"已贴图 {image.width} x {image.height}")
            self._restore_main_after_capture_if_needed(lift=False)
        else:
            self.record_screenshot(image)
            self.copy_capture_to_clipboard(image)
            open_image_editor = load_screenshot_components()["open_image_editor"]
            open_image_editor(
                self,
                image,
                settings=self.screenshot_settings,
                history=self.screenshot_history,
                on_history_change=self.refresh_recent,
                source_bbox=screen_bbox,
                initial_fit_to_window=True,
            )
            self.status_var.set(f"已打开编辑器 {image.width} x {image.height}")
            self._restore_main_after_capture_if_needed(lift=False)

    def _handle_capture_cancel(self) -> None:
        self._restore_main_after_capture_if_needed(lift=True)
        self.status_var.set("已取消截图")

    def _restore_main_after_capture_if_needed(self, lift: bool = False) -> None:
        if not self._restore_main_after_capture:
            return
        self.deiconify()
        if lift:
            self.lift()
            self.focus_force()
        self._restore_main_after_capture = False

    def record_screenshot(self, image: Image.Image) -> None:
        self.screenshot_history.add_image(image)
        self.refresh_recent()

    def copy_capture_to_clipboard(self, image: Image.Image, force: bool = False) -> bool:
        if not force and not self.screenshot_settings.auto_copy_after_capture:
            return False
        try:
            copy_image_to_clipboard(image)
            return True
        except Exception as exc:
            self.status_var.set(f"复制截图失败: {exc}")
            return False

    def edit_selected_image(self):
        item = self.get_selected_item()
        if not item:
            return
        path = self.image_path_for_item(item)
        if path is None:
            messagebox.showinfo("不能编辑", "只有存在文件的图片记录可以编辑。", parent=self)
            return
        try:
            with Image.open(path) as image:
                editor_image = image.copy()
            open_image_editor = load_screenshot_components()["open_image_editor"]
            open_image_editor(
                self,
                editor_image,
                settings=self.screenshot_settings,
                history=self.screenshot_history,
                on_history_change=self.refresh_recent,
                initial_fit_to_window=True,
            )
            self.status_var.set(f"已打开编辑器：{path}")
        except Exception as exc:
            messagebox.showerror("打开编辑器失败", str(exc), parent=self)

    def refresh_recent(self) -> None:
        if not hasattr(self, "recent_tree"):
            return
        selected = self.selected_recent_capture_id()
        for row in self.recent_tree.get_children():
            self.recent_tree.delete(row)
        keyword = self.recent_search_var.get().strip().lower() if hasattr(self, "recent_search_var") else ""
        for item in self.screenshot_history.recent(100):
            name = Path(item.path).name if item.path else ""
            time_str = self._format_time(item.created_at)
            if keyword and keyword not in name.lower() and keyword not in time_str.lower():
                continue
            self.recent_tree.insert(
                "",
                tk.END,
                iid=item.id,
                values=(time_str, name),
            )
        if selected and self.recent_tree.exists(selected):
            self.recent_tree.selection_set(selected)
        elif self.recent_tree.get_children():
            self.recent_tree.selection_set(self.recent_tree.get_children()[0])
        self.update_recent_preview()

    def selected_recent_capture_id(self) -> Optional[str]:
        if not hasattr(self, "recent_tree"):
            return None
        selection = self.recent_tree.selection()
        return selection[0] if selection else None

    def selected_recent_capture(self) -> Optional[CaptureHistoryItem]:
        item_id = self.selected_recent_capture_id()
        if not item_id:
            return None
        return self.screenshot_history.get(item_id)

    def update_recent_preview(self) -> None:
        item = self.selected_recent_capture()
        if not item:
            if hasattr(self, "recent_preview"):
                self.recent_preview.configure(image="", text="暂无截图\n点击「编辑截图」开始截取")
            return
        path = Path(item.path)
        try:
            from PIL import ImageTk

            width = max(1, self.recent_preview.winfo_width() - 12)
            height = max(1, self.recent_preview.winfo_height() - 12)
            if width <= 1 or height <= 1:
                return
            with Image.open(path) as image:
                preview = image.convert("RGB")
                preview.thumbnail((width, height), Image.Resampling.LANCZOS)
                self.recent_preview_image = ImageTk.PhotoImage(preview)
            self.recent_preview.configure(image=self.recent_preview_image, text="")
        except OSError:
            self.recent_preview.configure(image="", text="无法预览")

    def open_recent_capture(self) -> None:
        item = self.selected_recent_capture()
        if not item:
            return
        path = Path(item.path)
        if not path.exists():
            messagebox.showwarning("文件不存在", str(path), parent=self)
            return
        with Image.open(path) as image:
            open_image_editor = load_screenshot_components()["open_image_editor"]
            open_image_editor(
                self,
                image.copy(),
                settings=self.screenshot_settings,
                history=self.screenshot_history,
                on_history_change=self.refresh_recent,
                initial_fit_to_window=True,
            )

    def copy_recent_capture(self) -> None:
        item = self.selected_recent_capture()
        if not item:
            return
        try:
            with Image.open(item.path) as image:
                copy_image_to_clipboard(image.copy())
            self.status_var.set("已复制截图到剪切板")
        except Exception as exc:
            messagebox.showerror("复制失败", str(exc), parent=self)

    def reveal_recent_capture(self) -> None:
        item = self.selected_recent_capture()
        if not item:
            return
        path = Path(item.path)
        if path.exists():
            get_adapter().reveal_path_in_folder(str(path))

    def remove_recent_capture(self) -> None:
        item = self.selected_recent_capture()
        if not item:
            return
        self.screenshot_history.remove(item.id)
        self.refresh_recent()
        self.status_var.set("已移除截图历史")

    def clear_clipboard_history_cache(self) -> None:
        if not self.history:
            self.status_var.set("剪切板历史为空")
            return
        if not messagebox.askyesno("清理剪切板历史", "确定清理全部剪切板历史吗？\n包括文本、文件和图片缓存都会被清除。", parent=self):
            return
        try:
            clip.clear_system_clipboard()
            self.last_digest = None
            self.sync_clipboard_sequence()
        except Exception:
            pass
        deleted_items = list(self.history)
        self.history.clear()
        clip.delete_unreferenced_image_files(deleted_items, self.history)
        clip.delete_unreferenced_synced_files(deleted_items, self.history)
        clip.save_history(self.history)
        self.refresh_list()
        self.status_var.set("已清理全部剪切板历史和缓存文件")

    def clear_synced_files_cache(self) -> None:
        synced_dir = runtime_dir() / "synced_files"
        if not synced_dir.exists():
            self.status_var.set("同步文件缓存目录不存在")
            return
        if not messagebox.askyesno("清理缓存", "确定清理同步文件缓存吗？\n剪切板历史记录不会被删除。", parent=self):
            return
        removed = 0
        for group_dir in synced_dir.iterdir():
            if group_dir.is_dir():
                for path in group_dir.iterdir():
                    try:
                        if path.is_file():
                            path.unlink()
                            removed += 1
                    except OSError:
                        pass
                try:
                    group_dir.rmdir()
                except OSError:
                    pass
        self.status_var.set(f"已清理 {removed} 个同步文件缓存")

    def clear_screenshot_cache(self) -> None:
        if not messagebox.askyesno("清理截图", "确定清理全部截图历史和缓存图片吗？", parent=self):
            return
        removed = self.screenshot_history.clear_cache()
        self.refresh_recent()
        self.status_var.set(f"已清理 {removed} 个截图文件")

    @staticmethod
    def _format_time(value: str) -> str:
        try:
            return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return value

    def quit_app(self):
        if self.hotkey_manager:
            self.hotkey_manager.unregister_all()
            self.hotkey_manager = None
        save_integrated_config(self.screenshot_settings, self.hotkeys)
        super().quit_app()


def main() -> None:
    """启动整合版应用（跨平台兼容）。"""
    get_adapter().enable_dpi_awareness()
    app = IntegratedApp()
    if "--self-test-components" in sys.argv:
        app.update()
        load_screenshot_components()
        app.quit_app()
        return
    if "--self-test" in sys.argv:
        app.update()
        app.quit_app()
        return
    app.mainloop()


if __name__ == "__main__":
    main()
