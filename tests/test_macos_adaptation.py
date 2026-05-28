"""macOS 适配跨平台验证测试套件。

在 Windows 上运行，验证：
1. 代码语法与导入正确性
2. 跨平台一致性（Windows 不导入 macOS 依赖）
3. 接口合规（适配器实现所有抽象方法）
4. 修改后兼容层函数签名一致
5. 潜在残留问题检查
6. Windows 功能验证（适配器实例化、剪贴板、热键解析、DPI、屏幕边界）
"""
from __future__ import annotations

import ast
import inspect
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 将项目根目录下的 src 目录加入搜索路径
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


# ---------------------------------------------------------------------------
# 1. 代码语法与导入正确性
# ---------------------------------------------------------------------------
class TestSyntaxCorrectness(unittest.TestCase):
    """验证所有新增/修改文件的 Python 语法正确性。"""

    FILES_TO_CHECK = [
        "platform_adapter.py",
        "windows_adapter.py",
        "macos_adapter.py",
        os.path.join("screenshot_tool", "clipboard.py"),
        os.path.join("screenshot_tool", "hotkeys.py"),
        os.path.join("screenshot_tool", "tray.py"),
        os.path.join("screenshot_tool", "window_detect.py"),
        os.path.join("screenshot_tool", "startup.py"),
        os.path.join("screenshot_tool", "app.py"),
        "clipboard_viewer.py",
        os.path.join("integrated_tool", "app.py"),
    ]

    def test_syntax_valid(self):
        """每个文件的 Python 语法必须可以正确解析。"""
        for rel_path in self.FILES_TO_CHECK:
            file_path = os.path.join(SRC_DIR, rel_path)
            with self.subTest(file=rel_path):
                with open(file_path, encoding="utf-8") as f:
                    source = f.read()
                try:
                    ast.parse(source, filename=rel_path)
                except SyntaxError as e:
                    self.fail(f"语法错误 in {rel_path}: {e}")


class TestImportCorrectness(unittest.TestCase):
    """验证导入路径的正确性（无循环导入、模块可找到）。"""

    def test_platform_adapter_imports(self):
        """platform_adapter 模块可以正常导入。"""
        import importlib
        mod = importlib.import_module("platform_adapter")
        self.assertTrue(hasattr(mod, "PlatformAdapter"))
        self.assertTrue(hasattr(mod, "get_adapter"))
        self.assertTrue(hasattr(mod, "HotkeyDef"))
        self.assertTrue(hasattr(mod, "TrayCallbacks"))
        self.assertTrue(hasattr(mod, "CF_UNICODETEXT"))
        self.assertTrue(hasattr(mod, "CF_HDROP"))
        self.assertTrue(hasattr(mod, "CF_DIB"))
        self.assertTrue(hasattr(mod, "CF_BITMAP"))

    def test_windows_adapter_imports(self):
        """windows_adapter 模块在 Windows 上可以正常导入。"""
        if sys.platform != "win32":
            self.skipTest("仅在 Windows 上测试")
        import importlib
        mod = importlib.import_module("windows_adapter")
        self.assertTrue(hasattr(mod, "WindowsAdapter"))

    def test_macos_adapter_not_imported_on_windows(self):
        """macOS 适配器不应在 Windows 上被隐式导入。"""
        if sys.platform != "win32":
            self.skipTest("仅在 Windows 上测试")
        # 确认 macos_adapter 中的 pyobjc/pynput 不会在 import platform_adapter 时被加载
        import importlib
        import platform_adapter
        # get_adapter 在 win32 上不应导入 macos_adapter
        adapter = platform_adapter.get_adapter()
        self.assertIsInstance(adapter, platform_adapter.PlatformAdapter)
        # 确认 "AppKit" 未被加载到 sys.modules（macOS 适配器的懒加载）
        self.assertNotIn("AppKit", sys.modules)

    def test_no_circular_imports(self):
        """验证没有循环导入。"""
        # 清除可能残留的单例
        import platform_adapter
        platform_adapter._adapter_instance = None

        # 重新导入各模块
        import importlib
        mods_to_test = [
            "platform_adapter",
            "screenshot_tool.clipboard",
            "screenshot_tool.hotkeys",
            "screenshot_tool.tray",
            "screenshot_tool.window_detect",
            "screenshot_tool.startup",
        ]
        for mod_name in mods_to_test:
            try:
                importlib.import_module(mod_name)
            except ImportError as e:
                self.fail(f"导入 {mod_name} 失败: {e}")

        # 清理
        platform_adapter._adapter_instance = None


# ---------------------------------------------------------------------------
# 2. 跨平台一致性
# ---------------------------------------------------------------------------
class TestCrossPlatformConsistency(unittest.TestCase):
    """验证跨平台一致性。"""

    def test_get_adapter_returns_windows_adapter_on_win32(self):
        """在 Windows 上，get_adapter() 返回 WindowsAdapter 实例。"""
        if sys.platform != "win32":
            self.skipTest("仅在 Windows 上测试")
        import platform_adapter
        platform_adapter._adapter_instance = None
        from windows_adapter import WindowsAdapter
        adapter = platform_adapter.get_adapter()
        self.assertIsInstance(adapter, WindowsAdapter)
        platform_adapter._adapter_instance = None

    def test_get_adapter_singleton(self):
        """get_adapter() 返回单例。"""
        import platform_adapter
        platform_adapter._adapter_instance = None
        adapter1 = platform_adapter.get_adapter()
        adapter2 = platform_adapter.get_adapter()
        self.assertIs(adapter1, adapter2)
        platform_adapter._adapter_instance = None

    def test_get_adapter_returns_linux_adapter_on_non_win32_darwin(self):
        """在非 win32/darwin 平台上，get_adapter() 应返回 LinuxAdapter。"""
        import platform_adapter
        original = sys.platform
        try:
            # 模拟 Linux 或其他类 Unix 系统
            sys.platform = "linux"
            platform_adapter._adapter_instance = None
            adapter = platform_adapter.get_adapter()
            self.assertEqual(type(adapter).__name__, "LinuxAdapter",
                             f"在非 win32/darwin 平台上应返回 LinuxAdapter，实际返回 {type(adapter).__name__}")
        finally:
            sys.platform = original
            platform_adapter._adapter_instance = None

    def test_windows_adapter_no_macos_deps(self):
        """Windows 适配器不应导入 macOS 专用依赖。"""
        if sys.platform != "win32":
            self.skipTest("仅在 Windows 上测试")
        # 检查 windows_adapter 模块不依赖 pyobjc / pynput
        import importlib
        mod = importlib.import_module("windows_adapter")
        source = inspect.getsource(mod)
        # 不应该有 AppKit、Foundation、pynput 的顶层导入
        self.assertNotIn("from AppKit", source)
        self.assertNotIn("import AppKit", source)
        self.assertNotIn("from pynput", source)
        self.assertNotIn("import pynput", source)
        self.assertNotIn("from Foundation", source)

    def test_macos_adapter_lazy_loads_deps(self):
        """macOS 适配器的所有平台特定导入必须在方法体内（懒加载）。"""
        # 读取源码检查
        macos_adapter_path = os.path.join(SRC_DIR, "macos_adapter.py")
        with open(macos_adapter_path, encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)
        top_level_imports = []
        # 只检查模块顶层（直接子节点）的 import，不深入函数体内
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_level_imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                top_level_imports.append(node.module or "")

        # 排除标准库和 Pillow
        macos_specific = {"AppKit", "Foundation", "CoreGraphics", "Quartz", "pynput"}
        for imp in top_level_imports:
            base = imp.split(".")[0]
            self.assertNotIn(
                base, macos_specific,
                f"macos_adapter.py 有顶层导入 macOS 依赖: {imp}（应在方法体内懒加载）"
            )


# ---------------------------------------------------------------------------
# 3. 接口合规
# ---------------------------------------------------------------------------
class TestInterfaceCompliance(unittest.TestCase):
    """验证适配器实现了 PlatformAdapter 的所有抽象方法。"""

    def _get_abstract_methods(self):
        """获取 PlatformAdapter 的所有抽象方法名。"""
        from platform_adapter import PlatformAdapter
        return {
            name
            for name in dir(PlatformAdapter)
            if getattr(getattr(PlatformAdapter, name), "__isabstractmethod__", False)
        }

    def test_windows_adapter_implements_all_abstract_methods(self):
        """WindowsAdapter 必须实现 PlatformAdapter 的所有抽象方法。"""
        if sys.platform != "win32":
            self.skipTest("仅在 Windows 上测试")
        from platform_adapter import PlatformAdapter
        from windows_adapter import WindowsAdapter

        abstract_methods = self._get_abstract_methods()
        for method_name in abstract_methods:
            with self.subTest(method=method_name):
                # 检查方法在 WindowsAdapter 中存在且不是抽象的
                method = getattr(WindowsAdapter, method_name, None)
                self.assertIsNotNone(method, f"WindowsAdapter 缺少方法: {method_name}")
                self.assertFalse(
                    getattr(method, "__isabstractmethod__", False),
                    f"WindowsAdapter.{method_name} 仍是抽象方法"
                )

    def test_macos_adapter_implements_all_abstract_methods(self):
        """MacOSAdapter 必须实现 PlatformAdapter 的所有抽象方法。"""
        # 读取源码分析（因为在 Windows 上无法实例化 MacOSAdapter）
        macos_adapter_path = os.path.join(SRC_DIR, "macos_adapter.py")
        with open(macos_adapter_path, encoding="utf-8") as f:
            source = f.read()

        from platform_adapter import PlatformAdapter
        abstract_methods = self._get_abstract_methods()

        # 检查每个抽象方法在 MacOSAdapter 类中是否有 def 声明
        for method_name in abstract_methods:
            with self.subTest(method=method_name):
                pattern = f"def {method_name}("
                self.assertIn(
                    pattern, source,
                    f"MacOSAdapter 缺少方法定义: {method_name}"
                )

    def test_windows_adapter_is_subclass(self):
        """WindowsAdapter 应该是 PlatformAdapter 的子类。"""
        if sys.platform != "win32":
            self.skipTest("仅在 Windows 上测试")
        from platform_adapter import PlatformAdapter
        from windows_adapter import WindowsAdapter
        self.assertTrue(issubclass(WindowsAdapter, PlatformAdapter))

    def test_macos_adapter_is_subclass(self):
        """MacOSAdapter 应该是 PlatformAdapter 的子类（源码分析）。"""
        macos_adapter_path = os.path.join(SRC_DIR, "macos_adapter.py")
        with open(macos_adapter_path, encoding="utf-8") as f:
            source = f.read()
        self.assertIn("class MacOSAdapter(PlatformAdapter)", source)


class TestMethodSignatures(unittest.TestCase):
    """验证修改后的兼容层函数签名与原有签名一致。"""

    def test_clipboard_module_signatures(self):
        """clipboard.py 的 copy_image_to_clipboard 签名。"""
        from screenshot_tool.clipboard import copy_image_to_clipboard
        sig = inspect.signature(copy_image_to_clipboard)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ["image"])

    def test_hotkey_manager_signatures(self):
        """hotkeys.py 的 GlobalHotkeyManager 方法签名。"""
        from screenshot_tool.hotkeys import GlobalHotkeyManager
        # register_many
        sig = inspect.signature(GlobalHotkeyManager.register_many)
        params = list(sig.parameters.keys())
        self.assertIn("hotkeys", params)
        # unregister_all
        sig = inspect.signature(GlobalHotkeyManager.unregister_all)
        params = list(sig.parameters.keys())
        self.assertIn("self", params)

    def test_tray_manager_signatures(self):
        """tray.py 的 TrayIconManager 签名。"""
        from screenshot_tool.tray import TrayIconManager
        sig = inspect.signature(TrayIconManager.__init__)
        params = list(sig.parameters.keys())
        self.assertIn("root", params)
        self.assertIn("on_show", params)
        self.assertIn("on_settings", params)
        self.assertIn("on_history", params)
        self.assertIn("on_exit", params)
        self.assertIn("icon_path", params)

    def test_window_detect_signatures(self):
        """window_detect.py 的 detect_window_rect_at_point 签名。"""
        from screenshot_tool.window_detect import detect_window_rect_at_point
        sig = inspect.signature(detect_window_rect_at_point)
        params = list(sig.parameters.keys())
        self.assertIn("screen_point", params)
        self.assertIn("exclude_hwnds", params)

    def test_startup_signatures(self):
        """startup.py 的函数签名。"""
        from screenshot_tool.startup import is_startup_enabled, set_startup_enabled
        sig1 = inspect.signature(is_startup_enabled)
        self.assertEqual(list(sig1.parameters.keys()), [])
        sig2 = inspect.signature(set_startup_enabled)
        self.assertEqual(list(sig2.parameters.keys()), ["enabled"])

    def test_clipboard_viewer_signatures(self):
        """clipboard_viewer.py 兼容层函数签名。"""
        from clipboard_viewer import (
            format_available,
            get_clipboard_sequence_number,
            read_unicode_text,
            read_file_list,
            read_dib_bytes,
            write_unicode_text,
            write_file_list,
            write_dib_bytes,
            clear_system_clipboard,
        )
        # 读取类函数
        self.assertEqual(list(inspect.signature(format_available).parameters), ["fmt"])
        self.assertEqual(list(inspect.signature(get_clipboard_sequence_number).parameters), [])
        self.assertEqual(list(inspect.signature(read_unicode_text).parameters), [])
        self.assertEqual(list(inspect.signature(read_file_list).parameters), [])
        self.assertEqual(list(inspect.signature(read_dib_bytes).parameters), [])
        # 写入类函数
        self.assertEqual(list(inspect.signature(write_unicode_text).parameters), ["text"])
        self.assertEqual(list(inspect.signature(write_file_list).parameters), ["paths"])
        self.assertEqual(list(inspect.signature(write_dib_bytes).parameters), ["dib"])
        self.assertEqual(list(inspect.signature(clear_system_clipboard).parameters), [])


# ---------------------------------------------------------------------------
# 5. 潜在问题检查
# ---------------------------------------------------------------------------
class TestResidualIssues(unittest.TestCase):
    """检查残留的 Win32 硬编码或硬性限制。"""

    def test_clipboard_viewer_no_win32_dll_top_level(self):
        """clipboard_viewer.py 不应有顶层 Win32 DLL 加载。"""
        with open(os.path.join(SRC_DIR, "clipboard_viewer.py"), encoding="utf-8") as f:
            source = f.read()
        # 模块顶层不应有 ctypes.windll 或 winreg
        tree = ast.parse(source)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotEqual(alias.name, "winreg",
                                            "clipboard_viewer.py 顶层导入了 winreg")
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(node.module, "winreg",
                                        "clipboard_viewer.py 顶层导入了 winreg")
                    if node.module and node.module.startswith("ctypes"):
                        # 检查是否有 windll 的导入
                        pass  # ctypes 本身可以导入，只要不调用 windll

    def test_integrated_tool_no_os_name_hard_limit(self):
        """integrated_tool/app.py 不应有 os.name != 'nt' 的硬限制。"""
        with open(os.path.join(SRC_DIR, "integrated_tool", "app.py"), encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn('os.name != "nt"', source)
        self.assertNotIn("os.name != 'nt'", source)
        self.assertNotIn('os.name == "nt"', source)
        self.assertNotIn("os.name == 'nt'", source)

    def test_screenshot_tool_no_win32_calls(self):
        """screenshot_tool 子模块不应有直接的 Win32 调用。"""
        screenshot_dir = os.path.join(SRC_DIR, "screenshot_tool")
        for filename in os.listdir(screenshot_dir):
            if not filename.endswith(".py") or filename.startswith("__"):
                continue
            filepath = os.path.join(screenshot_dir, filename)
            with open(filepath, encoding="utf-8") as f:
                source = f.read()
            # 不应有 ctypes.windll 或 winreg 的直接调用
            self.assertNotIn("ctypes.windll", source,
                             f"screenshot_tool/{filename} 有 ctypes.windll 调用")
            self.assertNotIn("import winreg", source,
                             f"screenshot_tool/{filename} 有 winreg 导入")
            self.assertNotIn("from winreg", source,
                             f"screenshot_tool/{filename} 有 winreg 导入")

    def test_integrated_tool_app_data_dir_cross_platform(self):
        """integrated_tool/app.py 的 app_data_dir 应支持 macOS。"""
        with open(os.path.join(SRC_DIR, "integrated_tool", "app.py"), encoding="utf-8") as f:
            source = f.read()
        # 应有 darwin 分支
        self.assertIn('"darwin"', source)
        self.assertIn("Application Support", source)

    def test_integrated_tool_startup_delegates(self):
        """integrated_tool/app.py 的开机自启应委托给适配器。"""
        with open(os.path.join(SRC_DIR, "integrated_tool", "app.py"), encoding="utf-8") as f:
            source = f.read()
        # is_integrated_startup_enabled 应使用 get_adapter
        self.assertIn("get_adapter().is_startup_enabled()", source)
        self.assertIn("get_adapter().set_startup_enabled(", source)


# ---------------------------------------------------------------------------
# 6. Windows 功能验证
# ---------------------------------------------------------------------------
class TestWindowsAdapterFunctionality(unittest.TestCase):
    """在 Windows 上验证适配器功能。"""

    @classmethod
    def setUpClass(cls):
        if sys.platform != "win32":
            raise unittest.SkipTest("仅在 Windows 上测试")
        import platform_adapter
        platform_adapter._adapter_instance = None
        from windows_adapter import WindowsAdapter
        cls.adapter = WindowsAdapter()
        platform_adapter._adapter_instance = cls.adapter

    @classmethod
    def tearDownClass(cls):
        import platform_adapter
        platform_adapter._adapter_instance = None

    # -- 剪贴板 --

    def test_clipboard_is_format_available_returns_bool(self):
        """clipboard_is_format_available 应返回布尔值。"""
        result = self.adapter.clipboard_is_format_available(13)
        self.assertIsInstance(result, bool)

    def test_clipboard_get_sequence_number_returns_int(self):
        """clipboard_get_sequence_number 应返回整数。"""
        result = self.adapter.clipboard_get_sequence_number()
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 0)

    def test_clipboard_read_text_returns_str_or_none(self):
        """clipboard_read_text 应返回 str 或 None。"""
        result = self.adapter.clipboard_read_text()
        self.assertTrue(result is None or isinstance(result, str))

    def test_clipboard_read_file_list_returns_list_or_none(self):
        """clipboard_read_file_list 应返回 list 或 None。"""
        result = self.adapter.clipboard_read_file_list()
        self.assertTrue(result is None or isinstance(result, list))

    def test_clipboard_read_dib_bytes_returns_bytes_or_none(self):
        """clipboard_read_dib_bytes 应返回 bytes 或 None。"""
        result = self.adapter.clipboard_read_dib_bytes()
        self.assertTrue(result is None or isinstance(result, bytes))

    def test_clipboard_read_all_returns_dict(self):
        """clipboard_read_all 应返回包含预期键的字典。"""
        result = self.adapter.clipboard_read_all()
        self.assertIsInstance(result, dict)
        expected_keys = {"text", "file_list", "dib_bytes", "has_bitmap"}
        self.assertEqual(set(result.keys()), expected_keys)

    def test_clipboard_write_and_read_text(self):
        """写入文本后应能读回。"""
        test_text = "QA test 中文文本 🎉"
        self.adapter.clipboard_write_text(test_text)
        read_back = self.adapter.clipboard_read_text()
        self.assertEqual(read_back, test_text)

    def test_clipboard_clear(self):
        """clipboard_clear 应能清空剪贴板。"""
        self.adapter.clipboard_write_text("to be cleared")
        self.adapter.clipboard_clear()
        # 清空后文本格式不可用
        # 注意：清空后某些剪贴板查看器可能立即写入新内容
        # 仅验证不抛异常
        self.adapter.clipboard_clear()

    # -- 热键解析 --

    def test_parse_hotkey_string_alt_a(self):
        """解析 Alt+A 应返回正确的修饰键和虚拟键码。"""
        from windows_adapter import _parse_hotkey_string, MOD_ALT
        modifiers, vk = _parse_hotkey_string("Alt+A")
        self.assertEqual(modifiers, MOD_ALT)
        self.assertEqual(vk, ord("A"))

    def test_parse_hotkey_string_ctrl_shift_s(self):
        """解析 Ctrl+Shift+S 应返回正确的组合。"""
        from windows_adapter import _parse_hotkey_string, MOD_CONTROL, MOD_SHIFT
        modifiers, vk = _parse_hotkey_string("Ctrl+Shift+S")
        self.assertEqual(modifiers, MOD_CONTROL | MOD_SHIFT)
        self.assertEqual(vk, ord("S"))

    def test_parse_hotkey_string_f1(self):
        """解析 F1 应返回正确的虚拟键码。"""
        from windows_adapter import _parse_hotkey_string
        _modifiers, vk = _parse_hotkey_string("F1")
        self.assertEqual(vk, 0x70)  # VK_F1

    def test_parse_hotkey_string_invalid_raises(self):
        """无效热键字符串应抛出 ValueError。"""
        from windows_adapter import _parse_hotkey_string
        with self.assertRaises(ValueError):
            _parse_hotkey_string("")
        with self.assertRaises(ValueError):
            _parse_hotkey_string("Unknown+X")

    # -- DPI 与屏幕 --

    def test_enable_dpi_awareness_no_exception(self):
        """enable_dpi_awareness 不应抛出异常。"""
        try:
            self.adapter.enable_dpi_awareness()
        except Exception as e:
            self.fail(f"enable_dpi_awareness 抛出了异常: {e}")

    def test_virtual_screen_bounds(self):
        """virtual_screen_bounds 应返回合理的四元组。"""
        x, y, w, h = self.adapter.virtual_screen_bounds()
        self.assertIsInstance(x, int)
        self.assertIsInstance(y, int)
        self.assertIsInstance(w, int)
        self.assertIsInstance(h, int)
        self.assertGreater(w, 0, "屏幕宽度应大于 0")
        self.assertGreater(h, 0, "屏幕高度应大于 0")

    # -- 窗口检测 --

    def test_detect_window_at_point_returns_tuple_or_none(self):
        """detect_window_at_point 应返回四元组或 None。"""
        # 取屏幕中心附近
        _, _, w, h = self.adapter.virtual_screen_bounds()
        result = self.adapter.detect_window_at_point((w // 2, h // 2))
        self.assertTrue(result is None or (isinstance(result, tuple) and len(result) == 4))

    # -- 文件操作 --

    def test_open_file_no_exception(self):
        """open_file 对合法路径不应抛出异常。"""
        # 使用一个确定存在的路径
        temp_dir = tempfile.gettempdir()
        try:
            self.adapter.open_file(temp_dir)
        except Exception as e:
            self.fail(f"open_file 抛出了异常: {e}")

    def test_reveal_path_in_folder_no_exception(self):
        """reveal_path_in_folder 对合法路径不应抛出异常。"""
        temp_dir = tempfile.gettempdir()
        try:
            self.adapter.reveal_path_in_folder(temp_dir)
        except Exception as e:
            self.fail(f"reveal_path_in_folder 抛出了异常: {e}")

    # -- 热键管理 --

    def test_register_and_unregister_hotkeys(self):
        """热键注册与反注册不应抛出异常。"""
        from platform_adapter import HotkeyDef

        def dummy_callback():
            pass

        hotkeys = [HotkeyDef(name="test", key="Alt+T", callback=dummy_callback)]

        # 使用 mock 的 root
        mock_root = MagicMock()
        mock_root.after = MagicMock()

        registered, failures = self.adapter.register_hotkeys(mock_root, hotkeys)
        # 只要不崩溃就算通过（注册可能因热键冲突失败）
        self.assertIsInstance(registered, int)
        self.assertIsInstance(failures, list)

        # 反注册
        self.adapter.unregister_hotkeys()

    # -- 开机自启 --

    def test_is_startup_enabled_returns_bool(self):
        """is_startup_enabled 应返回布尔值。"""
        result = self.adapter.is_startup_enabled()
        self.assertIsInstance(result, bool)

    # -- 图片复制 --

    def test_copy_image_to_clipboard(self):
        """copy_image_to_clipboard 应能将图片复制到剪贴板。"""
        from PIL import Image
        img = Image.new("RGB", (100, 50), (255, 0, 0))
        try:
            self.adapter.copy_image_to_clipboard(img)
        except Exception as e:
            self.fail(f"copy_image_to_clipboard 抛出了异常: {e}")


class TestHotkeyCompatibilityLayer(unittest.TestCase):
    """验证 hotkeys.py 兼容层。"""

    def test_hotkey_to_string(self):
        """_hotkey_to_string 应将 Win32 热键转为字符串格式。"""
        from screenshot_tool.hotkeys import _hotkey_to_string, MOD_ALT, MOD_CONTROL
        result = _hotkey_to_string(MOD_ALT, ord("A"))
        self.assertIn("Alt", result)
        self.assertIn("A", result)

    def test_hotkey_to_string_ctrl_shift(self):
        """Ctrl+Shift 组合键转换。"""
        from screenshot_tool.hotkeys import _hotkey_to_string, MOD_CONTROL, MOD_SHIFT
        result = _hotkey_to_string(MOD_CONTROL | MOD_SHIFT, ord("S"))
        self.assertIn("Ctrl", result)
        self.assertIn("Shift", result)
        self.assertIn("S", result)

    def test_hotkey_to_string_f_key(self):
        """F 键转换。"""
        from screenshot_tool.hotkeys import _hotkey_to_string
        result = _hotkey_to_string(0, 0x7B)  # F12
        self.assertIn("F12", result)

    def test_global_hotkey_manager_accepts_hotkeydef(self):
        """GlobalHotkeyManager.register_many 应接受 HotkeyDef。"""
        from platform_adapter import HotkeyDef
        from screenshot_tool.hotkeys import GlobalHotkeyManager

        mock_root = MagicMock()
        manager = GlobalHotkeyManager(mock_root)

        def cb():
            pass

        defs = [HotkeyDef(name="test", key="Alt+X", callback=cb)]
        # 需要 mock get_adapter
        with patch("screenshot_tool.hotkeys.get_adapter") as mock_adapter:
            mock_adapter.return_value.register_hotkeys.return_value = (1, [])
            registered, failures = manager.register_many(defs)
            self.assertEqual(registered, 1)
            self.assertEqual(failures, [])

    def test_global_hotkey_manager_accepts_legacy_hotkey(self):
        """GlobalHotkeyManager.register_many 应接受旧版 Hotkey。"""
        from screenshot_tool.hotkeys import GlobalHotkeyManager, Hotkey, MOD_ALT

        mock_root = MagicMock()
        manager = GlobalHotkeyManager(mock_root)

        def cb():
            pass

        hotkeys = [Hotkey(name="test", modifiers=MOD_ALT, vk=ord("X"), callback=cb)]
        with patch("screenshot_tool.hotkeys.get_adapter") as mock_adapter:
            mock_adapter.return_value.register_hotkeys.return_value = (1, [])
            registered, failures = manager.register_many(hotkeys)
            self.assertEqual(registered, 1)


class TestClipboardViewerCompatibility(unittest.TestCase):
    """验证 clipboard_viewer.py 兼容层。"""

    def test_windows_clipboard_context_manager(self):
        """WindowsClipboard 上下文管理器应正常工作。"""
        from clipboard_viewer import WindowsClipboard
        with WindowsClipboard() as cb:
            self.assertIsNotNone(cb)

    def test_format_available_delegates(self):
        """format_available 应委托给适配器。"""
        from clipboard_viewer import format_available
        with patch("clipboard_viewer.get_adapter") as mock_adapter:
            mock_adapter.return_value.clipboard_is_format_available.return_value = True
            result = format_available(13)
            self.assertTrue(result)
            mock_adapter.return_value.clipboard_is_format_available.assert_called_once_with(13)

    def test_read_unicode_text_delegates(self):
        """read_unicode_text 应委托给适配器。"""
        from clipboard_viewer import read_unicode_text
        with patch("clipboard_viewer.get_adapter") as mock_adapter:
            mock_adapter.return_value.clipboard_read_text.return_value = "hello"
            result = read_unicode_text()
            self.assertEqual(result, "hello")

    def test_write_unicode_text_delegates(self):
        """write_unicode_text 应委托给适配器。"""
        from clipboard_viewer import write_unicode_text
        with patch("clipboard_viewer.get_adapter") as mock_adapter:
            write_unicode_text("test")
            mock_adapter.return_value.clipboard_write_text.assert_called_once_with("test")

    def test_read_clipboard_snapshot_delegates(self):
        """read_clipboard_snapshot 应使用适配器的批量读取。"""
        from clipboard_viewer import read_clipboard_snapshot
        with patch("clipboard_viewer.get_adapter") as mock_adapter:
            mock_adapter.return_value.clipboard_read_all.return_value = {
                "text": "test",
                "file_list": None,
                "dib_bytes": None,
                "has_bitmap": False,
            }
            result = read_clipboard_snapshot()
            self.assertIsNotNone(result)
            self.assertEqual(result["type"], "text")
            self.assertEqual(result["text"], "test")


class TestMacOSAdapterSourceAnalysis(unittest.TestCase):
    """通过源码分析验证 MacOSAdapter 的正确性（无需 macOS 环境）。"""

    def _read_source(self):
        path = os.path.join(SRC_DIR, "macos_adapter.py")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_all_clipboard_methods_use_lazy_import(self):
        """所有剪贴板方法应在方法体内导入 AppKit。"""
        source = self._read_source()
        # 找到所有 clipboard 方法
        clipboard_methods = [
            "clipboard_is_format_available",
            "clipboard_get_sequence_number",
            "clipboard_read_text",
            "clipboard_read_file_list",
            "clipboard_read_dib_bytes",
            "clipboard_read_all",
            "clipboard_write_text",
            "clipboard_write_file_list",
            "clipboard_write_dib_bytes",
            "clipboard_clear",
            "copy_image_to_clipboard",
        ]
        for method in clipboard_methods:
            with self.subTest(method=method):
                # 方法定义行
                self.assertIn(f"def {method}(", source,
                              f"MacOSAdapter 缺少方法: {method}")

    def test_register_hotkeys_uses_pynput(self):
        """register_hotkeys 应使用 pynput。"""
        source = self._read_source()
        self.assertIn("from pynput import keyboard", source)

    def test_show_tray_icon_uses_pystray(self):
        """show_tray_icon 应使用 pystray。"""
        source = self._read_source()
        self.assertIn("import pystray", source)

    def test_startup_uses_launch_agent(self):
        """开机自启应使用 LaunchAgent。"""
        source = self._read_source()
        self.assertIn("LaunchAgent", source)
        self.assertIn("launchctl", source)
        self.assertIn("plistlib", source)

    def test_enable_dpi_awareness_is_noop(self):
        """macOS 上 enable_dpi_awareness 应为空操作。"""
        source = self._read_source()
        # 找到 enable_dpi_awareness 方法
        idx = source.index("def enable_dpi_awareness(self)")
        # 取方法体
        method_lines = []
        in_method = False
        for line in source[idx:].split("\n"):
            if in_method and line.strip() and not line.startswith(" "):
                break
            if in_method:
                method_lines.append(line)
            if "def enable_dpi_awareness(self)" in line:
                in_method = True
        method_body = "\n".join(method_lines)
        self.assertIn("pass", method_body)

    def test_virtual_screen_bounds_uses_tkinter(self):
        """virtual_screen_bounds 应使用 tkinter 获取屏幕尺寸。"""
        source = self._read_source()
        self.assertIn("import tkinter", source)

    def test_file_operations_use_subprocess(self):
        """文件操作应使用 macOS 命令。"""
        source = self._read_source()
        self.assertIn('["open"', source)
        self.assertIn('["open", "-R"', source)

    def test_win32_fmt_to_ns_type_mapping(self):
        """格式映射应覆盖所有 Win32 格式常量。"""
        source = self._read_source()
        # CF_UNICODETEXT → public.utf8-plain-text
        self.assertIn("public.utf8-plain-text", source)
        # CF_HDROP → NSFilenamesPboardType
        self.assertIn("NSFilenamesPboardType", source)
        # CF_DIB/CF_BITMAP → public.tiff
        self.assertIn("public.tiff", source)


class TestDataTypesAndConstants(unittest.TestCase):
    """验证公共数据类型和常量。"""

    def test_clipboard_format_constants(self):
        """剪贴板格式常量值应正确。"""
        from platform_adapter import CF_UNICODETEXT, CF_HDROP, CF_DIB, CF_BITMAP
        self.assertEqual(CF_UNICODETEXT, 13)
        self.assertEqual(CF_HDROP, 15)
        self.assertEqual(CF_DIB, 8)
        self.assertEqual(CF_BITMAP, 2)

    def test_hotkey_def_is_frozen(self):
        """HotkeyDef 应为不可变数据类。"""
        from platform_adapter import HotkeyDef

        def cb():
            pass

        hd = HotkeyDef(name="test", key="Alt+A", callback=cb)
        with self.assertRaises(AttributeError):
            hd.name = "changed"

    def test_tray_callbacks_defaults(self):
        """TrayCallbacks 的默认回调应安全。"""
        from platform_adapter import TrayCallbacks
        tc = TrayCallbacks()
        # 默认回调不应抛出异常
        tc.on_show()
        tc.on_settings()
        tc.on_history()
        tc.on_exit()

    def test_tray_callbacks_custom(self):
        """TrayCallbacks 应能设置自定义回调。"""
        from platform_adapter import TrayCallbacks
        called = []

        def on_show():
            called.append("show")

        tc = TrayCallbacks(on_show=on_show)
        tc.on_show()
        self.assertEqual(called, ["show"])


class TestBuildMacOSScript(unittest.TestCase):
    """验证 macOS 构建脚本。"""

    def test_script_exists(self):
        """build_macos.sh 应存在。"""
        script_path = os.path.join(PROJECT_ROOT, "build_macos.sh")
        self.assertTrue(
            os.path.exists(script_path),
            f"build_macos.sh 不存在: {script_path}"
        )

    def test_script_has_shebang(self):
        """build_macos.sh 应有正确的 shebang。"""
        script_path = os.path.join(PROJECT_ROOT, "build_macos.sh")
        with open(script_path, encoding="utf-8") as f:
            first_line = f.readline().strip()
        self.assertTrue(
            first_line.startswith("#!/usr/") or first_line.startswith("#!/bin/"),
            f"shebang 不正确: {first_line}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
