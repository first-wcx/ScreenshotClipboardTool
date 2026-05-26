"""Windows 平台适配器。

将原散布在各模块中的 Win32 调用集中到此类，
上层通过 PlatformAdapter 抽象接口调用，无需直接接触 ctypes / winreg。
"""
from __future__ import annotations

import ctypes
import itertools
import os
import queue
import shlex
import struct
import subprocess
import sys
import threading
from ctypes import wintypes
from io import BytesIO
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

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
# Win32 常量
# ---------------------------------------------------------------------------
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040

WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20
WM_APP_CLOSE = WM_USER + 21
WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_LBUTTONDBLCLK = 0x0203
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_NULL = 0x0000

NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100

MENU_SHOW = 1001
MENU_SETTINGS = 1002
MENU_HISTORY = 1003
MENU_EXIT = 1004

DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
GW_HWNDNEXT = 2

POLL_INTERVAL_HOTKEY_MS = 120
POLL_INTERVAL_TRAY_MS = 250

RUN_VALUE_NAME = "ScreenshotTool"
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

# ---------------------------------------------------------------------------
# Win32 DLL 加载与函数签名
# ---------------------------------------------------------------------------
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
except OSError:
    dwmapi = None  # type: ignore[assignment]

# --- kernel32 ---
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.restype = wintypes.HGLOBAL
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t

# --- user32 ---
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT,
]
user32.PeekMessageW.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = wintypes.LPARAM
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = wintypes.BOOL
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.GetClipboardSequenceNumber.argtypes = []
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetTopWindow.argtypes = [wintypes.HWND]
user32.GetTopWindow.restype = wintypes.HWND
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.EnumChildWindows.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.LPARAM]
user32.EnumChildWindows.restype = wintypes.BOOL
user32.RegisterClassW.argtypes = [ctypes.c_void_p]
user32.RegisterClassW.restype = wintypes.ATOM
user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
user32.UnregisterClassW.restype = wintypes.BOOL
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.LoadIconW.restype = wintypes.HANDLE
user32.LoadImageW.argtypes = [
    wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.LoadImageW.restype = wintypes.HANDLE
user32.DestroyIcon.argtypes = [wintypes.HANDLE]
user32.DestroyIcon.restype = wintypes.BOOL
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL
user32.TrackPopupMenu.argtypes = [
    wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, ctypes.c_void_p,
]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.CreatePopupMenu.argtypes = []
user32.CreatePopupMenu.restype = wintypes.HANDLE
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.AppendMenuW.restype = wintypes.BOOL
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.DestroyMenu.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostQuitMessage.restype = None

# --- shell32 ---
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL
shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
shell32.DragQueryFileW.restype = wintypes.UINT

# --- dwmapi ---
if dwmapi is not None:
    dwmapi.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

# ---------------------------------------------------------------------------
# Win32 结构体
# ---------------------------------------------------------------------------
HICON = getattr(wintypes, "HICON", wintypes.HANDLE)
HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)
HBRUSH = getattr(wintypes, "HBRUSH", wintypes.HANDLE)
HMENU = getattr(wintypes, "HMENU", wintypes.HANDLE)
UINT_PTR = ctypes.c_size_t

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long,
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
)
ENUM_CHILD_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", HICON),
    ]


class DROPFILES(ctypes.Structure):
    _fields_ = [
        ("pFiles", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("fNC", wintypes.BOOL),
        ("fWide", wintypes.BOOL),
    ]


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def _parse_hotkey_string(value: str) -> Tuple[int, int]:
    """将 "Alt+A" 格式的字符串解析为 (modifiers, vk)。"""
    parts = [p.strip() for p in value.replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise ValueError(f"无效热键字符串: {value!r}")
    key = parts[-1].upper()
    modifiers = 0
    for part in parts[:-1]:
        name = part.upper()
        if name in {"CTRL", "CONTROL"}:
            modifiers |= MOD_CONTROL
        elif name == "SHIFT":
            modifiers |= MOD_SHIFT
        elif name == "ALT":
            modifiers |= MOD_ALT
        elif name in {"WIN", "WINDOWS"}:
            modifiers |= MOD_WIN
        else:
            raise ValueError(f"不支持的修饰键: {part}")
    if len(key) == 1 and key.isalnum():
        vk = ord(key)
    elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError(f"不支持的按键: {key}")
    return modifiers, vk


def _hotkey_def_to_win32(hd: HotkeyDef) -> Tuple[int, int]:
    """将 HotkeyDef 解析为 Win32 (modifiers, vk)。"""
    return _parse_hotkey_string(hd.key)


def _allocate_global_bytes(data: bytes, error_message: str) -> wintypes.HGLOBAL:
    """在全局堆上分配内存并复制数据。"""
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(data))
    if not handle:
        raise OSError(error_message)
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        raise OSError(error_message)
    try:
        ctypes.memmove(pointer, data, len(data))
    finally:
        kernel32.GlobalUnlock(handle)
    return handle


# ---------------------------------------------------------------------------
# WindowsAdapter
# ---------------------------------------------------------------------------
class WindowsAdapter(PlatformAdapter):
    """Windows 平台适配器，封装所有 Win32 特定操作。"""

    def __init__(self) -> None:
        # 热键管理内部状态
        self._hk_root = None
        self._hk_next_id = itertools.count(1000)
        self._hk_callbacks: Dict[int, Callable[[], None]] = {}
        self._hk_names: Dict[int, str] = {}
        self._hk_events: queue.Queue[int] = queue.Queue()
        self._hk_ready: queue.Queue[Tuple[int, List[str], int]] = queue.Queue()
        self._hk_thread: Optional[threading.Thread] = None
        self._hk_thread_id: int = 0
        self._hk_polling: bool = False

        # 托盘图标内部状态
        self._tray_root = None
        self._tray_callbacks: Optional[TrayCallbacks] = None
        self._tray_events: queue.Queue[str] = queue.Queue()
        self._tray_ready: queue.Queue[int] = queue.Queue()
        self._tray_thread: Optional[threading.Thread] = None
        self._tray_thread_id: int = 0
        self._tray_polling: bool = False

    # ------------------------------------------------------------------
    # 剪贴板：读取
    # ------------------------------------------------------------------
    def clipboard_is_format_available(self, fmt: int) -> bool:
        return bool(user32.IsClipboardFormatAvailable(fmt))

    def clipboard_get_sequence_number(self) -> int:
        return int(user32.GetClipboardSequenceNumber())

    def clipboard_read_text(self) -> Optional[str]:
        if not self.clipboard_is_format_available(CF_UNICODETEXT):
            return None
        if not user32.OpenClipboard(None):
            return None
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return None
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                return None
            try:
                return ctypes.wstring_at(pointer)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    def clipboard_read_file_list(self) -> Optional[List[str]]:
        if not self.clipboard_is_format_available(CF_HDROP):
            return None
        if not user32.OpenClipboard(None):
            return None
        try:
            handle = user32.GetClipboardData(CF_HDROP)
            if not handle:
                return None
            count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
            paths: List[str] = []
            for index in range(count):
                length = shell32.DragQueryFileW(handle, index, None, 0)
                buffer = ctypes.create_unicode_buffer(length + 1)
                shell32.DragQueryFileW(handle, index, buffer, length + 1)
                paths.append(buffer.value)
            return paths
        finally:
            user32.CloseClipboard()

    def clipboard_read_dib_bytes(self) -> Optional[bytes]:
        if not self.clipboard_is_format_available(CF_DIB):
            return None
        if not user32.OpenClipboard(None):
            return None
        try:
            handle = user32.GetClipboardData(CF_DIB)
            if not handle:
                return None
            size = int(kernel32.GlobalSize(handle))
            if size <= 0:
                return None
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                return None
            try:
                return ctypes.string_at(pointer, size)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    def clipboard_read_all(self) -> Dict[str, object]:
        """在单次 OpenClipboard/CloseClipboard 中读取所有格式。"""
        result: Dict[str, object] = {
            "text": None,
            "file_list": None,
            "dib_bytes": None,
            "has_bitmap": False,
        }
        if not user32.OpenClipboard(None):
            return result
        try:
            # 文件列表
            if user32.IsClipboardFormatAvailable(CF_HDROP):
                handle = user32.GetClipboardData(CF_HDROP)
                if handle:
                    count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
                    paths: List[str] = []
                    for index in range(count):
                        length = shell32.DragQueryFileW(handle, index, None, 0)
                        buffer = ctypes.create_unicode_buffer(length + 1)
                        shell32.DragQueryFileW(handle, index, buffer, length + 1)
                        paths.append(buffer.value)
                    result["file_list"] = paths

            # 文本
            if result["file_list"] is None and user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                handle = user32.GetClipboardData(CF_UNICODETEXT)
                if handle:
                    pointer = kernel32.GlobalLock(handle)
                    if pointer:
                        try:
                            result["text"] = ctypes.wstring_at(pointer)
                        finally:
                            kernel32.GlobalUnlock(handle)

            # DIB 图片
            if result["file_list"] is None and result["text"] is None:
                if user32.IsClipboardFormatAvailable(CF_DIB):
                    handle = user32.GetClipboardData(CF_DIB)
                    if handle:
                        size = int(kernel32.GlobalSize(handle))
                        if size > 0:
                            pointer = kernel32.GlobalLock(handle)
                            if pointer:
                                try:
                                    result["dib_bytes"] = ctypes.string_at(pointer, size)
                                finally:
                                    kernel32.GlobalUnlock(handle)
                if user32.IsClipboardFormatAvailable(CF_BITMAP):
                    result["has_bitmap"] = True
        finally:
            user32.CloseClipboard()
        return result

    # ------------------------------------------------------------------
    # 剪贴板：写入
    # ------------------------------------------------------------------
    def clipboard_write_text(self, text: str) -> None:
        data = (text + "\0").encode("utf-16-le")
        handle = _allocate_global_bytes(data, "无法写入剪贴板文本。")
        if not user32.OpenClipboard(None):
            kernel32.GlobalFree(handle)
            raise OSError("无法打开剪贴板。")
        try:
            if not user32.EmptyClipboard():
                kernel32.GlobalFree(handle)
                raise OSError("无法清空剪贴板。")
            if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                kernel32.GlobalFree(handle)
                raise OSError("无法写入剪贴板文本。")
            # 成功后系统拥有 handle，不要释放
        finally:
            user32.CloseClipboard()

    def clipboard_write_file_list(self, paths: List[str]) -> None:
        if not paths:
            raise OSError("没有可写入剪贴板的文件路径。")
        file_names = "\0".join(paths) + "\0\0"
        file_data = file_names.encode("utf-16-le")
        dropfiles = DROPFILES()
        dropfiles.pFiles = ctypes.sizeof(DROPFILES)
        dropfiles.fWide = 1
        handle = _allocate_global_bytes(bytes(dropfiles) + file_data, "无法写入剪贴板文件列表。")
        if not user32.OpenClipboard(None):
            kernel32.GlobalFree(handle)
            raise OSError("无法打开剪贴板。")
        try:
            if not user32.EmptyClipboard():
                kernel32.GlobalFree(handle)
                raise OSError("无法清空剪贴板。")
            if not user32.SetClipboardData(CF_HDROP, handle):
                kernel32.GlobalFree(handle)
                raise OSError("无法写入剪贴板文件列表。")
        finally:
            user32.CloseClipboard()

    def clipboard_write_dib_bytes(self, dib: bytes) -> None:
        if not dib:
            raise OSError("没有可写入剪贴板的图片数据。")
        handle = _allocate_global_bytes(dib, "无法写入剪贴板图片。")
        if not user32.OpenClipboard(None):
            kernel32.GlobalFree(handle)
            raise OSError("无法打开剪贴板。")
        try:
            if not user32.EmptyClipboard():
                kernel32.GlobalFree(handle)
                raise OSError("无法清空剪贴板。")
            if not user32.SetClipboardData(CF_DIB, handle):
                kernel32.GlobalFree(handle)
                raise OSError("无法写入剪贴板图片。")
        finally:
            user32.CloseClipboard()

    def clipboard_clear(self) -> None:
        if not user32.OpenClipboard(None):
            raise OSError("无法打开剪贴板。")
        try:
            if not user32.EmptyClipboard():
                raise OSError("无法清空剪贴板。")
        finally:
            user32.CloseClipboard()

    # ------------------------------------------------------------------
    # 图片复制到剪贴板
    # ------------------------------------------------------------------
    def copy_image_to_clipboard(self, image: Image.Image) -> None:
        output = BytesIO()
        image.convert("RGB").save(output, "BMP")
        dib = output.getvalue()[14:]
        output.close()

        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
        if not handle:
            raise OSError("GlobalAlloc failed while copying image to clipboard.")
        locked = kernel32.GlobalLock(handle)
        if not locked:
            kernel32.GlobalFree(handle)
            raise OSError("GlobalLock failed while copying image to clipboard.")
        ctypes.memmove(locked, dib, len(dib))
        kernel32.GlobalUnlock(handle)

        if not user32.OpenClipboard(None):
            kernel32.GlobalFree(handle)
            raise OSError("OpenClipboard failed. Another application may be using it.")
        try:
            if not user32.EmptyClipboard():
                raise OSError("EmptyClipboard failed.")
            if not user32.SetClipboardData(CF_DIB, handle):
                raise OSError("SetClipboardData failed.")
            # 成功后系统拥有 handle
        finally:
            user32.CloseClipboard()

    # ------------------------------------------------------------------
    # 窗口检测
    # ------------------------------------------------------------------
    def detect_window_at_point(
        self,
        screen_point: Tuple[int, int],
        exclude_ids: Optional[List[int]] = None,
    ) -> Optional[Tuple[int, int, int, int]]:
        exclude = {int(hwnd) for hwnd in (exclude_ids or []) if hwnd}
        top = self._top_level_window_at_point(screen_point, exclude)
        if not top:
            return None
        child_rect = self._best_child_rect_at_point(top, screen_point, exclude, min_size=18)
        if child_rect:
            return child_rect
        return self._window_rect(top)

    def _top_level_window_at_point(
        self, point: Tuple[int, int], exclude: set,
    ) -> Optional[int]:
        hwnd = user32.GetTopWindow(None)
        while hwnd:
            if hwnd not in exclude and self._is_candidate_window(hwnd):
                rect = self._window_rect(hwnd)
                if rect and self._contains(rect, point):
                    return hwnd
            hwnd = user32.GetWindow(hwnd, GW_HWNDNEXT)
        return None

    def _best_child_rect_at_point(
        self, parent_hwnd: int, point: Tuple[int, int], exclude: set, min_size: int,
    ) -> Optional[Tuple[int, int, int, int]]:
        matches: List[Tuple[int, int, int, int]] = []

        def enum_proc(hwnd, _lparam):
            if hwnd in exclude or not user32.IsWindowVisible(hwnd):
                return True
            rect = self._window_rect(hwnd)
            if not rect or not self._contains(rect, point):
                return True
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            if width >= min_size and height >= min_size:
                matches.append(rect)
            return True

        callback = ENUM_CHILD_PROC(enum_proc)
        user32.EnumChildWindows(parent_hwnd, callback, 0)
        if not matches:
            return None
        parent_rect = self._window_rect(parent_hwnd)
        if parent_rect:
            parent_area = self._area(parent_rect)
            matches = [rect for rect in matches if self._area(rect) < parent_area * 0.98]
        if not matches:
            return None
        return min(matches, key=self._area)

    def _is_candidate_window(self, hwnd: int) -> bool:
        if self._window_process_id(hwnd) == os.getpid():
            return False
        if not user32.IsWindowVisible(hwnd):
            return False
        if self._is_cloaked(hwnd):
            return False
        rect = self._window_rect(hwnd)
        if not rect:
            return False
        width = rect[2] - rect[0]
        height = rect[3] - rect[1]
        return width >= 24 and height >= 24

    def _window_rect(self, hwnd: int) -> Optional[Tuple[int, int, int, int]]:
        rect = wintypes.RECT()
        if dwmapi is not None:
            try:
                ok = dwmapi.DwmGetWindowAttribute(
                    wintypes.HWND(hwnd),
                    DWMWA_EXTENDED_FRAME_BOUNDS,
                    ctypes.byref(rect),
                    ctypes.sizeof(rect),
                )
                if ok == 0:
                    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
            except OSError:
                pass
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)

    @staticmethod
    def _window_process_id(hwnd: int) -> int:
        process_id = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        return int(process_id.value)

    @staticmethod
    def _is_cloaked(hwnd: int) -> bool:
        if dwmapi is None:
            return False
        cloaked = ctypes.c_int(0)
        try:
            ok = dwmapi.DwmGetWindowAttribute(
                wintypes.HWND(hwnd),
                DWMWA_CLOAKED,
                ctypes.byref(cloaked),
                ctypes.sizeof(cloaked),
            )
            return ok == 0 and bool(cloaked.value)
        except OSError:
            return False

    @staticmethod
    def _contains(rect: Tuple[int, int, int, int], point: Tuple[int, int]) -> bool:
        x, y = point
        return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]

    @staticmethod
    def _area(rect: Tuple[int, int, int, int]) -> int:
        return max(0, rect[2] - rect[0]) * max(0, rect[3] - rect[1])

    # ------------------------------------------------------------------
    # 热键管理
    # ------------------------------------------------------------------
    def register_hotkeys(self, root, hotkeys: List[HotkeyDef]) -> Tuple[int, List[str]]:
        """注册全局热键，内部使用 Win32 RegisterHotKey。"""
        self.unregister_hotkeys()
        self._hk_root = root
        entries: List[Tuple[int, int, int, Callable[[], None], str]] = []
        self._hk_callbacks.clear()
        self._hk_names.clear()
        for hd in hotkeys:
            try:
                modifiers, vk = _hotkey_def_to_win32(hd)
            except ValueError:
                continue
            hotkey_id = next(self._hk_next_id)
            entries.append((hotkey_id, modifiers, vk, hd.callback, hd.name))
            self._hk_callbacks[hotkey_id] = hd.callback
            self._hk_names[hotkey_id] = hd.name

        self._hk_thread = threading.Thread(
            target=self._hk_message_loop, args=(entries,), daemon=True,
        )
        self._hk_thread.start()
        try:
            registered, failures, thread_id = self._hk_ready.get(timeout=2.0)
        except queue.Empty:
            self._hk_callbacks.clear()
            self._hk_names.clear()
            return 0, ["Global hotkey message thread did not start."]

        self._hk_thread_id = thread_id
        if registered and not self._hk_polling:
            self._hk_polling = True
            root.after(POLL_INTERVAL_HOTKEY_MS, self._hk_poll_events)
        return registered, failures

    def unregister_hotkeys(self) -> None:
        if self._hk_thread_id:
            user32.PostThreadMessageW(self._hk_thread_id, WM_QUIT, 0, 0)
        if self._hk_thread and self._hk_thread.is_alive():
            self._hk_thread.join(timeout=1.0)
        self._hk_thread = None
        self._hk_thread_id = 0
        self._hk_callbacks.clear()
        self._hk_names.clear()
        self._drain_queue(self._hk_events)
        self._drain_queue(self._hk_ready)

    def _hk_message_loop(self, entries: list) -> None:
        thread_id = int(kernel32.GetCurrentThreadId())
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)

        registered_ids: List[int] = []
        failures: List[str] = []
        for hotkey_id, modifiers, vk, _callback, name in entries:
            ok = user32.RegisterHotKey(None, hotkey_id, modifiers, vk)
            if ok:
                registered_ids.append(hotkey_id)
            else:
                failures.append(name)

        self._hk_ready.put((len(registered_ids), failures, thread_id))
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    self._hk_events.put(int(msg.wParam))
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            for hotkey_id in registered_ids:
                user32.UnregisterHotKey(None, hotkey_id)

    def _hk_poll_events(self) -> None:
        try:
            while True:
                hotkey_id = self._hk_events.get_nowait()
                callback = self._hk_callbacks.get(hotkey_id)
                if callback:
                    callback()
        except queue.Empty:
            pass
        if self._hk_thread and self._hk_thread.is_alive() and self._hk_root:
            self._hk_root.after(POLL_INTERVAL_HOTKEY_MS, self._hk_poll_events)
        else:
            self._hk_polling = False

    # ------------------------------------------------------------------
    # 系统托盘
    # ------------------------------------------------------------------
    def show_tray_icon(
        self,
        root,
        callbacks: TrayCallbacks,
        icon_path: Optional[str] = None,
    ) -> bool:
        self.hide_tray_icon()
        self._tray_root = root
        self._tray_callbacks = callbacks
        self._tray_thread = threading.Thread(
            target=self._tray_message_loop, args=(icon_path,), daemon=True,
        )
        self._tray_thread.start()
        try:
            self._tray_thread_id = self._tray_ready.get(timeout=2.0)
        except queue.Empty:
            self._tray_thread = None
            self._tray_thread_id = 0
            return False
        if not self._tray_thread_id:
            self._tray_thread = None
            return False
        if not self._tray_polling:
            self._tray_polling = True
            root.after(POLL_INTERVAL_TRAY_MS, self._tray_poll_events)
        return True

    def hide_tray_icon(self) -> None:
        if self._tray_thread_id:
            user32.PostThreadMessageW(self._tray_thread_id, WM_APP_CLOSE, 0, 0)
        if self._tray_thread and self._tray_thread.is_alive():
            self._tray_thread.join(timeout=1.0)
        self._tray_thread = None
        self._tray_thread_id = 0

    def _tray_message_loop(self, icon_path: Optional[str]) -> None:
        thread_id = int(kernel32.GetCurrentThreadId())
        wndproc = self._tray_make_wndproc()
        class_name = f"ScreenshotToolTray{thread_id}"

        wndclass = WNDCLASS()
        wndclass.lpfnWndProc = wndproc
        wndclass.lpszClassName = class_name
        wndclass.hInstance = kernel32.GetModuleHandleW(None)
        atom = user32.RegisterClassW(ctypes.byref(wndclass))
        if not atom:
            self._tray_ready.put(0)
            return

        hwnd = user32.CreateWindowExW(
            0, class_name, class_name, 0, 0, 0, 0, 0,
            None, None, wndclass.hInstance, None,
        )
        if not hwnd:
            self._tray_ready.put(0)
            return

        icon, owns_icon = self._tray_load_icon(icon_path)
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = icon
        nid.szTip = "截图工具 - 双击显示，右键菜单"
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            if icon and owns_icon:
                user32.DestroyIcon(icon)
            user32.DestroyWindow(hwnd)
            user32.UnregisterClassW(class_name, wndclass.hInstance)
            self._tray_ready.put(0)
            return
        self._tray_ready.put(thread_id)

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_APP_CLOSE:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        if icon and owns_icon:
            user32.DestroyIcon(icon)
        user32.DestroyWindow(hwnd)
        user32.UnregisterClassW(class_name, wndclass.hInstance)

    def _tray_make_wndproc(self):
        events = self._tray_events

        def wndproc(hwnd, message, wparam, lparam):
            if message == WM_TRAYICON:
                if int(lparam) in {WM_LBUTTONDBLCLK, WM_LBUTTONUP}:
                    events.put("show")
                    return 0
                if int(lparam) == WM_RBUTTONUP:
                    command = self._tray_show_menu(hwnd)
                    if command == MENU_SHOW:
                        events.put("show")
                    elif command == MENU_SETTINGS:
                        events.put("settings")
                    elif command == MENU_HISTORY:
                        events.put("history")
                    elif command == MENU_EXIT:
                        events.put("exit")
                    return 0
            if message == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        return WNDPROC(wndproc)

    @staticmethod
    def _tray_show_menu(hwnd) -> int:
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, 0, MENU_SHOW, "显示主窗口")
        user32.AppendMenuW(menu, 0, MENU_SETTINGS, "设置")
        user32.AppendMenuW(menu, 0, MENU_HISTORY, "历史截图")
        user32.AppendMenuW(menu, 0, MENU_EXIT, "退出")
        user32.SetForegroundWindow(hwnd)
        command = user32.TrackPopupMenu(
            menu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
            point.x, point.y, 0, hwnd, None,
        )
        user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        return int(command)

    @staticmethod
    def _tray_load_icon(icon_path: Optional[str]) -> Tuple[int, bool]:
        if icon_path:
            icon = user32.LoadImageW(
                None, icon_path, IMAGE_ICON, 0, 0,
                LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )
            if icon:
                return icon, True
        return user32.LoadIconW(None, IDI_APPLICATION), False

    def _tray_poll_events(self) -> None:
        if self._tray_callbacks is None:
            self._tray_polling = False
            return
        try:
            while True:
                event = self._tray_events.get_nowait()
                if event == "show" and self._tray_callbacks.on_show:
                    self._tray_callbacks.on_show()
                elif event == "settings" and self._tray_callbacks.on_settings:
                    self._tray_callbacks.on_settings()
                elif event == "history" and self._tray_callbacks.on_history:
                    self._tray_callbacks.on_history()
                elif event == "exit" and self._tray_callbacks.on_exit:
                    self._tray_callbacks.on_exit()
        except queue.Empty:
            pass
        if self._tray_thread and self._tray_thread.is_alive() and self._tray_root:
            self._tray_root.after(POLL_INTERVAL_TRAY_MS, self._tray_poll_events)
        else:
            self._tray_polling = False

    # ------------------------------------------------------------------
    # 开机自启
    # ------------------------------------------------------------------
    def is_startup_enabled(self) -> bool:
        return self._read_run_value() is not None

    def set_startup_enabled(self, enabled: bool) -> Optional[str]:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                command = self._current_startup_command()
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, command)
                return command
            try:
                winreg.DeleteValue(key, RUN_VALUE_NAME)
            except FileNotFoundError:
                pass
            return None

    def _read_run_value(self) -> Optional[str]:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
                value, _value_type = winreg.QueryValueEx(key, RUN_VALUE_NAME)
                return str(value)
        except (FileNotFoundError, OSError):
            return None

    @staticmethod
    def _current_startup_command() -> str:
        if getattr(sys, "frozen", False):
            return f'"{Path(sys.executable).resolve()}"'
        script = WindowsAdapter._source_run_script()
        executable = Path(sys.executable).resolve()
        if os.name == "nt" and executable.name.lower() == "python.exe":
            pythonw = executable.with_name("pythonw.exe")
            if pythonw.exists():
                executable = pythonw
        return f'"{executable}" "{script}"'

    @staticmethod
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

    # ------------------------------------------------------------------
    # DPI 与屏幕
    # ------------------------------------------------------------------
    def enable_dpi_awareness(self) -> None:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    def virtual_screen_bounds(self) -> Tuple[int, int, int, int]:
        x = user32.GetSystemMetrics(76)
        y = user32.GetSystemMetrics(77)
        width = user32.GetSystemMetrics(78)
        height = user32.GetSystemMetrics(79)
        return x, y, width, height

    # ------------------------------------------------------------------
    # 文件操作
    # ------------------------------------------------------------------
    def open_file(self, path: str) -> None:
        os.startfile(path)

    def reveal_path_in_folder(self, path: str) -> None:
        subprocess.Popen(["explorer.exe", f"/select,{Path(path).resolve()}"])

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _drain_queue(target: queue.Queue) -> bool:
        try:
            target.get_nowait()
            return False
        except queue.Empty:
            return True
