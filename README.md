# Integrated Capture Clipboard

跨平台截图、剪贴板历史、图片编辑和局域网同步工具。

当前仓库包含：

- Windows / macOS / Linux 桌面端 Python 应用
- Android 原生客户端
- 局域网同步模块
- 可选 relay server，用于设备发现、信令和中继扩展

## 功能

- 截图并复制到剪贴板
- 截图后编辑、标注、马赛克、裁剪和贴图
- 剪贴板历史记录
- 多设备剪贴板同步
- Android 端截图、剪贴板记录和同步管理
- 局域网设备发现、配对和 WebSocket 同步

## 系统要求

| 平台 | 要求 |
| --- | --- |
| Windows | Windows 10 / 11, Python 3.9+ |
| macOS | Python 3.9+ |
| Linux | Python 3.9+，需要对应桌面环境剪贴板/托盘支持 |
| Android | Android 10+，JDK 17，Android SDK |

## 桌面端运行

```bat
git clone https://github.com/first-wcx/ScreenshotClipboardTool.git
cd ScreenshotClipboardTool
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

macOS / Linux 使用对应 shell 激活虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

## 桌面端打包

Windows:

```powershell
.\build_windows.ps1
```

macOS:

```bash
./build_macos.sh
```

Linux:

```bash
./build_linux.sh
```

Windows 打包产物默认位于：

```text
dist\IntegratedCaptureClipboard.exe
```

## Android 构建和安装

Android 工程位于 `android/`。

首次构建前，确认本机已安装：

- JDK 17
- Android SDK
- Android SDK Build-Tools / Platform-Tools

在 `android/local.properties` 写入本机 SDK 路径。Windows 路径建议使用正斜杠：

```properties
sdk.dir=C:/Users/your-name/AppData/Local/Android/Sdk
```

构建 debug APK：

```powershell
cd android
$env:JAVA_HOME="C:\Program Files\Java\jdk-17"
.\gradlew.bat :app:assembleDebug
```

APK 输出位置：

```text
android\app\build\outputs\apk\debug\app-debug.apk
```

连接 Android 设备并安装：

```powershell
adb install -r android\app\build\outputs\apk\debug\app-debug.apk
```

如果 `adb devices` 看不到设备，请先开启手机开发者选项和 USB 调试。

## 同步服务

桌面端同步模块位于 `src/sync/`，中继服务位于 `relay_server/`。

运行 relay server：

```bash
cd relay_server
pip install -r requirements.txt
python server.py
```

也可以使用 Docker：

```bash
docker build -t icc-relay relay_server
docker run --rm -p 8080:8080 icc-relay
```

## 数据目录

桌面端运行数据默认保存在：

```text
%APPDATA%\IntegratedCaptureClipboard
```

其中包含剪贴板历史、图片缓存、截图历史、缩略图和同步配置。

Android 端截图默认保存到应用私有目录；需要图库可见时可通过 MediaStore 保存。

## 开发验证

运行 Python 测试：

```bash
pytest -q
```

运行 Android debug 构建：

```powershell
cd android
.\gradlew.bat :app:assembleDebug
```

## 许可

MIT
