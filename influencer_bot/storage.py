"""Everything lives as plain files in the repo, so every post is versioned and auditable.

cast/<id>/*.jpg|png            reference photos of each character
products/<id>/product.yaml     product info  (+ 1-3 product photos in the same folder)
posts/<post_id>/image.jpg      final photo, or the cover/first frame of a reel
posts/<post_id>/video.mp4      reel video (removed after publishing to keep the repo small)
posts/<post_id>/post.json      idea, prompts, review scores, caption, status
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml

from .config import ConfigError

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_CHARACTER_REFS = 2
MAX_PRODUCT_REFS = 3


def _images_in(folder: Path, limit: int) -> list[bytes]:
    if not folder.is_dir():
        return []
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    return [p.read_bytes() for p in files[:limit]]


@dataclass
class Product:
    id: str
    name: str
    description: str
    price: str = ""
    sizes: str = ""
    photos: list[bytes] = field(default_factory=list, repr=False)


@dataclass
class Post:
    dir: Path
    data: dict[str, Any]

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def status(self) -> str:
        return self.data.get("status", "")

    @property
    def format(self) -> str:
        return self.data.get("format", "image")

    @property
    def image_path(self) -> Path:
        return self.dir / "image.jpg"

    @property
    def video_path(self) -> Path:
        return self.dir / "video.mp4"

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / "post.json.tmp"
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.dir / "post.json")


class Storage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.posts_dir = self.root / "posts"
        self.cast_dir = self.root / "cast"
        self.products_dir = self.root / "products"

    # ── posts ──
    def new_post(self, post_id: str) -> Post:
        d = self.posts_dir / post_id
        suffix = 2
        while d.exists():
            d = self.posts_dir / f"{post_id}-{suffix}"
            suffix += 1
        return Post(dir=d, data={"id": d.name})

    def iter_posts(self) -> Iterator[Post]:
        """Newest first."""
        if not self.posts_dir.exists():
            return
        for d in sorted((p for p in self.posts_dir.iterdir() if p.is_dir()), reverse=True):
            meta = d / "post.json"
            if meta.exists():
                yield Post(dir=d, data=json.loads(meta.read_text(encoding="utf-8")))

    def recent(self, limit: int) -> list[Post]:
        out = []
        for post in self.iter_posts():
            if post.status in {"published", "ready", "dry_run"}:
                out.append(post)
            if len(out) >= limit:
                break
        return out

    def latest_ready(self) -> Post | None:
        return next((p for p in self.iter_posts() if p.status == "ready"), None)

    def get(self, post_id: str) -> Post | None:
        return next((p for p in self.iter_posts() if p.id == post_id), None)

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    # ── cast & products ──
    def character_refs(self, character_id: str) -> list[bytes]:
        return _images_in(self.cast_dir / character_id, MAX_CHARACTER_REFS)

    def products(self) -> list[Product]:
        if not self.products_dir.is_dir():
            return []
        out = []
        for d in sorted(p for p in self.products_dir.iterdir() if p.is_dir()):
            meta = d / "product.yaml"
            if not meta.exists():
                continue
            data = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
            if not data.get("active", True):
                continue
            if not data.get("name") or not data.get("description"):
                raise ConfigError(f"{meta} içinde 'name' ve 'description' zorunlu.")
            out.append(Product(
                id=d.name, name=str(data["name"]), description=" ".join(str(data["description"]).split()),
                price=str(data.get("price", "")), sizes=str(data.get("sizes", "")),
                photos=_images_in(d, MAX_PRODUCT_REFS),
            ))
        return out
