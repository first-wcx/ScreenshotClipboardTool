from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from PIL import Image

from .config import app_data_dir


@dataclass
class HistoryItem:
    id: str
    path: str
    created_at: str
    width: int
    height: int
    thumbnail: str


class ScreenshotHistory:
    def __init__(self) -> None:
        self.directory = app_data_dir()
        self.captures_dir = self.directory / "captures"
        self.thumbnails_dir = self.directory / "thumbnails"
        self.path = self.directory / "history.json"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnails_dir.mkdir(parents=True, exist_ok=True)
        self.items: List[HistoryItem] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.items = []
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.items = []
            return
        items: List[HistoryItem] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                items.append(HistoryItem(**item))
            except TypeError:
                continue
        self.items = items

    def save(self) -> None:
        self.path.write_text(
            json.dumps([asdict(item) for item in self.items], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, image_path: Path, width: int, height: int) -> HistoryItem:
        item_id = uuid4().hex
        thumbnail_path = self.thumbnails_dir / f"{item_id}.png"
        self._make_thumbnail(image_path, thumbnail_path)
        item = HistoryItem(
            id=item_id,
            path=str(image_path),
            created_at=datetime.now().isoformat(timespec="seconds"),
            width=width,
            height=height,
            thumbnail=str(thumbnail_path),
        )
        self.items.insert(0, item)
        overflow = self.items[200:]
        self.items = self.items[:200]
        for stale in overflow:
            self._delete_item_files(stale)
        self.save()
        return item

    def add_image(self, image: Image.Image) -> HistoryItem:
        item_id = uuid4().hex
        image_path = self.captures_dir / f"{item_id}.png"
        image.convert("RGB").save(image_path, "PNG")
        return self.add(image_path, image.width, image.height)

    def recent(self, limit: int = 30) -> List[HistoryItem]:
        return self.items[:limit]

    def get(self, item_id: str) -> Optional[HistoryItem]:
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def remove(self, item_id: str) -> None:
        item = self.get(item_id)
        self.items = [existing for existing in self.items if existing.id != item_id]
        if item:
            self._delete_item_files(item)
        self.save()

    def clear_cache(self) -> int:
        removed = 0
        for directory in (self.captures_dir, self.thumbnails_dir):
            directory.mkdir(parents=True, exist_ok=True)
            for path in directory.iterdir():
                try:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                    removed += 1
                except OSError:
                    pass
        self.items = []
        self.save()
        return removed

    def _make_thumbnail(self, image_path: Path, thumbnail_path: Path) -> None:
        try:
            with Image.open(image_path) as image:
                image.thumbnail((320, 200))
                image.convert("RGB").save(thumbnail_path, "PNG")
        except OSError:
            pass

    def _delete_item_files(self, item: HistoryItem) -> None:
        try:
            Path(item.thumbnail).unlink(missing_ok=True)
        except OSError:
            pass
        try:
            image_path = Path(item.path)
            if image_path.parent.resolve() == self.captures_dir.resolve():
                image_path.unlink(missing_ok=True)
        except OSError:
            pass
