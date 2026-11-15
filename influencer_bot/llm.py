"""Thin, retrying wrapper around the Gemini API (google-genai SDK)."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Protocol, Sequence, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")

TRANSIENT_CODES = {408, 429, 500, 502, 503, 504}


class LLMError(Exception):
    """The model failed or returned something unusable."""


class LLM(Protocol):
    """What the agents need from a model provider. Easy to fake in tests."""

    def generate_json(self, prompt: str, schema: dict[str, Any], images: Sequence[bytes] = ()) -> dict[str, Any]: ...

    def generate_image(self, prompt: str, reference_images: Sequence[bytes] = (), aspect_ratio: str = "4:5") -> bytes: ...


def with_retry(fn: Callable[[], T], *, attempts: int = 4, base_delay: float = 2.0, what: str = "istek") -> T:
    """Retry transient API failures with exponential backoff."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - we re-raise non-transient errors below
            code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
            transient = code in TRANSIENT_CODES or isinstance(exc, (TimeoutError, ConnectionError))
            if not transient or attempt == attempts:
                raise
            delay = base_delay * 2 ** (attempt - 1)
            log.warning("%s başarısız (%s). %.0f sn sonra tekrar denenecek (%d/%d).", what, code or exc, delay, attempt, attempts)
            time.sleep(delay)
    raise AssertionError("unreachable")


def _sniff_mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


class GeminiLLM:
    """Gemini implementation of the LLM protocol."""

    def __init__(self, api_key: str, text_model: str, image_model: str):
        from google import genai  # imported lazily so tests don't need network/SDK setup
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=api_key)
        self.text_model = text_model
        self.image_model = image_model

    def _parts(self, prompt: str, images: Sequence[bytes]) -> list[Any]:
        parts: list[Any] = [self._types.Part.from_bytes(data=img, mime_type=_sniff_mime(img)) for img in images]
        parts.append(prompt)
        return parts

    def generate_json(self, prompt: str, schema: dict[str, Any], images: Sequence[bytes] = ()) -> dict[str, Any]:
        config = self._types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=schema,
            temperature=0.9,
        )
        response = with_retry(
            lambda: self._client.models.generate_content(
                model=self.text_model, contents=self._parts(prompt, images), config=config
            ),
            what="Gemini metin isteği",
        )
        text = (response.text or "").strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Model geçerli JSON döndürmedi: {text[:200]!r}") from exc
        if not isinstance(data, dict):
            raise LLMError("Model beklenen JSON nesnesini döndürmedi.")
        return data

    def generate_image(self, prompt: str, reference_images: Sequence[bytes] = (), aspect_ratio: str = "4:5") -> bytes:
        config = self._types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=self._types.ImageConfig(aspect_ratio=aspect_ratio),
        )
        response = with_retry(
            lambda: self._client.models.generate_content(
                model=self.image_model, contents=self._parts(prompt, reference_images), config=config
            ),
            what="Gemini görsel isteği",
        )
        for candidate in response.candidates or []:
            for part in (candidate.content.parts if candidate.content else None) or []:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data
        reason = ""
        if response.candidates:
            reason = str(response.candidates[0].finish_reason or "")
        raise LLMError(f"Model görsel döndürmedi. {reason}".strip())
