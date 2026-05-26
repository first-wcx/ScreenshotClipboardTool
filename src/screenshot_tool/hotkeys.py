from __future__ import annotations

import itertools
import queue
import sys
import threading
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple, Union

from platform_adapter import HotkeyDef, get_adapter

# ------------------------------------------------------------------
# Hotkey 数据类（保留原签名以兼容旧代码）
# ------------------------------------------------------------------
# Win32 修饰键常量（保留用于向后兼容）
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008


@dataclass(frozen=True)
class Hotkey:
    """Win32 风格的热键定义（保留用于向后兼容）。

    新代码应使用 platform_adapter.HotkeyDef 代替。
    """

    name: str
    modifiers: int
    vk: int
    callback: Callable[[], None]


# ------------------------------------------------------------------
# GlobalHotkeyManager（保留原签名，内部委托给平台适配器）
# ------------------------------------------------------------------
class GlobalHotkeyManager:
    """全局热键管理器（兼容层，委托给平台适配器）。"""

    def __init__(self, root) -> None:
        self.root = root
        self._next_id = itertools.count(1000)
        self._callbacks: Dict[int, Callable[[], None]] = {}
        self._names: Dict[int, str] = {}

    def register_many(self, hotkeys: Iterable[Union[Hotkey, HotkeyDef]]) -> Tuple[int, List[str]]:
        """注册全局热键，内部委托给平台适配器。

        接受 Win32 风格的 Hotkey 或跨平台的 HotkeyDef。
        """
        defs: List[HotkeyDef] = []
        self._callbacks.clear()
        self._names.clear()
        for hotkey in hotkeys:
            if isinstance(hotkey, HotkeyDef):
                defs.append(hotkey)
            elif isinstance(hotkey, Hotkey):
                key_str = _hotkey_to_string(hotkey.modifiers, hotkey.vk)
                hd = HotkeyDef(name=hotkey.name, key=key_str, callback=hotkey.callback)
                defs.append(hd)
            else:
                raise TypeError(f"不支持的热键类型: {type(hotkey)}")

        return get_adapter().register_hotkeys(self.root, defs)

    def unregister_all(self) -> None:
        """取消注册所有全局热键。"""
        get_adapter().unregister_hotkeys()
        self._callbacks.clear()
        self._names.clear()


# ------------------------------------------------------------------
# Hotkey → 字符串转换辅助
# ------------------------------------------------------------------
_MOD_NAMES = {
    MOD_ALT: "Alt",
    MOD_CONTROL: "Ctrl",
    MOD_SHIFT: "Shift",
    MOD_WIN: "Win",
}

_VK_MAP = {
    0x70: "F1", 0x71: "F2", 0x72: "F3", 0x73: "F4",
    0x74: "F5", 0x75: "F6", 0x76: "F7", 0x77: "F8",
    0x78: "F9", 0x79: "F10", 0x7A: "F11", 0x7B: "F12",
}


def _hotkey_to_string(modifiers: int, vk: int) -> str:
    """将 Win32 (modifiers, vk) 转换为 "Alt+A" 格式的字符串。"""
    parts: List[str] = []
    for mod_flag, mod_name in sorted(_MOD_NAMES.items(), key=lambda x: x[0]):
        if modifiers & mod_flag:
            parts.append(mod_name)

    # 虚拟键码转字符串
    if 0x30 <= vk <= 0x39:  # 0-9
        parts.append(chr(vk))
    elif 0x41 <= vk <= 0x5A:  # A-Z
        parts.append(chr(vk))
    elif vk in _VK_MAP:
        parts.append(_VK_MAP[vk])
    else:
        parts.append(chr(vk))

    return "+".join(parts)
