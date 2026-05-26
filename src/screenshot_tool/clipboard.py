from __future__ import annotations

import sys
from typing import Optional

from PIL import Image

# 向后兼容：保留原始模块级函数签名，内部委托给平台适配器


def copy_image_to_clipboard(image: Image.Image) -> None:
    """将 PIL Image 复制到系统剪贴板（跨平台兼容封装）。"""
    from platform_adapter import get_adapter

    get_adapter().copy_image_to_clipboard(image)


# ------------------------------------------------------------------
# 以下函数和常量保留用于向后兼容，内部委托给适配器
# ------------------------------------------------------------------

def _copy_windows_dib(image: Image.Image) -> None:
    """已弃用：保留签名以兼容旧调用，委托给适配器。"""
    copy_image_to_clipboard(image)
