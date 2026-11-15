"""Offline tests: no network, the model and Instagram are faked."""
from __future__ import annotations

import io
import json
import random
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from influencer_bot.__main__ import main
from influencer_bot.agents import Caption, merge_hashtags
from influencer_bot.config import ConfigError, Persona, Settings
from influencer_bot.imaging import to_instagram_jpeg
from influencer_bot.instagram import InstagramClient, InstagramError
from influencer_bot.pipeline import QualityError, generate, publish
from influencer_bot.storage import Storage

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 16, 19, 0, tzinfo=ZoneInfo("Europe/Istanbul"))


def png(w=800, h=800, color=(200, 150, 120)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


class FakeLLM:
    def __init__(self, scores=(9,), faces=None):
        self.scores = list(scores)
        self.faces = list(faces or scores)
        self.image_prompts: list[str] = []
        self.review_calls = 0

    def generate_json(self, prompt, schema, images=()):
        props = schema["properties"]
        if "scene" in props:
            return {"title": "Galata'da sabah kahvesi", "scene": "small café in Galata", "outfit": "camel coat",
                    "mood": "soft morning light", "shot": "medium shot"}
        if "face_match" in props:
            i = min(self.review_calls, len(self.scores) - 1)
            self.review_calls += 1
            return {"score": self.scores[i], "face_match": self.faces[i], "issues": ["el bozuk"] if self.scores[i] < 7 else [],
                    "fix_hint": "fix the left hand", "rule_violation": False}
        if "caption" in props:
            return {"caption": "Bugün kahvem biraz daha uzun sürdü. Sizin sabah ritüeliniz ne? #kahve",
                    "hashtags": ["kahve", "#galata", "#Istanbul", "#coffee time"]}
        raise AssertionError(f"unexpected schema {props}")

    def generate_image(self, prompt, reference_images=(), aspect_ratio="4:5"):
        self.image_prompts.append(prompt)
        return png()


@pytest.fixture
def workspace(tmp_path):
    shutil.copy(ROOT / "persona.yaml", tmp_path / "persona.yaml")
    (tmp_path / "references").mkdir()
    (tmp_path / "references" / "lina.png").write_bytes(png(400, 500))
    return tmp_path


@pytest.fixture
def persona(workspace):
    return Persona.load(workspace / "persona.yaml")


def settings_for(workspace, **overrides) -> Settings:
    base = dict(
        data_dir=workspace, persona_file=workspace / "persona.yaml", gemini_api_key="k", text_model="t", image_model="i",
        ig_access_token="tok", ig_user_id="123", ig_api_base="https://graph.instagram.com", ig_api_version="v21.0",
        image_host="github", imgbb_api_key=None, github_repository="me/bot", public_ref="abc123", dry_run=False,
    )
    base.update(overrides)
    return Settings(**base)


# ── persona & config ──

def test_persona_loads(persona):
    assert persona.name == "Lina"
    assert "hazel eyes" in persona.appearance
    assert persona.always_hashtags == ["#istanbul", "#aiinfluencer"]
    assert sum(t.weight for t in persona.themes) > 0


def test_persona_missing_field(tmp_path):
    (tmp_path / "p.yaml").write_text("name: X\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="appearance"):
        Persona.load(tmp_path / "p.yaml")


def test_require_reports_env_names(workspace):
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        settings_for(workspace, gemini_api_key=None).require("gemini_api_key")


# ── helpers ──

def test_hashtags_dedupe_clean_and_limit():
    tags = merge_hashtags(["#istanbul"], ["Istanbul", "coffee time", "#café!", "#", "a"] + [f"t{i}" for i in range(50)], 30)
    assert tags[:3] == ["#istanbul", "#coffeetime", "#café"]
    assert len(tags) == 30 and len({t.lower() for t in tags}) == 30


def test_caption_render_limits_length():
    text = Caption(text="x" * 3000, hashtags=["#a"]).render("🤖 AI")
    assert len(text) == 2200


def test_image_is_instagram_jpeg():
    out = to_instagram_jpeg(png(1024, 1024), 1080, 1350)
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "JPEG" and img.size == (1080, 1350)


# ── pipeline ──

def test_generate_happy_path(workspace, persona):
    llm = FakeLLM(scores=(9,))
    post = generate(llm, persona, Storage(workspace), now=NOW, rng=random.Random(1))
    data = json.loads((post.dir / "post.json").read_text(encoding="utf-8"))
    assert data["status"] == "ready" and post.id == "20261116-1900"
    assert data["caption"].startswith("Bugün kahvem")
    assert "#kahve" not in data["caption_text"]
    assert "🤖 Lina bir yapay zekâ karakteridir." in data["caption"]
    assert "#istanbul" in data["hashtags"] and "#Istanbul" not in data["hashtags"]
    assert persona.appearance in llm.image_prompts[0]
    assert "reference image" in llm.image_prompts[0]


def test_generate_retries_with_fix_hint(workspace, persona):
    llm = FakeLLM(scores=(4, 9))
    post = generate(llm, persona, Storage(workspace), now=NOW)
    assert len(post.data["attempts"]) == 2
    assert "fix the left hand" in llm.image_prompts[1]


def test_generate_refuses_bad_images(workspace, persona):
    with pytest.raises(QualityError):
        generate(FakeLLM(scores=(3, 4, 5)), persona, Storage(workspace), now=NOW)
    assert not (workspace / "posts").exists() or not any((workspace / "posts").iterdir())


def test_face_mismatch_is_rejected(workspace, persona):
    with pytest.raises(QualityError):
        generate(FakeLLM(scores=(9, 9, 9), faces=(2, 2, 2)), persona, Storage(workspace), now=NOW)


def test_theme_not_repeated(workspace, persona):
    storage = Storage(workspace)
    first = generate(FakeLLM(), persona, storage, now=NOW, rng=random.Random(0))
    for seed in range(20):
        second = generate(FakeLLM(), persona, storage, now=NOW, rng=random.Random(seed))
        assert second.data["theme"] != first.data["theme"] or len(persona.themes) == 1
        shutil.rmtree(second.dir)


# ── publishing ──

class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status
        self.ok = status < 400
        self.text = json.dumps(payload)

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, statuses=("IN_PROGRESS", "FINISHED"), fail_create=False):
        self.calls = []
        self.statuses = list(statuses)
        self.fail_create = fail_create

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if url.endswith("/123/media"):
            if self.fail_create:
                return FakeResponse({"error": {"message": "Invalid image URL", "code": 9004}}, 400)
            return FakeResponse({"id": "C1"})
        if url.endswith("/C1"):
            return FakeResponse({"status_code": self.statuses.pop(0)})
        if url.endswith("/media_publish"):
            return FakeResponse({"id": "M1"})
        if url.endswith("/M1"):
            return FakeResponse({"permalink": "https://instagram.com/p/xyz"})
        raise AssertionError(url)


def test_publish_flow(workspace, persona):
    storage = Storage(workspace)
    post = generate(FakeLLM(), persona, storage, now=NOW)
    session = FakeSession()
    settings = settings_for(workspace)
    factory = lambda: InstagramClient("tok", "123", session=session, sleep=lambda s: None)  # noqa: E731
    publish(settings, storage, post, client_factory=factory)

    assert post.data["status"] == "published" and post.data["permalink"].endswith("/xyz")
    create = session.calls[0][2]["data"]
    assert create["image_url"] == f"https://raw.githubusercontent.com/me/bot/abc123/posts/{post.id}/image.jpg"
    assert create["caption"] == post.data["caption"]
    assert create["is_ai_generated"] == "true"
    assert "/v26.0/" in session.calls[0][1]
    assert storage.latest_ready() is None


def test_publish_error_marks_failed(workspace, persona):
    storage = Storage(workspace)
    post = generate(FakeLLM(), persona, storage, now=NOW)
    factory = lambda: InstagramClient("tok", "123", session=FakeSession(fail_create=True), sleep=lambda s: None)  # noqa: E731
    with pytest.raises(InstagramError, match="Invalid image URL"):
        publish(settings_for(workspace), storage, post, client_factory=factory)
    assert json.loads((post.dir / "post.json").read_text())["status"] == "failed"


def test_dry_run_never_calls_instagram(workspace, persona):
    storage = Storage(workspace)
    post = generate(FakeLLM(), persona, storage, now=NOW)
    publish(settings_for(workspace, dry_run=True), storage, post,
            client_factory=lambda: (_ for _ in ()).throw(AssertionError("called")))
    assert post.data["status"] == "dry_run"


def test_container_error_is_reported():
    client = InstagramClient("tok", "123", session=FakeSession(statuses=("ERROR",)), sleep=lambda s: None)
    with pytest.raises(InstagramError, match="public|herkese"):
        client.publish_image("https://x/y.jpg", "hi")


# ── CLI ──

def test_cli_summary_and_missing_key(workspace, persona, monkeypatch, capsys):
    monkeypatch.setenv("DATA_DIR", str(workspace))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert main(["generate"]) == 1

    generate(FakeLLM(), persona, Storage(workspace), now=NOW)
    assert main(["summary"]) == 0
    out = capsys.readouterr().out
    assert "Galata'da sabah kahvesi" in out and "ready" in out
