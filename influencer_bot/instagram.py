"""Instagram content publishing (Instagram API with Instagram Login).

Flow: create media container -> wait until FINISHED -> media_publish.
Docs: https://developers.facebook.com/docs/instagram-platform/content-publishing
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

log = logging.getLogger(__name__)


class InstagramError(Exception):
    pass


@dataclass
class PublishResult:
    media_id: str
    permalink: str | None


class InstagramClient:
    def __init__(
        self,
        access_token: str,
        user_id: str | None = None,
        api_base: str = "https://graph.instagram.com",
        api_version: str = "v26.0",
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.token = access_token
        self.user_id = user_id
        self.base = f"{api_base.rstrip('/')}/{api_version}"
        self.root = api_base.rstrip("/")
        self.http = session or requests.Session()
        self.sleep = sleep

    # ── low level ──
    def _request(self, method: str, url: str, **params: Any) -> dict[str, Any]:
        params["access_token"] = self.token
        kwargs: dict[str, Any] = {"timeout": 60}
        kwargs["data" if method == "POST" else "params"] = params
        for attempt in range(1, 4):
            try:
                resp = self.http.request(method, url, **kwargs)
            except requests.RequestException as exc:
                if attempt == 3:
                    raise InstagramError(f"Instagram'a bağlanılamadı: {exc}") from exc
                self.sleep(5 * attempt)
                continue
            if resp.status_code >= 500 and attempt < 3:
                self.sleep(5 * attempt)
                continue
            try:
                payload = resp.json()
            except ValueError:
                payload = {}
            if not resp.ok or "error" in payload:
                err = payload.get("error", {})
                msg = err.get("error_user_msg") or err.get("message") or resp.text[:200]
                raise InstagramError(f"Instagram API hatası (HTTP {resp.status_code}, kod {err.get('code')}): {msg}")
            return payload
        raise AssertionError("unreachable")

    # ── account ──
    def me(self) -> dict[str, Any]:
        return self._request("GET", f"{self.base}/me", fields="user_id,username,account_type")

    def resolve_user_id(self) -> str:
        if not self.user_id:
            self.user_id = str(self.me()["user_id"])
        return self.user_id

    def refresh_token(self) -> dict[str, Any]:
        """Long-lived tokens last 60 days; refreshing returns a new 60-day token."""
        return self._request("GET", f"{self.root}/refresh_access_token", grant_type="ig_refresh_token")

    # ── publishing ──
    def publish_image(self, image_url: str, caption: str, ai_label: bool = True,
                      timeout: float = 180, poll: float = 5) -> PublishResult:
        return self._publish({"image_url": image_url, "caption": caption}, ai_label, timeout, poll)

    def publish_reel(self, video_url: str, caption: str, cover_url: str | None = None, ai_label: bool = True,
                     timeout: float = 600, poll: float = 10) -> PublishResult:
        params: dict[str, Any] = {"media_type": "REELS", "video_url": video_url, "caption": caption,
                                  "share_to_feed": "true"}
        if cover_url:
            params["cover_url"] = cover_url
        return self._publish(params, ai_label, timeout, poll)

    def _publish(self, params: dict[str, Any], ai_label: bool, timeout: float, poll: float) -> PublishResult:
        uid = self.resolve_user_id()
        if ai_label:
            params["is_ai_generated"] = "true"  # Instagram's official "AI info" label
        container = self._request("POST", f"{self.base}/{uid}/media", **params)["id"]
        log.info("Medya kapsayıcısı oluşturuldu: %s", container)

        waited = 0.0
        while True:
            status = self._request("GET", f"{self.base}/{container}", fields="status_code,status").get("status_code")
            if status in ("FINISHED", None):
                break
            if status in ("ERROR", "EXPIRED"):
                raise InstagramError(f"Instagram medyayı işleyemedi (durum: {status}). Dosya URL'si herkese açık mı?")
            if waited >= timeout:
                raise InstagramError("Instagram medyayı zamanında işlemedi.")
            self.sleep(poll)
            waited += poll

        media_id = self._request("POST", f"{self.base}/{uid}/media_publish", creation_id=container)["id"]
        permalink = None
        try:
            permalink = self._request("GET", f"{self.base}/{media_id}", fields="permalink").get("permalink")
        except InstagramError as exc:  # the post is live; a missing link is not fatal
            log.warning("Paylaşım linki alınamadı: %s", exc)
        return PublishResult(media_id=str(media_id), permalink=permalink)
