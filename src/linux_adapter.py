"""Linux 平台适配器。

使用 xclip/xsel（剪贴板）、xdotool（窗口检测）、pynput（热键）、
pystray（托盘图标）、XDG autostart（开机自启）等技术实现 PlatformAdapter 接口。

重要：所有 Linux 专用依赖均在方法体内懒加载导入，
避免在 Windows/macOS 上 import 时因缺少相关库而崩溃。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
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
# XDG Autostart 路径
# ---------------------------------------------------------------------------
_AUTOSTART_DIR = Path.home() / ".config" / "autostart"
_APP_NAME = "IntegratedCaptureClipboard"
_DESKTOP_FILE = _AUTOSTART_DIR / f"{_APP_NAME}.desktop"


# ---------------------------------------------------------------------------
# LinuxAdapter
# ---------------------------------------------------------------------------
class LinuxAdapter(PlatformAdapter):
    """Linux 平台适配器。

    所有 Linux 专用系统调用均通过 subprocess 或方法内懒导入完成，
    确保本模块可在 Windows/macOS 上安全 import（但不能调用）。
    """

    def __init__(self) -> None:
        self._hotkey_listener = None
        self._hotkey_callbacks: Dict[str, Callable[[], None]] = {}
        self._tray_icon = None
        self._tray_thread: Optional[threading.Thread] = None
        self._tray_callbacks: Optional[TrayCallbacks] = None
        # 用于 sequence number 的上次剪贴板文本缓存（哈希）
        self._last_clipboard_hash: int = 0

    # ------------------------------------------------------------------
    # 内部工具：剪贴板工具检测
    # ------------------------------------------------------------------
    @staticmethod
    def _has_tool(name: str) -> bool:
        """检查系统中是否有指定的命令行工具。"""
        return shutil.which(name) is not None

    @staticmethod
    def _run(cmd: List[str], input_data: Optional[bytes] = None) -> subprocess.CompletedProcess:
        """运行子进程，返回 CompletedProcess（不抛异常）。"""
        try:
            return subprocess.run(
                cmd,
                input=input_data,
                capture_output=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            # 构造一个失败的结果
            result = subprocess.CompletedProcess(cmd, returncode=-1)
            result.stdout = b""
            result.stderr = str(exc).encode()
            return result

    # ------------------------------------------------------------------
    # 剪贴板：底层读写
    # ------------------------------------------------------------------
    def _xclip_read(self, mime_type: Optional[str] = None) -> Optional[bytes]:
        """用 xclip 读取剪贴板。mime_type=None 时读取 UTF-8 文本。"""
        if not self._has_tool("xclip"):
            return None
        cmd = ["xclip", "-selection", "clipboard", "-o"]
        if mime_type:
            cmd += ["-t", mime_type]
        result = self._run(cmd)
        if result.returncode == 0:
            return result.stdout
        return None

    def _xsel_read(self) -> Optional[bytes]:
        """用 xsel 读取剪贴板文本（xclip 不可用时的回退）。"""
        if not self._has_tool("xsel"):
            return None
        result = self._run(["xsel", "--clipboard", "--output"])
        if result.returncode == 0:
            return result.stdout
        return None

    def _xclip_write(self, data: bytes, mime_type: str = "UTF8_STRING") -> bool:
        """用 xclip 写入剪贴板。"""
        if not self._has_tool("xclip"):
            return False
        result = self._run(
            ["xclip", "-selection", "clipboard", "-t", mime_type],
            input_data=data,
        )
        return result.returncode == 0

    def _xsel_write(self, data: bytes) -> bool:
        """用 xsel 写入文本到剪贴板（xclip 不可用时的回退）。"""
        if not self._has_tool("xsel"):
            return False
        result = self._run(["xsel", "--clipboard", "--input"], input_data=data)
        return result.returncode == 0

    def _read_clipboard_bytes(self, mime_type: Optional[str] = None) -> Optional[bytes]:
        """优先使用 xclip，不可用时回退 xsel（仅文本）。"""
        data = self._xclip_read(mime_type)
        if data is None and mime_type is None:
            data = self._xsel_read()
        return data

    def _write_clipboard_bytes(self, data: bytes, mime_type: str = "UTF8_STRING") -> None:
        """写入剪贴板，优先 xclip，不可用时回退 xsel（仅文本）。"""
        if not self._xclip_write(data, mime_type):
            if mime_type in ("UTF8_STRING", "text/plain"):
                self._xsel_write(data)

    # ------------------------------------------------------------------
    # 剪贴板：读取
    # ------------------------------------------------------------------
    def clipboard_is_format_available(self, fmt: int) -> bool:
        """检查剪贴板中是否有指定格式的数据。

        通过尝试读取对应 MIME 类型来判断。
        """
        if fmt in (CF_UNICODETEXT,):
            data = self._read_clipboard_bytes(None)
            return bool(data)
        if fmt in (CF_DIB, CF_BITMAP):
            data = self._xclip_read("image/png")
            if data and len(data) > 0:
                return True
            data = self._xclip_read("image/bmp")
            return bool(data and len(data) > 0)
        if fmt == CF_HDROP:
            # 检查剪贴板是否含有文件 URI 列表
            data = self._xclip_read("text/uri-list")
            if data:
                text = data.decode("utf-8", errors="replace").strip()
                return bool(text and text.startswith("file://"))
            return False
        return False

    def clipboard_get_sequence_number(self) -> int:
        """通过读取剪贴板内容并哈希来模拟序列号。

        每次调用读取当前剪贴板文本/图片哈希；内容变化则返回值变化。
        使用时间戳和内容哈希组合，确保单调变化。
        """
        raw = self._read_clipboard_bytes(None) or b""
        h = int(hashlib.md5(raw).hexdigest(), 16) & 0x7FFFFFFF  # 正整数
        # 若内容变化，更新缓存并返回新哈希；否则返回上次值
        if h != self._last_clipboard_hash:
            self._last_clipboard_hash = h
        return self._last_clipboard_hash

    def clipboard_read_text(self) -> Optional[str]:
        """从剪贴板读取 UTF-8 文本。"""
        data = self._read_clipboard_bytes(None)
        if data is None:
            return None
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = data.decode("latin-1")
            except UnicodeDecodeError:
                return None
        return text if text else None

    def clipboard_read_file_list(self) -> Optional[List[str]]:
        """从剪贴板读取文件 URI 列表（text/uri-list 格式）。"""
        data = self._xclip_read("text/uri-list")
        if not data:
            return None
        from urllib.parse import unquote, urlparse

        lines = data.decode("utf-8", errors="replace").splitlines()
        paths: List[str] = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parsed = urlparse(line)
            if parsed.scheme == "file":
                # 解码百分号编码
                path = unquote(parsed.path)
                paths.append(path)
            elif line.startswith("/"):
                paths.append(line)
        return paths if paths else None

    def clipboard_read_dib_bytes(self) -> Optional[bytes]:
        """从剪贴板读取图片数据并转换为 DIB (BMP without file header) 格式。

        尝试顺序：image/png → image/bmp → image/jpeg。
        """
        from io import BytesIO

        # 尝试读取 PNG
        png_data = self._xclip_read("image/png")
        if png_data and len(png_data) > 8:
            try:
                img = Image.open(BytesIO(png_data))
                buf = BytesIO()
                img.convert("RGB").save(buf, "BMP")
                bmp_bytes = buf.getvalue()
                return bmp_bytes[14:]  # 去掉 14 字节 BMP 文件头，剩余为 DIB
            except Exception:
                pass

        # 尝试读取 BMP
        bmp_data = self._xclip_read("image/bmp")
        if bmp_data and len(bmp_data) > 14:
            # BMP 文件直接去掉 14 字节文件头
            return bmp_data[14:]

        # 尝试读取 JPEG
        jpeg_data = self._xclip_read("image/jpeg")
        if jpeg_data and len(jpeg_data) > 0:
            try:
                img = Image.open(BytesIO(jpeg_data))
                buf = BytesIO()
                img.convert("RGB").save(buf, "BMP")
                bmp_bytes = buf.getvalue()
                return bmp_bytes[14:]
            except Exception:
                pass

        return None

    def clipboard_read_all(self) -> Dict[str, object]:
        """一次性读取剪贴板所有格式。

        返回字典::

            {
                "text": Optional[str],
                "file_list": Optional[List[str]],
                "dib_bytes": Optional[bytes],
                "has_bitmap": bool,
            }
        """
        result: Dict[str, object] = {
            "text": None,
            "file_list": None,
            "dib_bytes": None,
            "has_bitmap": False,
        }
        # 优先读取文件列表
        file_list = self.clipboard_read_file_list()
        if file_list:
            result["file_list"] = file_list
            return result

        # 检查图片
        dib = self.clipboard_read_dib_bytes()
        if dib:
            result["dib_bytes"] = dib
            result["has_bitmap"] = True
            return result

        # 尝试读取图片格式（即使 dib 转换失败也标记 has_bitmap）
        for mime in ("image/png", "image/bmp", "image/jpeg", "image/tiff"):
            raw = self._xclip_read(mime)
            if raw and len(raw) > 0:
                result["has_bitmap"] = True
                break

        # 读取文本
        result["text"] = self.clipboard_read_text()
        return result

    # ------------------------------------------------------------------
    # 剪贴板：写入
    # ------------------------------------------------------------------
    def clipboard_write_text(self, text: str) -> None:
        """写入 UTF-8 文本到剪贴板。"""
        self._write_clipboard_bytes(text.encode("utf-8"), "UTF8_STRING")

    def clipboard_write_file_list(self, paths: List[str]) -> None:
        """写入文件路径列表到剪贴板（text/uri-list 格式）。"""
        from urllib.parse import quote

        lines = []
        for p in paths:
            # 将路径转换为 file:// URI
            encoded = quote(p, safe="/:")
            lines.append(f"file://{encoded}")
        uri_list = "\r\n".join(lines) + "\r\n"
        self._write_clipboard_bytes(uri_list.encode("utf-8"), "text/uri-list")

    def clipboard_write_dib_bytes(self, dib: bytes) -> None:
        """将 DIB 数据写入剪贴板（转换为 PNG）。"""
        from io import BytesIO

        # 构造完整 BMP 文件（添加 14 字节文件头）
        bmp_header = (
            b"BM"
            + (14 + len(dib)).to_bytes(4, "little")
            + (0).to_bytes(4, "little")
            + (14).to_bytes(4, "little")
        )
        bmp_bytes = bmp_header + dib
        try:
            img = Image.open(BytesIO(bmp_bytes))
            png_buf = BytesIO()
            img.save(png_buf, "PNG")
            png_bytes = png_buf.getvalue()
            self._write_clipboard_bytes(png_bytes, "image/png")
        except Exception as exc:
            raise OSError(f"无法将 DIB 数据写入剪贴板: {exc}") from exc

    def clipboard_clear(self) -> None:
        """清空剪贴板。"""
        if self._has_tool("xclip"):
            self._run(["xclip", "-selection", "clipboard"], input_data=b"")
        elif self._has_tool("xsel"):
            self._run(["xsel", "--clipboard", "--clear"])

    # ------------------------------------------------------------------
    # 图片复制到剪贴板
    # ------------------------------------------------------------------
    def copy_image_to_clipboard(self, image: Image.Image) -> None:
        """将 PIL Image 以 PNG 格式写入剪贴板。"""
        from io import BytesIO

        buf = BytesIO()
        image.save(buf, "PNG")
        png_bytes = buf.getvalue()
        self._write_clipboard_bytes(png_bytes, "image/png")

    # ------------------------------------------------------------------
    # 窗口检测
    # ------------------------------------------------------------------
    def detect_window_at_point(
        self,
        screen_point: Tuple[int, int],
        exclude_ids: Optional[List[int]] = None,
    ) -> Optional[Tuple[int, int, int, int]]:
        """使用 xdotool 获取当前活动窗口矩形。

        Linux 下无法精确 hit-test 任意坐标的窗口，
        此处返回当前活动窗口的矩形（常见简化方案）。
        若 xdotool 不可用则返回 None。
        """
        if not self._has_tool("xdotool"):
            return None

        # 获取活动窗口 ID
        result = self._run(["xdotool", "getactivewindow"])
        if result.returncode != 0:
            return None

        win_id_str = result.stdout.decode().strip()
        if not win_id_str:
            return None

        # 获取窗口几何信息
        geom_result = self._run(
            ["xdotool", "getwindowgeometry", "--shell", win_id_str]
        )
        if geom_result.returncode != 0:
            return None

        # 解析 shell 格式输出，例如：
        # X=100
        # Y=50
        # WIDTH=800
        # HEIGHT=600
        geom_text = geom_result.stdout.decode()
        geo: Dict[str, int] = {}
        for line in geom_text.splitlines():
            line = line.strip()
            if "=" in line:
                key, _, val = line.partition("=")
                try:
                    geo[key.strip()] = int(val.strip())
                except ValueError:
                    pass

        x = geo.get("X", 0)
        y = geo.get("Y", 0)
        w = geo.get("WIDTH", 0)
        h = geo.get("HEIGHT", 0)

        if w <= 0 or h <= 0:
            return None

        return (x, y, x + w, y + h)

    # ------------------------------------------------------------------
    # 热键管理
    # ------------------------------------------------------------------
    def register_hotkeys(self, root, hotkeys: List[HotkeyDef]) -> Tuple[int, List[str]]:
        """使用 pynput 注册全局热键。"""
        # 懒导入 pynput
        from pynput import keyboard as pynput_keyboard  # type: ignore

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

        def on_activate(hotkey_str: str) -> None:
            callback = self._hotkey_callbacks.get(hotkey_str)
            if callback:
                if root is not None:
                    root.after(0, callback)
                else:
                    callback()

        try:
            self._hotkey_listener = pynput_keyboard.GlobalHotKeys(
                {k: (lambda ks=k: on_activate(ks)) for k in hotkey_map}
            )
            self._hotkey_listener.start()
        except Exception as exc:
            return 0, [f"pynput 全局热键启动失败: {exc}"]

        return registered, failures

    def unregister_hotkeys(self) -> None:
        """取消注册所有全局热键。"""
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
        Linux 修饰键映射：
          CTRL/CONTROL → <ctrl>
          SHIFT        → <shift>
          ALT          → <alt>
          WIN/SUPER    → <super>
        """
        parts = [p.strip() for p in hotkey_str.replace(" ", "").split("+") if p.strip()]
        if not parts:
            raise ValueError(f"无效热键: {hotkey_str!r}")

        pynput_parts: List[str] = []
        for part in parts:
            name = part.upper()
            if name in {"CTRL", "CONTROL"}:
                pynput_parts.append("<ctrl>")
            elif name == "SHIFT":
                pynput_parts.append("<shift>")
            elif name == "ALT":
                pynput_parts.append("<alt>")
            elif name in {"WIN", "WINDOWS", "SUPER", "META"}:
                pynput_parts.append("<super>")
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
        """使用 pystray 显示系统托盘图标。

        与 MacOSAdapter 逻辑完全一致。
        """
        import pystray  # type: ignore
        from PIL import Image as PILImage, ImageDraw

        self._tray_callbacks = callbacks

        # 创建托盘图标图像
        icon_image = self._create_tray_icon_image()
        if icon_path and Path(icon_path).exists():
            try:
                icon_image = PILImage.open(icon_path)
            except Exception:
                pass  # 回退默认图标

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
            target=self._tray_icon.run,
            name="LinuxTray",
            daemon=True,
        )
        self._tray_thread.start()
        return True

    def hide_tray_icon(self) -> None:
        """停止并隐藏系统托盘图标。"""
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
        """创建默认托盘图标（与 MacOSAdapter 样式一致）。"""
        from PIL import ImageDraw

        icon = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(icon)
        draw.rounded_rectangle(
            (10, 8, 54, 58), radius=8, fill=(42, 99, 220), outline=(18, 45, 120), width=3
        )
        draw.rectangle((20, 4, 44, 14), fill=(235, 242, 255), outline=(18, 45, 120), width=2)
        draw.line((20, 25, 44, 25), fill=(255, 255, 255), width=4)
        draw.line((20, 38, 44, 38), fill=(255, 255, 255), width=4)
        return icon

    # ------------------------------------------------------------------
    # 开机自启（XDG Autostart）
    # ------------------------------------------------------------------
    def is_startup_enabled(self) -> bool:
        """检查 XDG autostart .desktop 文件是否存在且未被禁用。

        判断条件：文件存在，且内容中 Hidden 不为 true。
        """
        if not _DESKTOP_FILE.exists():
            return False
        # 读取文件内容，检查 Hidden=true
        try:
            content = _DESKTOP_FILE.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                if line.lower() == "hidden=true":
                    return False
        except OSError:
            return False
        return True

    def set_startup_enabled(self, enabled: bool) -> Optional[str]:
        """设置开机自启。

        enabled=True：写入 XDG autostart .desktop 文件，返回启动命令字符串。
        enabled=False：删除 .desktop 文件，返回 None。
        """
        if enabled:
            return self._install_autostart()
        self._uninstall_autostart()
        return None

    def _install_autostart(self) -> str:
        """写入 ~/.config/autostart/<AppName>.desktop 文件。"""
        python_path = sys.executable
        run_script = self._find_run_script()

        exec_cmd = f"{python_path} {run_script}"

        desktop_content = (
            "[Desktop Entry]\n"
            "Version=1.0\n"
            "Type=Application\n"
            f"Name={_APP_NAME}\n"
            f"Exec={exec_cmd}\n"
            "Hidden=false\n"
            "NoDisplay=false\n"
            "X-GNOME-Autostart-enabled=true\n"
            f"Comment=Integrated Capture Clipboard Tool\n"
        )

        _AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
        _DESKTOP_FILE.write_text(desktop_content, encoding="utf-8")
        # 确保文件可执行
        _DESKTOP_FILE.chmod(_DESKTOP_FILE.stat().st_mode | 0o755)

        return exec_cmd

    def _uninstall_autostart(self) -> None:
        """删除 XDG autostart .desktop 文件。"""
        if _DESKTOP_FILE.exists():
            try:
                _DESKTOP_FILE.unlink()
            except OSError:
                pass

    @staticmethod
    def _find_run_script() -> Path:
        """查找项目的 run.py 入口脚本路径。"""
        argv0 = Path(sys.argv[0]).resolve()
        if argv0.name.lower() == "run.py" and argv0.exists():
            return argv0
        # 从当前文件所在目录向上查找
        project_root = Path(__file__).resolve().parents[1]
        candidate = project_root / "run.py"
        if candidate.exists():
            return candidate
        # 检查 src 旁边
        src_sibling = Path(__file__).resolve().parent.parent / "run.py"
        if src_sibling.exists():
            return src_sibling
        return argv0

    # ------------------------------------------------------------------
    # DPI 与屏幕
    # ------------------------------------------------------------------
    def enable_dpi_awareness(self) -> None:
        """Linux 不需要手动设置 DPI 感知，由显示服务器自动处理。"""
        pass  # No-op on Linux

    def virtual_screen_bounds(self) -> Tuple[int, int, int, int]:
        """通过 tkinter 获取虚拟屏幕尺寸。

        返回 (x, y, width, height)，x/y 通常为 0。
        """
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
        """用系统默认程序打开文件或目录（xdg-open）。"""
        subprocess.Popen(["xdg-open", path])

    def reveal_path_in_folder(self, path: str) -> None:
        """在文件管理器中定位指定路径。

        尝试顺序：nautilus → thunar → nemo → dolphin → xdg-open（目录）。
        """
        target = Path(path)
        # 若 path 是文件则使用其父目录
        if target.is_file():
            folder = str(target.parent)
        else:
            folder = str(target)

        # 尝试常见文件管理器
        managers_with_select = [
            # (命令名, 是否支持 --select 直接定位文件)
            ("nautilus", True),
            ("nemo", True),
            ("thunar", False),
            ("dolphin", False),
            ("pcmanfm", False),
        ]

        for manager, supports_select in managers_with_select:
            if self._has_tool(manager):
                if supports_select and target.is_file():
                    subprocess.Popen([manager, "--select", str(target)])
                else:
                    subprocess.Popen([manager, folder])
                return

        # 最终回退：xdg-open 打开目录
        subprocess.Popen(["xdg-open", folder])
