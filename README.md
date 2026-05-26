# 截图剪切板工具

> ⚠️ **仅支持 Windows** — 本工具深度依赖 Win32 API（全局热键、剪切板监听、系统托盘、窗口检测、DPI 适配等），目前无法在 Linux 或 macOS 上运行。

集成截图、剪切板历史、图片编辑、贴图和网络同步的 Windows 桌面应用。

当前版本为了降低常驻内存和打包体积，暂时移除了 OCR 和滚动长截图入口。截图编辑器会在第一次使用截图/编辑/贴图时按需加载。

## 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 / 11 |
| Python | 3.9+ |
| 依赖 | Pillow ≥ 10.0、pystray ≥ 0.19.0 |

## Windows 使用指南

### 方式一：直接运行（开发/调试）

1. **克隆仓库**

   ```bat
   git clone https://github.com/first-wcx/ScreenshotClipboardTool.git
   cd ScreenshotClipboardTool
   ```

2. **创建虚拟环境并安装依赖**

   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **启动应用**

   ```bat
   python run.py
   ```

### 方式二：打包为 EXE（免安装分发）

```powershell
.\build_windows.ps1
```

打包完成后，可执行文件位于：

```text
dist\IntegratedCaptureClipboard.exe
```

双击即可运行，无需安装 Python 环境。

> 💡 打包依赖 [PyInstaller](https://pyinstaller.org/)，首次打包会自动安装。

## 数据目录

运行数据统一保存在：

```text
%APPDATA%\IntegratedCaptureClipboard
```

其中包含剪切板历史、图片缓存、截图历史、缩略图和同步配置。

## 热键

默认热键可以在"同步/设置"页里修改：

| 热键 | 功能 |
|------|------|
| `Alt+A` | 截图并复制 |
| `Alt+S` | 截图并编辑 |
| `Alt+D` | 截图贴图 |
| `Ctrl+Shift+M` | 显示主窗口 |

## 设置项

- 截图前是否隐藏主窗口
- 开机自启（写入注册表 `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`）
- 保存目录
- 网络同步
- 全局热键

## 关于 Linux / macOS 支持

本工具核心功能依赖 Win32 API，暂不支持其他平台：

- **全局热键** → 依赖 `user32.dll` 的 `RegisterHotKey` / `UnregisterHotKey`
- **剪切板监听** → 依赖 `user32.dll` / `kernel32.dll` 的 Win32 剪切板 API
- **系统托盘** → 依赖 `shell32.dll` / `user32.dll` 的通知图标 API
- **窗口检测** → 依赖 `user32.dll` / `dwmapi.dll` 的窗口枚举与 DPI 适配
- **开机自启** → 依赖 `winreg` 读写注册表

如需在 Linux/macOS 上使用类似功能，需要分别替换为对应平台的方案（如 `python-xlib` / `pynput` 监听热键，`pyperclip` 访问剪切板，`ayatana-appindicator` 系统托盘等），欢迎贡献代码。

## 许可证

MIT
