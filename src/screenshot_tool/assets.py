from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageTk

from .config import app_data_dir


def bundled_resource_path(filename: str) -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "screenshot_tool" / "resources" / filename
    return Path(__file__).resolve().parent / "resources" / filename


def ensure_app_icon() -> Path:
    bundled = bundled_resource_path("app_icon.ico")
    if bundled.exists():
        return bundled

    path = app_data_dir() / "app_icon_2026.ico"
    path.parent.mkdir(parents=True, exist_ok=True)
    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((18, 18, size - 18, size - 18), radius=54, fill=(6, 12, 24, 255))
    draw.rounded_rectangle((26, 26, size - 26, size - 26), radius=46, outline=(19, 35, 58, 255), width=4)

    for offset, color in ((0, (56, 189, 248, 255)), (16, (125, 211, 252, 90))):
        draw.line((74 + offset, 72, 74 + offset, 112), fill=color, width=12)
        draw.line((74 + offset, 72, 114 + offset, 72), fill=color, width=12)
        draw.line((182 - offset, 72, 142 - offset, 72), fill=color, width=12)
        draw.line((182 - offset, 72, 182 - offset, 112), fill=color, width=12)
        draw.line((74 + offset, 184, 74 + offset, 144), fill=color, width=12)
        draw.line((74 + offset, 184, 114 + offset, 184), fill=color, width=12)
        draw.line((182 - offset, 184, 142 - offset, 184), fill=color, width=12)
        draw.line((182 - offset, 184, 182 - offset, 144), fill=color, width=12)

    draw.rounded_rectangle((102, 102, 154, 154), radius=14, outline=(45, 212, 191, 255), width=8)
    draw.ellipse((119, 119, 137, 137), fill=(248, 250, 252, 255))
    draw.line((84, 128, 172, 128), fill=(148, 163, 184, 150), width=4)
    draw.line((128, 84, 128, 172), fill=(148, 163, 184, 120), width=4)
    image.save(path, sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
    return path


def load_app_icon_photo() -> Optional[ImageTk.PhotoImage]:
    icon_path = ensure_app_icon()
    try:
        with Image.open(icon_path) as image:
            return ImageTk.PhotoImage(image.resize((32, 32), Image.Resampling.LANCZOS))
    except OSError:
        return None
