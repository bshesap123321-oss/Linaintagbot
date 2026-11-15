"""Orchestrates the agents: idea -> prompt -> image -> review (retry) -> caption -> publish."""
from __future__ import annotations

import logging
import random
from dataclasses import asdict
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from .agents import CaptionAgent, IdeaAgent, ImageAgent, PromptAgent, Review, ReviewAgent, idea_to_dict
from .config import Persona, Settings
from .hosting import public_url
from .imaging import to_instagram_jpeg
from .instagram import InstagramClient
from .llm import LLM, LLMError
from .storage import Post, Storage

log = logging.getLogger(__name__)


class QualityError(Exception):
    """No candidate image passed review; nothing is posted."""


def _now(persona: Persona) -> datetime:
    try:
        return datetime.now(ZoneInfo(persona.timezone))
    except Exception:  # noqa: BLE001 - bad tz name -> fall back to UTC
        return datetime.now(ZoneInfo("UTC"))


def generate(
    llm: LLM,
    persona: Persona,
    storage: Storage,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> Post:
    now = now or _now(persona)
    recent = storage.recent(persona.history_window)
    references = storage.references()
    if not references:
        log.warning("references/ klasöründe referans fotoğraf yok. Yüz tutarlılığı düşük olabilir.")

    idea = IdeaAgent(llm, persona, rng).run(
        recent_titles=[p.data.get("idea", {}).get("title", "") for p in recent],
        recent_themes=[p.data.get("theme", "") for p in recent],
        now=now,
    )
    log.info("Fikir: [%s] %s", idea.theme, idea.title)

    prompter, painter, critic = PromptAgent(persona), ImageAgent(llm, persona), ReviewAgent(llm, persona)
    attempts: list[dict] = []
    best: tuple[Review, bytes, str] | None = None
    fix_hint = ""
    for n in range(1, persona.max_attempts + 1):
        prompt = prompter.run(idea, has_reference=bool(references), fix_hint=fix_hint)
        try:
            raw = painter.run(prompt, references)
        except LLMError as exc:
            log.warning("Deneme %d: görsel üretilemedi (%s)", n, exc)
            attempts.append({"attempt": n, "error": str(exc)})
            continue
        review = critic.run(raw, idea, references)
        attempts.append({"attempt": n, **asdict(review)})
        log.info("Deneme %d: puan %.1f, yüz %.1f, onay=%s %s", n, review.score, review.face_match, review.approved,
                 ("| " + "; ".join(review.issues[:3])) if review.issues else "")
        if best is None or (review.score + review.face_match) > (best[0].score + best[0].face_match):
            best = (review, raw, prompt)
        if review.approved:
            break
        fix_hint = review.fix_hint

    if best is None or not best[0].approved:
        detail = f"en iyi puan {best[0].score:.1f}" if best else "hiç görsel üretilemedi"
        raise QualityError(f"{persona.max_attempts} denemede kaliteli görsel çıkmadı ({detail}). Bugün paylaşım yapılmadı.")

    review, raw, prompt = best
    image = to_instagram_jpeg(raw, persona.width, persona.height)
    caption = CaptionAgent(llm, persona).run(
        idea, image, recent_captions=[p.data.get("caption_text", "") for p in recent]
    )

    post = storage.new_post(now.strftime("%Y%m%d-%H%M"))
    post.dir.mkdir(parents=True, exist_ok=True)
    post.image_path.write_bytes(image)
    post.data.update(
        created_at=now.isoformat(timespec="seconds"),
        status="ready",
        theme=idea.theme,
        idea=idea_to_dict(idea),
        prompt=prompt,
        review=asdict(review),
        attempts=attempts,
        caption_text=caption.text,
        hashtags=caption.hashtags,
        caption=caption.render(persona.disclosure),
        ai_label=persona.ai_label,
    )
    post.save()
    log.info("Taslak hazır: %s", storage.relative(post.dir))
    return post


def publish(
    settings: Settings,
    storage: Storage,
    post: Post,
    client_factory: Callable[[], InstagramClient] | None = None,
) -> Post:
    if post.status == "published":
        log.info("%s zaten paylaşılmış, atlanıyor.", post.id)
        return post

    if settings.dry_run:
        post.data["status"] = "dry_run"
        post.save()
        log.info("DRY_RUN açık: Instagram'a gönderilmedi. Açıklama:\n%s", post.data["caption"])
        return post

    settings.require("ig_access_token")
    url = public_url(settings, post.image_path, storage.relative(post.image_path))
    client = (client_factory or (lambda: InstagramClient(
        settings.ig_access_token or "", settings.ig_user_id, settings.ig_api_base, settings.ig_api_version
    )))()
    try:
        result = client.publish_image(url, post.data["caption"], ai_label=post.data.get("ai_label", True))
    except Exception as exc:
        post.data.update(status="failed", error=str(exc))
        post.save()
        raise
    post.data.update(
        status="published",
        image_url=url,
        media_id=result.media_id,
        permalink=result.permalink,
        published_at=datetime.now(ZoneInfo("UTC")).isoformat(timespec="seconds"),
    )
    post.data.pop("error", None)
    post.save()
    log.info("Paylaşıldı: %s", result.permalink or result.media_id)
    return post
