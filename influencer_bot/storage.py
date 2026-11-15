"""Posts are stored as plain files in the repo, so every post is versioned and auditable.

posts/<post_id>/image.jpg   final 1080x1350 JPEG
posts/<post_id>/post.json   idea, prompt, review scores, caption, status
references/*.jpg|png        reference photos of the character (optional, recommended)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

REFERENCE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_REFERENCES = 3


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
    def image_path(self) -> Path:
        return self.dir / "image.jpg"

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / "post.json.tmp"
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.dir / "post.json")


class Storage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.posts_dir = self.root / "posts"
        self.references_dir = self.root / "references"

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

    def references(self) -> list[bytes]:
        if not self.references_dir.exists():
            return []
        files = sorted(p for p in self.references_dir.iterdir() if p.suffix.lower() in REFERENCE_EXTS)
        return [p.read_bytes() for p in files[:MAX_REFERENCES]]

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()
