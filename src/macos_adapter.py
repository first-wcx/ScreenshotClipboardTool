"""macOS 平台适配器。

使用 NSPasteboard (剪贴板)、pynput (热键)、pystray (托盘图标)、
LaunchAgents (开机自启) 等 macOS 技术实现 PlatformAdapter 接口。

重要：所有 macOS 专用依赖均在方法体内懒加载导入，
避免在 Windows 上 import 时因缺少 pyobjc / pynput 而崩溃。
"""
from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image

from platform_adapter import (
    CF_BITMAP,
    CF_DIB,
    CF_HDROP,
    CF_UNICODETEXT,
    HotkeyDef,
    PlatformAdapter,
    TrayCallbacks,
)

# ---------------------------------------------------------------------------
# LaunchAgent plist 路径
# ---------------------------------------------------------------------------
_LAUNCH_AGENT_ID = "com.integrated-capture-clipboard"
_LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
_LAUNCH_AGENT_PLIST = _LAUNCH_AGENTS_DIR / f"{_LAUNCH_AGENT_ID}.plist"


# ---------------------------------------------------------------------------
# MacOSAdapter
# ---------------------------------------------------------------------------
class MacOSAdapter(PlatformAdapter):
    """macOS 平台适配器。"""

    def __init__(self) -> None:
        self._hotkey_listener = None
        self._hotkey_callbacks: Dict[str, Callable[[], None]] = {}
        self._tray_icon = None
        self._tray_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # 剪贴板：读取
    # ------------------------------------------------------------------
    def clipboard_is_format_available(self, fmt: int) -> bool:
        """检查 NSPasteboard 中是否存在指定格式的数据。"""
        # 懒加载
        from AppKit import NSPasteboard  # noqa: F811

        pb = NSPasteboard.generalPasteboard()
        types = pb.types() or []

        # 将 Win32 格式 ID 映射为 NSPasteboard 类型名
        ns_type = self._win32_fmt_to_ns_type(fmt)
        if ns_type is None:
            return False
        return ns_type in types

    def clipboard_get_sequence_number(self) -> int:
        """使用 NSPasteboard.changeCount 作为序列号。"""
        from AppKit import NSPasteboard

        pb = NSPasteboard.generalPasteboard()
        return int(pb.changeCount())

    def clipboard_read_text(self) -> Optional[str]:
        """从 NSPasteboard 读取文本。"""
        from AppKit import NSPasteboard

        pb = NSPasteboard.generalPasteboard()
        text = pb.stringForType_("public.utf8-plain-text")
        return str(text) if text else None

    def clipboard_read_file_list(self) -> Optional[List[str]]:
        """从 NSPasteboard 读取文件 URL 列表。"""
        from AppKit import NSPasteboard

        pb = NSPasteboard.generalPasteboard()
        # 尝试读取文件 URL
        urls = pb.propertyListForType_("public.file-url")
        if urls:
            paths = []
            for url in urls:
                if isinstance(url, str):
                    from urllib.parse import urlparse, unquote
                    parsed = urlparse(url)
                    if parsed.scheme == "file":
                        paths.append(unquote(parsed.path))
                    else:
                        paths.append(url)
            if paths:
                return paths
        # 尝试直接读取 NSFilenamesPboardType
        filenames = pb.propertyListForType_("NSFilenamesPboardType")
        if filenames and isinstance(filenames, list):
            return [str(f) for f in filenames if isinstance(f, str)]
        return None

    def clipboard_read_dib_bytes(self) -> Optional[bytes]:
        """从 NSPasteboard 读取 TIFF 图片数据并转换为 BMP DIB。"""
        from AppKit import NSPasteboard

        pb = NSPasteboard.generalPasteboard()
        tiff_data = pb.dataForType_("public.tiff")
        if not tiff_data:
            return None
        tiff_bytes = bytes(tiff_data)
        # 将 TIFF 转换为 BMP DIB
        try:
            from io import BytesIO
            img = Image.open(BytesIO(tiff_bytes))
            buf = BytesIO()
            img.convert("RGB").save(buf, "BMP")
            bmp_bytes = buf.getvalue()
            # DIB = BMP 去掉 14 字节文件头
            return bmp_bytes[14:]
        except Exception:
            return None

    def clipboard_read_all(self) -> Dict[str, object]:
        """从 NSPasteboard 一次性读取所有格式。"""
        result: Dict[str, object] = {
            "text": None,
            "file_list": None,
            "dib_bytes": None,
            "has_bitmap": False,
        }
        # 优先读取文件列表
        result["file_list"] = self.clipboard_read_file_list()
        if result["file_list"] is None:
            result["text"] = self.clipboard_read_text()
        if result["file_list"] is None and result["text"] is None:
            result["dib_bytes"] = self.clipboard_read_dib_bytes()
            # 检查是否有图片格式
            from AppKit import NSPasteboard
            pb = NSPasteboard.generalPasteboard()
            types = pb.types() or []
            if "public.tiff" in types or "public.png" in types or "public.jpeg" in types:
                result["has_bitmap"] = True
        return result

    # ------------------------------------------------------------------
    # 剪贴板：写入
    # ------------------------------------------------------------------
    def clipboard_write_text(self, text: str) -> None:
        from AppKit import NSPasteboard

        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        from Foundation import NSString
        ns_string = NSString.alloc().initWithString_(text)
        pb.setString_forType_(ns_string, "public.utf8-plain-text")

    def clipboard_write_file_list(self, paths: List[str]) -> None:
        from AppKit import NSPasteboard
        from Foundation import NSArray, NSURL

        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        urls = []
        for path_str in paths:
            url = NSURL.fileURLWithPath_(path_str)
            if url:
                urls.append(url)
        if urls:
            pb.writeObjects_(NSArray.arrayWithArray_(urls))

    def clipboard_write_dib_bytes(self, dib: bytes) -> None:
        """将 DIB 数据写入 NSPasteboard（转换为 TIFF）。"""
        from io import BytesIO

        from AppKit import NSPasteboard

        # 将 DIB 转换为 PIL Image，再保存为 TIFF
        bmp_header = (
            b"BM"
            + (14 + len(dib)).to_bytes(4, "little")
            + (0).to_bytes(4, "little")
            + (14).to_bytes(4, "little")
        )
        bmp_bytes = bmp_header + dib
        try:
            img = Image.open(BytesIO(bmp_bytes))
        except Exception:
            raise OSError("无法将 DIB 数据转换为图片。")
        tiff_buf = BytesIO()
        img.save(tiff_buf, "TIFF")
        tiff_bytes = tiff_buf.getvalue()

        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        from Foundation import NSData
        ns_data = NSData.dataWithBytes_length_(tiff_bytes, len(tiff_bytes))
        pb.setData_forType_(ns_data, "public.tiff")

    def clipboard_clear(self) -> None:
        from AppKit import NSPasteboard

        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()

    # ------------------------------------------------------------------
    # 图片复制到剪贴板
    # ------------------------------------------------------------------
    def copy_image_to_clipboard(self, image: Image.Image) -> None:
        from io import BytesIO

        from AppKit import NSPasteboard
        from Foundation import NSData

        # 将 PIL Image 保存为 TIFF 数据
        tiff_buf = BytesIO()
        image.save(tiff_buf, "TIFF")
        tiff_bytes = tiff_buf.getvalue()

        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        ns_data = NSData.dataWithBytes_length_(tiff_bytes, len(tiff_bytes))
        pb.setData_forType_(ns_data, "public.tiff")

    # ------------------------------------------------------------------
    # 窗口检测
    # ------------------------------------------------------------------
    def detect_window_at_point(
        self,
        screen_point: Tuple[int, int],
        exclude_ids: Optional[List[int]] = None,
    ) -> Optional[Tuple[int, int, int, int]]:
        """使用 CGWindowListCopyWindowInfo 检测指定坐标处的窗口。"""
        from CoreGraphics import CGWindowListCopyWindowInfo, kCGNullWindowID, kCGWindowListOptionOnScreenOnly

        x, y = screen_point
        exclude = set(exclude_ids or [])
        own_pid = os.getpid()

        window_list = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID,
        )
        if not window_list:
            return None

        best_rect: Optional[Tuple[int, int, int, int]] = None
        best_area: int = 0

        for win in window_list:
            window_pid = win.get("kCGWindowOwnerPID", 0)
            window_number = win.get("kCGWindowNumber", 0)
            if window_pid == own_pid:
                continue
            if window_number in exclude:
                continue
            bounds = win.get("kCGWindowBounds")
            if not bounds:
                continue
            # macOS 坐标系：原点在左上角，与 Windows 一致
            wx = int(bounds.get("X", 0))
            wy = int(bounds.get("Y", 0))
            ww = int(bounds.get("Width", 0))
            wh = int(bounds.get("Height", 0))
            if ww < 24 or wh < 24:
                continue
            if wx <= x <= wx + ww and wy <= y <= wy + wh:
                area = ww * wh
                if best_rect is None or area < best_area:
                    best_rect = (wx, wy, wx + ww, wy + wh)
                    best_area = area

        return best_rect

    # ------------------------------------------------------------------
    # 热键管理
    # ------------------------------------------------------------------
    def register_hotkeys(self, root, hotkeys: List[HotkeyDef]) -> Tuple[int, List[str]]:
        """使用 pynput 注册全局热键。"""
        # 懒加载 pynput
        from pynput import keyboard as pynput_keyboard

        self.unregister_hotkeys()
        self._hotkey_callbacks.clear()
        registered = 0
        failures: List[str] = []

        hotkey_map: Dict[str, Callable[[], None]] = {}
        for hd in hotkeys:
            try:
                pynput_key = self._parse_hotkey_for_pynput(hd.key)
                hotkey_map[pynput_key] = hd.callback
                self._hotkey_callbacks[pynput_key] = hd.callback
                registered += 1
            except ValueError:
                failures.append(hd.name)

        if not hotkey_map:
            return 0, failures if failures else ["No valid hotkeys."]

        def on_activate(hotkey_str):
            callback = self._hotkey_callbacks.get(hotkey_str)
            if callback:
                # 在主线程中执行回调
                if root:
                    root.after(0, callback)
                else:
                    callback()

        try:
            # 使用 pynput 的 GlobalHotKeys
            hotkeys_obj = {}
            for key_str in hotkey_map:
                hotkeys_obj[key_str] = key_str

            self._hotkey_listener = pynput_keyboard.GlobalHotKeys(
                {k: (lambda ks=key_str: on_activate(ks)) for key_str in hotkey_map}
            )
            self._hotkey_listener.start()
        except Exception:
            return 0, ["pynput 全局热键启动失败。"]

        return registered, failures

    def unregister_hotkeys(self) -> None:
        if self._hotkey_listener is not None:
            try:
                self._hotkey_listener.stop()
            except Exception:
                pass
            self._hotkey_listener = None
        self._hotkey_callbacks.clear()

    @staticmethod
    def _parse_hotkey_for_pynput(hotkey_str: str) -> str:
        """将 "Alt+A" 格式转换为 pynput 热键字符串。

        pynput 使用 "<ctrl>+<shift>+m" 格式。
        """
        parts = [p.strip() for p in hotkey_str.replace(" ", "").split("+") if p.strip()]
        if not parts:
            raise ValueError(f"无效热键: {hotkey_str!r}")

        pynput_parts = []
        for part in parts:
            name = part.upper()
            if name in {"CTRL", "CONTROL"}:
                pynput_parts.append("<cmd>")
            elif name == "SHIFT":
                pynput_parts.append("<shift>")
            elif name == "ALT":
                pynput_parts.append("<alt>")
            elif name in {"CMD", "COMMAND", "SUPER", "WIN", "WINDOWS"}:
                pynput_parts.append("<cmd>")
            elif len(part) == 1:
                pynput_parts.append(part.lower())
            elif name.startswith("F") and name[1:].isdigit():
                pynput_parts.append(f"<{part.lower()}>")
            else:
                pynput_parts.append(part.lower())

        return "+".join(pynput_parts)

    # ------------------------------------------------------------------
    # 系统托盘
    # ------------------------------------------------------------------
    def show_tray_icon(
        self,
        root,
        callbacks: TrayCallbacks,
        icon_path: Optional[str] = None,
    ) -> bool:
        """使用 pystray 显示系统托盘图标。"""
        import pystray
        from PIL import Image as PILImage, ImageDraw

        self._tray_callbacks = callbacks

        # 创建托盘图标
        icon_image = self._create_tray_icon_image()
        if icon_path and Path(icon_path).exists():
            try:
                icon_image = PILImage.open(icon_path)
            except Exception:
                pass

        menu = pystray.Menu(
            pystray.MenuItem("显示主窗口", self._tray_on_show, default=True),
            pystray.MenuItem("设置", self._tray_on_settings),
            pystray.MenuItem("历史截图", self._tray_on_history),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._tray_on_exit),
        )

        self._tray_icon = pystray.Icon(
            "screenshot_tool",
            icon_image,
            "截图工具",
            menu=menu,
        )

        self._tray_thread = threading.Thread(
            target=self._tray_icon.run, name="MacOSTray", daemon=True,
        )
        self._tray_thread.start()
        return True

    def hide_tray_icon(self) -> None:
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
        if self._tray_thread is not None and self._tray_thread.is_alive():
            self._tray_thread.join(timeout=2.0)
        self._tray_thread = None

    def _tray_on_show(self, _icon=None, _item=None) -> None:
        if self._tray_callbacks and self._tray_callbacks.on_show:
            self._tray_callbacks.on_show()

    def _tray_on_settings(self, _icon=None, _item=None) -> None:
        if self._tray_callbacks and self._tray_callbacks.on_settings:
            self._tray_callbacks.on_settings()

    def _tray_on_history(self, _icon=None, _item=None) -> None:
        if self._tray_callbacks and self._tray_callbacks.on_history:
            self._tray_callbacks.on_history()

    def _tray_on_exit(self, _icon=None, _item=None) -> None:
        if self._tray_callbacks and self._tray_callbacks.on_exit:
            self._tray_callbacks.on_exit()

    @staticmethod
    def _create_tray_icon_image() -> Image.Image:
        """创建默认托盘图标。"""
        icon = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(icon)
        draw.rounded_rectangle((10, 8, 54, 58), radius=8, fill=(42, 99, 220), outline=(18, 45, 120), width=3)
        draw.rectangle((20, 4, 44, 14), fill=(235, 242, 255), outline=(18, 45, 120), width=2)
        draw.line((20, 25, 44, 25), fill=(255, 255, 255), width=4)
        draw.line((20, 38, 44, 38), fill=(255, 255, 255), width=4)
        return icon

    # ------------------------------------------------------------------
    # 开机自启
    # ------------------------------------------------------------------
    def is_startup_enabled(self) -> bool:
        """检查 LaunchAgent plist 是否存在且已加载。"""
        if not _LAUNCH_AGENT_PLIST.exists():
            return False
        # 检查是否已加载
        result = subprocess.run(
            ["launchctl", "list", _LAUNCH_AGENT_ID],
            capture_output=True, text=True,
        )
        return result.returncode == 0

    def set_startup_enabled(self, enabled: bool) -> Optional[str]:
        """使用 LaunchAgent 设置开机自启。"""
        if enabled:
            return self._install_launch_agent()
        self._uninstall_launch_agent()
        return None

    def _install_launch_agent(self) -> str:
        """安装 LaunchAgent plist 并加载。"""
        # 获取当前 Python 解释器路径
        python_path = sys.executable
        # 获取项目 run.py 路径
        run_script = self._find_run_script()

        plist_content = {
            "Label": _LAUNCH_AGENT_ID,
            "ProgramArguments": [python_path, str(run_script)],
            "RunAtLoad": True,
            "KeepAlive": False,
            "StandardOutPath": str(Path.home() / "Library" / "Logs" / f"{_LAUNCH_AGENT_ID}.log"),
            "StandardErrorPath": str(Path.home() / "Library" / "Logs" / f"{_LAUNCH_AGENT_ID}_error.log"),
        }

        _LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        with open(_LAUNCH_AGENT_PLIST, "wb") as f:
            plistlib.dump(plist_content, f)

        # 加载 LaunchAgent
        subprocess.run(
            ["launchctl", "load", str(_LAUNCH_AGENT_PLIST)],
            capture_output=True,
        )

        command = f"{python_path} {run_script}"
        return command

    def _uninstall_launch_agent(self) -> None:
        """卸载 LaunchAgent。"""
        if _LAUNCH_AGENT_PLIST.exists():
            # 先卸载
            subprocess.run(
                ["launchctl", "unload", str(_LAUNCH_AGENT_PLIST)],
                capture_output=True,
            )
            _LAUNCH_AGENT_PLIST.unlink()

    @staticmethod
    def _find_run_script() -> Path:
        argv0 = Path(sys.argv[0]).resolve()
        if argv0.name.lower() == "run.py" and argv0.exists():
            return argv0
        project_root = Path(__file__).resolve().parents[1]
        candidate = project_root / "run.py"
        if candidate.exists():
            return candidate
        return argv0

    # ------------------------------------------------------------------
    # DPI 与屏幕
    # ------------------------------------------------------------------
    def enable_dpi_awareness(self) -> None:
        """macOS 不需要手动设置 DPI 感知，Retina 由系统自动处理。"""
        pass

    def virtual_screen_bounds(self) -> Tuple[int, int, int, int]:
        """获取 macOS 主屏幕尺寸。"""
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        width = root.winfo_screenwidth()
        height = root.winfo_screenheight()
        root.destroy()
        return 0, 0, width, height

    # ------------------------------------------------------------------
    # 文件操作
    # ------------------------------------------------------------------
    def open_file(self, path: str) -> None:
        subprocess.Popen(["open", path])

    def reveal_path_in_folder(self, path: str) -> None:
        subprocess.Popen(["open", "-R", str(path)])

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _win32_fmt_to_ns_type(fmt: int) -> Optional[str]:
        """将 Win32 剪贴板格式 ID 映射为 NSPasteboard 类型字符串。"""
        _FMT_MAP = {
            CF_UNICODETEXT: "public.utf8-plain-text",
            CF_HDROP: "NSFilenamesPboardType",
            CF_DIB: "public.tiff",
            CF_BITMAP: "public.tiff",
        }
        return _FMT_MAP.get(fmt)
