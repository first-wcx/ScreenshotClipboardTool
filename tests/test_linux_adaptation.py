"""Linux 适配跨平台验证测试套件。

在 Windows 上运行，验证：
1. 代码语法正确性（linux_adapter.py 可 ast.parse）
2. 懒导入合规性（顶层无 pynput/pystray/xlib 导入）
3. 接口合规（LinuxAdapter 实现 PlatformAdapter 所有抽象方法）
4. platform_adapter.py 更新验证（else 分支含 LinuxAdapter，无 RuntimeError）
5. pyproject.toml 验证（linux 可选依赖存在）
6. build_linux.sh 语法验证（文件存在且含 pyinstaller 命令）
7. Windows 隔离验证（get_adapter 在 Windows 返回 WindowsAdapter，不触发 linux_adapter 导入）
8. LinuxAdapter 方法数量验证（>= 22 个方法）
9. 兼容层未破坏验证（clipboard/hotkeys/startup 可正常导入）
"""
from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 将项目根目录下的 src 目录加入搜索路径
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


# ---------------------------------------------------------------------------
# 1. 语法正确性
# ---------------------------------------------------------------------------
class TestLinuxAdapterSyntax(unittest.TestCase):
    """验证 linux_adapter.py 的 Python 语法正确性。"""

    def test_linux_adapter_ast_parse(self):
        """linux_adapter.py 必须可以 ast.parse，无 SyntaxError。"""
        file_path = os.path.join(SRC_DIR, "linux_adapter.py")
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        try:
            ast.parse(source, filename="linux_adapter.py")
        except SyntaxError as e:
            self.fail(f"语法错误 in linux_adapter.py: {e}")


# ---------------------------------------------------------------------------
# 2. 懒导入合规性
# ---------------------------------------------------------------------------
class TestLinuxAdapterLazyImports(unittest.TestCase):
    """验证 linux_adapter.py 的顶层导入不含 Linux 专用依赖。"""

    def test_no_top_level_pynput_import(self):
        """顶层不应有 pynput 导入（应在方法体内懒加载）。"""
        file_path = os.path.join(SRC_DIR, "linux_adapter.py")
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)

        top_level_imports = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_level_imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                top_level_imports.append(node.module or "")

        linux_specific = {"pynput", "pystray", "Xlib", "xlib"}
        for imp in top_level_imports:
            base = imp.split(".")[0]
            self.assertNotIn(
                base, linux_specific,
                f"linux_adapter.py 有顶层导入 Linux 依赖: {imp}（应在方法体内懒加载）"
            )

    def test_pynput_import_inside_method(self):
        """pynput 应在方法体内导入（懒加载）。"""
        file_path = os.path.join(SRC_DIR, "linux_adapter.py")
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        # pynput 应在 register_hotkeys 方法体内导入
        self.assertIn("from pynput", source,
                      "linux_adapter.py 应在方法体内导入 pynput")

    def test_pystray_import_inside_method(self):
        """pystray 应在方法体内导入（懒加载）。"""
        file_path = os.path.join(SRC_DIR, "linux_adapter.py")
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        self.assertIn("import pystray", source,
                      "linux_adapter.py 应在方法体内导入 pystray")


# ---------------------------------------------------------------------------
# 3. 接口合规
# ---------------------------------------------------------------------------
class TestLinuxAdapterInterfaceCompliance(unittest.TestCase):
    """验证 LinuxAdapter 实现了 PlatformAdapter 所有抽象方法。"""

    def _get_abstract_methods(self):
        """获取 PlatformAdapter 的所有抽象方法名。"""
        from platform_adapter import PlatformAdapter
        return {
            name
            for name in dir(PlatformAdapter)
            if getattr(getattr(PlatformAdapter, name), "__isabstractmethod__", False)
        }

    def test_linux_adapter_implements_all_abstract_methods(self):
        """LinuxAdapter 必须实现 PlatformAdapter 的所有抽象方法。"""
        file_path = os.path.join(SRC_DIR, "linux_adapter.py")
        with open(file_path, encoding="utf-8") as f:
            source = f.read()

        abstract_methods = self._get_abstract_methods()
        for method_name in abstract_methods:
            with self.subTest(method=method_name):
                pattern = f"def {method_name}("
                self.assertIn(
                    pattern, source,
                    f"LinuxAdapter 缺少方法定义: {method_name}"
                )

    def test_linux_adapter_is_subclass(self):
        """LinuxAdapter 应该是 PlatformAdapter 的子类（源码分析）。"""
        file_path = os.path.join(SRC_DIR, "linux_adapter.py")
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        self.assertIn("class LinuxAdapter(PlatformAdapter)", source)

    def test_get_adapter_returns_linux_adapter_on_linux(self):
        """在 Linux 平台上，get_adapter() 应返回 LinuxAdapter 实例。"""
        import platform_adapter
        original_platform = sys.platform
        original_instance = platform_adapter._adapter_instance
        try:
            sys.platform = "linux"
            platform_adapter._adapter_instance = None
            adapter = platform_adapter.get_adapter()
            self.assertEqual(type(adapter).__name__, "LinuxAdapter",
                             f"在 Linux 上 get_adapter() 应返回 LinuxAdapter，实际返回 {type(adapter).__name__}")
        finally:
            sys.platform = original_platform
            platform_adapter._adapter_instance = original_instance


# ---------------------------------------------------------------------------
# 4. platform_adapter.py 更新验证
# ---------------------------------------------------------------------------
class TestPlatformAdapterUpdate(unittest.TestCase):
    """验证 platform_adapter.py 已正确更新以支持 Linux。"""

    def test_linux_adapter_in_source(self):
        """platform_adapter.py 应包含 LinuxAdapter 字符串。"""
        file_path = os.path.join(SRC_DIR, "platform_adapter.py")
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        self.assertIn("LinuxAdapter", source,
                      "platform_adapter.py 未包含 LinuxAdapter 引用")

    def test_else_branch_has_linux_adapter_import(self):
        """platform_adapter.py 的 else 分支应导入并实例化 LinuxAdapter。"""
        file_path = os.path.join(SRC_DIR, "platform_adapter.py")
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        # 验证 else 分支中有 LinuxAdapter 的导入和实例化
        self.assertIn("from linux_adapter import LinuxAdapter", source,
                      "platform_adapter.py 未在 else 分支导入 LinuxAdapter")

    def test_no_runtime_error_in_else_branch(self):
        """platform_adapter.py 的 else 分支不应再 raise RuntimeError。"""
        file_path = os.path.join(SRC_DIR, "platform_adapter.py")
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        # 使用 AST 分析，确认 else 分支没有 raise RuntimeError
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise):
                if isinstance(node.exc, ast.Call):
                    if isinstance(node.exc.func, ast.Name) and node.exc.func.id == "RuntimeError":
                        self.fail("platform_adapter.py 仍有 raise RuntimeError 调用")

    def test_get_adapter_no_error_on_linux_platform(self):
        """mock sys.platform 为 'linux' 时 get_adapter() 不应抛异常。"""
        import platform_adapter
        original_platform = sys.platform
        original_instance = platform_adapter._adapter_instance
        try:
            sys.platform = "linux"
            platform_adapter._adapter_instance = None
            try:
                adapter = platform_adapter.get_adapter()
                self.assertIsNotNone(adapter)
            except Exception as e:
                self.fail(f"在 Linux 平台上 get_adapter() 抛出异常: {e}")
        finally:
            sys.platform = original_platform
            platform_adapter._adapter_instance = original_instance


# ---------------------------------------------------------------------------
# 5. pyproject.toml 验证
# ---------------------------------------------------------------------------
class TestPyprojectToml(unittest.TestCase):
    """验证 pyproject.toml 中的 Linux 可选依赖。"""

    def test_linux_optional_dependencies_exist(self):
        """pyproject.toml 应包含 [project.optional-dependencies] linux 段。"""
        toml_path = os.path.join(PROJECT_ROOT, "pyproject.toml")
        with open(toml_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("linux", content.split("[project.optional-dependencies]")[1]
                      if "[project.optional-dependencies]" in content else "",
                      "pyproject.toml 缺少 linux 可选依赖段")

    def test_linux_deps_include_pynput(self):
        """Linux 可选依赖应包含 pynput。"""
        toml_path = os.path.join(PROJECT_ROOT, "pyproject.toml")
        with open(toml_path, encoding="utf-8") as f:
            content = f.read()
        # 找到 linux 段落
        self.assertIn("pynput", content,
                      "pyproject.toml 的 Linux 依赖缺少 pynput")

    def test_linux_deps_include_python_xlib(self):
        """Linux 可选依赖应包含 python-xlib。"""
        toml_path = os.path.join(PROJECT_ROOT, "pyproject.toml")
        with open(toml_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("python-xlib", content,
                      "pyproject.toml 的 Linux 依赖缺少 python-xlib")


# ---------------------------------------------------------------------------
# 6. build_linux.sh 语法验证
# ---------------------------------------------------------------------------
class TestBuildLinuxScript(unittest.TestCase):
    """验证 build_linux.sh 构建脚本。"""

    def test_script_exists(self):
        """build_linux.sh 应存在。"""
        script_path = os.path.join(PROJECT_ROOT, "build_linux.sh")
        self.assertTrue(
            os.path.exists(script_path),
            f"build_linux.sh 不存在: {script_path}"
        )

    def test_script_has_shebang(self):
        """build_linux.sh 应有正确的 shebang。"""
        script_path = os.path.join(PROJECT_ROOT, "build_linux.sh")
        with open(script_path, encoding="utf-8") as f:
            first_line = f.readline().strip()
        self.assertTrue(
            first_line.startswith("#!/usr/") or first_line.startswith("#!/bin/"),
            f"shebang 不正确: {first_line}"
        )

    def test_script_has_pyinstaller(self):
        """build_linux.sh 应包含 pyinstaller 命令。"""
        script_path = os.path.join(PROJECT_ROOT, "build_linux.sh")
        with open(script_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("pyinstaller", content,
                      "build_linux.sh 缺少 pyinstaller 命令")


# ---------------------------------------------------------------------------
# 7. Windows 隔离验证
# ---------------------------------------------------------------------------
class TestWindowsIsolation(unittest.TestCase):
    """验证 Linux 适配器不会在 Windows 上被意外导入。"""

    def setUp(self):
        """每个测试前重置适配器单例。"""
        import platform_adapter
        self._original_instance = platform_adapter._adapter_instance
        platform_adapter._adapter_instance = None

    def tearDown(self):
        """每个测试后恢复适配器单例。"""
        import platform_adapter
        platform_adapter._adapter_instance = self._original_instance

    @unittest.skipUnless(sys.platform == "win32", "仅在 Windows 上测试")
    def test_get_adapter_returns_windows_adapter_on_win32(self):
        """在 Windows 上，get_adapter() 应返回 WindowsAdapter 实例。"""
        import platform_adapter
        from windows_adapter import WindowsAdapter
        adapter = platform_adapter.get_adapter()
        self.assertIsInstance(adapter, WindowsAdapter,
                              f"在 Windows 上 get_adapter() 应返回 WindowsAdapter，实际返回 {type(adapter).__name__}")

    @unittest.skipUnless(sys.platform == "win32", "仅在 Windows 上测试")
    def test_linux_adapter_not_in_sys_modules(self):
        """在 Windows 上调用 get_adapter() 后，linux_adapter 不应在 sys.modules 中。"""
        import platform_adapter
        # 先确保 linux_adapter 不在 sys.modules
        if "linux_adapter" in sys.modules:
            del sys.modules["linux_adapter"]
        # 调用 get_adapter
        adapter = platform_adapter.get_adapter()
        # linux_adapter 不应被导入
        self.assertNotIn("linux_adapter", sys.modules,
                         "在 Windows 上 get_adapter() 不应触发 linux_adapter 导入")

    @unittest.skipUnless(sys.platform == "win32", "仅在 Windows 上测试")
    def test_no_pynput_in_sys_modules_on_windows(self):
        """在 Windows 上调用 get_adapter() 后，pynput 不应在 sys.modules 中。"""
        import platform_adapter
        # 确保无残留
        for mod in list(sys.modules.keys()):
            if mod.startswith("pynput"):
                del sys.modules[mod]
        adapter = platform_adapter.get_adapter()
        pynput_loaded = any(mod.startswith("pynput") for mod in sys.modules)
        self.assertFalse(pynput_loaded,
                          "在 Windows 上 get_adapter() 不应触发 pynput 导入")


# ---------------------------------------------------------------------------
# 8. LinuxAdapter 方法数量验证
# ---------------------------------------------------------------------------
class TestLinuxAdapterMethodCount(unittest.TestCase):
    """验证 LinuxAdapter 类中的方法数量。"""

    def test_method_count_at_least_22(self):
        """LinuxAdapter 类中定义的方法数量应 >= 22。"""
        file_path = os.path.join(SRC_DIR, "linux_adapter.py")
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)

        # 找到 LinuxAdapter 类定义
        linux_adapter_class = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "LinuxAdapter":
                linux_adapter_class = node
                break

        self.assertIsNotNone(linux_adapter_class, "未找到 LinuxAdapter 类定义")

        # 统计方法数量（仅统计 def 语句，即函数/方法定义）
        method_count = sum(
            1 for item in linux_adapter_class.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        self.assertGreaterEqual(
            method_count, 22,
            f"LinuxAdapter 定义了 {method_count} 个方法，期望 >= 22"
        )


# ---------------------------------------------------------------------------
# 9. 兼容层未破坏验证
# ---------------------------------------------------------------------------
class TestCompatibilityLayerIntact(unittest.TestCase):
    """验证现有兼容层模块仍可正常导入。"""

    def setUp(self):
        """每个测试前重置适配器单例。"""
        import platform_adapter
        self._original_instance = platform_adapter._adapter_instance
        platform_adapter._adapter_instance = None

    def tearDown(self):
        """每个测试后恢复适配器单例。"""
        import platform_adapter
        platform_adapter._adapter_instance = self._original_instance

    def test_clipboard_module_importable(self):
        """screenshot_tool.clipboard 应可正常导入。"""
        import importlib
        try:
            mod = importlib.import_module("screenshot_tool.clipboard")
        except ImportError as e:
            self.fail(f"导入 screenshot_tool.clipboard 失败: {e}")

    def test_hotkeys_module_importable(self):
        """screenshot_tool.hotkeys 应可正常导入。"""
        import importlib
        try:
            mod = importlib.import_module("screenshot_tool.hotkeys")
        except ImportError as e:
            self.fail(f"导入 screenshot_tool.hotkeys 失败: {e}")

    def test_startup_module_importable(self):
        """screenshot_tool.startup 应可正常导入。"""
        import importlib
        try:
            mod = importlib.import_module("screenshot_tool.startup")
        except ImportError as e:
            self.fail(f"导入 screenshot_tool.startup 失败: {e}")


# ---------------------------------------------------------------------------
# 10. LinuxAdapter 源码分析（跨平台细节验证）
# ---------------------------------------------------------------------------
class TestLinuxAdapterSourceAnalysis(unittest.TestCase):
    """通过源码分析验证 LinuxAdapter 的关键实现特征。"""

    def _read_source(self):
        path = os.path.join(SRC_DIR, "linux_adapter.py")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_clipboard_uses_xclip(self):
        """剪贴板操作应使用 xclip。"""
        source = self._read_source()
        self.assertIn("xclip", source,
                      "LinuxAdapter 剪贴板操作应使用 xclip")

    def test_clipboard_has_xsel_fallback(self):
        """剪贴板操作应有 xsel 回退方案。"""
        source = self._read_source()
        self.assertIn("xsel", source,
                      "LinuxAdapter 剪贴板操作应有 xsel 回退")

    def test_window_detect_uses_xdotool(self):
        """窗口检测应使用 xdotool。"""
        source = self._read_source()
        self.assertIn("xdotool", source,
                      "LinuxAdapter 窗口检测应使用 xdotool")

    def test_startup_uses_xdg_autostart(self):
        """开机自启应使用 XDG autostart .desktop 文件。"""
        source = self._read_source()
        self.assertIn("autostart", source.lower(),
                      "LinuxAdapter 开机自启应使用 XDG autostart")
        self.assertIn(".desktop", source.lower(),
                      "LinuxAdapter 开机自启应使用 .desktop 文件")

    def test_file_open_uses_xdg_open(self):
        """文件打开应使用 xdg-open。"""
        source = self._read_source()
        self.assertIn("xdg-open", source,
                      "LinuxAdapter 文件操作应使用 xdg-open")

    def test_enable_dpi_awareness_is_noop(self):
        """Linux 上 enable_dpi_awareness 应为空操作。"""
        source = self._read_source()
        # 找到 enable_dpi_awareness 方法
        idx = source.find("def enable_dpi_awareness(self)")
        if idx == -1:
            self.fail("LinuxAdapter 缺少 enable_dpi_awareness 方法")
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
        self.assertIn("pass", method_body,
                      "LinuxAdapter.enable_dpi_awareness 应为 pass（空操作）")

    def test_virtual_screen_bounds_uses_tkinter(self):
        """virtual_screen_bounds 应使用 tkinter 获取屏幕尺寸。"""
        source = self._read_source()
        self.assertIn("import tkinter", source,
                      "LinuxAdapter.virtual_screen_bounds 应使用 tkinter")

    def test_hotkey_parse_supports_modifiers(self):
        """热键解析应支持 Ctrl/Shift/Alt/Super 修饰键。"""
        source = self._read_source()
        self.assertIn("<ctrl>", source,
                      "热键解析应支持 Ctrl → <ctrl> 映射")
        self.assertIn("<shift>", source,
                      "热键解析应支持 Shift → <shift> 映射")
        self.assertIn("<alt>", source,
                      "热键解析应支持 Alt → <alt> 映射")

    def test_tray_uses_pystray(self):
        """托盘图标应使用 pystray。"""
        source = self._read_source()
        self.assertIn("pystray", source,
                      "LinuxAdapter 托盘图标应使用 pystray")

    def test_reveal_path_supports_file_managers(self):
        """reveal_path_in_folder 应支持常见 Linux 文件管理器。"""
        source = self._read_source()
        self.assertIn("nautilus", source,
                      "LinuxAdapter 应支持 nautilus 文件管理器")


if __name__ == "__main__":
    unittest.main(verbosity=2)
