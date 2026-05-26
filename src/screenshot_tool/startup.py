from __future__ import annotations

import sys
from typing import Optional

from platform_adapter import get_adapter


def is_startup_enabled() -> bool:
    """检查开机自启是否已启用。"""
    return get_adapter().is_startup_enabled()


def set_startup_enabled(enabled: bool) -> Optional[str]:
    """设置开机自启。返回启动命令或 None。"""
    return get_adapter().set_startup_enabled(enabled)
