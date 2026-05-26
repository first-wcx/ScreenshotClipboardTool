from __future__ import annotations

import math
import os
import subprocess
import sys
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from threading import Thread
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageEnhance, ImageGrab, ImageTk

from platform_adapter import HotkeyDef, get_adapter
from .assets import ensure_app_icon, load_app_icon_photo
from .clipboard import copy_image_to_clipboard
from .config import Settings, ensure_runtime_dirs, load_settings, save_settings
from .hotkeys import GlobalHotkeyManager, Hotkey, MOD_ALT, MOD_CONTROL, MOD_SHIFT
from .history import HistoryItem, ScreenshotHistory
from .image_ops import (
    apply_highlight,
    blur_region,
    bbox_size,
    clamp_bbox,
    draw_arrow,
    draw_number_marker,
    load_ui_font,
    normalize_bbox,
    parse_color,
    pixelate_region,
)
from .ocr import OcrResult, format_ocr_text, recognize_text
from .scrolling import collect_scrolling_frames, stitch_vertical
from .startup import is_startup_enabled, set_startup_enabled
from .tray import TrayIconManager
from .window_detect import detect_window_rect_at_point


Point = Tuple[int, int]
BBox = Tuple[int, int, int, int]

TOOL_LABELS = {
    "pen": "画笔",
    "line": "直线",
    "arrow": "箭头",
    "rect": "矩形",
    "ellipse": "椭圆",
    "highlight": "高亮",
    "text": "文字",
    "number": "编号",
    "mosaic": "马赛克",
    "blur": "模糊",
    "crop": "裁剪",
}

PALETTE = [
    "#E53935",
    "#FB8C00",
    "#FDD835",
    "#43A047",
    "#1E88E5",
    "#8E24AA",
    "#111827",
    "#FFFFFF",
]


def enable_dpi_awareness() -> None:
    """启用 DPI 感知，委托给平台适配器。"""
    get_adapter().enable_dpi_awareness()


def virtual_screen_bounds() -> Tuple[int, int, int, int]:
    """获取虚拟屏幕边界，委托给平台适配器。"""
    return get_adapter().virtual_screen_bounds()


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


def image_for_editor(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    if "A" not in rgba.getbands():
        return rgba
    alpha = rgba.getchannel("A")
    if alpha.getextrema() == (255, 255):
        return rgba
    background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    background.paste(rgba, mask=alpha)
    return background


def clamp_zoom(value: float) -> float:
    return max(0.1, min(4.0, value))


def wheel_zoom_factor(delta: int) -> float:
    steps = delta / 120 if delta else 1
    steps = max(-5.0, min(5.0, steps))
    return 1.08 ** steps


def apply_window_icon(window: tk.Toplevel, icon_path: Path, icon_photo: Optional[ImageTk.PhotoImage] = None) -> None:
    """设置窗口图标，跨平台兼容。"""
    if sys.platform == "win32":
        try:
            window.iconbitmap(str(icon_path))
        except tk.TclError:
            pass
    if icon_photo is not None:
        try:
            window.iconphoto(False, icon_photo)
        except tk.TclError:
            pass


def inherited_icon_source(widget: tk.Widget) -> Tuple[Optional[Path], Optional[ImageTk.PhotoImage]]:
    current: Optional[tk.Widget] = widget
    while current is not None:
        icon_path = getattr(current, "app_icon_path", None)
        if icon_path is not None:
            return icon_path, getattr(current, "app_icon_photo", None)
        current = getattr(current, "master", None)
    return None, None


def apply_inherited_window_icon(window: tk.Toplevel) -> None:
    icon_path, icon_photo = inherited_icon_source(window)
    if icon_path is not None:
        apply_window_icon(window, icon_path, icon_photo)


def bounded_window_size(width: int, height: int, margin_x: int = 80, margin_y: int = 120) -> Tuple[int, int]:
    _vx, _vy, screen_width, screen_height = virtual_screen_bounds()
    bounded_width = min(width, max(360, screen_width - margin_x))
    bounded_height = min(height, max(320, screen_height - margin_y))
    return int(bounded_width), int(bounded_height)


def fit_window_to_content(
    window: tk.Toplevel,
    min_width: int,
    min_height: int,
    preferred_width: int = 0,
    preferred_height: int = 0,
    margin_x: int = 160,
    margin_y: int = 180,
) -> Tuple[int, int]:
    window.update_idletasks()
    vx, vy, screen_width, screen_height = virtual_screen_bounds()
    max_width = max(min_width, screen_width - margin_x)
    max_height = max(min_height, screen_height - margin_y)
    width = min(max(min_width, preferred_width, window.winfo_reqwidth()), max_width)
    height = min(max(min_height, preferred_height, window.winfo_reqheight()), max_height)
    x = vx + (screen_width - width) // 2
    y = vy + (screen_height - height) // 2
    window.geometry(f"{int(width)}x{int(height)}+{int(x)}+{int(y)}")
    return int(width), int(height)


def zoom_center_from_event(
    window: tk.Toplevel,
    image_size: Tuple[int, int],
    display_size: Tuple[int, int],
    new_zoom: float,
    event: tk.Event,
) -> Tuple[float, float]:
    old_width, old_height = display_size
    if old_width <= 0 or old_height <= 0:
        old_width = max(1, window.winfo_width())
        old_height = max(1, window.winfo_height())
    event_x = max(0, min(old_width, int(getattr(event, "x", old_width // 2))))
    event_y = max(0, min(old_height, int(getattr(event, "y", old_height // 2))))
    root_x = int(getattr(event, "x_root", window.winfo_x() + event_x))
    root_y = int(getattr(event, "y_root", window.winfo_y() + event_y))
    ratio_x = event_x / max(1, old_width)
    ratio_y = event_y / max(1, old_height)
    new_width = max(1, int(image_size[0] * new_zoom))
    new_height = max(1, int(image_size[1] * new_zoom))
    return (
        root_x + new_width * (0.5 - ratio_x),
        root_y + new_height * (0.5 - ratio_y),
    )


def draw_subtle_image_edge(canvas: tk.Canvas, width: int, height: int) -> None:
    if width < 3 or height < 3:
        return
    canvas.create_rectangle(0, 0, width - 1, height - 1, outline="#c5d0df", width=1)
    canvas.create_line(0, 0, width - 1, 0, fill="#edf4ff")
    canvas.create_line(0, 0, 0, height - 1, fill="#dce7f4")
    canvas.create_line(0, height - 1, width - 1, height - 1, fill="#707986")
    canvas.create_line(width - 1, 0, width - 1, height - 1, fill="#707986")


CLOSE_ACTION_LABELS = {
    "ask": "询问",
    "background": "后台运行",
    "exit": "退出程序",
}
CLOSE_ACTION_VALUES = {label: value for value, label in CLOSE_ACTION_LABELS.items()}

TOOLBAR_MODE_LABELS = {
    "mini": "极简工具条",
    "compact": "紧凑工具条",
    "panel": "控制面板",
}
TOOLBAR_MODE_VALUES = {label: value for value, label in TOOLBAR_MODE_LABELS.items()}

TOOLBAR_ACTIONS = (
    ("capture", "截图", "区域截图"),
    ("scroll", "长图", "滚动长截图"),
    ("ocr", "OCR", "截图 OCR"),
    ("history", "历史", "历史记录"),
    ("settings", "设置", "设置"),
    ("collapse", "收起", "收起到侧边"),
    ("close", "关闭", "关闭/托盘"),
)


class Tooltip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.window: Optional[tk.Toplevel] = None
        self.after_id: Optional[str] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _schedule(self, _event: tk.Event) -> None:
        self._hide()
        self.after_id = self.widget.after(450, self._show)

    def _show(self) -> None:
        self.after_id = None
        if self.window:
            return
        x = self.widget.winfo_rootx() + 8
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.window = tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        label = tk.Label(
            self.window,
            text=self.text,
            bg="#101828",
            fg="#e5f3ff",
            padx=8,
            pady=4,
            font=("Segoe UI", 9),
        )
        label.pack()
        self.window.geometry(f"+{x}+{y}")

    def _hide(self, _event: Optional[tk.Event] = None) -> None:
        if self.after_id is not None:
            try:
                self.widget.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
            self.window = None


class ScreenshotApp(tk.Tk):
    def __init__(self) -> None:
        enable_dpi_awareness()
        super().__init__()
        self.withdraw()
        self.settings = load_settings()
        if sys.platform == "win32":
            try:
                if is_startup_enabled() and not self.settings.start_with_windows:
                    self.settings.start_with_windows = True
                    save_settings(self.settings)
            except Exception:
                pass
        ensure_runtime_dirs(self.settings)
        self.history = ScreenshotHistory()
        self.app_icon_path = ensure_app_icon()
        self.app_icon_photo = load_app_icon_photo()
        self.toolbar_icons: Dict[str, ImageTk.PhotoImage] = {}
        apply_window_icon(self, self.app_icon_path, self.app_icon_photo)

        self.title("截图工具")
        self.geometry("820x560")
        self.minsize(720, 480)
        self.configure(bg="#f4f6f8")
        self.status_var = tk.StringVar(value="就绪")
        self.auto_copy_var = tk.BooleanVar(value=self.settings.auto_copy_after_capture)
        self.auto_save_var = tk.BooleanVar(value=self.settings.auto_save_after_capture)
        self.magnifier_var = tk.BooleanVar(value=self.settings.show_capture_magnifier)
        self.topmost_var = tk.BooleanVar(value=self.settings.keep_editor_on_top)
        self.float_after_capture_var = tk.BooleanVar(value=False)
        self.close_action_var = tk.StringVar(
            value=CLOSE_ACTION_LABELS.get(getattr(self.settings, "close_action", "ask"), "询问")
        )
        self.toolbar_mode_var = tk.StringVar(
            value=TOOLBAR_MODE_LABELS.get(getattr(self.settings, "toolbar_mode", "mini"), "极简工具条")
        )
        self.hotkey_var = tk.BooleanVar(value=self.settings.enable_global_hotkeys)
        self.ocr_language_var = tk.StringVar(value=self.settings.ocr_language)
        self.scroll_max_frames_var = tk.IntVar(value=self.settings.scroll_max_frames)
        self.scroll_delta_var = tk.IntVar(value=self.settings.scroll_wheel_delta)
        self.save_dir_var = tk.StringVar(value=self.settings.save_dir)
        self.startup_var = tk.BooleanVar(value=getattr(self.settings, "start_with_windows", False))
        self.capture_mode = "normal"
        self._restore_main_after_capture = False
        self.hotkey_manager = GlobalHotkeyManager(self)
        self.tray_manager = TrayIconManager(
            self,
            self.show_from_background,
            self.open_settings,
            self.open_history,
            self.quit_app,
            icon_path=str(self.app_icon_path),
        )
        self.settings_window: Optional[SettingsWindow] = None
        self.history_window: Optional[HistoryWindow] = None
        self._drag_start: Optional[Tuple[int, int]] = None
        self._toolbar_dragged = False
        self._main_ui_built = False

        self._configure_style()
        self._bind_shortcuts()
        self.hide_to_background()
        if getattr(self.settings, "start_with_windows", False):
            self.after(800, self._apply_startup_setting)
        self.after(300, self._apply_hotkey_setting)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), background="#f4f6f8")
        style.configure("Muted.TLabel", foreground="#667085", background="#f4f6f8")
        style.configure("Panel.TFrame", background="#ffffff")
        style.configure("Toolbar.TFrame", background="#f9fafb")
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"))

    def _build_ui(self) -> None:
        for child in self.winfo_children():
            if child.winfo_toplevel() == self:
                child.destroy()

        self.configure(bg="#05070d")
        mode = getattr(self.settings, "toolbar_mode", "mini")
        if mode == "panel":
            self._build_panel_ui()
        elif mode == "compact":
            self._build_compact_toolbar()
        else:
            self._build_mini_toolbar()

    def _build_mini_toolbar(self) -> None:
        bar = tk.Frame(self, bg="#202124", padx=8, pady=5, highlightthickness=1, highlightbackground="#2f3338")
        bar.pack(fill=tk.BOTH, expand=True)
        self._bind_drag(bar)
        for icon_key, name, tip in TOOLBAR_ACTIONS:
            command = self._command_for_toolbar_action(name)
            padx = (3, 11) if icon_key in {"history", "collapse"} else 3
            self._tool_button(bar, icon_key, command, tip=tip, size=34).pack(side=tk.LEFT, padx=padx, pady=0)

    def _build_compact_toolbar(self) -> None:
        bar = tk.Frame(self, bg="#202124", highlightthickness=1, highlightbackground="#2f3338")
        bar.pack(fill=tk.BOTH, expand=True)
        self._bind_drag(bar)
        top = tk.Frame(bar, bg="#202124")
        top.pack(fill=tk.X, padx=10, pady=(8, 2))
        self._bind_drag(top)
        app_icon = self._toolbar_icon("app", 24)
        title = tk.Label(top, image=app_icon, bg="#202124")
        title.image = app_icon
        title.pack(side=tk.LEFT)
        self._bind_drag(title)
        row = tk.Frame(bar, bg="#202124")
        row.pack(fill=tk.X, padx=8, pady=(2, 8))
        self._bind_drag(row)
        for icon_key, name, tip in TOOLBAR_ACTIONS:
            command = self._command_for_toolbar_action(name)
            self._tool_button(row, icon_key, command, tip=tip, size=26).pack(side=tk.LEFT, padx=4)

    def _build_panel_ui(self) -> None:
        panel = tk.Frame(self, bg="#0b1020", padx=14, pady=12)
        panel.pack(fill=tk.BOTH, expand=True)
        header = tk.Frame(panel, bg="#0b1020")
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text="截图工具",
            fg="#f8fafc",
            bg="#0b1020",
            font=("Segoe UI", 16, "bold"),
        ).pack(side=tk.LEFT)
        tk.Label(header, textvariable=self.status_var, fg="#93a4b8", bg="#0b1020").pack(side=tk.RIGHT)
        row = tk.Frame(panel, bg="#0b1020")
        row.pack(fill=tk.X, pady=(18, 10))
        for icon_key, name, tip in TOOLBAR_ACTIONS:
            command = self._command_for_toolbar_action(name)
            self._tool_button(row, icon_key, command, tip=tip, size=28).pack(side=tk.LEFT, padx=5)

    def _command_for_toolbar_action(self, name: str) -> Callable[[], None]:
        return {
            "截图": self.start_edit_capture,
            "长图": self.start_scroll_capture,
            "OCR": self.start_ocr_capture,
            "历史": self.open_history,
            "设置": self.open_settings,
            "收起": self.collapse_to_side,
            "关闭": self.on_close,
        }[name]

    def _toolbar_icon(self, key: str, size: int = 22) -> ImageTk.PhotoImage:
        cache_key = f"{key}:{size}"
        cached = self.toolbar_icons.get(cache_key)
        if cached is not None:
            return cached

        scale = 4
        canvas = size * scale
        image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        fg = (218, 222, 232, 255)
        muted = (164, 169, 179, 235)
        width = 2.15
        pad = 6.0
        left, top, right, bottom = pad, pad, size - pad, size - pad

        def n(value: float) -> int:
            return int(round(value * scale))

        def line(points: Tuple[Tuple[float, float], ...], fill=fg, line_width: float = width) -> None:
            draw.line([(n(x), n(y)) for x, y in points], fill=fill, width=max(1, n(line_width)), joint="curve")

        def rounded_rect(box: Tuple[float, float, float, float], outline=fg, radius: float = 4, line_width: float = width) -> None:
            draw.rounded_rectangle(
                tuple(n(value) for value in box),
                radius=n(radius),
                outline=outline,
                width=max(1, n(line_width)),
            )

        def ellipse(box: Tuple[float, float, float, float], outline=fg, fill=None, line_width: float = width) -> None:
            draw.ellipse(
                tuple(n(value) for value in box),
                outline=outline,
                fill=fill,
                width=max(1, n(line_width)),
            )

        def polygon(points: Tuple[Tuple[float, float], ...], fill=fg) -> None:
            draw.polygon([(n(x), n(y)) for x, y in points], fill=fill)

        def arc(box: Tuple[float, float, float, float], start: float, end: float, fill=fg, line_width: float = width) -> None:
            draw.arc(tuple(n(value) for value in box), start=start, end=end, fill=fill, width=max(1, n(line_width)))

        if key == "app":
            rounded_rect((5, 5, size - 5, size - 5), radius=7)
            line(((left, top), (left, top + 7), (left, top), (left + 7, top)))
            line(((right, top), (right - 7, top), (right, top), (right, top + 7)))
            line(((left, bottom), (left, bottom - 7), (left, bottom), (left + 7, bottom)))
            line(((right, bottom), (right - 7, bottom), (right, bottom), (right, bottom - 7)))
        elif key == "capture":
            rounded_rect((7, 8, size - 7, size - 8), radius=3.5)
            line(((11, 13), (11, 10), (14, 10)), line_width=1.8)
            line(((size - 11, 13), (size - 11, 10), (size - 14, 10)), line_width=1.8)
            line(((11, size - 13), (11, size - 10), (14, size - 10)), line_width=1.8)
            line(((size - 11, size - 13), (size - 11, size - 10), (size - 14, size - 10)), line_width=1.8)
            ellipse((size / 2 - 3.2, size / 2 - 3.2, size / 2 + 3.2, size / 2 + 3.2), line_width=1.8)
        elif key == "scroll":
            rounded_rect((9, 7, size - 9, size - 7), radius=4)
            line(((size / 2, 11), (size / 2, size - 11)), fill=muted, line_width=1.8)
            line(((size / 2, 11), (size / 2 - 4.2, 15.2), (size / 2, 11), (size / 2 + 4.2, 15.2)))
            line(((size / 2, size - 11), (size / 2 - 4.2, size - 15.2), (size / 2, size - 11), (size / 2 + 4.2, size - 15.2)))
        elif key == "ocr":
            rounded_rect((8, 7, size - 8, size - 7), radius=3.5)
            line(((12, 13), (size - 12, 13)), fill=muted, line_width=1.6)
            line(((12, 18), (size - 12, 18)), line_width=1.8)
            line(((12, 23), (size - 16, 23)), fill=muted, line_width=1.6)
            line(((10, 10), (14, 10), (10, 10), (10, 14)), line_width=1.6)
            line(((size - 10, size - 14), (size - 10, size - 10), (size - 14, size - 10)), line_width=1.6)
        elif key == "history":
            cx = cy = size / 2
            radius = size / 3.1
            points = []
            for idx in range(48):
                angle = idx * 0.46
                current = radius * (1 - idx / 58)
                points.append((cx + math.cos(angle) * current, cy + math.sin(angle) * current))
            if len(points) > 1:
                line(tuple(points), line_width=2.3)
            ellipse((cx - 2.4, cy - 2.4, cx + 2.4, cy + 2.4), fill=fg, line_width=0)
        elif key == "settings":
            cx = cy = size / 2
            points = []
            for idx in range(24):
                radians = math.radians(-90 + idx * 15)
                radius = size / 3.0 if idx % 3 == 0 else size / 4.0
                points.append((cx + math.cos(radians) * radius, cy + math.sin(radians) * radius))
            line(tuple(points + [points[0]]), line_width=1.7)
            ellipse((cx - 4.0, cy - 4.0, cx + 4.0, cy + 4.0), outline=fg, line_width=1.8)
        elif key == "collapse":
            cx = size / 2
            line(((cx + 5, 9), (cx - 4, size / 2), (cx + 5, size - 9)), line_width=2.6)
            line(((right, 9), (right, size - 9)), fill=muted, line_width=1.8)
        elif key == "close":
            line(((10, 10), (size - 10, size - 10)), line_width=2.1)
            line(((size - 10, 10), (10, size - 10)), line_width=2.1)

        image = image.resize((size, size), Image.Resampling.LANCZOS)

        photo = ImageTk.PhotoImage(image)
        self.toolbar_icons[cache_key] = photo
        return photo

    def _tool_button_palette(self, icon_key: str) -> Tuple[str, str]:
        return "#202124", "#2b2d31"

    def _tool_button(
        self,
        parent: tk.Widget,
        icon_key: str,
        command: Callable[[], None],
        tip: Optional[str] = None,
        size: int = 22,
    ) -> tk.Button:
        icon = self._toolbar_icon(icon_key, size)
        bg, active_bg = self._tool_button_palette(icon_key)
        button = tk.Button(
            parent,
            image=icon,
            command=lambda: self._toolbar_button_command(command),
            width=size + 14,
            height=size + 14,
            bd=0,
            relief=tk.FLAT,
            fg="#dbeafe",
            bg=bg,
            activeforeground="#ffffff",
            activebackground=active_bg,
            font=("Segoe UI Symbol", 11, "bold"),
            cursor="hand2",
            padx=0,
            pady=0,
            highlightthickness=0,
        )
        button.image = icon
        self._bind_drag(button)
        if tip:
            Tooltip(button, tip)
        return button

    def _toolbar_button_command(self, command: Callable[[], None]) -> None:
        if self._toolbar_dragged:
            self._toolbar_dragged = False
            return
        command()

    def _bind_drag(self, widget: tk.Widget) -> None:
        widget.bind("<ButtonPress-1>", self._start_toolbar_drag, add="+")
        widget.bind("<B1-Motion>", self._drag_toolbar, add="+")
        widget.bind("<ButtonRelease-1>", self._end_toolbar_drag, add="+")

    def _start_toolbar_drag(self, event: tk.Event) -> None:
        self._drag_start = (event.x_root, event.y_root)
        self._toolbar_dragged = False

    def _drag_toolbar(self, event: tk.Event) -> None:
        if not self._drag_start:
            return
        start_x, start_y = self._drag_start
        dx = event.x_root - start_x
        dy = event.y_root - start_y
        if abs(dx) + abs(dy) > 3:
            self._toolbar_dragged = True
        self.geometry(f"+{self.winfo_x() + dx}+{self.winfo_y() + dy}")
        self._drag_start = (event.x_root, event.y_root)

    def _end_toolbar_drag(self, _event: tk.Event) -> None:
        self._drag_start = None

    def _ensure_main_ui(self) -> None:
        if self._main_ui_built:
            return
        self._build_ui()
        self._main_ui_built = True
        self.refresh_recent()

    def apply_toolbar_mode(self, place: bool = False, show: bool = True) -> None:
        mode = getattr(self.settings, "toolbar_mode", "mini")
        self.withdraw()
        if mode == "panel":
            self.overrideredirect(False)
            self.attributes("-topmost", False)
            self.minsize(520, 220)
            self.geometry("560x220")
            self.resizable(False, False)
        elif mode == "compact":
            self.overrideredirect(True)
            self.attributes("-topmost", True)
            self.minsize(1, 1)
            self.geometry("460x84")
            self.resizable(False, False)
        else:
            self.overrideredirect(True)
            self.attributes("-topmost", True)
            self.minsize(1, 1)
            self.geometry("420x64")
            self.resizable(False, False)
        if place:
            self._place_toolbar_bottom_right()
        if show:
            self.deiconify()

    def _place_toolbar_bottom_right(self) -> None:
        self.update_idletasks()
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        vx, vy, vw, vh = virtual_screen_bounds()
        x = vx + vw - width - 18
        y = vy + vh - height - 58
        self.geometry(f"{width}x{height}+{int(x)}+{int(y)}")

    def collapse_to_side(self) -> None:
        for child in self.winfo_children():
            if child.winfo_toplevel() == self:
                child.destroy()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#202124")
        tab_icon = self._toolbar_icon("capture", 24)
        tab = tk.Button(
            self,
            image=tab_icon,
            command=lambda: self._toolbar_button_command(self.expand_from_side),
            bd=0,
            fg="#e0f2fe",
            bg="#0f2742",
            activebackground="#1d4f7a",
            activeforeground="#ffffff",
            font=("Segoe UI", 11, "bold"),
            cursor="hand2",
            highlightthickness=0,
        )
        tab.image = tab_icon
        self._bind_drag(tab)
        tab.pack(fill=tk.BOTH, expand=True)
        vx, vy, vw, vh = virtual_screen_bounds()
        width, height = 34, 78
        x = vx + vw - width
        y = vy + vh - height - 160
        self.geometry(f"{width}x{height}+{int(x)}+{int(y)}")

    def expand_from_side(self) -> None:
        self._build_ui()
        self._main_ui_built = True
        self.apply_toolbar_mode(place=True)

    def open_settings(self) -> None:
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
            return
        self.settings_window = SettingsWindow(self)

    def _bind_shortcuts(self) -> None:
        self.bind("<Alt-A>", lambda _event: self.start_clipboard_capture())
        self.bind("<Alt-a>", lambda _event: self.start_clipboard_capture())
        self.bind("<Alt-S>", lambda _event: self.start_edit_capture())
        self.bind("<Alt-s>", lambda _event: self.start_edit_capture())
        self.bind("<Alt-D>", lambda _event: self.start_pin_capture())
        self.bind("<Alt-d>", lambda _event: self.start_pin_capture())

    def _sync_settings(self) -> None:
        previous_mode = getattr(self.settings, "toolbar_mode", "mini")
        previous_hotkeys = self.settings.enable_global_hotkeys
        previous_startup = getattr(self.settings, "start_with_windows", False)
        previous_state = (
            self.settings.auto_copy_after_capture,
            self.settings.auto_save_after_capture,
            self.settings.show_capture_magnifier,
            self.settings.keep_editor_on_top,
            self.settings.float_after_capture,
            self.settings.close_action,
            self.settings.minimize_to_background,
            self.settings.toolbar_mode,
            self.settings.enable_global_hotkeys,
            self.settings.ocr_language,
            self.settings.scroll_max_frames,
            self.settings.scroll_wheel_delta,
            self.settings.save_dir,
            getattr(self.settings, "start_with_windows", False),
        )
        self.settings.auto_copy_after_capture = self.auto_copy_var.get()
        self.settings.auto_save_after_capture = self.auto_save_var.get()
        self.settings.show_capture_magnifier = self.magnifier_var.get()
        self.settings.keep_editor_on_top = self.topmost_var.get()
        self.settings.float_after_capture = False
        self.settings.close_action = CLOSE_ACTION_VALUES.get(self.close_action_var.get(), "ask")
        self.settings.minimize_to_background = self.settings.close_action == "background"
        self.settings.toolbar_mode = TOOLBAR_MODE_VALUES.get(self.toolbar_mode_var.get(), "mini")
        self.settings.enable_global_hotkeys = self.hotkey_var.get()
        self.settings.ocr_language = self.ocr_language_var.get()
        self.settings.scroll_max_frames = max(2, int(self.scroll_max_frames_var.get()))
        self.settings.scroll_wheel_delta = max(120, int(self.scroll_delta_var.get()))
        self.settings.save_dir = self.save_dir_var.get()
        self.settings.start_with_windows = self.startup_var.get()
        current_state = (
            self.settings.auto_copy_after_capture,
            self.settings.auto_save_after_capture,
            self.settings.show_capture_magnifier,
            self.settings.keep_editor_on_top,
            self.settings.float_after_capture,
            self.settings.close_action,
            self.settings.minimize_to_background,
            self.settings.toolbar_mode,
            self.settings.enable_global_hotkeys,
            self.settings.ocr_language,
            self.settings.scroll_max_frames,
            self.settings.scroll_wheel_delta,
            self.settings.save_dir,
            self.settings.start_with_windows,
        )
        if current_state != previous_state:
            ensure_runtime_dirs(self.settings)
            save_settings(self.settings)
        if self.settings.enable_global_hotkeys != previous_hotkeys:
            self._apply_hotkey_setting()
        if self.settings.start_with_windows != previous_startup:
            if not self._apply_startup_setting(show_errors=True):
                self.settings.start_with_windows = previous_startup
                self.startup_var.set(previous_startup)
                save_settings(self.settings)
        if self.settings.toolbar_mode != previous_mode:
            should_show = getattr(self, "_main_ui_built", False) and self.state() != "withdrawn"
            if self._main_ui_built:
                self._build_ui()
            self.apply_toolbar_mode(place=True, show=should_show)

    def _apply_startup_setting(self, show_errors: bool = False) -> bool:
        try:
            set_startup_enabled(bool(self.settings.start_with_windows))
        except Exception as exc:
            self.status_var.set(f"开机自启设置失败：{exc}")
            if show_errors:
                messagebox.showerror("开机自启设置失败", str(exc), parent=self)
            return False

        if self.settings.start_with_windows:
            self.status_var.set("已启用开机自启")
        else:
            self.status_var.set("已关闭开机自启")
        return True

    def _apply_hotkey_setting(self) -> None:
        if not hasattr(self, "hotkey_manager"):
            return
        self.hotkey_manager.unregister_all()
        if not self.settings.enable_global_hotkeys:
            self.status_var.set("全局热键已关闭")
            return
        registered, failures = self.hotkey_manager.register_many(
            [
                Hotkey("Alt+A", MOD_ALT, ord("A"), self.start_clipboard_capture),
                Hotkey("Alt+S", MOD_ALT, ord("S"), self.start_edit_capture),
                Hotkey("Alt+D", MOD_ALT, ord("D"), self.start_pin_capture),
                Hotkey("Ctrl+Shift+S", MOD_CONTROL | MOD_SHIFT, ord("S"), self.start_scroll_capture),
                Hotkey("Ctrl+Shift+O", MOD_CONTROL | MOD_SHIFT, ord("O"), self.start_ocr_capture),
                Hotkey("Ctrl+Shift+M", MOD_CONTROL | MOD_SHIFT, ord("M"), self.show_from_background),
            ]
        )
        if failures:
            self.status_var.set(f"全局热键部分注册失败：{', '.join(failures)}")
        elif registered:
            self.status_var.set("全局热键：Alt+A 复制 / Alt+S 编辑 / Alt+D 贴图")

    def on_close(self) -> None:
        action = getattr(self.settings, "close_action", "ask")
        if action == "background":
            self.hide_to_background()
            return
        if action == "exit":
            self.quit_app()
            return

        choice = messagebox.askyesnocancel(
            "关闭截图工具",
            "要后台运行吗？\n\n是：隐藏到后台，热键继续可用。\n否：退出程序。\n取消：不关闭。",
            parent=self,
        )
        if choice is None:
            return
        if choice:
            self.hide_to_background()
            return
        self.quit_app()

    def hide_to_background(self) -> None:
        self.withdraw()
        if hasattr(self, "tray_manager"):
            if not self.tray_manager.show():
                self._ensure_main_ui()
                self.apply_toolbar_mode(place=True, show=True)
                self.status_var.set("托盘不可用，已显示主窗口")

    def show_from_background(self) -> None:
        self._ensure_main_ui()
        self.apply_toolbar_mode(place=True, show=True)
        self.deiconify()
        self.lift()
        self.focus_force()

    def quit_app(self) -> None:
        if hasattr(self, "tray_manager"):
            self.tray_manager.stop()
        if hasattr(self, "hotkey_manager"):
            self.hotkey_manager.unregister_all()
        self.destroy()

    def choose_save_dir(self) -> None:
        directory = filedialog.askdirectory(initialdir=self.settings.save_dir, parent=self)
        if not directory:
            return
        self.save_dir_var.set(directory)
        self._sync_settings()
        self.status_var.set(f"保存位置：{directory}")

    def _mark_capture_visibility(self) -> None:
        try:
            self._restore_main_after_capture = self.state() != "withdrawn"
        except tk.TclError:
            self._restore_main_after_capture = False

    def _restore_main_after_capture_if_needed(self, lift: bool = False) -> None:
        if not getattr(self, "_restore_main_after_capture", False):
            return
        try:
            self.deiconify()
            if lift:
                self.lift()
        except tk.TclError:
            pass

    def start_capture(self, delay_seconds: int = 0, mode: str = "editor") -> None:
        self._sync_settings()
        self.capture_mode = mode
        self.status_var.set("正在准备截图...")
        self._mark_capture_visibility()
        self.withdraw()
        self.after(max(0, delay_seconds) * 1000, self._capture_screen)

    def start_clipboard_capture(self) -> None:
        self.start_capture(mode="clipboard")

    def start_edit_capture(self) -> None:
        self.start_capture(mode="editor")

    def start_pin_capture(self) -> None:
        self.start_capture(mode="pin")

    def start_scroll_capture(self) -> None:
        self.start_capture(mode="scroll")

    def start_ocr_capture(self) -> None:
        self.start_capture(mode="ocr")

    def _capture_screen(self) -> None:
        self.update_idletasks()
        time.sleep(0.15)
        try:
            screenshot = ImageGrab.grab(all_screens=True)
        except TypeError:
            screenshot = ImageGrab.grab()
        except OSError as exc:
            self._restore_main_after_capture_if_needed(lift=True)
            messagebox.showerror("截图失败", str(exc), parent=self)
            return

        x, y, width, height = virtual_screen_bounds()
        if screenshot.size != (width, height):
            x, y = 0, 0
            width, height = screenshot.size

        CaptureOverlay(
            self,
            screenshot.convert("RGB"),
            (x, y, width, height),
            self._handle_capture_selection,
            self._handle_capture_cancel,
            show_magnifier=self.settings.show_capture_magnifier,
        )

    def _handle_capture_selection(self, image: Image.Image, screen_bbox: BBox) -> None:
        mode = self.capture_mode
        self.capture_mode = "editor"
        if mode == "scroll":
            self._handle_scroll_capture(image, screen_bbox)
            return
        if mode == "ocr":
            self._restore_main_after_capture_if_needed(lift=True)
            self.open_ocr_result(image)
            self.status_var.set(f"OCR 截图区域 {image.width} x {image.height}")
            return
        if mode == "clipboard":
            self._handle_clipboard_capture(image)
            return
        if mode == "pin":
            copied = self.show_pin_result(image, screen_bbox)
            suffix = "，已复制到剪贴板" if copied else ""
            self.status_var.set(f"已贴图 {image.width} x {image.height}{suffix}")
            return

        copied = self.show_capture_result(image, screen_bbox)
        suffix = "，已复制到剪贴板" if copied else ""
        self.status_var.set(f"已截图 {image.width} x {image.height}{suffix}")

    def _handle_capture_cancel(self) -> None:
        self.capture_mode = "editor"
        self._restore_main_after_capture_if_needed(lift=True)
        self.status_var.set("已取消截图")

    def _handle_scroll_capture(self, image: Image.Image, screen_bbox: BBox) -> None:
        try:
            frames = collect_scrolling_frames(
                initial_frame=image,
                screen_bbox=screen_bbox,
                virtual_bounds=virtual_screen_bounds(),
                max_frames=self.settings.scroll_max_frames,
                wheel_delta=self.settings.scroll_wheel_delta,
                pause_ms=self.settings.scroll_pause_ms,
            )
            stitched = stitch_vertical(frames)
        except Exception as exc:
            self._restore_main_after_capture_if_needed(lift=True)
            messagebox.showerror("滚动长截图失败", str(exc), parent=self)
            self.status_var.set("滚动长截图失败")
            return

        copied = self.show_capture_result(stitched, screen_bbox)
        suffix = "，已复制到剪贴板" if copied else ""
        self.status_var.set(f"滚动长截图完成：{len(frames)} 段，{stitched.width} x {stitched.height}{suffix}")

    def open_ocr_result(self, image: Image.Image) -> None:
        OcrWindow(self, image.convert("RGB"), self.settings.ocr_language)

    def record_capture_result(self, image: Image.Image) -> None:
        try:
            self.history.add_image(image)
            self.refresh_recent()
        except OSError:
            pass

    def copy_capture_to_clipboard(self, image: Image.Image, force: bool = False) -> bool:
        if not force and not self.settings.auto_copy_after_capture:
            return False
        try:
            copy_image_to_clipboard(image)
            return True
        except Exception as exc:
            self.status_var.set(f"复制到剪贴板失败：{exc}")
            return False

    def _handle_clipboard_capture(self, image: Image.Image) -> None:
        self.record_capture_result(image)
        copied = self.copy_capture_to_clipboard(image, force=True)
        self._restore_main_after_capture_if_needed(lift=False)
        if copied:
            self.status_var.set(f"已复制截图 {image.width} x {image.height}")
        else:
            self.status_var.set("复制截图失败")

    def show_pin_result(self, image: Image.Image, screen_bbox: Optional[BBox] = None) -> bool:
        self.record_capture_result(image)
        copied = self.copy_capture_to_clipboard(image)
        self._restore_main_after_capture_if_needed(lift=False)
        FloatingCaptureWindow(
            self,
            image,
            self.settings,
            self.history,
            on_history_change=self.refresh_recent,
            source_bbox=screen_bbox,
        )
        return copied

    def show_capture_result(self, image: Image.Image, screen_bbox: Optional[BBox] = None) -> bool:
        self.record_capture_result(image)
        copied = self.copy_capture_to_clipboard(image)

        self._restore_main_after_capture_if_needed(lift=False)
        editor = EditorWindow(
            self,
            image,
            self.settings,
            self.history,
            on_history_change=self.refresh_recent,
            source_bbox=screen_bbox,
        )
        if self.settings.keep_editor_on_top:
            editor.attributes("-topmost", True)
        if self.settings.auto_save_after_capture:
            editor.quick_save(silent=True)
        return copied

    def refresh_recent(self) -> None:
        if not hasattr(self, "recent_tree"):
            return
        for row in self.recent_tree.get_children():
            self.recent_tree.delete(row)
        for item in self.history.recent(40):
            path = Path(item.path)
            self.recent_tree.insert(
                "",
                tk.END,
                iid=item.id,
                values=(format_datetime(item.created_at), f"{item.width}x{item.height}", path.name),
            )

    def selected_recent_item(self) -> Optional[HistoryItem]:
        selection = self.recent_tree.selection()
        if not selection:
            return None
        return self.history.get(selection[0])

    def open_selected_recent(self) -> None:
        item = self.selected_recent_item()
        if not item:
            return
        self.open_history_item(item)

    def open_history_item(self, item: HistoryItem) -> None:
        path = Path(item.path)
        if not path.exists():
            messagebox.showwarning("文件不存在", f"找不到文件：\n{path}", parent=self)
            return
        with Image.open(path) as image:
            EditorWindow(
                self,
                image_for_editor(image.copy()),
                self.settings,
                self.history,
                on_history_change=self.refresh_recent,
            )

    def open_history(self) -> None:
        if self.history_window and self.history_window.winfo_exists():
            self.history_window.refresh()
            self.history_window.lift()
            self.history_window.focus_force()
            return
        self.history_window = HistoryWindow(self, self.history)

    def clear_screenshot_cache(self, parent: Optional[tk.Misc] = None) -> None:
        dialog_parent = parent
        if dialog_parent is None:
            dialog_parent = self.settings_window if self.settings_window and self.settings_window.winfo_exists() else self
        choice = messagebox.askyesno(
            "清理截图缓存",
            "确定清理历史截图缓存吗？\n\n会删除自动缓存的截图、缩略图和历史记录，不会删除你另存到图片文件夹里的截图。",
            parent=dialog_parent,
        )
        if not choice:
            return
        removed = self.history.clear_cache()
        self.refresh_recent()
        if self.history_window and self.history_window.winfo_exists():
            self.history_window.refresh()
        self.status_var.set(f"已清理截图缓存：{removed} 个文件")
        messagebox.showinfo(
            "清理完成",
            f"已清理截图缓存：{removed} 个文件。",
            parent=dialog_parent,
        )

    def open_save_folder(self) -> None:
        ensure_runtime_dirs(self.settings)
        path = Path(self.settings.save_dir)
        try:
            get_adapter().open_file(str(path))
        except OSError:
            messagebox.showinfo("保存目录", str(path), parent=self)


class CaptureOverlay(tk.Toplevel):
    def __init__(
        self,
        master: ScreenshotApp,
        image: Image.Image,
        bounds: BBox,
        on_selection: Callable[[Image.Image, BBox], None],
        on_cancel: Callable[[], None],
        show_magnifier: bool = True,
    ) -> None:
        super().__init__(master)
        self.master = master
        self.image = image
        self.bounds = bounds
        self.on_selection = on_selection
        self.on_cancel = on_cancel
        self.show_magnifier = show_magnifier
        self.start: Optional[Point] = None
        self.press_auto_bbox: Optional[BBox] = None
        self.dragging = False
        self.preview_ids: List[int] = []
        self.crosshair_ids: List[int] = []
        self.magnifier_ids: List[int] = []
        self.auto_ids: List[int] = []
        self.auto_bbox: Optional[BBox] = None
        self.selection_photo: Optional[ImageTk.PhotoImage] = None
        self.auto_photo: Optional[ImageTk.PhotoImage] = None
        self.magnifier_photo: Optional[ImageTk.PhotoImage] = None

        x, y, width, height = bounds
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.configure(bg="black")

        self.canvas = tk.Canvas(self, width=width, height=height, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        dimmed = ImageEnhance.Brightness(image).enhance(0.42)
        self.background_photo = ImageTk.PhotoImage(dimmed)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.background_photo)

        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", lambda _event: self.cancel())
        self.bind("<Escape>", lambda _event: self.cancel())
        self.bind("<Return>", self._copy_fullscreen)
        self.bind("<KP_Enter>", self._copy_fullscreen)
        self.focus_force()
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _copy_fullscreen(self, _event: tk.Event) -> None:
        self._finish((0, 0, self.image.width, self.image.height))

    def _on_motion(self, event: tk.Event) -> None:
        point = self._event_point(event)
        self._draw_crosshair(point)
        if self.start is None:
            self._update_auto_selection(point)
        if self.show_magnifier:
            self._draw_magnifier(point)

    def _on_press(self, event: tk.Event) -> None:
        self.start = self._event_point(event)
        self.press_auto_bbox = self.auto_bbox
        self.dragging = False
        self._clear_preview()

    def _on_drag(self, event: tk.Event) -> None:
        if self.start is None:
            return
        point = self._event_point(event)
        self._draw_crosshair(point)
        if self.show_magnifier:
            self._draw_magnifier(point)
        if math.dist(self.start, point) >= 5:
            self.dragging = True
            self._clear_auto_selection()
        bbox = normalize_bbox(self.start, point)
        bbox = clamp_bbox(bbox, self.image.width, self.image.height)
        self._draw_selection(bbox)

    def _on_release(self, event: tk.Event) -> None:
        if self.start is None:
            return
        end = self._event_point(event)
        bbox = clamp_bbox(normalize_bbox(self.start, end), self.image.width, self.image.height)
        width, height = bbox_size(bbox)
        if width < 5 or height < 5:
            if self.press_auto_bbox:
                self._finish(self.press_auto_bbox)
                return
            self.start = None
            self._clear_preview()
            return
        self._finish(bbox)

    def _event_point(self, event: tk.Event) -> Point:
        return (
            int(max(0, min(self.image.width, event.x))),
            int(max(0, min(self.image.height, event.y))),
        )

    def _draw_crosshair(self, point: Point) -> None:
        for item in self.crosshair_ids:
            self.canvas.delete(item)
        x, y = point
        self.crosshair_ids = [
            self.canvas.create_line(x, 0, x, self.image.height, fill="#dbeafe", dash=(3, 4)),
            self.canvas.create_line(0, y, self.image.width, y, fill="#dbeafe", dash=(3, 4)),
        ]

    def _draw_selection(self, bbox: BBox) -> None:
        self._clear_preview()
        x1, y1, x2, y2 = bbox
        width = x2 - x1
        height = y2 - y1
        if width < 1 or height < 1:
            return

        crop = self.image.crop(bbox)
        self.selection_photo = ImageTk.PhotoImage(crop)
        self.preview_ids.append(self.canvas.create_image(x1, y1, anchor=tk.NW, image=self.selection_photo))
        self.preview_ids.append(self.canvas.create_rectangle(x1 - 1, y1 - 1, x2 + 1, y2 + 1, outline="#0f172a", width=3))
        self.preview_ids.append(self.canvas.create_rectangle(x1, y1, x2, y2, outline="#e0f2fe", width=1))
        self.preview_ids.append(self.canvas.create_rectangle(x1 + 1, y1 + 1, x2 - 1, y2 - 1, outline="#38bdf8", width=1))

    def _update_auto_selection(self, point: Point) -> None:
        screen_point = (self.bounds[0] + point[0], self.bounds[1] + point[1])
        exclude = [int(self.winfo_id())]
        try:
            if self.master.winfo_exists():
                exclude.append(int(self.master.winfo_id()))
        except tk.TclError:
            pass
        screen_rect = detect_window_rect_at_point(screen_point, exclude_hwnds=exclude)
        if not screen_rect:
            self.auto_bbox = None
            self._clear_auto_selection()
            return
        local_rect = (
            screen_rect[0] - self.bounds[0],
            screen_rect[1] - self.bounds[1],
            screen_rect[2] - self.bounds[0],
            screen_rect[3] - self.bounds[1],
        )
        local_rect = clamp_bbox(local_rect, self.image.width, self.image.height)
        width, height = bbox_size(local_rect)
        if width < 8 or height < 8:
            self.auto_bbox = None
            self._clear_auto_selection()
            return
        if local_rect == self.auto_bbox:
            return
        self.auto_bbox = local_rect
        self._draw_auto_selection(local_rect)

    def _draw_auto_selection(self, bbox: BBox) -> None:
        self._clear_auto_selection()
        x1, y1, x2, y2 = bbox
        crop = self.image.crop(bbox)
        self.auto_photo = ImageTk.PhotoImage(crop)
        self.auto_ids.append(self.canvas.create_image(x1, y1, anchor=tk.NW, image=self.auto_photo))
        self.auto_ids.append(self.canvas.create_rectangle(x1 - 1, y1 - 1, x2 + 1, y2 + 1, outline="#020617", width=3))
        self.auto_ids.append(self.canvas.create_rectangle(x1, y1, x2, y2, outline="#f8fafc", width=1))
        self.auto_ids.append(self.canvas.create_rectangle(x1 + 2, y1 + 2, x2 - 2, y2 - 2, outline="#38bdf8", width=1))

    def _draw_magnifier(self, point: Point) -> None:
        for item in self.magnifier_ids:
            self.canvas.delete(item)
        x, y = point
        radius = 14
        left = max(0, x - radius)
        top = max(0, y - radius)
        right = min(self.image.width, x + radius)
        bottom = min(self.image.height, y + radius)
        crop = self.image.crop((left, top, right, bottom)).resize((126, 126), Image.Resampling.NEAREST)
        self.magnifier_photo = ImageTk.PhotoImage(crop)

        mx = x + 24
        my = y + 24
        if mx + 134 > self.image.width:
            mx = x - 158
        if my + 156 > self.image.height:
            my = y - 180

        self.magnifier_ids.append(
            self.canvas.create_rectangle(mx - 4, my - 4, mx + 130, my + 130, fill="#111827", outline="#38bdf8")
        )
        self.magnifier_ids.append(self.canvas.create_image(mx, my, anchor=tk.NW, image=self.magnifier_photo))
        self.magnifier_ids.append(
            self.canvas.create_line(mx + 63, my, mx + 63, my + 126, fill="#ef4444", width=1)
        )
        self.magnifier_ids.append(
            self.canvas.create_line(mx, my + 63, mx + 126, my + 63, fill="#ef4444", width=1)
        )

    def _clear_preview(self) -> None:
        for item in self.preview_ids:
            self.canvas.delete(item)
        self.preview_ids = []

    def _clear_auto_selection(self) -> None:
        for item in self.auto_ids:
            self.canvas.delete(item)
        self.auto_ids = []
        self.auto_photo = None

    def _finish(self, bbox: BBox) -> None:
        x1, y1, x2, y2 = bbox
        selected = self.image.crop(bbox)
        screen_bbox = (
            self.bounds[0] + x1,
            self.bounds[1] + y1,
            self.bounds[0] + x2,
            self.bounds[1] + y2,
        )
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        self.on_selection(selected, screen_bbox)

    def cancel(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        self.on_cancel()


class EditorWindow(tk.Toplevel):
    def __init__(
        self,
        master: tk.Widget,
        image: Image.Image,
        settings: Settings,
        history: ScreenshotHistory,
        on_history_change: Optional[Callable[[], None]] = None,
        source_bbox: Optional[BBox] = None,
        initial_fit_to_window: bool = False,
    ) -> None:
        super().__init__(master)
        self.master = master
        self.settings = settings
        self.history = history
        self.on_history_change = on_history_change
        self.source_bbox = source_bbox
        self.image = image.convert("RGBA")
        self.undo_stack: List[Image.Image] = []
        self.redo_stack: List[Image.Image] = []
        self.zoom = 1.0
        self.tool_var = tk.StringVar(value="arrow")
        self.color_var = tk.StringVar(value=PALETTE[0])
        self.width_var = tk.IntVar(value=4)
        self.status_var = tk.StringVar()
        self.image_id: Optional[int] = None
        self.tk_image: Optional[ImageTk.PhotoImage] = None
        self.preview_ids: List[int] = []
        self.start: Optional[Point] = None
        self.last_point: Optional[Point] = None
        self.pen_points: List[Point] = []
        self.step_number = 1
        self.last_saved_path: Optional[Path] = None

        self.title("截图编辑器")
        apply_inherited_window_icon(self)
        self.geometry(self._initial_geometry())
        self.minsize(720, 500)
        self.configure(bg="#eef2f6")
        self._build_ui()
        self._bind_events()
        self.render_image()
        self.update_status()
        self._fit_window_to_content()
        if initial_fit_to_window:
            self.after_idle(lambda: self.fit_to_window(max_zoom=1.0))

    def _initial_geometry(self) -> str:
        width, height = bounded_window_size(max(self.image.width + 220, 1500), max(self.image.height + 300, 840))
        return f"{width}x{height}"

    def _fit_window_to_content(self) -> None:
        preferred_width = max(self.image.width + 220, self.winfo_reqwidth() + 80, 1500)
        preferred_height = max(self.image.height + 300, self.winfo_reqheight() + 70, 840)
        width, height = fit_window_to_content(
            self,
            min_width=1320,
            min_height=760,
            preferred_width=preferred_width,
            preferred_height=preferred_height,
            margin_x=140,
            margin_y=160,
        )
        self.minsize(min(1320, width), min(760, height))

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(10, 8), style="Toolbar.TFrame")
        toolbar.pack(fill=tk.X)

        ttk.Label(toolbar, text="工具").pack(side=tk.LEFT, padx=(0, 4))
        for key, label in TOOL_LABELS.items():
            ttk.Radiobutton(
                toolbar,
                text=label,
                value=key,
                variable=self.tool_var,
                command=self.update_status,
            ).pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(toolbar, text="颜色").pack(side=tk.LEFT, padx=(0, 4))
        for color in PALETTE:
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
            ("OCR", self.run_ocr),
            ("快速保存", self.quick_save),
            ("另存为", self.save_as),
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

    def _bind_events(self) -> None:
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.bind("<Control-z>", lambda _event: self.undo())
        self.bind("<Control-y>", lambda _event: self.redo())
        self.bind("<Control-s>", lambda _event: self.quick_save())
        self.bind("<Control-c>", lambda _event: self.copy_to_clipboard())
        self.bind("<Escape>", lambda _event: self.destroy())

    def render_image(self) -> None:
        width = max(1, int(self.image.width * self.zoom))
        height = max(1, int(self.image.height * self.zoom))
        if self.zoom == 1.0:
            display = self.image
        else:
            display = self.image.resize((width, height), Image.Resampling.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(display)
        if self.image_id is None:
            self.image_id = self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)
        else:
            self.canvas.itemconfigure(self.image_id, image=self.tk_image)
        self.canvas.configure(scrollregion=(0, 0, width, height))
        self._clear_preview()
        self.update_status()

    def set_color(self, color: str) -> None:
        self.color_var.set(color)
        self.update_status()

    def current_color(self, alpha: int = 255) -> Tuple[int, int, int, int]:
        return parse_color(self.color_var.get(), alpha=alpha)

    def on_mouse_down(self, event: tk.Event) -> None:
        point = self.canvas_to_image(event)
        if not self.point_inside_image(point):
            return

        tool = self.tool_var.get()
        if tool == "text":
            self.add_text(point)
            return
        if tool == "number":
            self.add_number(point)
            return

        self.start = point
        self.last_point = point
        self.pen_points = [point]
        self._clear_preview()
        if tool == "pen":
            self.push_undo()

    def on_mouse_drag(self, event: tk.Event) -> None:
        if self.start is None:
            return
        point = self.canvas_to_image(event)
        point = (max(0, min(self.image.width, point[0])), max(0, min(self.image.height, point[1])))
        tool = self.tool_var.get()
        if tool == "pen":
            if self.last_point:
                self.pen_points.append(point)
                self.preview_ids.append(
                    self.canvas.create_line(
                        *self.image_to_canvas(self.last_point),
                        *self.image_to_canvas(point),
                        fill=self.color_var.get(),
                        width=max(1, int(self.width_var.get() * self.zoom)),
                        capstyle=tk.ROUND,
                        smooth=True,
                    )
                )
            self.last_point = point
            return
        self.draw_preview(self.start, point)

    def on_mouse_up(self, event: tk.Event) -> None:
        if self.start is None:
            return
        end = self.canvas_to_image(event)
        end = (max(0, min(self.image.width, end[0])), max(0, min(self.image.height, end[1])))
        tool = self.tool_var.get()
        if tool == "pen":
            self.commit_pen()
        else:
            self.commit_tool(tool, self.start, end)
        self.start = None
        self.last_point = None
        self.pen_points = []
        self._clear_preview()
        self.render_image()

    def on_mouse_wheel(self, event: tk.Event) -> None:
        if event.state & 0x0004:
            self.change_zoom(1.1 if event.delta > 0 else 0.9)

    def canvas_to_image(self, event: tk.Event) -> Point:
        x = self.canvas.canvasx(event.x) / self.zoom
        y = self.canvas.canvasy(event.y) / self.zoom
        return int(round(x)), int(round(y))

    def image_to_canvas(self, point: Point) -> Point:
        return int(point[0] * self.zoom), int(point[1] * self.zoom)

    def point_inside_image(self, point: Point) -> bool:
        return 0 <= point[0] <= self.image.width and 0 <= point[1] <= self.image.height

    def draw_preview(self, start: Point, end: Point) -> None:
        self._clear_preview()
        tool = self.tool_var.get()
        sx, sy = self.image_to_canvas(start)
        ex, ey = self.image_to_canvas(end)
        color = self.color_var.get()
        width = max(1, int(self.width_var.get() * self.zoom))
        bbox = normalize_bbox((sx, sy), (ex, ey))

        if tool == "line":
            self.preview_ids.append(self.canvas.create_line(sx, sy, ex, ey, fill=color, width=width))
        elif tool == "arrow":
            self.preview_ids.append(
                self.canvas.create_line(sx, sy, ex, ey, fill=color, width=width, arrow=tk.LAST, arrowshape=(14, 18, 6))
            )
        elif tool == "rect":
            self.preview_ids.append(self.canvas.create_rectangle(*bbox, outline=color, width=width))
        elif tool == "ellipse":
            self.preview_ids.append(self.canvas.create_oval(*bbox, outline=color, width=width))
        elif tool == "highlight":
            self.preview_ids.append(self.canvas.create_rectangle(*bbox, fill=color, stipple="gray25", outline=color))
        elif tool in {"mosaic", "blur", "crop"}:
            self.preview_ids.append(self.canvas.create_rectangle(*bbox, outline="#38bdf8", width=2, dash=(4, 3)))

    def commit_pen(self) -> None:
        if len(self.pen_points) < 2:
            return
        draw = ImageDraw.Draw(self.image)
        draw.line(self.pen_points, fill=self.current_color(), width=self.width_var.get(), joint="curve")
        self.redo_stack.clear()

    def commit_tool(self, tool: str, start: Point, end: Point) -> None:
        bbox = clamp_bbox(normalize_bbox(start, end), self.image.width, self.image.height)
        width, height = bbox_size(bbox)
        if tool not in {"line", "arrow"} and (width < 3 or height < 3):
            return
        if tool in {"line", "arrow"} and math.dist(start, end) < 3:
            return

        self.push_undo()
        draw = ImageDraw.Draw(self.image)
        color = self.current_color()
        stroke_width = self.width_var.get()

        if tool == "line":
            draw.line([start, end], fill=color, width=stroke_width)
        elif tool == "arrow":
            draw_arrow(draw, start, end, color, stroke_width)
        elif tool == "rect":
            draw.rectangle(bbox, outline=color, width=stroke_width)
        elif tool == "ellipse":
            draw.ellipse(bbox, outline=color, width=stroke_width)
        elif tool == "highlight":
            self.image = apply_highlight(self.image, bbox, color)
        elif tool == "mosaic":
            self.image = pixelate_region(self.image, bbox, block_size=max(6, stroke_width * 3))
        elif tool == "blur":
            self.image = blur_region(self.image, bbox, radius=max(4, stroke_width * 2))
        elif tool == "crop":
            self.image = self.image.crop(bbox)
        self.redo_stack.clear()

    def add_text(self, point: Point) -> None:
        text = simpledialog.askstring("文字", "请输入要添加的文字：", parent=self)
        if not text:
            return
        self.push_undo()
        font_size = max(16, self.width_var.get() * 5)
        font = load_ui_font(font_size, bold=True)
        draw = ImageDraw.Draw(self.image)
        draw.text(point, text, fill=self.current_color(), font=font)
        self.redo_stack.clear()
        self.render_image()

    def add_number(self, point: Point) -> None:
        self.push_undo()
        marker_size = max(26, self.width_var.get() * 8)
        self.image = draw_number_marker(self.image, point, self.step_number, self.current_color(), marker_size)
        self.step_number += 1
        self.redo_stack.clear()
        self.render_image()

    def push_undo(self) -> None:
        self.undo_stack.append(self.image.copy())
        if len(self.undo_stack) > 40:
            self.undo_stack.pop(0)

    def undo(self) -> None:
        if not self.undo_stack:
            return
        self.redo_stack.append(self.image.copy())
        self.image = self.undo_stack.pop()
        self.render_image()

    def redo(self) -> None:
        if not self.redo_stack:
            return
        self.undo_stack.append(self.image.copy())
        self.image = self.redo_stack.pop()
        self.render_image()

    def change_zoom(self, factor: float) -> None:
        self.zoom = max(0.1, min(4.0, self.zoom * factor))
        self.render_image()

    def zoom_actual(self) -> None:
        self.zoom = 1.0
        self.render_image()

    def fit_to_window(self, max_zoom: float = 2.0) -> None:
        self.update_idletasks()
        canvas_width = max(1, self.canvas.winfo_width() - 20)
        canvas_height = max(1, self.canvas.winfo_height() - 20)
        self.zoom = max(0.1, min(max_zoom, canvas_width / self.image.width, canvas_height / self.image.height))
        self.render_image()

    def quick_save(self, silent: bool = False) -> Optional[Path]:
        ensure_runtime_dirs(self.settings)
        filename = datetime.now().strftime(self.settings.filename_pattern)
        path = unique_path(Path(self.settings.save_dir) / filename)
        return self.save_to_path(path, silent=silent)

    def save_as(self) -> Optional[Path]:
        ensure_runtime_dirs(self.settings)
        initial_file = datetime.now().strftime(self.settings.filename_pattern)
        path = filedialog.asksaveasfilename(
            parent=self,
            initialdir=self.settings.save_dir,
            initialfile=initial_file,
            defaultextension=".png",
            filetypes=[
                ("PNG 图片", "*.png"),
                ("JPEG 图片", "*.jpg;*.jpeg"),
                ("BMP 图片", "*.bmp"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return None
        return self.save_to_path(Path(path), silent=False)

    def save_to_path(self, path: Path, silent: bool = False) -> Optional[Path]:
        try:
            save_image_file(self.image, path)
            self.last_saved_path = path
            self.history.add(path, self.image.width, self.image.height)
            if self.on_history_change:
                self.on_history_change()
            self.status_var.set(f"已保存：{path}")
            if not silent:
                messagebox.showinfo("已保存", f"已保存到：\n{path}", parent=self)
            return path
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            return None

    def copy_to_clipboard(self, silent: bool = False) -> None:
        try:
            copy_image_to_clipboard(self.image)
            self.status_var.set("已复制图片到剪贴板")
            if not silent:
                self.bell()
        except Exception as exc:
            messagebox.showerror("复制失败", str(exc), parent=self)

    def run_ocr(self) -> None:
        self.status_var.set("正在识别文字...")
        image = self.image.copy()
        language = self.settings.ocr_language

        def worker() -> None:
            try:
                result = recognize_text(image, language)
            except Exception as exc:
                self.after(0, lambda error=exc: self._show_ocr_error(error))
                return
            self.after(0, lambda: self._show_ocr_result(result))

        Thread(target=worker, daemon=True).start()

    def _show_ocr_result(self, result: OcrResult) -> None:
        self.status_var.set(f"OCR 完成：{result.engine}")
        OcrResultWindow(self, result)

    def _show_ocr_error(self, exc: Exception) -> None:
        self.status_var.set("OCR 失败")
        messagebox.showerror("OCR 失败", str(exc), parent=self)

    def pin_current(self) -> None:
        PinWindow(self, self.image.copy())

    def _clear_preview(self) -> None:
        for item in self.preview_ids:
            self.canvas.delete(item)
        self.preview_ids = []

    def update_status(self) -> None:
        self.status_var.set(
            f"{self.image.width} x {self.image.height}px | "
            f"工具：{TOOL_LABELS.get(self.tool_var.get(), self.tool_var.get())} | "
            f"缩放：{int(self.zoom * 100)}%"
        )


def open_image_editor(
    master: tk.Widget,
    image: Image.Image,
    settings: Optional[Settings] = None,
    history: Optional[ScreenshotHistory] = None,
    on_history_change: Optional[Callable[[], None]] = None,
    source_bbox: Optional[BBox] = None,
    initial_fit_to_window: bool = False,
) -> EditorWindow:
    editor_settings = settings if settings is not None else load_settings()
    editor_history = history if history is not None else ScreenshotHistory()
    return EditorWindow(
        master,
        image_for_editor(image),
        editor_settings,
        editor_history,
        on_history_change=on_history_change,
        source_bbox=source_bbox,
        initial_fit_to_window=initial_fit_to_window,
    )


class FloatingCaptureWindow(tk.Toplevel):
    def __init__(
        self,
        master: ScreenshotApp,
        image: Image.Image,
        settings: Settings,
        history: ScreenshotHistory,
        on_history_change: Optional[Callable[[], None]] = None,
        source_bbox: Optional[BBox] = None,
    ) -> None:
        super().__init__(master)
        self.master = master
        self.image = image.convert("RGBA")
        self.settings = settings
        self.history = history
        self.on_history_change = on_history_change
        self.source_bbox = source_bbox
        self.zoom = self._initial_zoom()
        self.target_zoom = self.zoom
        self.zoom_after_id: Optional[str] = None
        self.zoom_settle_after_id: Optional[str] = None
        self.tk_image: Optional[ImageTk.PhotoImage] = None
        self.display_size: Tuple[int, int] = (0, 0)
        self.render_size: Optional[Tuple[int, int]] = None
        self.zoom_center: Optional[Tuple[float, float]] = None
        self.drag_start: Optional[Tuple[int, int]] = None
        self.last_saved_path: Optional[Path] = None
        self.restore_master_on_destroy = False

        apply_inherited_window_icon(self)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#111827")
        self.canvas = tk.Canvas(self, bg="#111827", bd=0, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.render(high_quality=True)
        self._place_window()

        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<Double-Button-1>", lambda _event: self.destroy())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-3>", self._menu)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Control-s>", lambda _event: self.quick_save())
        self.bind("<Control-c>", lambda _event: self.copy_current())
        self.bind("<Return>", lambda _event: self.edit())

        if self.settings.auto_save_after_capture:
            self.quick_save(silent=True)

    def _initial_zoom(self) -> float:
        max_width = 760
        max_height = 540
        zoom = min(1.0, max_width / max(1, self.image.width), max_height / max(1, self.image.height))
        return max(0.15, zoom)

    def _place_window(self) -> None:
        self.update_idletasks()
        width = max(1, int(self.image.width * self.zoom))
        height = max(1, int(self.image.height * self.zoom))
        vx, vy, vw, vh = virtual_screen_bounds()
        if self.source_bbox:
            x = self.source_bbox[2] + 16
            y = self.source_bbox[1]
            if x + width > vx + vw:
                x = self.source_bbox[0] - width - 16
            if x < vx:
                x = vx + 24
            if y + height > vy + vh:
                y = vy + vh - height - 24
            if y < vy:
                y = vy + 24
        else:
            x = vx + (vw - width) // 2
            y = vy + (vh - height) // 2
        self.geometry(f"{width}x{height}+{int(x)}+{int(y)}")
        self.display_size = (width, height)
        self.zoom_center = None

    def render(self, high_quality: bool = True) -> None:
        width = max(1, int(self.image.width * self.zoom))
        height = max(1, int(self.image.height * self.zoom))
        if not high_quality and self.render_size == (width, height) and self.tk_image is not None:
            self._resize_to_image(width, height)
            return
        resample = Image.Resampling.LANCZOS if high_quality else Image.Resampling.BILINEAR
        display = self.image.resize((width, height), resample)
        self.tk_image = ImageTk.PhotoImage(display)
        self.render_size = (width, height)
        self.canvas.configure(width=width, height=height, scrollregion=(0, 0, width, height))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)
        draw_subtle_image_edge(self.canvas, width, height)
        self._resize_to_image(width, height)

    def _resize_to_image(self, width: int, height: int) -> None:
        try:
            center = self.zoom_center
            if center is None:
                old_width, old_height = self.display_size
                if old_width <= 0 or old_height <= 0:
                    old_width = max(1, self.winfo_width())
                    old_height = max(1, self.winfo_height())
                center = (
                    self.winfo_x() + old_width / 2,
                    self.winfo_y() + old_height / 2,
                )
            center_x, center_y = center
            x = int(round(center_x - width / 2))
            y = int(round(center_y - height / 2))
            vx, vy, vw, vh = virtual_screen_bounds()
            x = max(vx, min(x, vx + vw - width)) if width <= vw else vx
            y = max(vy, min(y, vy + vh - height)) if height <= vh else vy
            self.geometry(f"{width}x{height}+{x}+{y}")
            self.display_size = (width, height)
        except tk.TclError:
            pass

    def _start_drag(self, event: tk.Event) -> None:
        self.zoom_center = None
        self.drag_start = (event.x_root, event.y_root)

    def _drag(self, event: tk.Event) -> None:
        if not self.drag_start:
            return
        start_x, start_y = self.drag_start
        dx = event.x_root - start_x
        dy = event.y_root - start_y
        self.geometry(f"+{self.winfo_x() + dx}+{self.winfo_y() + dy}")
        self.drag_start = (event.x_root, event.y_root)

    def _wheel(self, event: tk.Event) -> None:
        if self.zoom_settle_after_id is not None:
            self.after_cancel(self.zoom_settle_after_id)
            self.zoom_settle_after_id = None
        if self.zoom_after_id is not None:
            self.after_cancel(self.zoom_after_id)
            self.zoom_after_id = None

        new_zoom = clamp_zoom(self.zoom * wheel_zoom_factor(event.delta))
        self.zoom_center = zoom_center_from_event(self, self.image.size, self.display_size, new_zoom, event)
        self.zoom = new_zoom
        self.target_zoom = self.zoom
        self.render(high_quality=False)
        self.zoom_settle_after_id = self.after(90, self._settle_zoom)

    def _settle_zoom(self) -> None:
        self.zoom_settle_after_id = None
        if self.zoom_after_id is not None:
            self.after_cancel(self.zoom_after_id)
            self.zoom_after_id = None
        self.zoom = self.target_zoom
        self.render(high_quality=True)
        self.zoom_center = None

    def _cancel_zoom_callbacks(self) -> None:
        for attr in ("zoom_after_id", "zoom_settle_after_id"):
            after_id = getattr(self, attr, None)
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass
                setattr(self, attr, None)
        self.zoom_center = None

    def _menu(self, event: tk.Event) -> None:
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="编辑", command=self.edit)
        menu.add_command(label="快速保存", command=self.quick_save)
        menu.add_command(label="另存为", command=self.save_as)
        menu.add_separator()
        menu.add_command(label="复制图片", command=self.copy_current)
        menu.add_command(label="OCR 识别", command=self.run_ocr)
        menu.add_separator()
        menu.add_command(label="切换置顶", command=self.toggle_topmost)
        menu.add_command(label="显示主窗口", command=self.show_main_window)
        menu.add_command(label="关闭", command=self.destroy)
        menu.tk_popup(event.x_root, event.y_root)

    def edit(self) -> None:
        editor = EditorWindow(
            self.master,
            self.image.copy(),
            self.settings,
            self.history,
            on_history_change=self.on_history_change,
            source_bbox=self.source_bbox,
        )
        if self.settings.keep_editor_on_top:
            editor.attributes("-topmost", True)
        self.destroy()

    def quick_save(self, silent: bool = False) -> Optional[Path]:
        ensure_runtime_dirs(self.settings)
        filename = datetime.now().strftime(self.settings.filename_pattern)
        path = unique_path(Path(self.settings.save_dir) / filename)
        return self.save_to_path(path, silent=silent)

    def save_as(self) -> Optional[Path]:
        ensure_runtime_dirs(self.settings)
        initial_file = datetime.now().strftime(self.settings.filename_pattern)
        path = filedialog.asksaveasfilename(
            parent=self,
            initialdir=self.settings.save_dir,
            initialfile=initial_file,
            defaultextension=".png",
            filetypes=[
                ("PNG 图片", "*.png"),
                ("JPEG 图片", "*.jpg;*.jpeg"),
                ("BMP 图片", "*.bmp"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return None
        return self.save_to_path(Path(path), silent=False)

    def save_to_path(self, path: Path, silent: bool = False) -> Optional[Path]:
        try:
            save_image_file(self.image, path)
            self.last_saved_path = path
            self.history.add(path, self.image.width, self.image.height)
            if self.on_history_change:
                self.on_history_change()
            self.master.status_var.set(f"已保存：{path}")
            if not silent:
                self.bell()
            return path
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            return None

    def copy_current(self, silent: bool = False) -> None:
        try:
            copy_image_to_clipboard(self.image)
            self.master.status_var.set("已复制图片到剪贴板")
            if not silent:
                self.bell()
        except Exception as exc:
            messagebox.showerror("复制失败", str(exc), parent=self)

    def run_ocr(self) -> None:
        OcrWindow(self, self.image.copy(), self.settings.ocr_language)

    def toggle_topmost(self) -> None:
        current = bool(self.attributes("-topmost"))
        self.attributes("-topmost", not current)

    def show_main_window(self) -> None:
        self.master.show_from_background()

    def destroy(self) -> None:
        self._cancel_zoom_callbacks()
        if getattr(self, "restore_master_on_destroy", False):
            try:
                if self.master.winfo_exists():
                    self.master.deiconify()
            except tk.TclError:
                pass
        super().destroy()


class SettingsWindow(tk.Toplevel):
    def __init__(self, master: ScreenshotApp) -> None:
        super().__init__(master)
        self.master = master
        self.title("设置")
        apply_inherited_window_icon(self)
        width, height = bounded_window_size(900, 860, margin_x=160, margin_y=180)
        self.geometry(f"{width}x{height}")
        self.minsize(min(760, width), min(620, height))
        self.configure(bg="#f6f8fb")
        self._build_ui()

    def _build_ui(self) -> None:
        shell = ttk.Frame(self)
        shell.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(shell, bg="#f6f8fb", highlightthickness=0)
        scrollbar = ttk.Scrollbar(shell, orient=tk.VERTICAL, command=canvas.yview)
        self._settings_canvas = canvas
        self._settings_scrollbar = scrollbar
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        root = ttk.Frame(canvas, padding=22)
        window_id = canvas.create_window((0, 0), window=root, anchor=tk.NW)
        root.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        def on_canvas_configure(event: tk.Event) -> None:
            canvas.itemconfigure(window_id, width=event.width)
            self.after_idle(lambda: self._sync_scrollbar_visibility(root))

        canvas.bind("<Configure>", on_canvas_configure)
        self.bind("<MouseWheel>", lambda event: canvas.yview_scroll(-1 * int(event.delta / 120), "units"))
        root.columnconfigure(0, weight=1)

        ttk.Label(root, text="设置", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(root, text="主界面只保留常用按钮，细项都在这里调整。", foreground="#667085").grid(
            row=1, column=0, sticky="w", pady=(2, 16)
        )

        display = ttk.LabelFrame(root, text="显示")
        display.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        display.columnconfigure(1, weight=1)
        ttk.Label(display, text="主界面形态").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        mode_box = ttk.Combobox(
            display,
            textvariable=self.master.toolbar_mode_var,
            values=tuple(TOOLBAR_MODE_VALUES.keys()),
            state="readonly",
            width=18,
        )
        mode_box.grid(row=0, column=1, sticky="w", padx=10, pady=10)
        mode_box.bind("<<ComboboxSelected>>", lambda _event: self.master._sync_settings())
        ttk.Label(display, text="截图方式").grid(row=1, column=0, sticky="w", padx=10, pady=(0, 10))
        ttk.Label(display, text="Alt+A 复制，Alt+S 编辑，Alt+D 贴图", foreground="#667085").grid(
            row=1, column=1, sticky="w", padx=10, pady=(0, 10)
        )
        self._check(display, "编辑器保持置顶", self.master.topmost_var, 2)
        self._check(display, "选择区域时显示放大镜", self.master.magnifier_var, 3)

        behavior = ttk.LabelFrame(root, text="行为")
        behavior.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        behavior.columnconfigure(1, weight=1)
        ttk.Label(behavior, text="关闭按钮行为").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        close_box = ttk.Combobox(
            behavior,
            textvariable=self.master.close_action_var,
            values=tuple(CLOSE_ACTION_VALUES.keys()),
            state="readonly",
            width=18,
        )
        close_box.grid(row=0, column=1, sticky="w", padx=10, pady=10)
        close_box.bind("<<ComboboxSelected>>", lambda _event: self.master._sync_settings())
        self._check(behavior, "开机自动启动", self.master.startup_var, 1)
        self._check(behavior, "启用全局热键", self.master.hotkey_var, 2)
        self._check(behavior, "截图后自动复制到剪贴板", self.master.auto_copy_var, 3)
        self._check(behavior, "截图后自动快速保存", self.master.auto_save_var, 4)

        capture = ttk.LabelFrame(root, text="识别与长截图")
        capture.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        capture.columnconfigure(1, weight=1)
        ttk.Label(capture, text="OCR 语言").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        language_box = ttk.Combobox(
            capture,
            textvariable=self.master.ocr_language_var,
            values=("zh-Hans", "en-US", "ja-JP", "ko-KR"),
            state="readonly",
            width=18,
        )
        language_box.grid(row=0, column=1, sticky="w", padx=10, pady=10)
        language_box.bind("<<ComboboxSelected>>", lambda _event: self.master._sync_settings())
        ttk.Label(capture, text="长截图段数").grid(row=1, column=0, sticky="w", padx=10, pady=10)
        ttk.Spinbox(
            capture,
            from_=2,
            to=40,
            width=8,
            textvariable=self.master.scroll_max_frames_var,
            command=self.master._sync_settings,
        ).grid(row=1, column=1, sticky="w", padx=10, pady=10)
        ttk.Label(capture, text="滚动量").grid(row=2, column=0, sticky="w", padx=10, pady=10)
        ttk.Spinbox(
            capture,
            from_=120,
            to=1800,
            increment=60,
            width=8,
            textvariable=self.master.scroll_delta_var,
            command=self.master._sync_settings,
        ).grid(row=2, column=1, sticky="w", padx=10, pady=10)

        storage = ttk.LabelFrame(root, text="保存")
        storage.grid(row=5, column=0, sticky="ew")
        storage.columnconfigure(0, weight=1)
        ttk.Entry(storage, textvariable=self.master.save_dir_var).grid(
            row=0, column=0, sticky="ew", padx=10, pady=10
        )
        ttk.Button(storage, text="选择目录", command=self.master.choose_save_dir).grid(
            row=0, column=1, sticky="e", padx=(0, 10), pady=10
        )
        ttk.Label(storage, text="截图缓存").grid(row=1, column=0, sticky="w", padx=10, pady=(0, 10))
        ttk.Button(storage, text="清理截图缓存", command=self.master.clear_screenshot_cache).grid(
            row=1, column=1, sticky="e", padx=(0, 10), pady=(0, 10)
        )

        buttons = ttk.Frame(root)
        buttons.grid(row=6, column=0, sticky="ew", pady=(16, 0))
        ttk.Button(buttons, text="应用", command=self.master._sync_settings).pack(side=tk.LEFT)
        ttk.Button(buttons, text="关闭", command=self.destroy).pack(side=tk.RIGHT)
        self.after_idle(lambda: self._fit_to_content(root))

    def _fit_to_content(self, content: tk.Widget) -> None:
        self.update_idletasks()
        preferred_width = max(900, content.winfo_reqwidth() + 36)
        preferred_height = max(680, content.winfo_reqheight() + 20)
        width, height = fit_window_to_content(
            self,
            min_width=760,
            min_height=620,
            preferred_width=preferred_width,
            preferred_height=preferred_height,
            margin_x=160,
            margin_y=180,
        )
        self.minsize(min(760, width), min(620, height))
        self.update_idletasks()
        self.after_idle(lambda: self._sync_scrollbar_visibility(content))

    def _sync_scrollbar_visibility(self, content: tk.Widget) -> None:
        self.update_idletasks()
        if content.winfo_reqheight() <= self._settings_canvas.winfo_height() + 2:
            self._settings_scrollbar.pack_forget()
        elif not self._settings_scrollbar.winfo_ismapped():
            self._settings_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _check(self, parent: tk.Widget, text: str, variable: tk.BooleanVar, row: int) -> None:
        ttk.Checkbutton(parent, text=text, variable=variable, command=self.master._sync_settings).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 10)
        )


class OcrWindow(tk.Toplevel):
    OCR_VIEW_MODES = {
        "整理文本": "clean",
        "按区域": "blocks",
        "逐行原文": "lines",
        "原始输出": "raw",
    }

    def __init__(self, master: tk.Widget, image: Image.Image, language: str) -> None:
        super().__init__(master)
        self.image = image.copy()
        self.language = language
        self.result: Optional[OcrResult] = None
        self.ocr_view_var = tk.StringVar(value="整理文本")
        self.title("OCR 文字识别")
        apply_inherited_window_icon(self)
        width, height = bounded_window_size(980, 700)
        self.geometry(f"{width}x{height}")
        self.minsize(min(620, width), min(420, height))
        self._build_ui()
        self._set_text("正在识别文字...")
        Thread(target=self._worker, daemon=True).start()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)
        self.status_var = tk.StringVar(value=f"语言：{self.language}")
        ttk.Label(root, textvariable=self.status_var, foreground="#475467").pack(anchor=tk.W)

        text_frame = ttk.Frame(root)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 8))
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        self.text = tk.Text(text_frame, wrap=tk.WORD, undo=True, font=("Microsoft YaHei UI", 10), spacing3=3)
        self.text.grid(row=0, column=0, sticky="nsew")
        text_y = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.text.yview)
        text_y.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=text_y.set)

        buttons = ttk.Frame(root)
        buttons.pack(fill=tk.X)
        ttk.Label(buttons, text="视图").pack(side=tk.LEFT, padx=(0, 4))
        mode_box = ttk.Combobox(
            buttons,
            textvariable=self.ocr_view_var,
            values=tuple(self.OCR_VIEW_MODES.keys()),
            state="readonly",
            width=12,
        )
        mode_box.pack(side=tk.LEFT, padx=(0, 8))
        mode_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_text())
        ttk.Button(buttons, text="复制文本", command=self.copy_text).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(buttons, text="保存 TXT", command=self.save_text).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(buttons, text="关闭", command=self.destroy).pack(side=tk.RIGHT)

    def _worker(self) -> None:
        try:
            result = recognize_text(self.image, self.language)
        except Exception as exc:
            self.after(0, lambda error=exc: self._show_error(error))
            return
        self.after(0, lambda: self._show_result(result))

    def _show_result(self, result: OcrResult) -> None:
        self.result = result
        line_count = len([line for line in result.lines if line.strip()])
        self.status_var.set(f"识别完成：{result.engine} / {result.language} / {line_count} 行")
        self.refresh_text()

    def _show_error(self, exc: Exception) -> None:
        self.status_var.set("OCR 失败")
        self._set_text(str(exc))

    def _set_text(self, value: str) -> None:
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", value)

    def refresh_text(self) -> None:
        if not self.result:
            return
        mode = self.OCR_VIEW_MODES.get(self.ocr_view_var.get(), "clean")
        value = format_ocr_text(self.result, mode=mode) or "未识别到文字。"
        self._set_text(value)

    def copy_text(self) -> None:
        text = self.text.get("1.0", tk.END).strip()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("已复制识别文本")

    def save_text(self) -> None:
        text = self.text.get("1.0", tk.END).strip()
        path = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".txt",
            filetypes=[("Text file", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        Path(path).write_text(text, encoding="utf-8")
        self.status_var.set(f"已保存：{path}")


class OcrResultWindow(OcrWindow):
    def __init__(self, master: tk.Widget, result: OcrResult) -> None:
        self.initial_result = result
        super().__init__(master, Image.new("RGB", (1, 1), "white"), result.language)

    def _worker(self) -> None:
        self.after(0, lambda: self._show_result(self.initial_result))


class PinWindow(tk.Toplevel):
    def __init__(self, master: EditorWindow, image: Image.Image) -> None:
        super().__init__(master)
        self.image = image.convert("RGBA")
        self.zoom = min(1.0, 680 / max(1, self.image.width), 480 / max(1, self.image.height))
        self.zoom = max(0.2, self.zoom)
        self.target_zoom = self.zoom
        self.zoom_after_id: Optional[str] = None
        self.zoom_settle_after_id: Optional[str] = None
        self.tk_image: Optional[ImageTk.PhotoImage] = None
        self.display_size: Tuple[int, int] = (0, 0)
        self.render_size: Optional[Tuple[int, int]] = None
        self.zoom_center: Optional[Tuple[float, float]] = None
        self.drag_start: Optional[Tuple[int, int]] = None

        apply_inherited_window_icon(self)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#111827")
        self.canvas = tk.Canvas(self, bg="#111827", bd=0, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.render()
        self._place_window()

        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<Double-Button-1>", lambda _event: self.destroy())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-3>", self._menu)
        self.bind("<Escape>", lambda _event: self.destroy())

    def _place_window(self) -> None:
        self.update_idletasks()
        width = max(1, int(self.image.width * self.zoom))
        height = max(1, int(self.image.height * self.zoom))
        vx, vy, vw, vh = virtual_screen_bounds()
        x = vx + (vw - width) // 2
        y = vy + (vh - height) // 2
        self.geometry(f"{width}x{height}+{int(x)}+{int(y)}")
        self.display_size = (width, height)
        self.zoom_center = None

    def render(self, high_quality: bool = True) -> None:
        width = max(1, int(self.image.width * self.zoom))
        height = max(1, int(self.image.height * self.zoom))
        if not high_quality and self.render_size == (width, height) and self.tk_image is not None:
            self._resize_to_image(width, height)
            return
        resample = Image.Resampling.LANCZOS if high_quality else Image.Resampling.BILINEAR
        display = self.image.resize((width, height), resample)
        self.tk_image = ImageTk.PhotoImage(display)
        self.render_size = (width, height)
        self.canvas.configure(width=width, height=height, scrollregion=(0, 0, width, height))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)
        draw_subtle_image_edge(self.canvas, width, height)
        self._resize_to_image(width, height)

    def _resize_to_image(self, width: int, height: int) -> None:
        try:
            center = self.zoom_center
            if center is None:
                old_width, old_height = self.display_size
                if old_width <= 0 or old_height <= 0:
                    old_width = max(1, self.winfo_width())
                    old_height = max(1, self.winfo_height())
                center = (
                    self.winfo_x() + old_width / 2,
                    self.winfo_y() + old_height / 2,
                )
            center_x, center_y = center
            x = int(round(center_x - width / 2))
            y = int(round(center_y - height / 2))
            vx, vy, vw, vh = virtual_screen_bounds()
            x = max(vx, min(x, vx + vw - width)) if width <= vw else vx
            y = max(vy, min(y, vy + vh - height)) if height <= vh else vy
            self.geometry(f"{width}x{height}+{x}+{y}")
            self.display_size = (width, height)
        except tk.TclError:
            pass

    def _start_drag(self, event: tk.Event) -> None:
        self.zoom_center = None
        self.drag_start = (event.x_root, event.y_root)

    def _drag(self, event: tk.Event) -> None:
        if not self.drag_start:
            return
        start_x, start_y = self.drag_start
        dx = event.x_root - start_x
        dy = event.y_root - start_y
        current_x = self.winfo_x()
        current_y = self.winfo_y()
        self.geometry(f"+{current_x + dx}+{current_y + dy}")
        self.drag_start = (event.x_root, event.y_root)

    def _wheel(self, event: tk.Event) -> None:
        if self.zoom_settle_after_id is not None:
            self.after_cancel(self.zoom_settle_after_id)
            self.zoom_settle_after_id = None
        if self.zoom_after_id is not None:
            self.after_cancel(self.zoom_after_id)
            self.zoom_after_id = None

        new_zoom = clamp_zoom(self.zoom * wheel_zoom_factor(event.delta))
        self.zoom_center = zoom_center_from_event(self, self.image.size, self.display_size, new_zoom, event)
        self.zoom = new_zoom
        self.target_zoom = self.zoom
        self.render(high_quality=False)
        self.zoom_settle_after_id = self.after(90, self._settle_zoom)

    def _settle_zoom(self) -> None:
        self.zoom_settle_after_id = None
        if self.zoom_after_id is not None:
            self.after_cancel(self.zoom_after_id)
        self.zoom_after_id = None
        self.zoom = self.target_zoom
        self.render(high_quality=True)
        self.zoom_center = None

    def _cancel_zoom_callbacks(self) -> None:
        for attr in ("zoom_after_id", "zoom_settle_after_id"):
            after_id = getattr(self, attr, None)
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass
                setattr(self, attr, None)
        self.zoom_center = None

    def _menu(self, event: tk.Event) -> None:
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="复制", command=self.copy_current)
        menu.add_command(label="关闭", command=self.destroy)
        menu.tk_popup(event.x_root, event.y_root)

    def copy_current(self) -> None:
        try:
            copy_image_to_clipboard(self.image)
        except Exception as exc:
            messagebox.showerror("复制失败", str(exc), parent=self)

    def destroy(self) -> None:
        self._cancel_zoom_callbacks()
        super().destroy()


class HistoryWindow(tk.Toplevel):
    def __init__(self, master: ScreenshotApp, history: ScreenshotHistory) -> None:
        super().__init__(master)
        self.master = master
        self.history = history
        self.items: List[HistoryItem] = []
        self.preview_image: Optional[ImageTk.PhotoImage] = None

        self.title("截图历史")
        apply_inherited_window_icon(self)
        width, height = bounded_window_size(1200, 780, margin_x=160, margin_y=180)
        self.geometry(f"{width}x{height}")
        self.minsize(min(940, width), min(620, height))
        self._build_ui()
        self.refresh()
        self._fit_window_to_content()

    def _fit_window_to_content(self) -> None:
        width, height = fit_window_to_content(
            self,
            min_width=1400,
            min_height=780,
            preferred_width=1700,
            preferred_height=920,
            margin_x=160,
            margin_y=180,
        )
        self.minsize(min(1200, width), min(720, height))

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=5, minsize=900)
        root.columnconfigure(1, weight=2, minsize=360)
        root.rowconfigure(0, weight=1)

        list_panel = ttk.Frame(root)
        list_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        list_panel.columnconfigure(0, weight=1)
        list_panel.rowconfigure(0, weight=1)
        self.listbox = tk.Listbox(list_panel, activestyle="dotbox", font=("Consolas", 10), width=100)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        list_y = ttk.Scrollbar(list_panel, orient=tk.VERTICAL, command=self.listbox.yview)
        list_y.grid(row=0, column=1, sticky="ns")
        list_x = ttk.Scrollbar(list_panel, orient=tk.HORIZONTAL, command=self.listbox.xview)
        list_x.grid(row=1, column=0, sticky="ew")
        self.listbox.configure(yscrollcommand=list_y.set, xscrollcommand=list_x.set)
        self.listbox.bind("<<ListboxSelect>>", lambda _event: self.update_preview())
        self.listbox.bind("<Double-Button-1>", lambda _event: self.open_selected())
        self.listbox.bind("<Button-3>", self.show_context_menu)
        self.listbox.bind("<Control-Button-1>", self.show_context_menu)

        preview_panel = ttk.Frame(root)
        preview_panel.grid(row=0, column=1, sticky="nsew")
        preview_panel.rowconfigure(0, weight=1)
        preview_panel.columnconfigure(0, weight=1)
        self.preview = ttk.Label(preview_panel, anchor=tk.CENTER)
        self.preview.grid(row=0, column=0, sticky="nsew")
        self.detail_var = tk.StringVar(value="")
        self.detail_label = ttk.Label(preview_panel, textvariable=self.detail_var, foreground="#475467", justify=tk.LEFT)
        self.detail_label.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        preview_panel.bind(
            "<Configure>",
            lambda event: self.detail_label.configure(wraplength=max(260, event.width - 12)),
        )

        buttons = ttk.Frame(root)
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(buttons, text="打开/编辑", command=self.open_selected).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(buttons, text="复制", command=self.copy_selected).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(buttons, text="OCR", command=self.ocr_selected).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(buttons, text="在目录中查看", command=self.reveal_selected).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(buttons, text="清理截图缓存", command=self.clear_cache).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(buttons, text="从历史移除", command=self.remove_selected).pack(side=tk.RIGHT)

    def refresh(self) -> None:
        self.history.load()
        self.items = self.history.recent(200)
        self.listbox.delete(0, tk.END)
        for item in self.items:
            path = Path(item.path)
            label = f"{path.name}  |  {format_datetime(item.created_at)}  |  {item.width}x{item.height}px"
            self.listbox.insert(tk.END, label)
        if self.items:
            self.listbox.selection_set(0)
            self.update_preview()
        else:
            self.update_preview()

    def selected_item(self) -> Optional[HistoryItem]:
        selection = self.listbox.curselection()
        if not selection:
            return None
        index = selection[0]
        if index >= len(self.items):
            return None
        return self.items[index]

    def update_preview(self) -> None:
        item = self.selected_item()
        if not item:
            self.preview.configure(image="", text="未选择截图")
            self.detail_var.set("")
            return
        thumbnail = Path(item.thumbnail)
        if thumbnail.exists():
            with Image.open(thumbnail) as image:
                self.preview_image = ImageTk.PhotoImage(image.copy())
            self.preview.configure(image=self.preview_image, text="")
        else:
            self.preview.configure(image="", text="无法预览")
        self.detail_var.set(
            f"{Path(item.path)}\n"
            f"{format_datetime(item.created_at)}  |  {item.width} x {item.height}px"
        )

    def open_selected(self) -> None:
        item = self.selected_item()
        if item:
            self.master.open_history_item(item)

    def copy_selected(self) -> None:
        item = self.selected_item()
        if not item:
            return
        path = Path(item.path)
        if not path.exists():
            messagebox.showwarning("文件不存在", f"找不到文件：\n{path}", parent=self)
            return
        try:
            with Image.open(path) as image:
                copy_image_to_clipboard(image.copy())
        except Exception as exc:
            messagebox.showerror("复制失败", str(exc), parent=self)

    def ocr_selected(self) -> None:
        item = self.selected_item()
        if not item:
            return
        path = Path(item.path)
        if not path.exists():
            messagebox.showwarning("文件不存在", f"找不到文件：\n{path}", parent=self)
            return
        with Image.open(path) as image:
            OcrWindow(self, image.copy(), self.master.settings.ocr_language)

    def select_item_at(self, y: int) -> Optional[HistoryItem]:
        if not self.items:
            return None
        index = self.listbox.nearest(y)
        if index < 0 or index >= len(self.items):
            return None
        bounds = self.listbox.bbox(index)
        if bounds is None:
            return None
        _x, item_y, _width, item_height = bounds
        if y < item_y or y > item_y + item_height:
            return None
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        self.listbox.focus_set()
        self.update_preview()
        return self.items[index]

    def show_context_menu(self, event: tk.Event) -> None:
        if not self.select_item_at(event.y):
            return
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="打开/编辑", command=self.open_selected)
        menu.add_command(label="复制", command=self.copy_selected)
        menu.add_command(label="OCR", command=self.ocr_selected)
        menu.add_separator()
        menu.add_command(label="在目录中查看", command=self.reveal_selected)
        menu.add_command(label="从历史移除", command=self.remove_selected)
        menu.add_separator()
        menu.add_command(label="清理截图缓存", command=self.clear_cache)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def reveal_selected(self) -> None:
        item = self.selected_item()
        if not item:
            return
        path = Path(item.path)
        if path.exists():
            try:
                get_adapter().reveal_path_in_folder(str(path))
            except OSError:
                folder = path.parent if path.parent.exists() else Path(self.master.settings.save_dir)
                get_adapter().open_file(str(folder))
        elif path.parent.exists():
            messagebox.showwarning("文件不存在", f"找不到文件，将打开所在目录：\n{path}", parent=self)
            try:
                get_adapter().open_file(str(path.parent))
            except OSError:
                messagebox.showinfo("目录", str(path.parent), parent=self)
        else:
            messagebox.showwarning("文件不存在", f"找不到文件：\n{path}", parent=self)

    def clear_cache(self) -> None:
        self.master.clear_screenshot_cache(parent=self)

    def remove_selected(self) -> None:
        item = self.selected_item()
        if not item:
            return
        self.history.remove(item.id)
        self.master.refresh_recent()
        self.refresh()


def format_datetime(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


def main() -> None:
    app = ScreenshotApp()
    app.mainloop()
