from __future__ import annotations

import ctypes
import os
import sys
from typing import List, Optional, Tuple


BBox = Tuple[int, int, int, int]


if sys.platform == "win32":
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    try:
        dwmapi = ctypes.windll.dwmapi
    except OSError:
        dwmapi = None

    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    DWMWA_CLOAKED = 14
    GW_HWNDNEXT = 2
    ENUM_CHILD_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    user32.GetTopWindow.argtypes = [wintypes.HWND]
    user32.GetTopWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.EnumChildWindows.argtypes = [wintypes.HWND, ENUM_CHILD_PROC, wintypes.LPARAM]
    user32.EnumChildWindows.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    if dwmapi is not None:
        dwmapi.DwmGetWindowAttribute.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long


def detect_window_rect_at_point(
    screen_point: Tuple[int, int],
    exclude_hwnds: Optional[List[int]] = None,
    min_size: int = 18,
) -> Optional[BBox]:
    if sys.platform != "win32":
        return None

    exclude = {int(hwnd) for hwnd in (exclude_hwnds or []) if hwnd}
    top = _top_level_window_at_point(screen_point, exclude)
    if not top:
        return None

    child_rect = _best_child_rect_at_point(top, screen_point, exclude, min_size)
    if child_rect:
        return child_rect
    return _window_rect(top)


def _top_level_window_at_point(point: Tuple[int, int], exclude: set) -> Optional[int]:
    hwnd = user32.GetTopWindow(None)
    while hwnd:
        if hwnd not in exclude and _is_candidate_window(hwnd):
            rect = _window_rect(hwnd)
            if rect and _contains(rect, point):
                return hwnd
        hwnd = user32.GetWindow(hwnd, GW_HWNDNEXT)
    return None


def _best_child_rect_at_point(
    parent_hwnd: int,
    point: Tuple[int, int],
    exclude: set,
    min_size: int,
) -> Optional[BBox]:
    matches: List[BBox] = []

    def enum_proc(hwnd, _lparam):
        if hwnd in exclude or not user32.IsWindowVisible(hwnd):
            return True
        rect = _window_rect(hwnd)
        if not rect or not _contains(rect, point):
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

    parent_rect = _window_rect(parent_hwnd)
    if parent_rect:
        parent_area = _area(parent_rect)
        matches = [rect for rect in matches if _area(rect) < parent_area * 0.98]
    if not matches:
        return None
    return min(matches, key=_area)


def _is_candidate_window(hwnd: int) -> bool:
    if _window_process_id(hwnd) == os.getpid():
        return False
    if not user32.IsWindowVisible(hwnd):
        return False
    if _is_cloaked(hwnd):
        return False
    rect = _window_rect(hwnd)
    if not rect:
        return False
    width = rect[2] - rect[0]
    height = rect[3] - rect[1]
    return width >= 24 and height >= 24


def _window_rect(hwnd: int) -> Optional[BBox]:
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


def _window_process_id(hwnd: int) -> int:
    process_id = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    return int(process_id.value)


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


def _contains(rect: BBox, point: Tuple[int, int]) -> bool:
    x, y = point
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def _area(rect: BBox) -> int:
    return max(0, rect[2] - rect[0]) * max(0, rect[3] - rect[1])
