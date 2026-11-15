"""Settings: persona file + environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Raised when a required setting is missing or invalid."""


@dataclass(frozen=True)
class Theme:
    name: str
    weight: float = 1.0


@dataclass(frozen=True)
class Persona:
    name: str
    appearance: str
    personality: str
    voice: str
    photo_style: str
    themes: list[Theme]
    language: str = "tr"
    timezone: str = "UTC"
    handle: str = ""
    always_hashtags: list[str] = field(default_factory=list)
    hashtag_count: int = 10
    disclosure: str = ""
    ai_label: bool = True
    content_rules: list[str] = field(default_factory=list)
    max_attempts: int = 3
    min_score: float = 7
    history_window: int = 20
    aspect_ratio: str = "4:5"
    width: int = 1080
    height: int = 1350

    @classmethod
    def load(cls, path: str | Path) -> "Persona":
        path = Path(path)
        if not path.exists():
            raise ConfigError(f"Persona dosyası bulunamadı: {path}")
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

        for key in ("name", "appearance", "personality", "voice", "photo_style", "themes"):
            if not data.get(key):
                raise ConfigError(f"persona.yaml içinde '{key}' alanı eksik.")

        themes = [
            Theme(name=t["name"], weight=float(t.get("weight", 1))) if isinstance(t, dict) else Theme(name=str(t))
            for t in data["themes"]
        ]
        if any(t.weight <= 0 for t in themes):
            raise ConfigError("Tema ağırlıkları 0'dan büyük olmalı.")

        tags = data.get("hashtags") or {}
        review = data.get("review") or {}
        image = data.get("image") or {}
        count = int(tags.get("count", 10))
        if not 0 <= count <= 30:
            raise ConfigError("hashtags.count 0 ile 30 arasında olmalı (Instagram sınırı).")

        return cls(
            name=data["name"],
            handle=data.get("handle", ""),
            appearance=" ".join(data["appearance"].split()),
            personality=data["personality"].strip(),
            voice=data["voice"].strip(),
            photo_style=" ".join(data["photo_style"].split()),
            themes=themes,
            language=data.get("language", "tr"),
            timezone=data.get("timezone", "UTC"),
            always_hashtags=[_normalize_tag(t) for t in tags.get("always", [])],
            hashtag_count=count,
            disclosure=data.get("disclosure", "").strip(),
            ai_label=bool(data.get("ai_label", True)),
            content_rules=list(data.get("content_rules", [])),
            max_attempts=max(1, int(review.get("max_attempts", 3))),
            min_score=float(review.get("min_score", 7)),
            history_window=int(review.get("history_window", 20)),
            aspect_ratio=str(image.get("aspect_ratio", "4:5")),
            width=int(image.get("width", 1080)),
            height=int(image.get("height", 1350)),
        )


def _normalize_tag(tag: str) -> str:
    tag = tag.strip().replace(" ", "")
    return tag if tag.startswith("#") else f"#{tag}"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "evet"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    persona_file: Path
    gemini_api_key: str | None
    text_model: str
    image_model: str
    ig_access_token: str | None
    ig_user_id: str | None
    ig_api_base: str
    ig_api_version: str
    image_host: str
    imgbb_api_key: str | None
    github_repository: str | None
    public_ref: str | None
    dry_run: bool

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("DATA_DIR", ".")).resolve()
        return cls(
            data_dir=data_dir,
            persona_file=Path(os.getenv("PERSONA_FILE", data_dir / "persona.yaml")),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            text_model=os.getenv("GEMINI_TEXT_MODEL") or "gemini-flash-latest",
            image_model=os.getenv("GEMINI_IMAGE_MODEL") or "gemini-3.1-flash-image",
            ig_access_token=os.getenv("IG_ACCESS_TOKEN") or None,
            ig_user_id=os.getenv("IG_USER_ID") or None,
            ig_api_base=(os.getenv("IG_API_BASE") or "https://graph.instagram.com").rstrip("/"),
            ig_api_version=os.getenv("IG_API_VERSION") or "v26.0",
            image_host=(os.getenv("IMAGE_HOST") or "github").lower(),
            imgbb_api_key=os.getenv("IMGBB_API_KEY") or None,
            github_repository=os.getenv("GITHUB_REPOSITORY") or None,
            public_ref=os.getenv("PUBLIC_REF") or None,
            dry_run=_env_bool("DRY_RUN"),
        )

    def require(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            env_names = {
                "gemini_api_key": "GEMINI_API_KEY",
                "ig_access_token": "IG_ACCESS_TOKEN",
                "ig_user_id": "IG_USER_ID",
                "imgbb_api_key": "IMGBB_API_KEY",
                "github_repository": "GITHUB_REPOSITORY",
                "public_ref": "PUBLIC_REF",
            }
            pretty = ", ".join(env_names.get(n, n) for n in missing)
            raise ConfigError(f"Eksik ayar(lar): {pretty}. GitHub > Settings > Secrets bölümüne ekleyin.")
