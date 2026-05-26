from __future__ import annotations

import ctypes
import itertools
import queue
import sys
import threading
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple


if sys.platform == "win32":
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    user32.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = wintypes.LPARAM
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
POLL_INTERVAL_MS = 120


@dataclass(frozen=True)
class Hotkey:
    name: str
    modifiers: int
    vk: int
    callback: Callable[[], None]


class GlobalHotkeyManager:
    """Register hotkeys on a private message thread.

    Avoid subclassing Tk's HWND. Calling Python through a Win32 window-proc
    callback while Tk owns the message loop can crash the interpreter on some
    Python/Tk builds.
    """

    def __init__(self, root) -> None:
        self.root = root
        self._next_id = itertools.count(1000)
        self._callbacks: Dict[int, Callable[[], None]] = {}
        self._names: Dict[int, str] = {}
        self._events: "queue.Queue[int]" = queue.Queue()
        self._ready: "queue.Queue[Tuple[int, List[str], int]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._thread_id = 0
        self._polling = False

    def register_many(self, hotkeys: Iterable[Hotkey]) -> Tuple[int, List[str]]:
        self.unregister_all()
        if sys.platform != "win32":
            return 0, ["Global hotkeys are implemented for Windows only."]

        entries: List[Tuple[int, Hotkey]] = []
        self._callbacks.clear()
        self._names.clear()
        for hotkey in hotkeys:
            hotkey_id = next(self._next_id)
            entries.append((hotkey_id, hotkey))
            self._callbacks[hotkey_id] = hotkey.callback
            self._names[hotkey_id] = hotkey.name

        self._thread = threading.Thread(target=self._message_loop, args=(entries,), daemon=True)
        self._thread.start()
        try:
            registered, failures, thread_id = self._ready.get(timeout=2.0)
        except queue.Empty:
            self._callbacks.clear()
            self._names.clear()
            return 0, ["Global hotkey message thread did not start."]

        self._thread_id = thread_id
        if registered and not self._polling:
            self._polling = True
            self.root.after(POLL_INTERVAL_MS, self._poll_events)
        return registered, failures

    def unregister_all(self) -> None:
        if sys.platform == "win32" and self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        self._thread_id = 0
        self._callbacks.clear()
        self._names.clear()
        while not self._drain_queue(self._events):
            pass
        while not self._drain_queue(self._ready):
            pass

    def _message_loop(self, entries: List[Tuple[int, Hotkey]]) -> None:
        thread_id = int(kernel32.GetCurrentThreadId())

        # Force creation of this thread's message queue before reporting ready.
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)

        registered_ids: List[int] = []
        failures: List[str] = []
        for hotkey_id, hotkey in entries:
            ok = user32.RegisterHotKey(None, hotkey_id, hotkey.modifiers, hotkey.vk)
            if ok:
                registered_ids.append(hotkey_id)
            else:
                failures.append(hotkey.name)

        self._ready.put((len(registered_ids), failures, thread_id))

        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    self._events.put(int(msg.wParam))
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            for hotkey_id in registered_ids:
                user32.UnregisterHotKey(None, hotkey_id)

    def _poll_events(self) -> None:
        try:
            while True:
                hotkey_id = self._events.get_nowait()
                callback = self._callbacks.get(hotkey_id)
                if callback:
                    callback()
        except queue.Empty:
            pass

        if self._thread and self._thread.is_alive():
            self.root.after(POLL_INTERVAL_MS, self._poll_events)
        else:
            self._polling = False

    @staticmethod
    def _drain_queue(target: "queue.Queue") -> bool:
        try:
            target.get_nowait()
            return False
        except queue.Empty:
            return True
