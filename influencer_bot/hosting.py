"""Instagram downloads the image from a public URL, so the file must be reachable online.

github : the image is committed to this repo and served from raw.githubusercontent.com
         (free, zero setup; the repository must be PUBLIC)
imgbb  : uploaded to imgbb.com (free API key; works with PRIVATE repositories)
"""
from __future__ import annotations

import base64
from pathlib import Path

import requests

from .config import ConfigError, Settings


class HostingError(Exception):
    pass


def public_url(settings: Settings, image_path: Path, relative_path: str, session: requests.Session | None = None) -> str:
    host = settings.image_host
    if host == "github":
        settings.require("github_repository", "public_ref")
        return f"https://raw.githubusercontent.com/{settings.github_repository}/{settings.public_ref}/{relative_path}"
    if host == "imgbb":
        settings.require("imgbb_api_key")
        http = session or requests.Session()
        resp = http.post(
            "https://api.imgbb.com/1/upload",
            data={"key": settings.imgbb_api_key, "image": base64.b64encode(image_path.read_bytes()).decode()},
            timeout=60,
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise HostingError(f"imgbb yanıtı okunamadı (HTTP {resp.status_code}).") from exc
        if not resp.ok or not payload.get("success"):
            raise HostingError(f"imgbb yükleme hatası: {payload.get('error', {}).get('message', resp.status_code)}")
        return payload["data"]["url"]
    raise ConfigError(f"Bilinmeyen IMAGE_HOST: {host!r}. 'github' veya 'imgbb' kullanın.")
