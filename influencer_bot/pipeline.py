"""Orchestration: plan -> idea -> prompt -> image (review, retry) -> [video (review, retry)] -> caption -> publish."""
from __future__ import annotations

import logging
import random
from dataclasses import asdict
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from .agents import (CaptionAgent, IdeaAgent, ImageAgent, Plan, Planner, PromptAgent, References, Review,
                     ReviewAgent, VideoAgent, to_dict)
from .config import Brand, Settings
from .hosting import public_url
from .imaging import to_instagram_jpeg
from .instagram import InstagramClient
from .llm import LLM, LLMError
from .storage import Post, Storage

log = logging.getLogger(__name__)

SIZES = {"image": (1080, 1350), "reel": (1080, 1920)}


class QualityError(Exception):
    """No candidate passed review; nothing is posted."""


def _now(brand: Brand) -> datetime:
    try:
        return datetime.now(ZoneInfo(brand.timezone))
    except Exception:  # noqa: BLE001 - bad tz name -> UTC
        return datetime.now(ZoneInfo("UTC"))


def _better(a: Review, b: Review | None) -> bool:
    return b is None or (a.score + a.identity_match + a.product_match) > (b.score + b.identity_match + b.product_match)


def _log_review(kind: str, n: int, r: Review) -> None:
    log.info("%s %d: puan %.1f · kişi %.1f · ürün %.1f · onay=%s %s", kind, n, r.score, r.identity_match,
             r.product_match, r.approved, ("| " + "; ".join(r.issues[:3])) if r.issues else "")


def generate(
    llm: LLM,
    brand: Brand,
    storage: Storage,
    now: datetime | None = None,
    rng: random.Random | None = None,
    force_format: str | None = None,
) -> Post:
    now = now or _now(brand)
    recent_posts = storage.recent(brand.history_window)
    recent = [p.data.get("plan", {}) for p in recent_posts]

    plan = Planner(brand, rng).run(storage.products(), recent, force_format)
    log.info("Plan: %s · %s · %s · %s", plan.format, plan.scene.name, ", ".join(c.name for c in plan.cast),
             plan.product.name if plan.product else "ürünsüz")
    if plan.product and not plan.product.photos:
        log.warning("'%s' için ürün fotoğrafı yok. Maske birebir çıkmayabilir: products/%s/ klasörüne fotoğraf ekleyin.",
                    plan.product.name, plan.product.id)
    refs = References.build(plan, {c.id: storage.character_refs(c.id) for c in plan.cast})

    idea = IdeaAgent(llm, brand).run(plan, [p.data.get("idea", {}).get("title", "") for p in recent_posts], now)
    log.info("Fikir: %s", idea.title)

    # ── photo / first frame ──
    prompter, painter, critic = PromptAgent(brand), ImageAgent(llm), ReviewAgent(llm, brand)
    attempts: list[dict] = []
    best: tuple[Review, bytes, str] | None = None
    fix = ""
    for n in range(1, brand.max_attempts + 1):
        prompt = prompter.run(plan, idea, refs, fix)
        try:
            raw = painter.run(prompt, refs, plan.format)
        except LLMError as exc:
            log.warning("Görsel %d üretilemedi: %s", n, exc)
            attempts.append({"kind": "image", "attempt": n, "error": str(exc)})
            continue
        review = critic.image(raw, plan, idea, refs)
        attempts.append({"kind": "image", "attempt": n, **asdict(review)})
        _log_review("Görsel", n, review)
        if _better(review, best[0] if best else None):
            best = (review, raw, prompt)
        if review.approved:
            break
        fix = review.fix_hint
    if best is None or not best[0].approved:
        detail = f"en iyi puan {best[0].score:.1f}" if best else "hiç görsel üretilemedi"
        raise QualityError(f"{brand.max_attempts} denemede kaliteli görsel çıkmadı ({detail}). Bugün paylaşım yapılmadı.")
    image_review, raw_image, image_prompt = best

    # ── reel video ──
    video_bytes, video_prompt, video_review = None, None, None
    if plan.format == "reel":
        director = VideoAgent(llm, brand)
        best_v: tuple[Review, bytes, str] | None = None
        fix = ""
        for n in range(1, brand.video_attempts + 1):
            try:
                clip, vprompt = director.run(plan, idea, raw_image, fix)
            except LLMError as exc:
                log.warning("Video %d üretilemedi: %s", n, exc)
                attempts.append({"kind": "video", "attempt": n, "error": str(exc)})
                continue
            review = critic.video(clip, plan, idea, refs)
            attempts.append({"kind": "video", "attempt": n, **asdict(review)})
            _log_review("Video", n, review)
            if _better(review, best_v[0] if best_v else None):
                best_v = (review, clip, vprompt)
            if review.approved:
                break
            fix = review.fix_hint
        if best_v is None or not best_v[0].approved:
            raise QualityError(f"{brand.video_attempts} denemede kaliteli video çıkmadı. Bugün paylaşım yapılmadı.")
        video_review, video_bytes, video_prompt = best_v

    width, height = SIZES[plan.format]
    image = to_instagram_jpeg(raw_image, width, height)
    caption = CaptionAgent(llm, brand).run(plan, idea, image, [p.data.get("caption_text", "") for p in recent_posts])

    post = storage.new_post(now.strftime("%Y%m%d-%H%M"))
    post.dir.mkdir(parents=True, exist_ok=True)
    post.image_path.write_bytes(image)
    if video_bytes:
        post.video_path.write_bytes(video_bytes)
    post.data.update(
        created_at=now.isoformat(timespec="seconds"),
        status="ready",
        format=plan.format,
        plan=plan.summary(),
        idea=to_dict(idea),
        image_prompt=image_prompt,
        video_prompt=video_prompt,
        review=asdict(video_review or image_review),
        attempts=attempts,
        caption_text=caption.text,
        hashtags=caption.hashtags,
        caption=caption.render(brand.call_to_action, brand.disclosure),
        ai_label=brand.ai_label,
    )
    post.save()
    log.info("Taslak hazır: %s", storage.relative(post.dir))
    return post


def media_url(settings: Settings, storage: Storage, post: Post) -> str:
    path = post.video_path if post.format == "reel" else post.image_path
    return public_url(settings, path, storage.relative(path))


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
    client = (client_factory or (lambda: InstagramClient(
        settings.ig_access_token or "", settings.ig_user_id, settings.ig_api_base, settings.ig_api_version
    )))()
    ai_label = post.data.get("ai_label", True)
    try:
        if post.format == "reel":
            url = media_url(settings, storage, post)
            cover = public_url(settings, post.image_path, storage.relative(post.image_path))
            result = client.publish_reel(url, post.data["caption"], cover_url=cover, ai_label=ai_label)
        else:
            url = media_url(settings, storage, post)
            result = client.publish_image(url, post.data["caption"], ai_label=ai_label)
    except Exception as exc:
        post.data.update(status="failed", error=str(exc))
        post.save()
        raise
    post.data.update(
        status="published",
        media_url=url,
        media_id=result.media_id,
        permalink=result.permalink,
        published_at=datetime.now(ZoneInfo("UTC")).isoformat(timespec="seconds"),
    )
    post.data.pop("error", None)
    if post.format == "reel" and post.video_path.exists():
        post.video_path.unlink()  # Instagram has its own copy now; keeps the repo small
    post.save()
    log.info("Paylaşıldı: %s", result.permalink or result.media_id)
    return post
