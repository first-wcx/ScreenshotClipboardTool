from __future__ import annotations

import ctypes
import sys
from io import BytesIO

from PIL import Image


def copy_image_to_clipboard(image: Image.Image) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Image clipboard copy is currently implemented for Windows.")
    _copy_windows_dib(image)


def _copy_windows_dib(image: Image.Image) -> None:
    output = BytesIO()
    image.convert("RGB").save(output, "BMP")
    dib = output.getvalue()[14:]
    output.close()

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_int
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = ctypes.c_int
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_int

    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_int
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p

    cf_dib = 8
    gmem_moveable = 0x0002
    handle = kernel32.GlobalAlloc(gmem_moveable, len(dib))
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
        if not user32.SetClipboardData(cf_dib, handle):
            raise OSError("SetClipboardData failed.")
        handle = None
    finally:
        user32.CloseClipboard()
        if handle:
            kernel32.GlobalFree(handle)
