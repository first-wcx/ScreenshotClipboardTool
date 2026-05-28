"""跨平台适配器抽象基类与公共数据类型。

所有平台特定操作通过 PlatformAdapter 抽象，子类在各平台模块中实现。
上层代码通过 get_adapter() 获取当前平台的适配器实例。
"""
from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image


# ---------------------------------------------------------------------------
# 剪贴板格式常量（与 Win32 格式 ID 兼容，macOS 适配器内部映射）
# ---------------------------------------------------------------------------
CF_UNICODETEXT = 13
CF_HDROP = 15
CF_DIB = 8
CF_BITMAP = 2


# ---------------------------------------------------------------------------
# 跨平台热键定义
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HotkeyDef:
    """跨平台热键定义。

    key 使用可读字符串格式，如 "Alt+A"、"Ctrl+Shift+M"、"F1"。
    各平台适配器自行将字符串解析为本平台所需的修饰键/键码。
    """

    name: str
    key: str
    callback: Callable[[], None] = field(compare=False)


# ---------------------------------------------------------------------------
# 系统托盘回调集合
# ---------------------------------------------------------------------------
@dataclass
class TrayCallbacks:
    """系统托盘图标的回调函数集合。"""

    on_show: Callable[[], None] = field(default=lambda: None)
    on_settings: Callable[[], None] = field(default=lambda: None)
    on_history: Callable[[], None] = field(default=lambda: None)
    on_exit: Callable[[], None] = field(default=lambda: None)


# ---------------------------------------------------------------------------
# 平台适配器抽象基类
# ---------------------------------------------------------------------------
class PlatformAdapter(ABC):
    """平台适配器抽象基类，定义所有平台相关操作的统一接口。"""

    # ---- 剪贴板：读取 ----

    @abstractmethod
    def clipboard_is_format_available(self, fmt: int) -> bool:
        """检查剪贴板中是否有指定格式的数据。"""
        ...

    @abstractmethod
    def clipboard_get_sequence_number(self) -> int:
        """获取剪贴板序列号（用于检测剪贴板变化）。"""
        ...

    @abstractmethod
    def clipboard_read_text(self) -> Optional[str]:
        """读取剪贴板中的 Unicode 文本，无则返回 None。"""
        ...

    @abstractmethod
    def clipboard_read_file_list(self) -> Optional[List[str]]:
        """读取剪贴板中的文件列表，无则返回 None。"""
        ...

    @abstractmethod
    def clipboard_read_dib_bytes(self) -> Optional[bytes]:
        """读取剪贴板中的 DIB 图片数据，无则返回 None。"""
        ...

    @abstractmethod
    def clipboard_read_all(self) -> Dict[str, object]:
        """在一次剪贴板访问中读取所有格式。

        返回字典格式::

            {
                "text": Optional[str],
                "file_list": Optional[List[str]],
                "dib_bytes": Optional[bytes],
                "has_bitmap": bool,
            }

        在 Windows 上使用单次 OpenClipboard/CloseClipboard 以避免竞态；
        在 macOS 上直接从 NSPasteboard 读取。
        """
        ...

    # ---- 剪贴板：写入 ----

    @abstractmethod
    def clipboard_write_text(self, text: str) -> None:
        """写入 Unicode 文本到剪贴板。"""
        ...

    @abstractmethod
    def clipboard_write_file_list(self, paths: List[str]) -> None:
        """写入文件列表到剪贴板。"""
        ...

    @abstractmethod
    def clipboard_write_dib_bytes(self, dib: bytes) -> None:
        """写入 DIB 图片数据到剪贴板。"""
        ...

    @abstractmethod
    def clipboard_clear(self) -> None:
        """清空系统剪贴板。"""
        ...

    # ---- 图片复制 ----

    @abstractmethod
    def copy_image_to_clipboard(self, image: Image.Image) -> None:
        """将 PIL Image 复制到系统剪贴板。"""
        ...

    # ---- 窗口检测 ----

    @abstractmethod
    def detect_window_at_point(
        self,
        screen_point: Tuple[int, int],
        exclude_ids: Optional[List[int]] = None,
    ) -> Optional[Tuple[int, int, int, int]]:
        """检测指定屏幕坐标处的窗口矩形区域。

        返回 (left, top, right, bottom) 或 None。
        """
        ...

    # ---- 热键管理 ----

    @abstractmethod
    def register_hotkeys(self, root, hotkeys: List[HotkeyDef]) -> Tuple[int, List[str]]:
        """注册全局热键。

        返回 (成功注册数量, 失败的热键名称列表)。
        """
        ...

    @abstractmethod
    def unregister_hotkeys(self) -> None:
        """取消注册所有全局热键。"""
        ...

    # ---- 系统托盘 ----

    @abstractmethod
    def show_tray_icon(
        self,
        root,
        callbacks: TrayCallbacks,
        icon_path: Optional[str] = None,
    ) -> bool:
        """显示系统托盘图标。返回是否成功。"""
        ...

    @abstractmethod
    def hide_tray_icon(self) -> None:
        """隐藏系统托盘图标。"""
        ...

    # ---- 开机自启 ----

    @abstractmethod
    def is_startup_enabled(self) -> bool:
        """检查开机自启是否已启用。"""
        ...

    @abstractmethod
    def set_startup_enabled(self, enabled: bool) -> Optional[str]:
        """设置开机自启。enabled=True 时返回启动命令字符串，否则返回 None。"""
        ...

    # ---- DPI 与屏幕 ----

    @abstractmethod
    def enable_dpi_awareness(self) -> None:
        """启用 DPI 感知（仅 Windows 需要实际操作）。"""
        ...

    @abstractmethod
    def virtual_screen_bounds(self) -> Tuple[int, int, int, int]:
        """获取虚拟屏幕边界 (x, y, width, height)。"""
        ...

    # ---- 文件操作 ----

    @abstractmethod
    def open_file(self, path: str) -> None:
        """用系统默认程序打开文件或目录。"""
        ...

    @abstractmethod
    def reveal_path_in_folder(self, path: str) -> None:
        """在文件管理器中定位并选中指定路径。"""
        ...


# ---------------------------------------------------------------------------
# 适配器工厂（懒加载单例）
# ---------------------------------------------------------------------------
_adapter_instance: Optional[PlatformAdapter] = None


def get_adapter() -> PlatformAdapter:
    """获取当前平台的适配器实例（懒加载单例）。"""
    global _adapter_instance
    if _adapter_instance is None:
        if sys.platform == "win32":
            from windows_adapter import WindowsAdapter
            _adapter_instance = WindowsAdapter()
        elif sys.platform == "darwin":
            from macos_adapter import MacOSAdapter
            _adapter_instance = MacOSAdapter()
        else:
            # Linux 及其他类 Unix 系统
            from linux_adapter import LinuxAdapter
            _adapter_instance = LinuxAdapter()
    return _adapter_instance
