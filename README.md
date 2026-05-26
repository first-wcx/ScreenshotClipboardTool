# 截图剪切板工具

这是一个独立整合版应用，合并了剪切板历史、网络同步、截图、图片编辑和贴图。

源码目录已包含运行所需的剪切板和截图编辑模块，不再依赖旁边的 `screenshot_tool` 或 `剪切板` 目录。

当前版本为了降低常驻内存和打包体积，暂时移除了 OCR 和滚动长截图入口。截图编辑器会在第一次使用截图/编辑/贴图时按需加载。

## 运行

```bat
..\.venv\Scripts\python.exe run.py
```

## 打包

```powershell
.\build_windows.ps1
```

输出文件：

```text
dist\IntegratedCaptureClipboard.exe
```

## 数据目录

运行数据统一保存在：

```text
%APPDATA%\IntegratedCaptureClipboard
```

其中包含剪切板历史、图片缓存、截图历史、缩略图和同步配置。

## 热键

默认热键可以在“同步/设置”页里修改：

- `Alt+A` 截图并复制
- `Alt+S` 截图并编辑
- `Alt+D` 截图贴图
- `Ctrl+Shift+M` 显示主窗口

## 设置项

- 截图前是否隐藏主窗口
- 开机自启
- 保存目录
- 网络同步
- 全局热键
