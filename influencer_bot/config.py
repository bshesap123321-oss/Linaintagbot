"""Settings: brand file (brand.yaml) + environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Raised when a required setting is missing or invalid."""


@dataclass(frozen=True)
class Character:
    id: str
    name: str
    appearance: str
    style: str = ""


@dataclass(frozen=True)
class Scene:
    name: str
    weight: float = 1.0
    min_people: int = 1
    max_people: int = 2


def _squash(text: Any) -> str:
    return " ".join(str(text or "").split())


@dataclass(frozen=True)
class Brand:
    name: str
    about: str
    voice: str
    cast: list[Character]
    scenes: list[Scene]
    language: str = "tr"
    timezone: str = "UTC"
    handle: str = ""
    call_to_action: str = ""
    formats: dict[str, float] = field(default_factory=lambda: {"image": 1.0})
    always_hashtags: list[str] = field(default_factory=list)
    hashtag_count: int = 12
    ai_label: bool = True
    disclosure: str = ""
    content_rules: list[str] = field(default_factory=list)
    max_attempts: int = 3
    min_score: float = 7
    history_window: int = 20
    video_attempts: int = 2
    photo_style: str = ""
    video_style: str = ""

    def character(self, cid: str) -> Character:
        for c in self.cast:
            if c.id == cid:
                return c
        raise KeyError(cid)

    @classmethod
    def load(cls, path: str | Path) -> "Brand":
        path = Path(path)
        if not path.exists():
            raise ConfigError(f"Marka dosyası bulunamadı: {path}")
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key in ("name", "about", "voice", "cast", "scenes"):
            if not data.get(key):
                raise ConfigError(f"brand.yaml içinde '{key}' alanı eksik.")

        cast = []
        for raw in data["cast"]:
            if not raw.get("id") or not raw.get("appearance"):
                raise ConfigError("Her karakterin 'id' ve 'appearance' alanı olmalı.")
            cast.append(Character(id=str(raw["id"]), name=str(raw.get("name", raw["id"])),
                                  appearance=_squash(raw["appearance"]), style=_squash(raw.get("style"))))
        if len({c.id for c in cast}) != len(cast):
            raise ConfigError("Karakter id'leri benzersiz olmalı.")

        scenes = []
        for raw in data["scenes"]:
            lo, hi = (raw.get("people") or [1, 2]) if isinstance(raw, dict) else (1, 2)
            name = raw["name"] if isinstance(raw, dict) else str(raw)
            weight = float(raw.get("weight", 1)) if isinstance(raw, dict) else 1.0
            lo, hi = max(1, int(lo)), min(len(cast), int(hi))
            if weight <= 0 or lo > hi:
                raise ConfigError(f"Sahne ayarı hatalı: {name}")
            scenes.append(Scene(name=name, weight=weight, min_people=lo, max_people=hi))

        formats = {k: float(v) for k, v in (data.get("formats") or {"image": 1}).items() if float(v) > 0}
        if not formats or set(formats) - {"image", "reel"}:
            raise ConfigError("formats yalnızca 'image' ve 'reel' içerebilir ve en az biri açık olmalı.")

        tags = data.get("hashtags") or {}
        review = data.get("review") or {}
        count = int(tags.get("count", 12))
        if not 0 <= count <= 30:
            raise ConfigError("hashtags.count 0 ile 30 arasında olmalı (Instagram sınırı).")

        return cls(
            name=str(data["name"]),
            handle=str(data.get("handle", "")),
            about=_squash(data["about"]),
            voice=_squash(data["voice"]),
            cast=cast,
            scenes=scenes,
            language=data.get("language", "tr"),
            timezone=data.get("timezone", "UTC"),
            call_to_action=str(data.get("call_to_action", "")).strip(),
            formats=formats,
            always_hashtags=[_normalize_tag(t) for t in tags.get("always", [])],
            hashtag_count=count,
            ai_label=bool(data.get("ai_label", True)),
            disclosure=str(data.get("disclosure", "")).strip(),
            content_rules=list(data.get("content_rules", [])),
            max_attempts=max(1, int(review.get("max_attempts", 3))),
            min_score=float(review.get("min_score", 7)),
            history_window=int(review.get("history_window", 20)),
            video_attempts=max(1, int(review.get("video_attempts", 2))),
            photo_style=_squash(data.get("photo_style")),
            video_style=_squash(data.get("video_style")),
        )


def _normalize_tag(tag: str) -> str:
    tag = tag.strip().replace(" ", "")
    return tag if tag.startswith("#") else f"#{tag}"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "evet"}


ENV_NAMES = {
    "gemini_api_key": "GEMINI_API_KEY",
    "ig_access_token": "IG_ACCESS_TOKEN",
    "ig_user_id": "IG_USER_ID",
    "imgbb_api_key": "IMGBB_API_KEY",
    "github_repository": "GITHUB_REPOSITORY",
    "public_ref": "PUBLIC_REF",
}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    brand_file: Path
    gemini_api_key: str | None
    text_model: str
    image_model: str
    video_model: str
    ig_access_token: str | None
    ig_user_id: str | None
    ig_api_base: str
    ig_api_version: str
    media_host: str
    imgbb_api_key: str | None
    github_repository: str | None
    public_ref: str | None
    dry_run: bool
    force_format: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("DATA_DIR", ".")).resolve()
        fmt = (os.getenv("FORCE_FORMAT") or "").strip().lower() or None
        if fmt not in (None, "image", "reel"):
            raise ConfigError("FORCE_FORMAT 'image' ya da 'reel' olmalı.")
        return cls(
            data_dir=data_dir,
            brand_file=Path(os.getenv("BRAND_FILE", data_dir / "brand.yaml")),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            text_model=os.getenv("GEMINI_TEXT_MODEL") or "gemini-flash-latest",
            image_model=os.getenv("GEMINI_IMAGE_MODEL") or "gemini-3.1-flash-image",
            video_model=os.getenv("GEMINI_VIDEO_MODEL") or "veo-3.1-fast-generate-preview",
            ig_access_token=os.getenv("IG_ACCESS_TOKEN") or None,
            ig_user_id=os.getenv("IG_USER_ID") or None,
            ig_api_base=(os.getenv("IG_API_BASE") or "https://graph.instagram.com").rstrip("/"),
            ig_api_version=os.getenv("IG_API_VERSION") or "v26.0",
            media_host=(os.getenv("MEDIA_HOST") or "pages").lower(),
            imgbb_api_key=os.getenv("IMGBB_API_KEY") or None,
            github_repository=os.getenv("GITHUB_REPOSITORY") or None,
            public_ref=os.getenv("PUBLIC_REF") or None,
            dry_run=_env_bool("DRY_RUN"),
            force_format=fmt,
        )

    def require(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            pretty = ", ".join(ENV_NAMES.get(n, n) for n in missing)
            raise ConfigError(f"Eksik ayar(lar): {pretty}. GitHub > Settings > Secrets bölümüne ekleyin.")
