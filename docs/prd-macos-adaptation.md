# ScreenshotClipboardTool macOS 适配 PRD

## 项目信息

- **Language**: 中文
- **Programming Language**: Python (Tkinter + PIL)
- **Project Name**: `screenshot_clipboard_macos`
- **原始需求**: 将深度依赖 Win32 API 的 ScreenshotClipboardTool 桌面应用适配到 macOS，使核心功能在 macOS 上可用

---

## 产品目标

让 macOS 用户能够使用与 Windows 版本对等的截图、剪切板历史、图片编辑和贴图核心功能，同时尊重 macOS 的平台惯例（如全局热键使用 Cmd 而非 Alt、开机自启通过 LaunchAgent 实现）。

---

## 用户故事

1. **As a** macOS 用户, **I want** 用全局快捷键一键触发截图/贴图/复制, **so that** 无需先切到应用窗口即可高效操作
2. **As a** macOS 用户, **I want** 剪切板历史自动记录我复制的文本、图片和文件, **so that** 我可以随时回溯和复用之前的内容
3. **As a** macOS 用户, **I want** 截图后进入编辑器进行标注（箭头、马赛克、文字等）, **so that** 我可以快速制作带标注的截图用于沟通
4. **As a** macOS 用户, **I want** 截图后以浮动窗口置顶贴在屏幕上, **so that** 我可以边看截图边在其他窗口操作
5. **As a** macOS 用户, **I want** 关闭窗口后应用缩到菜单栏图标继续运行, **so that** 热键和剪切板监听持续可用

---

## 需求池

### P0 — macOS 上核心功能可用

| # | 需求 | Win32 依赖现状 | macOS 替代方案 |
|---|------|---------------|---------------|
| P0-1 | **全局热键注册与回调** | `user32.RegisterHotKey` / 消息线程轮询 | 使用 `pynput` 的 `GlobalHotKeyListener` 或 `Quartz CGEvent` 注册系统全局热键；修饰键映射 Alt→Cmd |
| P0-2 | **剪切板读取（文本/图片/文件列表）** | `user32.OpenClipboard` / `GetClipboardData` / `kernel32.GlobalLock` | 使用 `AppKit.NSPasteboard`（pyobjc）读取 `public.utf8-plain-text`、`public.tiff`、`public.file-url` 等类型 |
| P0-3 | **剪切板写入（文本/图片/文件列表）** | `user32.SetClipboardData` / `EmptyClipboard` | 使用 `AppKit.NSPasteboard` 写入对应 UTI 类型 |
| P0-4 | **剪切板变化监听** | `user32.GetClipboardSequenceNumber` 轮询 | 使用 `AppKit.NSPasteboard.changeCount` 轮询（与 Windows 类似的轮询模式，API 更简单） |
| P0-5 | **系统托盘/菜单栏图标** | `shell32.Shell_NotifyIconW` / Win32 窗口过程 | 使用 `rumps`（基于 PyObjC）或 `pystray`（已依赖，macOS 后端可用） |
| P0-6 | **窗口自动检测（鼠标悬停识别窗口边界）** | `user32.EnumChildWindows` / `dwmapi.DwmGetWindowAttribute` | 使用 `Quartz.CGWindowListCopyWindowInfo` + `CoreGraphics` API 枚举窗口及获取边界 |
| P0-7 | **截图屏幕捕获** | `ImageGrab.grab(all_screens=True)` | `ImageGrab.grab()` 在 macOS 上可用；多屏需通过 `AppKit.NSScreen` 获取屏幕几何信息后拼接 |
| P0-8 | **跨平台抽象层** | 各模块内 `if sys.platform != "win32": return` | 引入 `PlatformAdapter` 接口，各模块通过工厂方法获取当前平台的实现 |
| P0-9 | **应用数据目录** | `os.environ.get("APPDATA")` | macOS 使用 `~/Library/Application Support/{APP_NAME}` |
| P0-10 | **图标格式** | `.ico` 格式 | macOS 使用 `.icns` 或 `.png`；Tkinter `iconphoto` 在 macOS 上可接受 PNG |

### P1 — macOS 特有体验优化

| # | 需求 | 说明 |
|---|------|------|
| P1-1 | **开机自启** | Windows 用 `winreg` 写注册表 `CurrentVersion\Run`；macOS 通过 `~/Library/LaunchAgents/{bundle_id}.plist` 实现守护进程式自启 |
| P1-2 | **DPI/Retina 适配** | Windows 需要 `SetProcessDpiAwareness(2)`；macOS Tkinter 原生支持 Retina，`enable_dpi_awareness()` 直接跳过即可 |
| P1-3 | **热键修饰键映射** | Windows 热键为 `Alt+A/S/D`、`Ctrl+Shift+M`；macOS 应映射为 `Cmd+Shift+A/S/D`、`Cmd+Shift+M`（符合 macOS 快捷键惯例） |
| P1-4 | **"打开所在文件夹"功能** | Windows 使用 `explorer.exe /select,`；macOS 使用 `open -R` 或 `NSWorkspace.activateFileViewerSelectingFiles` |
| P1-5 | **菜单栏图标行为** | Windows 是右键弹出菜单；macOS 菜单栏图标默认左键弹出菜单，支持右键（与 Windows 行为一致用 pystray 即可） |
| P1-6 | **窗口置顶行为** | macOS 上 `attributes("-topmost", True)` 对 Tkinter 部分有效但不完全；可能需要 `NSPanel` 或 `NSWindow.setLevel` 实现 |
| P1-7 | **字体回退** | Windows UI 使用 `Segoe UI`；macOS 回退到 `Helvetica Neue` 或 `SF Pro` |
| P1-8 | **应用标题栏** | macOS 不显示 `iconbitmap`；移除 `iconbitmap` 调用，仅使用 `iconphoto` |

### P2 — 未来可选

| # | 需求 | 说明 |
|---|------|------|
| P2-1 | **OCR 集成** | 当前 OCR 模块依赖 Windows 上的 Tesseract 安装路径；macOS 可通过 Homebrew 安装 Tesseract 或使用 Vision.framework |
| P2-2 | **滚动长截图** | macOS 上滚动截取逻辑不同（窗口滚动事件获取方式不同），需单独适配 |
| P2-3 | **网络同步** | 当前网络同步基于 TCP socket，理论上跨平台可用，但文件列表读取（`CF_HDROP`）需 macOS 替代 |
| P2-4 | **Touch Bar 支持** | 可选，为 MacBook Pro Touch Bar 提供截图快捷按钮 |
| P2-5 | **原生菜单栏菜单** | 使用 PyObjC 创建原生 NSMenu 替代 pystray 的跨平台菜单 |

---

## macOS 特有行为说明

### 1. 全局热键

| 行为 | Windows | macOS |
|------|---------|-------|
| 注册方式 | `user32.RegisterHotKey` | `pynput` 监听 / `Quartz CGEvent` |
| 修饰键 | Alt / Ctrl+Shift | Cmd+Shift（Alt 在 macOS 上是 Option，不适合做主修饰键） |
| 热键冲突 | 返回注册失败 | `pynput` 无法阻止其他应用消费事件，可能需 `CGEventTap` |
| 应用不在前台 | 热键仍可用 | 需要辅助功能权限（Accessibility）才能监听全局键盘事件 |

**关键差异**：macOS 上全局热键需要用户在「系统设置 > 隐私与安全性 > 辅助功能」中授权。首次启动时应引导用户授权。

### 2. 剪切板

| 行为 | Windows | macOS |
|------|---------|-------|
| API | Win32 Clipboard API | `NSPasteboard` |
| 变化检测 | `GetClipboardSequenceNumber` | `NSPasteboard.changeCount` |
| 文件列表格式 | `CF_HDROP` (DROPFILES) | `public.file-url` (NSURL 列表) |
| 图片格式 | `CF_DIB` (BMP DIB) | `public.tiff` / `public.png` |
| 写入图片 | 手动构造 DIB 数据 | 写入 `NSImage` 的 TIFF 表示 |

**关键差异**：macOS 剪切板写入后不需要手动管理内存（无需 `GlobalAlloc/GlobalFree`），`NSPasteboard` 自行管理。

### 3. 系统托盘 / 菜单栏

| 行为 | Windows | macOS |
|------|---------|-------|
| 位置 | 任务栏右下角 | 屏幕右上角菜单栏 |
| 交互 | 左键双击/右键菜单 | 左键/右键均可弹出菜单 |
| 实现 | `Shell_NotifyIconW` | `pystray`（已依赖，内部用 `rumps` 或 PyObjC） |
| 图标格式 | `.ico` | `.png` 即可 |

**关键差异**：项目已依赖 `pystray`，`clipboard_viewer.py` 中的 `TrayIcon` 类已经使用了 `pystray`，macOS 上应该可以直接使用。需要验证 `pystray` 在 macOS 上的行为。

### 4. 开机自启

| 行为 | Windows | macOS |
|------|---------|-------|
| 机制 | 注册表 `HKCU\...\Run` | `~/Library/LaunchAgents/{id}.plist` |
| 配置 | 键值对（名称 + 命令行） | XML plist（Label + ProgramArguments + RunAtLoad） |
| 用户感知 | 任务管理器"启动"选项卡可见 | 系统设置 > 通用 > 登录项 可见 |

### 5. 窗口检测

| 行为 | Windows | macOS |
|------|---------|-------|
| 枚举窗口 | `EnumChildWindows` / `GetTopWindow` | `CGWindowListCopyWindowInfo` |
| 获取窗口边界 | `GetWindowRect` / `DwmGetWindowAttribute` | `CGWindowListCopyWindowInfo` 返回的 `kCGWindowBounds` |
| 排除自身 | 通过 `HWND` 和进程 ID | 通过 `kCGWindowOwnerPID` 排除 |
| 隐藏窗口排除 | `DWMWA_CLOAKED` | `kCGWindowIsOnscreen` |

**关键差异**：macOS `CGWindowListCopyWindowInfo` 一次调用即可获取所有窗口信息（位置、大小、PID、层级），比 Win32 多次枚举更高效。

### 6. Retina / HiDPI

- macOS Tkinter 原生支持 Retina 显示，`winfo_fpixels("1i")` 返回 144（2x）而非 96
- `dpi_scale()` 函数已经能正确返回缩放因子
- `enable_dpi_awareness()` 在 macOS 上直接 `return` 即可
- 截图时 `ImageGrab.grab()` 返回的图片已经是实际像素尺寸（含 Retina 缩放），与逻辑坐标的换算需注意

---

## 待确认问题

1. **全局热键方案选型**：`pynput` vs 直接使用 `Quartz.CGEventTap`？
   - `pynput` 封装较好但可能存在事件延迟
   - `CGEventTap` 更底层但需要更多样板代码
   - 需要确认哪种方案在 macOS Sonoma/Sequoia 上稳定性更好

2. **剪切板图片写入格式**：macOS 上写入 `NSPasteboard` 时，应使用 TIFF 还是 PNG？
   - TIFF 是 macOS 原生格式，兼容性最好
   - PNG 更通用，文件更小
   - 建议同时写入两种格式

3. **辅助功能权限引导**：全局热键在 macOS 上需要辅助功能权限，如何优雅地引导用户授权？
   - 是否需要检测权限状态？
   - 是否提供跳转到系统设置的按钮？

4. **`pystray` macOS 兼容性**：项目已依赖 `pystray`，但在 macOS 上的行为是否与 Windows 一致？是否需要回退到 `rumps`？

5. **窗口检测必要性**：macOS 用户是否真的需要鼠标悬停自动识别窗口边界？macOS 原生截图工具 (`Cmd+Shift+4`) 没有此功能。可以考虑简化为手动拖选。

6. **打包方式**：macOS 上是否需要 `.app` Bundle？如果需要，使用 `py2app` 还是 `PyInstaller`？
   - `.app` Bundle 对开机自启（LaunchAgent）和辅助功能权限更友好
   - 纯脚本运行可能遇到权限问题

7. **网络同步中的文件列表**：macOS 剪切板上复制的文件列表格式为 `public.file-url`，同步协议中的 `files` 类型需要适配 macOS 的 URL 格式。

8. **滚动长截图 (P2)**：macOS 上的窗口滚动行为与 Windows 不同，是否需要在 P0/P1 阶段就禁用该功能？

9. **`iconbitmap` 兼容性**：macOS Tkinter 不支持 `iconbitmap()`，调用会抛出 `TclError`。当前代码已有 `try/except TclError` 保护，但需要确认所有调用点。
