from __future__ import annotations

import sys
from typing import List, Optional, Tuple

from platform_adapter import get_adapter

BBox = Tuple[int, int, int, int]


def detect_window_rect_at_point(
    screen_point: Tuple[int, int],
    exclude_hwnds: Optional[List[int]] = None,
    min_size: int = 18,
) -> Optional[BBox]:
    """检测指定屏幕坐标处的窗口矩形区域（跨平台兼容封装）。"""
    return get_adapter().detect_window_at_point(screen_point, exclude_hwnds)
