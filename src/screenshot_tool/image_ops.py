from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, Tuple, Union

from PIL import Image, ImageDraw, ImageFilter, ImageFont

Color = Tuple[int, int, int, int]
Point = Tuple[int, int]
BBox = Tuple[int, int, int, int]


def normalize_bbox(a: Point, b: Point) -> BBox:
    x1, y1 = a
    x2, y2 = b
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def clamp_bbox(bbox: BBox, width: int, height: int) -> BBox:
    x1, y1, x2, y2 = bbox
    return (
        max(0, min(width, x1)),
        max(0, min(height, y1)),
        max(0, min(width, x2)),
        max(0, min(height, y2)),
    )


def bbox_size(bbox: BBox) -> Tuple[int, int]:
    x1, y1, x2, y2 = bbox
    return max(0, x2 - x1), max(0, y2 - y1)


def parse_color(hex_color: str, alpha: int = 255) -> Color:
    value = hex_color.lstrip("#")
    return (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
        alpha,
    )


def draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: Point,
    end: Point,
    color: Color,
    width: int,
) -> None:
    draw.line([start, end], fill=color, width=width)
    sx, sy = start
    ex, ey = end
    angle = math.atan2(ey - sy, ex - sx)
    head_length = max(14, width * 5)
    head_width = max(8, width * 3)

    left = (
        ex - head_length * math.cos(angle) + head_width * math.sin(angle) / 2,
        ey - head_length * math.sin(angle) - head_width * math.cos(angle) / 2,
    )
    right = (
        ex - head_length * math.cos(angle) - head_width * math.sin(angle) / 2,
        ey - head_length * math.sin(angle) + head_width * math.cos(angle) / 2,
    )
    draw.polygon([end, (int(left[0]), int(left[1])), (int(right[0]), int(right[1]))], fill=color)


def pixelate_region(image: Image.Image, bbox: BBox, block_size: int = 12) -> Image.Image:
    bbox = clamp_bbox(bbox, image.width, image.height)
    width, height = bbox_size(bbox)
    if width < 2 or height < 2:
        return image

    region = image.crop(bbox)
    small_size = (max(1, width // block_size), max(1, height // block_size))
    region = region.resize(small_size, Image.Resampling.BILINEAR)
    region = region.resize((width, height), Image.Resampling.NEAREST)
    result = image.copy()
    result.paste(region, bbox)
    return result


def blur_region(image: Image.Image, bbox: BBox, radius: int = 12) -> Image.Image:
    bbox = clamp_bbox(bbox, image.width, image.height)
    width, height = bbox_size(bbox)
    if width < 2 or height < 2:
        return image

    region = image.crop(bbox).filter(ImageFilter.GaussianBlur(radius=radius))
    result = image.copy()
    result.paste(region, bbox)
    return result


def apply_highlight(image: Image.Image, bbox: BBox, color: Color) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    highlight = (color[0], color[1], color[2], 80)
    draw.rectangle(bbox, fill=highlight)
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def load_ui_font(size: int, bold: bool = False) -> Union[ImageFont.FreeTypeFont, ImageFont.ImageFont]:
    candidates: Iterable[Path]
    windows_fonts = Path("C:/Windows/Fonts")
    if bold:
        candidates = (
            windows_fonts / "msyhbd.ttc",
            windows_fonts / "simhei.ttf",
            windows_fonts / "arialbd.ttf",
        )
    else:
        candidates = (
            windows_fonts / "msyh.ttc",
            windows_fonts / "simhei.ttf",
            windows_fonts / "arial.ttf",
        )

    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def draw_number_marker(
    image: Image.Image,
    point: Point,
    number: int,
    color: Color,
    size: int = 34,
) -> Image.Image:
    result = image.copy().convert("RGBA")
    draw = ImageDraw.Draw(result)
    x, y = point
    radius = size // 2
    bbox = (x - radius, y - radius, x + radius, y + radius)
    draw.ellipse(bbox, fill=color, outline=(255, 255, 255, 255), width=max(2, size // 14))

    text = str(number)
    font = load_ui_font(max(14, size // 2), bold=True)
    text_bbox = draw.textbbox((0, 0), text, font=font)
    tw = text_bbox[2] - text_bbox[0]
    th = text_bbox[3] - text_bbox[1]
    draw.text((x - tw / 2, y - th / 2 - 1), text, fill=(255, 255, 255, 255), font=font)
    return result
