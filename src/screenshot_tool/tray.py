from __future__ import annotations

import queue
import sys
import threading
from typing import Callable, Optional

from platform_adapter import TrayCallbacks, get_adapter


class TrayIconManager:
    """系统托盘图标管理器（兼容层，委托给平台适配器）。"""

    def __init__(
        self,
        root,
        on_show: Callable[[], None],
        on_settings: Callable[[], None],
        on_history: Callable[[], None],
        on_exit: Callable[[], None],
        icon_path: Optional[str] = None,
    ) -> None:
        self.root = root
        self.on_show = on_show
        self.on_settings = on_settings
        self.on_history = on_history
        self.on_exit = on_exit
        self.icon_path = icon_path
        self._callbacks = TrayCallbacks(
            on_show=on_show,
            on_settings=on_settings,
            on_history=on_history,
            on_exit=on_exit,
        )

    def show(self) -> bool:
        """显示系统托盘图标，委托给平台适配器。"""
        return get_adapter().show_tray_icon(self.root, self._callbacks, self.icon_path)

    def hide(self) -> None:
        """隐藏系统托盘图标。"""
        get_adapter().hide_tray_icon()

    def stop(self) -> None:
        """停止并隐藏托盘图标。"""
        self.hide()
