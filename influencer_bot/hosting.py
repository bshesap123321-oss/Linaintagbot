"""Instagram downloads photos and videos from a public URL, so files must be reachable online.

pages  : served by GitHub Pages from this repo (default; free; photos AND videos;
         repository must be public and Pages enabled: Settings > Pages > Deploy from branch "main")
github : raw.githubusercontent.com (photos only; GitHub serves videos with a type Instagram rejects)
imgbb  : imgbb.com upload (photos only; works with private repositories)
"""
from __future__ import annotations

import base64
from pathlib import Path

import requests

from .config import ConfigError, Settings


class HostingError(Exception):
    pass


def public_url(settings: Settings, path: Path, relative_path: str, session: requests.Session | None = None) -> str:
    host = settings.media_host
    is_video = path.suffix.lower() == ".mp4"
    if host == "pages":
        settings.require("github_repository")
        owner, repo = (settings.github_repository or "").split("/", 1)
        if repo.lower() == f"{owner.lower()}.github.io":
            return f"https://{owner.lower()}.github.io/{relative_path}"
        return f"https://{owner.lower()}.github.io/{repo}/{relative_path}"
    if is_video:
        raise ConfigError("Videolar (Reels) için MEDIA_HOST=pages gerekir.")
    if host == "github":
        settings.require("github_repository", "public_ref")
        return f"https://raw.githubusercontent.com/{settings.github_repository}/{settings.public_ref}/{relative_path}"
    if host == "imgbb":
        settings.require("imgbb_api_key")
        http = session or requests.Session()
        resp = http.post(
            "https://api.imgbb.com/1/upload",
            data={"key": settings.imgbb_api_key, "image": base64.b64encode(path.read_bytes()).decode()},
            timeout=60,
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise HostingError(f"imgbb yanıtı okunamadı (HTTP {resp.status_code}).") from exc
        if not resp.ok or not payload.get("success"):
            raise HostingError(f"imgbb yükleme hatası: {payload.get('error', {}).get('message', resp.status_code)}")
        return payload["data"]["url"]
    raise ConfigError(f"Bilinmeyen MEDIA_HOST: {host!r}. 'pages', 'github' veya 'imgbb' kullanın.")
