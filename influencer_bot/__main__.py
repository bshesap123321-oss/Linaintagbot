"""Command line interface.

  python -m influencer_bot generate        create today's post (image + caption), do not publish
  python -m influencer_bot publish         publish the newest ready post
  python -m influencer_bot run             generate + publish in one go (use with IMAGE_HOST=imgbb)
  python -m influencer_bot check           verify Gemini key, Instagram token and persona file
  python -m influencer_bot refresh-token   print a fresh 60-day Instagram token
  python -m influencer_bot summary         print a Markdown report of the newest post
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from .config import ConfigError, Persona, Settings
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
    return GeminiLLM(settings.gemini_api_key or "", settings.text_model, settings.image_model)


def _ig(settings: Settings):
    from .instagram import InstagramClient

    settings.require("ig_access_token")
    return InstagramClient(settings.ig_access_token or "", settings.ig_user_id, settings.ig_api_base, settings.ig_api_version)


def cmd_generate(settings: Settings, args: argparse.Namespace) -> int:
    from .pipeline import generate

    persona = Persona.load(settings.persona_file)
    post = generate(_llm(settings), persona, Storage(settings.data_dir))
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

    if settings.image_host == "github" and not settings.dry_run:
        raise ConfigError("'run' komutu IMAGE_HOST=imgbb ile çalışır. GitHub barındırmada 'generate' ve 'publish' ayrı çalıştırılır.")
    storage = Storage(settings.data_dir)
    post = generate(_llm(settings), Persona.load(settings.persona_file), storage)
    publish(settings, storage, post)
    return EXIT_OK


def cmd_check(settings: Settings, args: argparse.Namespace) -> int:
    ok = True
    try:
        persona = Persona.load(settings.persona_file)
        print(f"✅ Persona: {persona.name} ({len(persona.themes)} tema)")
    except ConfigError as exc:
        print(f"❌ Persona: {exc}")
        ok = False
    refs = Storage(settings.data_dir).references()
    print(f"{'✅' if refs else '⚠️ '} Referans fotoğraf: {len(refs)} adet" + ("" if refs else " (references/ klasörüne ekleyin)"))
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


def cmd_summary(settings: Settings, args: argparse.Namespace) -> int:
    storage = Storage(settings.data_dir)
    post = next(storage.iter_posts(), None)
    if post is None:
        print("Henüz gönderi yok.")
        return EXIT_OK
    d = post.data
    review = d.get("review") or {}
    lines = [
        f"## {d.get('idea', {}).get('title', post.id)}",
        f"**Durum:** {d.get('status')}  ·  **Tema:** {d.get('theme')}  ·  "
        f"**Puan:** {review.get('score', '-')} / yüz {review.get('face_match', '-')}  ·  "
        f"**Deneme:** {len(d.get('attempts', []))}",
    ]
    if d.get("permalink"):
        lines.append(f"**Instagram:** {d['permalink']}")
    if d.get("image_url"):
        lines.append(f"\n![görsel]({d['image_url']})")
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
    "summary": cmd_summary,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="influencer_bot", description="AI influencer otomatik paylaşım botu")
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--post-id", help="publish: belirli bir gönderiyi paylaş")
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
