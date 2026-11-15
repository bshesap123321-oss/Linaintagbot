"""Offline tests: no network. The model and Instagram are faked."""
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
from influencer_bot.agents import Caption, Planner, merge_hashtags
from influencer_bot.config import Brand, ConfigError, Settings
from influencer_bot.hosting import public_url
from influencer_bot.imaging import to_instagram_jpeg
from influencer_bot.instagram import InstagramClient, InstagramError
from influencer_bot.pipeline import QualityError, generate, publish
from influencer_bot.storage import Storage

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 16, 19, 0, tzinfo=ZoneInfo("Europe/Istanbul"))
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


def png(w=600, h=800, color=(200, 150, 120)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


class FakeLLM:
    def __init__(self, scores=(9,), video_scores=(9,), product=None):
        self.scores, self.video_scores = list(scores), list(video_scores)
        self.product = product
        self.image_calls: list[tuple[str, int, str]] = []
        self.video_prompts: list[str] = []
        self.idea_prompts: list[str] = []
        self.n_img_reviews = self.n_vid_reviews = 0

    def generate_json(self, prompt, schema, images=()):
        props = schema["properties"]
        if "motion" in props:
            self.idea_prompts.append(prompt)
            return {"title": "Telesiyejde üç amca", "setting": "chairlift above a snowy slope",
                    "action": "three friends wearing the mask salute the camera", "shot": "selfie from the front",
                    "mood": "bright sun", "motion": "they turn to the camera and salute, then laugh",
                    "hook": "POV: en iyi kayak maskesini aldın 😂"}
        if "product_match" in props:
            video = images and images[-1][4:8] == b"ftyp"
            seq, attr = (self.video_scores, "n_vid_reviews") if video else (self.scores, "n_img_reviews")
            i = min(getattr(self, attr), len(seq) - 1)
            setattr(self, attr, getattr(self, attr) + 1)
            s = seq[i]
            p = self.product if self.product is not None else s
            return {"score": s, "identity_match": s, "product_match": p, "issues": [] if s >= 7 else ["el bozuk"],
                    "fix_hint": "fix the left hand", "rule_violation": False}
        if "caption" in props:
            return {"caption": "POV: en iyi kayak maskesini aldın 😂\nBıyıklı Amca maskesi. #komik",
                    "hashtags": ["kayak", "#Karmaskesi", "#ski mask", "#uludag"]}
        raise AssertionError(f"unexpected schema {props}")

    def generate_image(self, prompt, reference_images=(), aspect_ratio="4:5"):
        self.image_calls.append((prompt, len(reference_images), aspect_ratio))
        return png()

    def generate_video(self, prompt, first_frame, aspect_ratio="9:16", negative_prompt=""):
        self.video_prompts.append(prompt)
        return MP4


@pytest.fixture
def workspace(tmp_path):
    shutil.copy(ROOT / "brand.yaml", tmp_path / "brand.yaml")
    shutil.copytree(ROOT / "products", tmp_path / "products")
    shutil.copytree(ROOT / "cast", tmp_path / "cast")
    (tmp_path / "products" / "biyikli-amca" / "front.png").write_bytes(png(500, 500, (220, 180, 160)))
    (tmp_path / "cast" / "lina" / "lina.png").write_bytes(png(400, 500))
    return tmp_path


@pytest.fixture
def brand(workspace):
    return Brand.load(workspace / "brand.yaml")


def settings_for(workspace, **overrides) -> Settings:
    base = dict(
        data_dir=workspace, brand_file=workspace / "brand.yaml", gemini_api_key="k", text_model="t", image_model="i",
        video_model="v", ig_access_token="tok", ig_user_id="123", ig_api_base="https://graph.instagram.com",
        ig_api_version="v26.0", media_host="pages", imgbb_api_key=None, github_repository="Me/Linaintagbot",
        public_ref="abc123", dry_run=False,
    )
    base.update(overrides)
    return Settings(**base)


# ── brand, catalog ──

def test_brand_loads(brand):
    assert [c.id for c in brand.cast] == ["lina", "ahmet", "mehmet", "zeynep"]
    assert set(brand.formats) == {"image", "reel"}
    assert all(1 <= s.min_people <= s.max_people <= 4 for s in brand.scenes)


def test_brand_validation(tmp_path):
    (tmp_path / "b.yaml").write_text("name: X\nabout: a\nvoice: b\ncast: [{id: a}]\nscenes: [x]\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="appearance"):
        Brand.load(tmp_path / "b.yaml")


def test_products_and_refs(workspace):
    s = Storage(workspace)
    products = {p.id: p for p in s.products()}
    assert set(products) == {"biyikli-amca", "sari-blok-kafa"}
    assert len(products["biyikli-amca"].photos) == 1 and not products["sari-blok-kafa"].photos
    assert len(s.character_refs("lina")) == 1 and s.character_refs("ahmet") == []


def test_require_reports_env_names(workspace):
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        settings_for(workspace, gemini_api_key=None).require("gemini_api_key")


# ── planner ──

def test_planner_rotates_products_and_cast(brand, workspace):
    products = Storage(workspace).products()
    recent = [{"product": "biyikli-amca", "cast": ["lina", "ahmet"], "scene": brand.scenes[0].name}]
    for seed in range(30):
        plan = Planner(brand, random.Random(seed)).run(products, recent)
        assert plan.product.id == "sari-blok-kafa"
        assert plan.scene.name != brand.scenes[0].name
        assert plan.scene.min_people <= len(plan.cast) <= plan.scene.max_people
        assert len({c.id for c in plan.cast}) == len(plan.cast)
        if len(plan.cast) <= 2:
            assert not {"lina", "ahmet"} & {c.id for c in plan.cast}


def test_force_format(brand, workspace):
    assert Planner(brand, random.Random(1)).run([], [], force_format="reel").format == "reel"


# ── helpers ──

def test_hashtags_dedupe_clean_and_limit():
    tags = merge_hashtags(["#kayak"], ["Kayak", "ski mask", "#café!", "#", "a"] + [f"t{i}" for i in range(50)], 30)
    assert tags[:3] == ["#kayak", "#skimask", "#café"]
    assert len(tags) == 30


def test_caption_render():
    text = Caption(text="Merhaba", hashtags=["#a", "#b"]).render("DM yazın", "AI notu")
    assert text == "Merhaba\n\nDM yazın\n\nAI notu\n\n#a #b"
    assert len(Caption(text="x" * 3000, hashtags=[]).render()) == 2200


@pytest.mark.parametrize("size", [(1080, 1350), (1080, 1920)])
def test_image_is_instagram_jpeg(size):
    with Image.open(io.BytesIO(to_instagram_jpeg(png(1024, 1024), *size))) as img:
        assert img.format == "JPEG" and img.size == size


def test_hosting_urls(workspace):
    p = workspace / "posts" / "x" / "video.mp4"
    assert public_url(settings_for(workspace), p, "posts/x/video.mp4") == "https://me.github.io/Linaintagbot/posts/x/video.mp4"
    with pytest.raises(ConfigError, match="pages"):
        public_url(settings_for(workspace, media_host="github"), p, "posts/x/video.mp4")


# ── pipeline ──

def test_generate_photo(workspace, brand):
    llm = FakeLLM()
    post = generate(llm, brand, Storage(workspace), now=NOW, rng=random.Random(3), force_format="image")
    d = post.data
    assert d["status"] == "ready" and d["format"] == "image" and post.id == "20261116-1900"
    assert d["caption"].startswith("POV: en iyi kayak maskesini aldın")
    assert "#komik" not in d["caption_text"]
    assert "DM'den \"MASKE\" yazın" in d["caption"] and "yapay zekâ" in d["caption"]
    prompt, n_refs, ratio = llm.image_calls[0]
    assert ratio == "4:5"
    assert "Reproduce the PRODUCT exactly" in prompt or d["plan"]["product"] == "sari-blok-kafa"
    for cid in d["plan"]["cast"]:
        assert brand.character(cid).appearance in prompt
    with Image.open(post.image_path) as img:
        assert img.size == (1080, 1350)


def test_generate_reel(workspace, brand):
    llm = FakeLLM(video_scores=(5, 9))
    post = generate(llm, brand, Storage(workspace), now=NOW, force_format="reel")
    assert post.format == "reel" and post.video_path.read_bytes() == MP4
    assert llm.image_calls[0][2] == "9:16"
    assert len(llm.video_prompts) == 2 and "fix the left hand" in llm.video_prompts[1]
    assert [a["kind"] for a in post.data["attempts"]] == ["image", "video", "video"]
    with Image.open(post.image_path) as img:
        assert img.size == (1080, 1920)


def test_retry_then_success(workspace, brand):
    llm = FakeLLM(scores=(4, 9))
    post = generate(llm, brand, Storage(workspace), now=NOW, force_format="image")
    assert len(post.data["attempts"]) == 2 and "fix the left hand" in llm.image_calls[1][0]


def test_bad_images_are_never_saved(workspace, brand):
    with pytest.raises(QualityError):
        generate(FakeLLM(scores=(3, 4, 5)), brand, Storage(workspace), now=NOW, force_format="image")
    assert not (workspace / "posts").exists()


def test_wrong_product_is_rejected(workspace, brand):
    shutil.rmtree(workspace / "products" / "sari-blok-kafa")  # only the product with a reference photo remains
    with pytest.raises(QualityError):
        generate(FakeLLM(scores=(9, 9, 9), product=2), brand, Storage(workspace), now=NOW, force_format="image")


def test_bad_video_is_rejected(workspace, brand):
    with pytest.raises(QualityError, match="video"):
        generate(FakeLLM(video_scores=(3, 3)), brand, Storage(workspace), now=NOW, force_format="reel")


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
        self.calls, self.statuses, self.fail_create = [], list(statuses), fail_create

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if url.endswith("/123/media"):
            if self.fail_create:
                return FakeResponse({"error": {"message": "Invalid media URL", "code": 9004}}, 400)
            return FakeResponse({"id": "C1"})
        if url.endswith("/C1"):
            return FakeResponse({"status_code": self.statuses.pop(0)})
        if url.endswith("/media_publish"):
            return FakeResponse({"id": "M1"})
        if url.endswith("/M1"):
            return FakeResponse({"permalink": "https://instagram.com/p/xyz"})
        raise AssertionError(url)


def _client(session):
    return lambda: InstagramClient("tok", "123", session=session, sleep=lambda s: None)


def test_publish_photo(workspace, brand):
    storage = Storage(workspace)
    post = generate(FakeLLM(), brand, storage, now=NOW, force_format="image")
    session = FakeSession()
    publish(settings_for(workspace), storage, post, client_factory=_client(session))
    create = session.calls[0][2]["data"]
    assert create["image_url"] == f"https://me.github.io/Linaintagbot/posts/{post.id}/image.jpg"
    assert create["is_ai_generated"] == "true" and "/v26.0/" in session.calls[0][1]
    assert post.data["status"] == "published" and storage.latest_ready() is None


def test_publish_reel_removes_video(workspace, brand):
    storage = Storage(workspace)
    post = generate(FakeLLM(), brand, storage, now=NOW, force_format="reel")
    session = FakeSession()
    publish(settings_for(workspace), storage, post, client_factory=_client(session))
    create = session.calls[0][2]["data"]
    assert create["media_type"] == "REELS" and create["video_url"].endswith("/video.mp4")
    assert create["cover_url"].endswith("/image.jpg") and create["share_to_feed"] == "true"
    assert not post.video_path.exists() and post.image_path.exists()


def test_publish_error_marks_failed(workspace, brand):
    storage = Storage(workspace)
    post = generate(FakeLLM(), brand, storage, now=NOW, force_format="image")
    with pytest.raises(InstagramError, match="Invalid media URL"):
        publish(settings_for(workspace), storage, post, client_factory=_client(FakeSession(fail_create=True)))
    assert json.loads((post.dir / "post.json").read_text())["status"] == "failed"


def test_dry_run_never_calls_instagram(workspace, brand):
    storage = Storage(workspace)
    post = generate(FakeLLM(), brand, storage, now=NOW)
    publish(settings_for(workspace, dry_run=True), storage, post,
            client_factory=lambda: (_ for _ in ()).throw(AssertionError("called")))
    assert post.data["status"] == "dry_run"


def test_container_error_is_reported():
    client = InstagramClient("tok", "123", session=FakeSession(statuses=("ERROR",)), sleep=lambda s: None)
    with pytest.raises(InstagramError, match="herkese"):
        client.publish_image("https://x/y.jpg", "hi")


# ── CLI ──

def test_cli(workspace, brand, monkeypatch, capsys):
    monkeypatch.setenv("DATA_DIR", str(workspace))
    monkeypatch.setenv("GITHUB_REPOSITORY", "Me/Linaintagbot")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert main(["generate"]) == 1

    post = generate(FakeLLM(), brand, Storage(workspace), now=NOW, force_format="reel")
    assert main(["media-url"]) == 0
    assert main(["summary"]) == 0
    out = capsys.readouterr().out
    assert f"https://me.github.io/Linaintagbot/posts/{post.id}/video.mp4" in out
    assert "Telesiyejde üç amca" in out and "reel" in out
