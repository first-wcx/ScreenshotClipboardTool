import base64
import binascii
import ctypes
import hashlib
import json
import os
import queue
import socket
import struct
import subprocess
import sys
import threading
import tkinter as tk
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from PIL import Image, ImageDraw
import pystray


def app_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = app_base_dir()
HISTORY_FILE = APP_DIR / "clipboard_history.json"
IMAGE_DIR = APP_DIR / "images"
SYNC_CONFIG_FILE = APP_DIR / "clipboard_sync.json"
MAX_TEXT_DISPLAY = 12000
POLL_MS = 700
MAX_HISTORY = 30
WINDOW_WIDTH = 430
WINDOW_HEIGHT = 560
SYNC_DEFAULT_PORT = 8765
SYNC_RECONNECT_SECONDS = 3
SYNC_SOCKET_TIMEOUT = 1
SYNC_MAX_IMAGE_BYTES = 32 * 1024 * 1024
SYNC_MAX_MESSAGE_BYTES = SYNC_MAX_IMAGE_BYTES * 2
SYNC_STREAM_BUFFER = 65536
SYNCED_FILES_DIR_NAME = "synced_files"
SCREENSHOT_EDITOR_COMPONENTS = None

CF_UNICODETEXT = 13
CF_HDROP = 15
CF_DIB = 8
CF_BITMAP = 2

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)


class DROPFILES(ctypes.Structure):
    _fields_ = [
        ("pFiles", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("fNC", wintypes.BOOL),
        ("fWide", wintypes.BOOL),
    ]

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wintypes.BOOL
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = wintypes.BOOL
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.GetClipboardSequenceNumber.argtypes = []
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD

kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.restype = wintypes.HGLOBAL
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t

shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
shell32.DragQueryFileW.restype = wintypes.UINT

GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040


def enable_dpi_awareness():
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def dpi_scale(widget):
    try:
        return max(1.0, float(widget.winfo_fpixels("1i")) / 96.0)
    except tk.TclError:
        return 1.0


def ensure_screenshot_tool_import_path():
    candidates = [
        APP_DIR.parent / "screenshot_tool" / "src",
        APP_DIR.parent.parent / "screenshot_tool" / "src",
    ]
    for candidate in candidates:
        if (candidate / "screenshot_tool" / "app.py").exists():
            path_text = str(candidate)
            if path_text not in sys.path:
                sys.path.insert(0, path_text)
            return


def load_screenshot_editor_components():
    global SCREENSHOT_EDITOR_COMPONENTS
    if SCREENSHOT_EDITOR_COMPONENTS is not None:
        return SCREENSHOT_EDITOR_COMPONENTS, None

    ensure_screenshot_tool_import_path()
    try:
        from screenshot_tool.app import open_image_editor
        from screenshot_tool.config import load_settings
        from screenshot_tool.history import ScreenshotHistory
    except Exception as exc:
        return None, exc

    SCREENSHOT_EDITOR_COMPONENTS = (open_image_editor, load_settings, ScreenshotHistory)
    return SCREENSHOT_EDITOR_COMPONENTS, None


def now_label():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def shorten(value, limit=80):
    value = " ".join(str(value).replace("\r", "\n").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "..."


class ClipboardAccessError(Exception):
    pass


class WindowsClipboard:
    def __enter__(self):
        if not user32.OpenClipboard(None):
            raise ClipboardAccessError("剪切板正被其他程序占用，请稍后重试。")
        return self

    def __exit__(self, exc_type, exc, tb):
        user32.CloseClipboard()


def format_available(fmt):
    return bool(user32.IsClipboardFormatAvailable(fmt))


def get_clipboard_sequence_number():
    return int(user32.GetClipboardSequenceNumber())


def read_unicode_text():
    if not format_available(CF_UNICODETEXT):
        return None
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


def read_file_list():
    if not format_available(CF_HDROP):
        return None
    handle = user32.GetClipboardData(CF_HDROP)
    if not handle:
        return None
    count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
    paths = []
    for index in range(count):
        length = shell32.DragQueryFileW(handle, index, None, 0)
        buffer = ctypes.create_unicode_buffer(length + 1)
        shell32.DragQueryFileW(handle, index, buffer, length + 1)
        paths.append(buffer.value)
    return paths


def read_dib_bytes():
    if not format_available(CF_DIB):
        return None
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


def dib_to_bmp_bytes(dib):
    if len(dib) < 16:
        return None

    header_size = int.from_bytes(dib[0:4], "little")
    pixel_offset = 14 + header_size

    if header_size == 12 and len(dib) >= 12:
        bit_count = int.from_bytes(dib[10:12], "little")
        palette_size = (1 << bit_count) * 3 if bit_count <= 8 else 0
        pixel_offset += palette_size
    elif header_size >= 40 and len(dib) >= 40:
        bit_count = int.from_bytes(dib[14:16], "little")
        compression = int.from_bytes(dib[16:20], "little")
        colors_used = int.from_bytes(dib[32:36], "little")
        palette_size = (colors_used or (1 << bit_count if bit_count <= 8 else 0)) * 4
        masks_size = 12 if compression == 3 and header_size == 40 else 0
        pixel_offset += palette_size + masks_size
    else:
        return None

    file_size = 14 + len(dib)
    bmp_header = (
        b"BM"
        + file_size.to_bytes(4, "little")
        + (0).to_bytes(4, "little")
        + pixel_offset.to_bytes(4, "little")
    )
    return bmp_header + dib


def save_clipboard_image(dib):
    digest = hashlib.sha256(dib).hexdigest()
    bmp = dib_to_bmp_bytes(dib)
    if not bmp:
        return digest, None

    IMAGE_DIR.mkdir(exist_ok=True)
    path = IMAGE_DIR / f"clipboard_{digest[:16]}.bmp"
    if not path.exists():
        path.write_bytes(bmp)
    return digest, str(path)


def get_synced_files_dir():
    directory = APP_DIR / SYNCED_FILES_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_synced_files(files_data):
    sync_dir = get_synced_files_dir()
    sync_id = hashlib.sha256(os.urandom(8)).hexdigest()[:12]
    group_dir = sync_dir / sync_id
    group_dir.mkdir(parents=True, exist_ok=True)
    new_paths = []
    for file_info in files_data:
        rel = file_info.get("rel_path")
        if rel:
            target = group_dir / rel
        else:
            orig_path = Path(file_info["path"])
            target = group_dir / orig_path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target = target.parent / f"{target.stem}_{hashlib.sha256(target.name.encode()).hexdigest()[:6]}{target.suffix}"
        target.write_bytes(base64.b64decode(file_info["data"]))
        new_paths.append(str(target))
    return new_paths, sync_id


def allocate_global_bytes(data, error_message):
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(data))
    if not handle:
        raise ClipboardAccessError(error_message)

    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        raise ClipboardAccessError(error_message)
    try:
        ctypes.memmove(pointer, data, len(data))
    finally:
        kernel32.GlobalUnlock(handle)
    return handle


def replace_clipboard_data(format_id, handle, error_message):
    with WindowsClipboard():
        if not user32.EmptyClipboard():
            kernel32.GlobalFree(handle)
            raise ClipboardAccessError("无法清空当前剪切板。")
        if not user32.SetClipboardData(format_id, handle):
            kernel32.GlobalFree(handle)
            raise ClipboardAccessError(error_message)


def write_unicode_text(text):
    data = (text + "\0").encode("utf-16-le")
    handle = allocate_global_bytes(data, "无法写入剪切板文本。")
    replace_clipboard_data(CF_UNICODETEXT, handle, "无法写入剪切板。")


def write_file_list(paths):
    if not paths:
        raise ClipboardAccessError("这条文件记录没有可恢复的路径。")

    file_names = "\0".join(paths) + "\0\0"
    file_data = file_names.encode("utf-16-le")
    dropfiles = DROPFILES()
    dropfiles.pFiles = ctypes.sizeof(DROPFILES)
    dropfiles.fWide = 1
    handle = allocate_global_bytes(bytes(dropfiles) + file_data, "无法写入剪切板文件列表。")
    replace_clipboard_data(CF_HDROP, handle, "无法写入剪切板文件列表。")


def write_dib_bytes(dib):
    if not dib:
        raise ClipboardAccessError("这条图片记录没有可恢复的图片数据。")
    handle = allocate_global_bytes(dib, "无法写入剪切板图片。")
    replace_clipboard_data(CF_DIB, handle, "无法写入剪切板图片。")


def write_image_file_to_clipboard(path):
    if not path:
        raise ClipboardAccessError("这条图片记录没有可恢复的图片文件。")

    image_path = Path(path)
    if not image_path.exists():
        raise ClipboardAccessError("这条图片记录对应的图片文件已不存在。")

    try:
        data = image_path.read_bytes()
    except OSError as exc:
        raise ClipboardAccessError(f"无法读取图片文件: {exc}") from exc

    if data[:2] == b"BM" and len(data) > 14:
        write_dib_bytes(data[14:])
        return

    raise ClipboardAccessError("这条图片记录不是可恢复的 BMP 图片。")


def write_clipboard_item(item):
    kind = item.get("type")
    if kind == "text":
        write_unicode_text(item.get("text", ""))
        return "文本"
    if kind == "files":
        write_file_list(item.get("paths", []))
        return "文件/文件夹"
    if kind == "image":
        write_image_file_to_clipboard(item.get("image_path", ""))
        return "图片"
    raise ClipboardAccessError("这条记录的类型不能恢复到系统剪切板。")


def clear_system_clipboard():
    with WindowsClipboard():
        if not user32.EmptyClipboard():
            raise ClipboardAccessError("无法清空当前剪切板。")


def read_clipboard_snapshot():
    with WindowsClipboard():
        files = read_file_list()
        if files:
            digest = hashlib.sha256("\n".join(files).encode("utf-8", errors="ignore")).hexdigest()
            return {
                "type": "files",
                "time": now_label(),
                "paths": files,
                "digest": f"files:{digest}",
                "preview": f"{len(files)} 个文件/文件夹: {shorten(files[0])}",
            }

        text = read_unicode_text()
        if text:
            digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
            return {
                "type": "text",
                "time": now_label(),
                "text": text,
                "digest": f"text:{digest}",
                "preview": shorten(text),
            }

        dib = read_dib_bytes()
        if dib or format_available(CF_BITMAP):
            if dib:
                image_digest, image_path = save_clipboard_image(dib)
                digest = f"image:{image_digest}"
                size = len(dib)
            else:
                image_path = None
                size = 0
                digest = "image:bitmap"
            return {
                "type": "image",
                "time": now_label(),
                "size": size,
                "image_path": image_path,
                "digest": digest,
                "preview": f"图片数据 ({size} bytes)" if size else "图片数据",
            }

        return None


def load_history():
    if not HISTORY_FILE.exists():
        return []
    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_history(items):
    with HISTORY_FILE.open("w", encoding="utf-8") as file:
        json.dump(items, file, ensure_ascii=False, indent=2)


def default_sync_config():
    return {
        "enabled": False,
        "listen_host": "0.0.0.0",
        "port": SYNC_DEFAULT_PORT,
        "peer_host": "",
        "shared_secret": "",
        "sync_text": True,
        "sync_images": True,
    }


def parse_sync_port(value):
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return SYNC_DEFAULT_PORT
    if 1 <= port <= 65535:
        return port
    return SYNC_DEFAULT_PORT


def load_sync_config():
    config = default_sync_config()
    if SYNC_CONFIG_FILE.exists():
        try:
            with SYNC_CONFIG_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, dict):
                for key in config:
                    if key in data:
                        config[key] = data[key]
        except (OSError, json.JSONDecodeError):
            pass

    config["enabled"] = bool(config.get("enabled"))
    config["listen_host"] = str(config.get("listen_host") or "0.0.0.0").strip() or "0.0.0.0"
    config["port"] = parse_sync_port(config.get("port"))
    config["peer_host"] = str(config.get("peer_host") or "").strip()
    config["shared_secret"] = str(config.get("shared_secret") or "")
    config["sync_text"] = bool(config.get("sync_text", True))
    config["sync_images"] = bool(config.get("sync_images", True))
    return config


def save_sync_config(config):
    with SYNC_CONFIG_FILE.open("w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=False, indent=2)


def serialize_item_for_sync(item, config):
    kind = item.get("type")
    if kind == "text":
        if not config.get("sync_text", True):
            return None
        text = item.get("text")
        if not isinstance(text, str):
            return None
        return {
            "type": "text",
            "time": item.get("time", now_label()),
            "text": text,
            "digest": item.get("digest"),
            "preview": item.get("preview", shorten(text)),
        }

    if kind == "image":
        if not config.get("sync_images", True):
            return None
        image_path = item.get("image_path")
        if not image_path:
            return None

        try:
            data = Path(image_path).read_bytes()
        except OSError:
            return None

        dib = data[14:] if data[:2] == b"BM" and len(data) > 14 else data
        if not dib or len(dib) > SYNC_MAX_IMAGE_BYTES:
            return None

        return {
            "type": "image",
            "time": item.get("time", now_label()),
            "digest": item.get("digest"),
            "preview": item.get("preview", f"图片数据 ({len(dib)} bytes)"),
            "size": len(dib),
            "dib_b64": base64.b64encode(dib).decode("ascii"),
        }

    if kind == "files":
        paths = item.get("paths", [])
        if not paths:
            return None
        entries = []
        total_size = 0
        for path_text in paths:
            try:
                path = Path(path_text)
                if not path.exists():
                    continue
                if path.is_file():
                    size = path.stat().st_size
                    total_size += size
                    entries.append({
                        "rel_path": path.name,
                        "abs_path": str(path),
                        "size": size,
                    })
                elif path.is_dir():
                    for root, _dirs, files in os.walk(path):
                        root_path = Path(root)
                        for fname in files:
                            try:
                                fpath = root_path / fname
                                size = fpath.stat().st_size
                                total_size += size
                                rel = str(root_path.relative_to(path.parent) / fname)
                                entries.append({
                                    "rel_path": rel,
                                    "abs_path": str(fpath),
                                    "size": size,
                                })
                            except OSError:
                                continue
            except OSError:
                continue
        if not entries:
            return None
        return {
            "_stream": True,
            "type": "files",
            "time": item.get("time", now_label()),
            "digest": item.get("digest"),
            "preview": item.get("preview", f"{len(entries)} 个文件"),
            "files": [{"rel_path": e["rel_path"], "size": e["size"]} for e in entries],
            "_abs_paths": [e["abs_path"] for e in entries],
            "_total_size": total_size,
        }

    return None


def deserialize_synced_item(payload, config):
    if not isinstance(payload, dict):
        return None

    kind = payload.get("type")
    if kind == "text":
        if not config.get("sync_text", True):
            return None
        text = payload.get("text")
        if not isinstance(text, str) or not text:
            return None
        digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
        return {
            "type": "text",
            "time": now_label(),
            "text": text,
            "digest": f"text:{digest}",
            "preview": shorten(text),
        }

    if kind == "image":
        if not config.get("sync_images", True):
            return None
        encoded = payload.get("dib_b64")
        if not isinstance(encoded, str) or not encoded:
            return None
        try:
            dib = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (ValueError, binascii.Error):
            return None
        if not dib or len(dib) > SYNC_MAX_IMAGE_BYTES:
            return None

        image_digest, image_path = save_clipboard_image(dib)
        if not image_path:
            return None
        return {
            "type": "image",
            "time": now_label(),
            "size": len(dib),
            "image_path": image_path,
            "digest": f"image:{image_digest}",
            "preview": f"图片数据 ({len(dib)} bytes)",
        }

    if kind == "files":
        files_data = payload.get("files")
        if not isinstance(files_data, list) or not files_data:
            return None
        for file_info in files_data:
            if not isinstance(file_info, dict) or "path" not in file_info or "data" not in file_info:
                return None
        new_paths, sync_id = save_synced_files(files_data)
        if not new_paths:
            return None
        digest = hashlib.sha256(sync_id.encode()).hexdigest()
        return {
            "type": "files",
            "time": now_label(),
            "paths": new_paths,
            "digest": f"files:{digest}",
            "preview": f"{len(new_paths)} 个文件/文件夹: {shorten(new_paths[0])}",
        }

    return None


def normalized_path(value):
    if not value:
        return None
    try:
        return str(Path(value).resolve()).lower()
    except OSError:
        return str(value).lower()


def image_paths_from_items(items):
    paths = set()
    for item in items:
        if item.get("type") == "image":
            path = normalized_path(item.get("image_path"))
            if path:
                paths.add(path)
    return paths


def synced_file_paths_from_items(items):
    paths = set()
    for item in items:
        if item.get("type") == "files":
            for path_text in item.get("paths", []):
                path = normalized_path(path_text)
                if path:
                    paths.add(path)
    return paths


def delete_unreferenced_image_files(deleted_items, remaining_items):
    remaining_paths = image_paths_from_items(remaining_items)
    deleted_paths = image_paths_from_items(deleted_items)
    deleted_count = 0
    failed_paths = []

    for path_text in deleted_paths - remaining_paths:
        path = Path(path_text)
        try:
            if path.exists() and path.is_file():
                path.unlink()
                deleted_count += 1
        except OSError:
            failed_paths.append(str(path))

    return deleted_count, failed_paths


def delete_unreferenced_synced_files(deleted_items, remaining_items):
    remaining_paths = synced_file_paths_from_items(remaining_items)
    deleted_paths = synced_file_paths_from_items(deleted_items)
    deleted_count = 0
    failed_paths = []

    for path_text in deleted_paths - remaining_paths:
        path = Path(path_text)
        try:
            if path.exists() and path.is_file():
                path.unlink()
                deleted_count += 1
        except OSError:
            failed_paths.append(str(path))

    # Clean up empty group directories
    synced_dir = get_synced_files_dir()
    if synced_dir.exists():
        for group_dir in synced_dir.iterdir():
            if group_dir.is_dir():
                try:
                    remaining = list(group_dir.iterdir())
                    if not remaining:
                        group_dir.rmdir()
                except OSError:
                    pass

    return deleted_count, failed_paths


def limit_history(items):
    kept_items = items[:MAX_HISTORY]
    removed_items = items[MAX_HISTORY:]
    deleted_images, failed_images = delete_unreferenced_image_files(removed_items, kept_items)
    deleted_synced, failed_synced = delete_unreferenced_synced_files(removed_items, kept_items)
    return kept_items, removed_items, deleted_images + deleted_synced, failed_images + failed_synced


class ClipboardSyncManager:
    def __init__(self, config, event_queue):
        self.config = dict(config)
        self.event_queue = event_queue
        self.node_id = hashlib.sha256(os.urandom(16)).hexdigest()[:16]
        self.stop_event = threading.Event()
        self.outgoing = queue.Queue()
        self.clients = []
        self.clients_lock = threading.Lock()
        self.server_socket = None
        self.threads = []

    def start(self):
        self.stop_event.clear()
        self._start_thread(self._send_loop, "ClipboardSyncSend")
        self._start_thread(self._listen_loop, "ClipboardSyncListen")
        if self.config.get("peer_host"):
            self._start_thread(self._connect_loop, "ClipboardSyncConnect")

    def stop(self):
        self.stop_event.set()
        if self.server_socket:
            try:
                self.server_socket.close()
            except OSError:
                pass
            self.server_socket = None

        with self.clients_lock:
            clients = list(self.clients)
            self.clients.clear()
        for client in clients:
            self._close_socket(client)

    def publish(self, item):
        if self.stop_event.is_set():
            return
        payload = serialize_item_for_sync(item, self.config)
        if not payload:
            return
        if payload.pop("_stream", False):
            abs_paths = payload.pop("_abs_paths", [])
            total_size = payload.pop("_total_size", 0)
            self.outgoing.put({
                "_stream": True,
                "kind": "file_stream",
                "origin": self.node_id,
                "secret": self.config.get("shared_secret", ""),
                "item": payload,
                "_abs_paths": abs_paths,
                "_total_size": total_size,
            })
        else:
            self.outgoing.put({
                "kind": "clipboard",
                "origin": self.node_id,
                "secret": self.config.get("shared_secret", ""),
                "item": payload,
            })

    def _start_thread(self, target, name):
        thread = threading.Thread(target=target, name=name, daemon=True)
        self.threads.append(thread)
        thread.start()

    def _listen_loop(self):
        host = self.config.get("listen_host") or "0.0.0.0"
        port = parse_sync_port(self.config.get("port"))
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.settimeout(SYNC_SOCKET_TIMEOUT)
        self.server_socket = server

        try:
            server.bind((host, port))
            server.listen()
            self._post_status(f"网络同步已监听 {host}:{port}")
        except OSError as exc:
            self._post_status(f"网络同步监听失败: {exc}")
            self._close_socket(server)
            return

        while not self.stop_event.is_set():
            try:
                client, address = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            label = f"{address[0]}:{address[1]}"
            self._start_thread(lambda sock=client, name=label: self._handle_client(sock, name), "ClipboardSyncClient")

        self._close_socket(server)

    def _connect_loop(self):
        peer_host = self.config.get("peer_host")
        port = parse_sync_port(self.config.get("port"))
        last_error = None

        while not self.stop_event.is_set():
            try:
                client = socket.create_connection((peer_host, port), timeout=3)
            except OSError as exc:
                error_text = str(exc)
                if error_text != last_error:
                    self._post_status(f"正在连接对端 {peer_host}:{port}: {exc}")
                    last_error = error_text
                self.stop_event.wait(SYNC_RECONNECT_SECONDS)
                continue

            last_error = None
            self._handle_client(client, f"{peer_host}:{port}")
            self.stop_event.wait(SYNC_RECONNECT_SECONDS)

    def _handle_client(self, client, label):
        client.settimeout(SYNC_SOCKET_TIMEOUT)
        self._add_client(client)
        self._post_status(f"网络同步已连接 {label}")
        buffer = b""

        def read_exact(size):
            nonlocal buffer
            result = b""
            while len(result) < size:
                if buffer:
                    take = min(size - len(result), len(buffer))
                    result += buffer[:take]
                    buffer = buffer[take:]
                else:
                    try:
                        chunk = client.recv(min(SYNC_STREAM_BUFFER, size - len(result)))
                    except socket.timeout:
                        continue
                    except OSError:
                        return None
                    if not chunk:
                        return None
                    result += chunk
            return result

        def read_exact_long_timeout(size):
            old_timeout = client.gettimeout()
            client.settimeout(30)
            try:
                return read_exact(size)
            finally:
                client.settimeout(old_timeout)

        try:
            while not self.stop_event.is_set():
                if b"\n" not in buffer:
                    try:
                        chunk = client.recv(65536)
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    if not chunk:
                        break
                    buffer += chunk
                    if len(buffer) > SYNC_MAX_MESSAGE_BYTES and b"\n" not in buffer:
                        buffer = b""
                        self._post_status("收到的同步消息过大，已忽略。")
                        continue

                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line:
                        continue
                    try:
                        message = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if not isinstance(message, dict):
                        continue
                    if message.get("kind") == "file_stream":
                        self._receive_stream_files(message, read_exact_long_timeout)
                    else:
                        self._handle_message_obj(message)
        finally:
            self._remove_client(client)
            self._close_socket(client)
            self._post_status(f"网络同步连接已断开 {label}")

    def _receive_stream_files(self, message, read_exact):
        item = message.get("item", {})
        files_meta = item.get("files", []) if isinstance(item, dict) else []

        if message.get("origin") == self.node_id:
            for finfo in files_meta:
                fsize = finfo.get("size", 0)
                if fsize > 0:
                    read_exact(fsize)
            return
        if str(message.get("secret", "")) != self.config.get("shared_secret", ""):
            for finfo in files_meta:
                fsize = finfo.get("size", 0)
                if fsize > 0:
                    read_exact(fsize)
            return

        if not files_meta:
            self._post_status("收到空的文件流消息")
            return

        sync_dir = get_synced_files_dir()
        sync_id = hashlib.sha256(os.urandom(8)).hexdigest()[:12]
        group_dir = sync_dir / sync_id
        group_dir.mkdir(parents=True, exist_ok=True)

        new_paths = []
        failed = 0
        for i, finfo in enumerate(files_meta):
            rel = finfo.get("rel_path", "")
            fsize = finfo.get("size", 0)
            target = group_dir / rel if rel else group_dir / f"file_{i}"
            target.parent.mkdir(parents=True, exist_ok=True)
            if fsize == 0:
                target.write_bytes(b"")
                new_paths.append(str(target))
                continue
            written = 0
            try:
                with open(target, "wb") as f:
                    while written < fsize:
                        chunk = read_exact(min(SYNC_STREAM_BUFFER, fsize - written))
                        if not chunk:
                            break
                        f.write(chunk)
                        written += len(chunk)
            except OSError:
                failed += 1
                continue
            if written == fsize:
                new_paths.append(str(target))
            else:
                failed += 1
                try:
                    target.unlink()
                except OSError:
                    pass

        if new_paths:
            digest = hashlib.sha256(sync_id.encode()).hexdigest()
            item = {
                "type": "files",
                "time": now_label(),
                "paths": new_paths,
                "digest": f"files:{digest}",
                "preview": f"{len(new_paths)} 个文件",
            }
            self.event_queue.put(("clipboard", item))
            self._post_status(f"收到 {len(new_paths)} 个文件" + (f"，{failed} 个失败" if failed else ""))
        else:
            self._post_status(f"文件接收全部失败 ({len(files_meta)} 个)")

    def _handle_message_obj(self, message):
        if message.get("kind") != "clipboard":
            return
        if message.get("origin") == self.node_id:
            return
        if str(message.get("secret", "")) != self.config.get("shared_secret", ""):
            return

        payload = message.get("item")
        if not isinstance(payload, dict):
            return

        item = deserialize_synced_item(payload, self.config)
        if item:
            self.event_queue.put(("clipboard", item))

    def _send_loop(self):
        while not self.stop_event.is_set():
            try:
                message = self.outgoing.get(timeout=0.5)
            except queue.Empty:
                continue

            if message.get("_stream"):
                self._send_stream(message)
                continue

            data = (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            if len(data) > SYNC_MAX_MESSAGE_BYTES:
                self._post_status("剪贴板内容过大，未同步。")
                continue

            with self.clients_lock:
                clients = list(self.clients)

            dead_clients = []
            for client in clients:
                try:
                    client.sendall(data)
                except OSError:
                    dead_clients.append(client)

            for client in dead_clients:
                self._remove_client(client)
                self._close_socket(client)

    def _send_stream(self, message):
        abs_paths = message.pop("_abs_paths", [])
        total_size = message.pop("_total_size", 0)
        header = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        header_bytes = header.encode("utf-8")

        with self.clients_lock:
            clients = list(self.clients)

        if not clients:
            self._post_status(f"无对端连接，{len(abs_paths)} 个文件未同步")
            return

        self._post_status(f"开始同步 {len(abs_paths)} 个文件 ({total_size / 1048576:.1f} MB)...")
        dead_clients = []
        for client in clients:
            try:
                client.sendall(header_bytes)
                for abs_path in abs_paths:
                    fpath = Path(abs_path)
                    if not fpath.exists():
                        continue
                    fsize = fpath.stat().st_size
                    sent = 0
                    with open(fpath, "rb") as f:
                        while sent < fsize:
                            chunk = f.read(SYNC_STREAM_BUFFER)
                            if not chunk:
                                break
                            client.sendall(chunk)
                            sent += len(chunk)
            except OSError as exc:
                self._post_status(f"同步发送失败: {exc}")
                dead_clients.append(client)

        for client in dead_clients:
            self._remove_client(client)
            self._close_socket(client)
        if not dead_clients:
            self._post_status(f"同步完成：{len(abs_paths)} 个文件")

    def _add_client(self, client):
        with self.clients_lock:
            if client not in self.clients:
                self.clients.append(client)

    def _remove_client(self, client):
        with self.clients_lock:
            if client in self.clients:
                self.clients.remove(client)

    def _close_socket(self, sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def _post_status(self, message):
        self.event_queue.put(("status", message))


class TrayIcon:
    def __init__(self, command_queue):
        self.command_queue = command_queue
        self.icon = pystray.Icon(
            "clipboard_viewer",
            self._create_icon_image(),
            "Windows 剪切板查看器",
            menu=pystray.Menu(
                pystray.MenuItem("主页面", self._show_main, default=True),
                pystray.MenuItem("缩放到托盘", self._hide_main),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", self._quit),
            ),
        )
        self.thread = threading.Thread(target=self.icon.run, name="ClipboardTray", daemon=True)
        self.thread.start()

    def _create_icon_image(self):
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((10, 8, 54, 58), radius=8, fill=(42, 99, 220), outline=(18, 45, 120), width=3)
        draw.rectangle((20, 4, 44, 14), fill=(235, 242, 255), outline=(18, 45, 120), width=2)
        draw.line((20, 25, 44, 25), fill=(255, 255, 255), width=4)
        draw.line((20, 38, 44, 38), fill=(255, 255, 255), width=4)
        return image

    def _show_main(self, _icon=None, _item=None):
        self.command_queue.put("show")

    def _hide_main(self, _icon=None, _item=None):
        self.command_queue.put("hide")

    def _quit(self, _icon=None, _item=None):
        self.command_queue.put("quit")

    def remove(self):
        self.icon.stop()


class ClipboardViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Windows 剪切板查看器")
        self.ui_scale = dpi_scale(self)
        self.default_width = int(WINDOW_WIDTH * self.ui_scale)
        self.default_height = int(WINDOW_HEIGHT * self.ui_scale)
        self.geometry(f"{self.default_width}x{self.default_height}")
        self.minsize(int(390 * self.ui_scale), int(480 * self.ui_scale))
        self._quitting = False
        self._hiding_to_tray = False
        self.tray_commands = queue.Queue()
        self.sync_events = queue.Queue()
        self.sync_config = load_sync_config()
        self.sync_manager = None
        self.screenshot_editor_settings = None
        self.screenshot_editor_history = None

        self.history = load_history()
        self.history, removed_items, _deleted_images, _failed_images = limit_history(self.history)
        if removed_items:
            save_history(self.history)
        self.last_digest = self.history[0].get("digest") if self.history else None
        self.last_clipboard_sequence = None
        self.sync_enabled_var = tk.BooleanVar(value=self.sync_config.get("enabled", False))
        self.sync_peer_host_var = tk.StringVar(value=self.sync_config.get("peer_host", ""))
        self.sync_port_var = tk.StringVar(value=str(self.sync_config.get("port", SYNC_DEFAULT_PORT)))
        self.sync_secret_var = tk.StringVar(value=self.sync_config.get("shared_secret", ""))
        self.sync_images_var = tk.BooleanVar(value=self.sync_config.get("sync_images", True))
        self.sync_status_var = tk.StringVar(value="网络同步未启用")
        self.status_var = tk.StringVar(value="启动后会自动记录新的剪切板内容；最小化或关闭会缩到托盘。")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh_list())

        self._configure_style()
        self._build_ui()
        self.center_window()
        self.tray_icon = TrayIcon(self.tray_commands)
        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.bind("<Unmap>", self._on_unmap)
        self.refresh_list()
        self.after(120, self.process_tray_commands)
        self.after(150, self.process_sync_events)
        self.restart_sync()
        self.after(POLL_MS, self.poll_clipboard)

    def _configure_style(self):
        style = ttk.Style(self)
        try:
            tree_font = tkfont.nametofont("TkDefaultFont")
            row_height = max(int(24 * self.ui_scale), tree_font.metrics("linespace") + int(4 * self.ui_scale))
        except tk.TclError:
            row_height = int(24 * self.ui_scale)
        style.configure("Treeview", rowheight=row_height)
        style.configure("Treeview.Heading", padding=(0, int(3 * self.ui_scale)))

    def _build_ui(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        toolbar = ttk.Frame(root)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure(1, weight=1)

        ttk.Label(toolbar, text="搜索").grid(row=0, column=0, padx=(0, 6))
        search = ttk.Entry(toolbar, textvariable=self.search_var)
        search.grid(row=0, column=1, sticky="ew")

        actions = ttk.Frame(root)
        actions.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for column in range(4):
            actions.columnconfigure(column, weight=1)

        ttk.Button(actions, text="复制", command=self.copy_selected).grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 4))
        ttk.Button(actions, text="保存文本", command=self.save_selected_text).grid(row=0, column=1, sticky="ew", padx=2, pady=(0, 4))
        ttk.Button(actions, text="打开", command=self.open_selected).grid(row=0, column=2, sticky="ew", padx=2, pady=(0, 4))
        ttk.Button(actions, text="编辑图片", command=self.edit_selected_image).grid(row=0, column=3, sticky="ew", padx=(4, 0), pady=(0, 4))
        ttk.Button(actions, text="删除", command=self.delete_selected).grid(row=1, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(actions, text="清空", command=self.clear_history).grid(row=1, column=1, sticky="ew", padx=2)
        ttk.Button(actions, text="缩到托盘", command=self.hide_to_tray).grid(row=1, column=2, columnspan=2, sticky="ew", padx=(4, 0))

        sync = ttk.Frame(root)
        sync.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        sync.columnconfigure(2, weight=1)

        ttk.Checkbutton(sync, text="网络同步", variable=self.sync_enabled_var).grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Label(sync, text="对端").grid(row=0, column=1, sticky="w")
        ttk.Entry(sync, textvariable=self.sync_peer_host_var, width=13).grid(row=0, column=2, sticky="ew", padx=(4, 8))
        ttk.Label(sync, text="端口").grid(row=0, column=3, sticky="w")
        ttk.Entry(sync, textvariable=self.sync_port_var, width=6).grid(row=0, column=4, sticky="w", padx=(4, 8))
        ttk.Button(sync, text="应用", command=self.apply_sync_settings).grid(row=0, column=5, sticky="ew")

        ttk.Label(sync, text="密钥").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(sync, textvariable=self.sync_secret_var, show="*", width=16).grid(row=1, column=1, columnspan=2, sticky="ew", padx=(4, 8), pady=(4, 0))
        ttk.Checkbutton(sync, text="同步图片", variable=self.sync_images_var).grid(row=1, column=3, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(sync, textvariable=self.sync_status_var).grid(row=2, column=0, columnspan=6, sticky="ew", pady=(4, 0))

        main = ttk.PanedWindow(root, orient=tk.VERTICAL)
        main.grid(row=3, column=0, sticky="nsew")

        left = ttk.Frame(main)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        main.add(left, weight=2)

        columns = ("time", "type", "preview")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse", height=8)
        self.tree.heading("time", text="时间")
        self.tree.heading("type", text="类型")
        self.tree.heading("preview", text="内容预览")
        self.tree.column("time", width=int(142 * self.ui_scale), anchor="w", stretch=False)
        self.tree.column("type", width=int(54 * self.ui_scale), anchor="center", stretch=False)
        self.tree.column("preview", width=int(210 * self.ui_scale), anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.show_selected())
        self.tree.bind("<Button-3>", self.show_tree_context_menu)

        scrollbar = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        right = ttk.Frame(main, padding=(0, 8, 0, 0))
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        main.add(right, weight=3)

        self.detail_title = ttk.Label(right, text="详情", font=("", 11, "bold"))
        self.detail_title.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.detail = tk.Text(right, wrap=tk.WORD, undo=False, height=8)
        self.detail.grid(row=1, column=0, sticky="nsew")
        detail_scrollbar = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.detail.yview)
        detail_scrollbar.grid(row=1, column=1, sticky="ns")
        self.detail.configure(yscrollcommand=detail_scrollbar.set)
        self.detail.configure(state=tk.DISABLED)

        status = ttk.Label(root, textvariable=self.status_var, anchor="w")
        status.grid(row=4, column=0, sticky="ew", pady=(8, 0))

    def center_window(self):
        self.update_idletasks()
        width = max(self.winfo_width(), self.default_width)
        height = max(self.winfo_height(), self.default_height)
        x = max((self.winfo_screenwidth() - width) // 2, 0)
        y = max((self.winfo_screenheight() - height) // 2, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _on_unmap(self, event):
        if event.widget is self and not self._quitting and not self._hiding_to_tray:
            self.after(80, self._hide_if_minimized)

    def _hide_if_minimized(self):
        if not self._quitting and self.state() == "iconic":
            self.hide_to_tray()

    def hide_to_tray(self):
        if self._quitting:
            return
        self.status_var.set("已缩到托盘；右键托盘图标可打开主页面或退出。")
        self._hiding_to_tray = True
        try:
            self.withdraw()
        finally:
            self._hiding_to_tray = False

    def show_main_window(self):
        if self._quitting:
            return
        self._hiding_to_tray = True
        try:
            self.deiconify()
            self.state("normal")
            self.lift()
            self.focus_force()
        finally:
            self._hiding_to_tray = False

    def quit_app(self):
        self._quitting = True
        if self.sync_manager:
            self.sync_manager.stop()
            self.sync_manager = None
        tray_icon = getattr(self, "tray_icon", None)
        if tray_icon:
            tray_icon.remove()
        self.destroy()

    def sync_clipboard_sequence(self):
        self.last_clipboard_sequence = get_clipboard_sequence_number()

    def process_tray_commands(self):
        while True:
            try:
                command = self.tray_commands.get_nowait()
            except queue.Empty:
                break

            if command == "show":
                self.show_main_window()
            elif command == "hide":
                self.hide_to_tray()
            elif command == "quit":
                self.quit_app()
                return

        if not self._quitting:
            self.after(120, self.process_tray_commands)

    def read_sync_config_from_ui(self):
        port_text = self.sync_port_var.get().strip()
        try:
            port = int(port_text)
        except ValueError:
            messagebox.showerror("同步设置", "端口必须是 1-65535 之间的数字。")
            return None
        if not 1 <= port <= 65535:
            messagebox.showerror("同步设置", "端口必须是 1-65535 之间的数字。")
            return None

        config = default_sync_config()
        config.update(
            {
                "enabled": bool(self.sync_enabled_var.get()),
                "port": port,
                "peer_host": self.sync_peer_host_var.get().strip(),
                "shared_secret": self.sync_secret_var.get(),
                "sync_images": bool(self.sync_images_var.get()),
            }
        )
        return config

    def apply_sync_settings(self):
        config = self.read_sync_config_from_ui()
        if config is None:
            return

        self.sync_config = config
        try:
            save_sync_config(config)
        except OSError as exc:
            messagebox.showerror("同步设置", f"无法保存同步设置: {exc}")
            return

        self.restart_sync()

    def restart_sync(self):
        if self.sync_manager:
            self.sync_manager.stop()
            self.sync_manager = None

        if not self.sync_config.get("enabled"):
            self.sync_status_var.set("网络同步未启用")
            return

        self.sync_manager = ClipboardSyncManager(self.sync_config, self.sync_events)
        self.sync_manager.start()
        if self.sync_config.get("peer_host"):
            self.sync_status_var.set("网络同步启动，正在连接对端。")
        else:
            self.sync_status_var.set("网络同步启动，等待虚拟机连接。")

    def publish_sync_item(self, item):
        if self.sync_manager:
            self.sync_manager.publish(item)

    def process_sync_events(self):
        while True:
            try:
                event_type, payload = self.sync_events.get_nowait()
            except queue.Empty:
                break

            if event_type == "status":
                self.sync_status_var.set(payload)
            elif event_type == "clipboard":
                self.apply_synced_clipboard_item(payload)

        if not self._quitting:
            self.after(150, self.process_sync_events)

    def build_cleanup_message(self, removed_items, deleted_images, failed_images):
        if not removed_items:
            return ""

        cleanup_message = f" 历史已保留最近 {MAX_HISTORY} 条。"
        if deleted_images:
            cleanup_message += f" 已清理 {deleted_images} 个旧图片文件。"
        if failed_images:
            cleanup_message += f" {len(failed_images)} 个旧图片文件清理失败。"
        return cleanup_message

    def record_history_item(self, item, broadcast=False):
        self.history.insert(0, item)
        self.history, removed_items, deleted_images, failed_images = limit_history(self.history)
        self.last_digest = item["digest"]
        save_history(self.history)
        self.refresh_list()
        if broadcast:
            self.publish_sync_item(item)
        return removed_items, deleted_images, failed_images

    def apply_synced_clipboard_item(self, item):
        if not item or item.get("digest") == self.last_digest:
            return

        clipboard_message = ""
        try:
            label = write_clipboard_item(item)
            self.sync_clipboard_sequence()
            clipboard_message = f"已写入剪切板"
        except ClipboardAccessError as exc:
            clipboard_message = f"剪切板写入失败: {exc}"

        removed_items, deleted_images, failed_images = self.record_history_item(item, broadcast=False)
        cleanup_message = self.build_cleanup_message(removed_items, deleted_images, failed_images)
        self.status_var.set(f"{item['time']} 已从网络同步{cleanup_message}{clipboard_message}")

    def type_label(self, item):
        return {
            "text": "文本",
            "files": "文件",
            "image": "图片",
        }.get(item.get("type"), "其他")

    def filtered_history(self):
        keyword = self.search_var.get().strip().lower()
        if not keyword:
            return list(enumerate(self.history))
        result = []
        for index, item in enumerate(self.history):
            haystack = "\n".join(
                [
                    item.get("preview", ""),
                    item.get("text", ""),
                    "\n".join(item.get("paths", [])),
                    item.get("time", ""),
                    self.type_label(item),
                ]
            ).lower()
            if keyword in haystack:
                result.append((index, item))
        return result

    def refresh_list(self):
        selected_index = self.get_selected_history_index()
        for row in self.tree.get_children():
            self.tree.delete(row)

        for index, item in self.filtered_history():
            self.tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(item.get("time", ""), self.type_label(item), item.get("preview", "")),
            )

        if selected_index is not None and self.tree.exists(str(selected_index)):
            self.tree.selection_set(str(selected_index))
        elif self.tree.get_children():
            self.tree.selection_set(self.tree.get_children()[0])
        else:
            self.show_message("暂无记录。\n\n这个工具只能记录它运行之后复制的内容。")

    def poll_clipboard(self):
        try:
            sequence = get_clipboard_sequence_number()
            if sequence == self.last_clipboard_sequence:
                return
            self.last_clipboard_sequence = sequence

            item = read_clipboard_snapshot()
            if item and item["digest"] != self.last_digest:
                removed_items, deleted_images, failed_images = self.record_history_item(item, broadcast=True)
                cleanup_message = self.build_cleanup_message(removed_items, deleted_images, failed_images)
                self.status_var.set(f"{item['time']} 已记录新的{self.type_label(item)}内容。{cleanup_message}")
                return
        except ClipboardAccessError as exc:
            self.status_var.set(str(exc))
        except Exception as exc:
            self.status_var.set(f"读取剪切板失败: {exc}")
        finally:
            if not self._quitting:
                self.after(POLL_MS, self.poll_clipboard)

    def get_selected_history_index(self):
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def get_selected_item(self):
        index = self.get_selected_history_index()
        if index is None or index < 0 or index >= len(self.history):
            return None
        return self.history[index]

    def show_selected(self):
        item = self.get_selected_item()
        if not item:
            return

        kind = item.get("type")
        if kind == "text":
            text = item.get("text", "")
            body = text if len(text) <= MAX_TEXT_DISPLAY else text[:MAX_TEXT_DISPLAY] + "\n\n...内容太长，已截断显示。"
        elif kind == "files":
            body = "\n".join(item.get("paths", []))
        elif kind == "image":
            image_path = item.get("image_path")
            if image_path:
                body = f"检测到图片剪切板数据。\n\n图片已保存到:\n{image_path}"
            else:
                body = "检测到图片剪切板数据。\n\n这个图片格式只能检测，不能自动保存。"
        else:
            body = item.get("preview", "无法显示这种剪切板格式。")

        self.detail_title.configure(text=f"{item.get('time', '')}  {self.type_label(item)}")
        self.show_message(body)

    def show_message(self, body):
        self.detail.configure(state=tk.NORMAL)
        self.detail.delete("1.0", tk.END)
        self.detail.insert("1.0", body)
        self.detail.configure(state=tk.DISABLED)

    def copy_selected(self):
        item = self.get_selected_item()
        if not item:
            return

        try:
            label = write_clipboard_item(item)
            self.last_digest = item.get("digest")
            self.sync_clipboard_sequence()
            self.publish_sync_item(item)
            self.status_var.set(f"已把选中{label}复制回剪切板。")
        except ClipboardAccessError as exc:
            messagebox.showerror("复制失败", str(exc))

    def open_selected(self):
        item = self.get_selected_item()
        if not item:
            return

        target = None
        if item.get("type") == "image":
            target = item.get("image_path")
        elif item.get("type") == "files":
            paths = item.get("paths", [])
            target = paths[0] if paths else None

        if not target:
            messagebox.showinfo("无法打开", "当前记录没有可直接打开的文件。")
            return

        try:
            os.startfile(target)
        except OSError as exc:
            messagebox.showerror("打开失败", str(exc))

    def image_path_for_item(self, item):
        if item.get("type") != "image":
            return None

        image_path = item.get("image_path")
        if not image_path:
            return None

        path = Path(image_path)
        if path.exists():
            return path
        return None

    def edit_selected_image(self):
        item = self.get_selected_item()
        if not item:
            return
        if item.get("type") != "image":
            messagebox.showinfo("不能编辑", "只有图片记录可以打开截图编辑器。")
            return

        path = self.image_path_for_item(item)
        if path is None:
            messagebox.showinfo("不能编辑", "这条图片记录对应的图片文件不存在。")
            return

        components, error = load_screenshot_editor_components()
        if components is None:
            messagebox.showerror(
                "编辑器不可用",
                f"无法加载 screenshot_tool 的编辑器模块。\n\n{error}",
            )
            return

        open_image_editor, load_editor_settings, ScreenshotHistory = components
        try:
            if self.screenshot_editor_settings is None:
                self.screenshot_editor_settings = load_editor_settings()
            if self.screenshot_editor_history is None:
                self.screenshot_editor_history = ScreenshotHistory()

            with Image.open(path) as image:
                editor_image = image.copy()

            open_image_editor(
                self,
                editor_image,
                settings=self.screenshot_editor_settings,
                history=self.screenshot_editor_history,
                initial_fit_to_window=True,
            )
            self.status_var.set(f"已打开截图编辑器：{path}")
        except Exception as exc:
            messagebox.showerror("打开编辑器失败", str(exc))

    def location_target_for_item(self, item):
        if item.get("type") == "image":
            image_path = item.get("image_path")
            if image_path:
                path = Path(image_path)
                if path.exists():
                    return path

        if item.get("type") == "files":
            for path_text in item.get("paths", []):
                path = Path(path_text)
                if path.exists():
                    return path

        return None

    def reveal_selected_in_folder(self):
        item = self.get_selected_item()
        if not item:
            return

        target = self.location_target_for_item(item)
        if not target:
            messagebox.showinfo("无法查看", "当前记录没有可在目录中查看的路径，或文件已经不存在。")
            return

        try:
            subprocess.Popen(["explorer.exe", f"/select,{target.resolve()}"])
            self.status_var.set(f"已在目录中定位: {target}")
        except OSError as exc:
            messagebox.showerror("打开目录失败", str(exc))

    def show_tree_context_menu(self, event):
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return

        self.tree.focus(row_id)
        self.tree.selection_set(row_id)
        self.show_selected()

        item = self.get_selected_item()
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="复制", command=self.copy_selected)
        if item and self.image_path_for_item(item):
            menu.add_command(label="编辑图片", command=self.edit_selected_image)

        if item and self.location_target_for_item(item):
            menu.add_command(label="在目录中查看", command=self.reveal_selected_in_folder)

        menu.add_command(label="打开", command=self.open_selected)
        menu.add_separator()
        menu.add_command(label="删除", command=self.delete_selected)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def save_selected_text(self):
        item = self.get_selected_item()
        if not item:
            return
        if item.get("type") != "text":
            messagebox.showinfo("不能保存", "只有文本记录可以直接保存为文件。")
            return

        filename = filedialog.asksaveasfilename(
            title="保存文本",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not filename:
            return
        try:
            Path(filename).write_text(item.get("text", ""), encoding="utf-8")
            self.status_var.set(f"已保存到 {filename}")
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc))

    def is_current_clipboard_item(self, item):
        selected_digest = item.get("digest")
        if not selected_digest:
            return False

        current_item = read_clipboard_snapshot()
        current_digest = current_item.get("digest") if current_item else None
        return current_digest == selected_digest

    def next_clipboard_item_after_delete(self, deleted_index):
        if not self.history:
            return None
        if deleted_index < len(self.history):
            return self.history[deleted_index]
        return self.history[-1]

    def delete_selected(self):
        index = self.get_selected_history_index()
        if index is None:
            return
        item = self.history[index]
        item_was_current = False
        replacement_label = None
        clipboard_error = None
        image_delete_error = None

        try:
            item_was_current = self.is_current_clipboard_item(item)
        except ClipboardAccessError as exc:
            clipboard_error = str(exc)

        del self.history[index]
        deleted_images, failed_images = delete_unreferenced_image_files([item], self.history)
        deleted_synced, failed_synced = delete_unreferenced_synced_files([item], self.history)
        deleted_images += deleted_synced
        if failed_images or failed_synced:
            image_delete_error = f"{len(failed_images) + len(failed_synced)} 个文件删除失败"

        if item_was_current:
            replacement = self.next_clipboard_item_after_delete(index)
            try:
                if replacement:
                    replacement_label = write_clipboard_item(replacement)
                    self.last_digest = replacement.get("digest")
                else:
                    clear_system_clipboard()
                    self.last_digest = None
                self.sync_clipboard_sequence()
                if replacement:
                    self.publish_sync_item(replacement)
            except ClipboardAccessError as exc:
                clipboard_error = str(exc)

        save_history(self.history)
        self.refresh_list()
        if clipboard_error:
            self.status_var.set(f"已删除选中记录，但系统剪切板未能切换: {clipboard_error}")
        elif image_delete_error:
            self.status_var.set(f"已删除选中记录，但{image_delete_error}。")
        else:
            parts = ["已删除选中记录"]
            if replacement_label:
                parts.append(f"已自动切换到下一条{replacement_label}")
            elif item_was_current:
                parts.append("没有下一条可恢复内容，系统剪切板已清空")
            if deleted_images:
                parts.append(f"已删除 {deleted_images} 个图片文件")
            self.status_var.set("，".join(parts) + "。")

    def clear_history(self):
        if not self.history:
            return
        if not messagebox.askyesno("清空历史", "确定要清空本工具记录的全部剪切板历史吗？"):
            return
        try:
            clear_system_clipboard()
            self.last_digest = None
            self.sync_clipboard_sequence()
            clipboard_message = "，并已清空当前系统剪切板"
        except ClipboardAccessError as exc:
            clipboard_message = f"，但系统剪切板未清空: {exc}"
        deleted_items = list(self.history)
        self.history.clear()
        deleted_images, failed_images = delete_unreferenced_image_files(deleted_items, self.history)
        deleted_synced, failed_synced = delete_unreferenced_synced_files(deleted_items, self.history)
        save_history(self.history)
        self.refresh_list()
        total_deleted = deleted_images + deleted_synced
        total_failed = len(failed_images) + len(failed_synced)
        image_message = ""
        if total_failed:
            image_message = f"，{total_failed} 个文件删除失败"
        elif total_deleted:
            image_message = f"，并已删除 {total_deleted} 个缓存文件"
        self.status_var.set(f"历史已清空{clipboard_message}{image_message}。")


def main():
    if os.name != "nt":
        raise SystemExit("这个小应用只支持 Windows。")
    enable_dpi_awareness()
    app = ClipboardViewer()
    app.mainloop()


if __name__ == "__main__":
    main()
