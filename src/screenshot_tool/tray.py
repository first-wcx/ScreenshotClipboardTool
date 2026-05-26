from __future__ import annotations

import ctypes
import queue
import sys
import threading
from typing import Callable, Optional


if sys.platform == "win32":
    from ctypes import wintypes

POLL_INTERVAL_MS = 250


class TrayIconManager:
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
        self._events: "queue.Queue[str]" = queue.Queue()
        self._ready: "queue.Queue[int]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._thread_id = 0
        self._polling = False

    def show(self) -> bool:
        if sys.platform != "win32":
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._thread = threading.Thread(target=self._message_loop, args=(self.icon_path,), daemon=True)
        self._thread.start()
        try:
            self._thread_id = self._ready.get(timeout=2.0)
        except queue.Empty:
            self._thread = None
            self._thread_id = 0
            return False
        if not self._thread_id:
            self._thread = None
            return False
        if not self._polling:
            self._polling = True
            self.root.after(POLL_INTERVAL_MS, self._poll_events)
        return True

    def hide(self) -> None:
        if sys.platform == "win32" and self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_APP_CLOSE, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        self._thread_id = 0

    def stop(self) -> None:
        self.hide()

    def _poll_events(self) -> None:
        try:
            while True:
                event = self._events.get_nowait()
                if event == "show":
                    self.on_show()
                elif event == "settings":
                    self.on_settings()
                elif event == "history":
                    self.on_history()
                elif event == "exit":
                    self.on_exit()
        except queue.Empty:
            pass
        if self._thread and self._thread.is_alive():
            self.root.after(POLL_INTERVAL_MS, self._poll_events)
        else:
            self._polling = False

    def _message_loop(self, icon_path: Optional[str]) -> None:
        thread_id = int(kernel32.GetCurrentThreadId())
        wndproc = _make_wndproc(self._events)
        class_name = f"ScreenshotToolTray{thread_id}"

        wndclass = WNDCLASS()
        wndclass.lpfnWndProc = wndproc
        wndclass.lpszClassName = class_name
        wndclass.hInstance = kernel32.GetModuleHandleW(None)
        atom = user32.RegisterClassW(ctypes.byref(wndclass))
        if not atom:
            self._ready.put(0)
            return

        hwnd = user32.CreateWindowExW(
            0,
            class_name,
            class_name,
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            wndclass.hInstance,
            None,
        )
        if not hwnd:
            self._ready.put(0)
            return

        icon, owns_icon = _load_icon(icon_path)
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
            self._ready.put(0)
            return
        self._ready.put(thread_id)

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


if sys.platform == "win32":
    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    kernel32 = ctypes.windll.kernel32

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

    WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )
    HICON = getattr(wintypes, "HICON", wintypes.HANDLE)
    HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)
    HBRUSH = getattr(wintypes, "HBRUSH", wintypes.HANDLE)
    HMENU = getattr(wintypes, "HMENU", wintypes.HANDLE)
    UINT_PTR = ctypes.c_size_t

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

    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    user32.UnregisterClassW.restype = wintypes.BOOL
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user32.LoadIconW.restype = HICON
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.LoadImageW.restype = HICON
    user32.DestroyIcon.argtypes = [HICON]
    user32.DestroyIcon.restype = wintypes.BOOL
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL
    user32.TrackPopupMenu.argtypes = [
        HMENU,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        ctypes.c_void_p,
    ]
    user32.TrackPopupMenu.restype = ctypes.c_int
    user32.CreatePopupMenu.argtypes = []
    user32.CreatePopupMenu.restype = HMENU
    user32.AppendMenuW.argtypes = [HMENU, wintypes.UINT, UINT_PTR, wintypes.LPCWSTR]
    user32.AppendMenuW.restype = wintypes.BOOL
    user32.DestroyMenu.argtypes = [HMENU]
    user32.DestroyMenu.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostQuitMessage.restype = None
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostThreadMessageW.restype = wintypes.BOOL
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

    def _load_icon(icon_path: Optional[str]):
        if icon_path:
            icon = user32.LoadImageW(
                None,
                icon_path,
                IMAGE_ICON,
                0,
                0,
                LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )
            if icon:
                return icon, True
        return user32.LoadIconW(None, IDI_APPLICATION), False

    def _make_wndproc(events: "queue.Queue[str]"):
        def wndproc(hwnd, message, wparam, lparam):
            if message == WM_TRAYICON:
                if int(lparam) in {WM_LBUTTONDBLCLK, WM_LBUTTONUP}:
                    events.put("show")
                    return 0
                if int(lparam) == WM_RBUTTONUP:
                    command = _show_menu(hwnd)
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

        callback = WNDPROC(wndproc)
        return callback

    def _show_menu(hwnd) -> int:
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, 0, MENU_SHOW, "显示主窗口")
        user32.AppendMenuW(menu, 0, MENU_SETTINGS, "设置")
        user32.AppendMenuW(menu, 0, MENU_HISTORY, "历史截图")
        user32.AppendMenuW(menu, 0, MENU_EXIT, "退出")
        user32.SetForegroundWindow(hwnd)
        command = user32.TrackPopupMenu(
            menu,
            TPM_RIGHTBUTTON | TPM_RETURNCMD,
            point.x,
            point.y,
            0,
            hwnd,
            None,
        )
        user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        return int(command)
