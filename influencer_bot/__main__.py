"""Command line interface.

  python -m influencer_bot generate        create today's post (image + caption), do not publish
  python -m influencer_bot publish         publish the newest ready post
  python -m influencer_bot run             generate + publish in one go (MEDIA_HOST=imgbb, photos only)
  python -m influencer_bot media-url       print the public URL of the newest ready post
  python -m influencer_bot check           verify keys, brand file, cast photos and products
  python -m influencer_bot refresh-token   print a fresh 60-day Instagram token
  python -m influencer_bot summary         print a Markdown report of the newest post
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from .config import Brand, ConfigError, Settings
from .storage import Storage

log = logging.getLogger("influencer_bot")

EXIT_OK, EXIT_ERROR, EXIT_QUALITY = 0, 1, 3


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    for noisy in ("httpx", "urllib3", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _llm(settings: Settings):
    from .llm import GeminiLLM

    settings.require("gemini_api_key")
    return GeminiLLM(settings.gemini_api_key or "", settings.text_model, settings.image_model, settings.video_model)


def _ig(settings: Settings):
    from .instagram import InstagramClient

    settings.require("ig_access_token")
    return InstagramClient(settings.ig_access_token or "", settings.ig_user_id, settings.ig_api_base, settings.ig_api_version)


def cmd_generate(settings: Settings, args: argparse.Namespace) -> int:
    from .pipeline import generate

    brand = Brand.load(settings.brand_file)
    post = generate(_llm(settings), brand, Storage(settings.data_dir), force_format=settings.force_format)
    print(post.id)
    return EXIT_OK


def cmd_publish(settings: Settings, args: argparse.Namespace) -> int:
    from .pipeline import publish

    storage = Storage(settings.data_dir)
    post = storage.get(args.post_id) if args.post_id else storage.latest_ready()
    if post is None:
        log.error("Paylaşılacak hazır gönderi bulunamadı.")
        return EXIT_ERROR
    publish(settings, storage, post)
    return EXIT_OK


def cmd_run(settings: Settings, args: argparse.Namespace) -> int:
    from .pipeline import generate, publish

    if settings.media_host != "imgbb" and not settings.dry_run:
        raise ConfigError("'run' komutu MEDIA_HOST=imgbb ile çalışır. GitHub'da 'generate' ve 'publish' ayrı çalıştırılır.")
    storage = Storage(settings.data_dir)
    post = generate(_llm(settings), Brand.load(settings.brand_file), storage, force_format="image")
    publish(settings, storage, post)
    return EXIT_OK


def cmd_check(settings: Settings, args: argparse.Namespace) -> int:
    ok = True
    storage = Storage(settings.data_dir)
    try:
        brand = Brand.load(settings.brand_file)
        print(f"✅ Marka: {brand.name} · {len(brand.cast)} karakter · {len(brand.scenes)} sahne · türler: {', '.join(brand.formats)}")
        for c in brand.cast:
            n = len(storage.character_refs(c.id))
            print(f"   {'✅' if n else '⚠️ '} {c.name}: {n} referans fotoğraf" + ("" if n else f" (cast/{c.id}/ klasörüne ekleyin)"))
        products = storage.products()
        print(f"{'✅' if products else '⚠️ '} Ürün: {len(products)} adet")
        for p in products:
            print(f"   {'✅' if p.photos else '⚠️ '} {p.name}: {len(p.photos)} fotoğraf" + ("" if p.photos else f" (products/{p.id}/ klasörüne ekleyin)"))
    except ConfigError as exc:
        print(f"❌ Marka: {exc}")
        ok = False
    try:
        reply = _llm(settings).generate_json(
            'Reply with {"ok": true}', {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
        )
        print(f"✅ Gemini anahtarı çalışıyor ({settings.text_model})" if reply.get("ok") else "⚠️  Gemini beklenmedik yanıt verdi")
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Gemini: {exc}")
        ok = False
    if settings.dry_run:
        print("ℹ️  DRY_RUN açık: Instagram kontrolü atlandı.")
    else:
        try:
            me = _ig(settings).me()
            print(f"✅ Instagram: @{me.get('username')} ({me.get('account_type')}), IG_USER_ID={me.get('user_id')}")
        except Exception as exc:  # noqa: BLE001
            print(f"❌ Instagram: {exc}")
            ok = False
    return EXIT_OK if ok else EXIT_ERROR


def cmd_refresh_token(settings: Settings, args: argparse.Namespace) -> int:
    data = _ig(settings).refresh_token()
    token = data.get("access_token")
    if not token:
        log.error("Yeni token alınamadı.")
        return EXIT_ERROR
    days = int(data.get("expires_in", 0)) // 86400
    log.info("Yeni token alındı, %d gün geçerli.", days)
    print(token)
    return EXIT_OK


def cmd_media_url(settings: Settings, args: argparse.Namespace) -> int:
    from .pipeline import media_url

    storage = Storage(settings.data_dir)
    post = storage.get(args.post_id) if args.post_id else storage.latest_ready()
    if post is None:
        log.error("Hazır gönderi yok.")
        return EXIT_ERROR
    print(media_url(settings, storage, post))
    return EXIT_OK


def cmd_summary(settings: Settings, args: argparse.Namespace) -> int:
    storage = Storage(settings.data_dir)
    post = next(storage.iter_posts(), None)
    if post is None:
        print("Henüz gönderi yok.")
        return EXIT_OK
    d = post.data
    review = d.get("review") or {}
    plan = d.get("plan") or {}
    lines = [
        f"## {d.get('idea', {}).get('title', post.id)}",
        f"**Durum:** {d.get('status')}  ·  **Tür:** {d.get('format')}  ·  **Sahne:** {plan.get('scene')}",
        f"**Kadro:** {', '.join(plan.get('cast') or [])}  ·  **Ürün:** {plan.get('product')}",
        f"**Puan:** {review.get('score', '-')} · kişi {review.get('identity_match', '-')} · "
        f"ürün {review.get('product_match', '-')}  ·  **Deneme:** {len(d.get('attempts', []))}",
    ]
    if d.get("permalink"):
        lines.append(f"**Instagram:** {d['permalink']}")
    lines += ["", "```", d.get("caption", ""), "```"]
    if d.get("error"):
        lines.append(f"\n> ❌ {d['error']}")
    print("\n".join(lines))
    return EXIT_OK


COMMANDS = {
    "generate": cmd_generate,
    "publish": cmd_publish,
    "run": cmd_run,
    "check": cmd_check,
    "refresh-token": cmd_refresh_token,
    "media-url": cmd_media_url,
    "summary": cmd_summary,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="influencer_bot", description="AI influencer otomatik paylaşım botu")
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--post-id", help="publish/media-url: belirli bir gönderi")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    _setup_logging(args.verbose or os.getenv("RUNNER_DEBUG") == "1")

    from .pipeline import QualityError

    try:
        return COMMANDS[args.command](Settings.from_env(), args)
    except ConfigError as exc:
        log.error("Ayar hatası: %s", exc)
        return EXIT_ERROR
    except QualityError as exc:
        log.error("%s", exc)
        return EXIT_QUALITY
    except Exception as exc:  # noqa: BLE001 - top-level: show a clean message, full trace with -v
        log.error("%s: %s", type(exc).__name__, exc, exc_info=log.isEnabledFor(logging.DEBUG))
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
