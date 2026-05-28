# 截图剪贴板工具

> 当前版本仅支持 Windows。Linux、macOS 和 Android 适配已撤回，后续会在稳定后再重新规划。

这是一个集成截图、剪贴板历史、图片编辑、贴图和基础配置管理的 Windows 桌面应用。

当前版本为了降低常驻内存和打包体积，暂时移除了 OCR 和滚动长截图入口。截图编辑器会在第一次使用截图、编辑或贴图时按需加载。

## 系统要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Windows 10 / 11 |
| Python | 3.9+ |
| 主要依赖 | Pillow >= 10.0, pystray >= 0.19.0 |

## Windows 使用指南

### 直接运行

```bat
git clone https://github.com/first-wcx/ScreenshotClipboardTool.git
cd ScreenshotClipboardTool
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

### 打包为 EXE

```powershell
.\build_windows.ps1
```

打包完成后，可执行文件位于：

```text
dist\IntegratedCaptureClipboard.exe
```

双击即可运行，无需安装 Python 环境。

## 数据目录

运行数据默认保存在：

```text
%APPDATA%\IntegratedCaptureClipboard
```

其中包含剪贴板历史、图片缓存、截图历史、缩略图和配置文件。

## 默认热键

默认热键可以在设置页中修改。

| 热键 | 功能 |
| --- | --- |
| `Alt+A` | 截图并复制 |
| `Alt+S` | 截图并编辑 |
| `Alt+D` | 截图贴图 |
| `Ctrl+Shift+M` | 显示主窗口 |

## 设置项

- 截图前是否隐藏主窗口
- 开机自启
- 保存目录
- 全局热键

## 平台说明

当前代码以 Windows 桌面端为主，核心能力依赖 Win32 API：

- 全局热键：`user32.dll`
- 剪贴板监听：Win32 clipboard API
- 系统托盘：`shell32.dll` / `user32.dll`
- 窗口检测和 DPI 适配：`user32.dll` / `dwmapi.dll`
- 开机自启：Windows 注册表

Linux、macOS 和 Android 适配暂不在当前主分支提供。

## 开发验证

```bash
pytest -q
```

## 许可证

MIT
