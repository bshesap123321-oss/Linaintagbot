"""The planner and the agents. Each agent has one job and talks to the model through the LLM protocol."""
from __future__ import annotations

import logging
import random
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Sequence

from .config import Brand, Character, Scene
from .llm import LLM, LLMError
from .storage import Product

log = logging.getLogger(__name__)

INSTAGRAM_CAPTION_LIMIT = 2200
INSTAGRAM_HASHTAG_LIMIT = 30
ASPECT = {"image": "4:5", "reel": "9:16"}


# ───────────────────────── data passed between agents ─────────────────────────

@dataclass
class Plan:
    format: str
    scene: Scene
    cast: list[Character]
    product: Product | None

    def summary(self) -> dict:
        return {
            "format": self.format,
            "scene": self.scene.name,
            "cast": [c.id for c in self.cast],
            "product": self.product.id if self.product else None,
        }


@dataclass
class Idea:
    title: str
    setting: str
    action: str
    shot: str
    mood: str
    motion: str
    hook: str


@dataclass
class Review:
    approved: bool
    score: float
    identity_match: float
    product_match: float
    issues: list[str] = field(default_factory=list)
    fix_hint: str = ""


@dataclass
class Caption:
    text: str
    hashtags: list[str]

    def render(self, call_to_action: str = "", disclosure: str = "") -> str:
        parts = [self.text.strip()]
        if call_to_action:
            parts.append(call_to_action)
        if disclosure:
            parts.append(disclosure)
        if self.hashtags:
            parts.append(" ".join(self.hashtags))
        return "\n\n".join(parts)[:INSTAGRAM_CAPTION_LIMIT]


def _rules(brand: Brand) -> str:
    return "\n".join(f"- {r}" for r in brand.content_rules) or "- Keep it tasteful and brand-safe."


def _clamp(value: object) -> float:
    try:
        return max(0.0, min(10.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


# ───────────────────────── 0. Planner (no model call) ─────────────────────────

class Planner:
    """Decides format, scene, cast and product so that content rotates fairly and predictably."""

    def __init__(self, brand: Brand, rng: random.Random | None = None):
        self.brand, self.rng = brand, rng or random.Random()

    def run(self, products: Sequence[Product], recent: Sequence[dict], force_format: str | None = None) -> Plan:
        fmt = force_format or self._weighted(list(self.brand.formats), list(self.brand.formats.values()))
        last_scene = recent[0].get("scene") if recent else None
        scenes = [s for s in self.brand.scenes if s.name != last_scene] or self.brand.scenes
        scene = self._weighted(scenes, [s.weight for s in scenes])
        k = self.rng.randint(scene.min_people, scene.max_people)
        return Plan(format=fmt, scene=scene, cast=self._least_recent(self.brand.cast, recent, "cast", k),
                    product=(self._least_recent(products, recent, "product", 1) or [None])[0])

    def _weighted(self, items, weights):
        return self.rng.choices(items, weights=weights, k=1)[0]

    def _least_recent(self, items, recent, key, k):
        """Items never used come first, then those used longest ago; ties are shuffled."""
        def last_used(item) -> int:
            for i, post in enumerate(recent):
                used = post.get(key)
                if used == item.id or (isinstance(used, list) and item.id in used):
                    return i
            return len(recent) + 1
        ranked = sorted(items, key=lambda it: (-last_used(it), self.rng.random()))
        return ranked[:k]


# ───────────────────────── 1. Idea agent ─────────────────────────

class IdeaAgent:
    """Turns the plan into a concrete, funny, believable moment."""

    SCHEMA = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short internal title, max 8 words, in Turkish"},
            "setting": {"type": "string", "description": "Exact place, weather and background, in English"},
            "action": {"type": "string", "description": "What each named person is doing and wearing in this exact frame, in English"},
            "shot": {"type": "string", "description": "Camera position, framing and angle, in English"},
            "mood": {"type": "string", "description": "Light and emotion, in English"},
            "motion": {"type": "string", "description": "For video: what happens over 8 seconds, beat by beat, in English"},
            "hook": {"type": "string", "description": "One funny opening line for the caption, in the brand language"},
        },
        "required": ["title", "setting", "action", "shot", "mood", "motion", "hook"],
    }

    def __init__(self, llm: LLM, brand: Brand):
        self.llm, self.brand = llm, brand

    def run(self, plan: Plan, recent_titles: Sequence[str], now: datetime) -> Idea:
        b = self.brand
        people = "\n".join(f"- {c.name}: {c.appearance}; usually wears {c.style or 'casual winter clothes'}" for c in plan.cast)
        product = (f"{plan.product.name}: {plan.product.description}" if plan.product
                   else "No specific product today; a fun lifestyle moment for the brand.")
        recent = "\n".join(f"- {t}" for t in recent_titles if t) or "- (none yet)"
        fmt = "an 8-second vertical Reel (the image you describe is its FIRST frame)" if plan.format == "reel" else "a single photo"
        prompt = f"""You are the creative director of the Instagram account of "{b.name}".
About the brand: {b.about}
Today: {now.strftime('%A %d %B %Y')}
Format: {fmt}
Scene to build on: {plan.scene.name}

People in the shot (use exactly these, by name, no extra main characters):
{people}

Product to feature: {product}
The product must be clearly visible and recognizable, worn by at least one person (usually everyone).
The comedy usually comes from the contrast between the funny mask and normal skiing life.

Recent posts. Do NOT repeat these ideas:
{recent}

Invent ONE specific, scroll-stopping but believable moment. It must look like friends filmed it on a phone,
not like an advert. Content rules:
{_rules(b)}

Language for 'title' and 'hook': {b.language}. All other fields in English."""
        data = self.llm.generate_json(prompt, self.SCHEMA)
        try:
            return Idea(**{k: str(data[k]).strip() for k in self.SCHEMA["required"]})
        except KeyError as exc:
            raise LLMError(f"Fikir ajanı eksik alan döndürdü: {exc}") from exc


# ───────────────────────── 2. Prompt agent (deterministic) ─────────────────────────

@dataclass
class References:
    """Reference images in the exact order they are sent to the model, with a label for each."""
    images: list[bytes] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    has_people: bool = False
    has_product: bool = False

    @classmethod
    def build(cls, plan: Plan, character_refs: dict[str, list[bytes]]) -> "References":
        refs = cls()
        if plan.product:
            for img in plan.product.photos:
                refs.images.append(img)
                refs.labels.append(f"the PRODUCT ({plan.product.name})")
                refs.has_product = True
        for c in plan.cast:
            for img in character_refs.get(c.id, []):
                refs.images.append(img)
                refs.labels.append(f"{c.name}")
                refs.has_people = True
        return refs

    def legend(self) -> str:
        if not self.images:
            return ""
        lines = [f"Reference image {i}: {label}" for i, label in enumerate(self.labels, 1)]
        return "\n".join(lines)


class PromptAgent:
    """Builds the image prompt. No model call: the characters' looks stay 100% consistent."""

    def __init__(self, brand: Brand):
        self.brand = brand

    def run(self, plan: Plan, idea: Idea, refs: References, fix_hint: str = "") -> str:
        b = self.brand
        parts = []
        if refs.images:
            parts.append(refs.legend())
            if refs.has_product:
                parts.append("Reproduce the PRODUCT exactly as in its reference photos: same print, colors, shape, "
                             "proportions and details. Do not redesign, simplify or add logos to it.")
            if refs.has_people:
                parts.append("Keep each person's face, hair and body identical to their reference photos.")
        people = "; ".join(f"{c.name}: {c.appearance}, wearing {c.style or 'winter clothes'}" for c in plan.cast)
        parts += [
            f"People ({len(plan.cast)}): {people}.",
        ]
        if plan.product:
            parts.append(f"Product: {plan.product.name}: {plan.product.description}")
        parts += [
            f"Setting: {idea.setting}.",
            f"Action: {idea.action}.",
            f"Camera: {idea.shot}. Mood and light: {idea.mood}.",
            f"Style: {b.photo_style}. Vertical {ASPECT[plan.format]} frame.",
            "Natural anatomy: correct hands with five fingers, realistic proportions.",
            "Strictly avoid: " + "; ".join(b.content_rules) + ".",
        ]
        if fix_hint:
            parts.append(f"Important correction from the previous attempt: {fix_hint}")
        return "\n".join(parts)


# ───────────────────────── 3. Image & video agents ─────────────────────────

class ImageAgent:
    def __init__(self, llm: LLM):
        self.llm = llm

    def run(self, prompt: str, refs: References, fmt: str) -> bytes:
        return self.llm.generate_image(prompt, reference_images=refs.images, aspect_ratio=ASPECT[fmt])


class VideoAgent:
    def __init__(self, llm: LLM, brand: Brand):
        self.llm, self.brand = llm, brand

    def prompt(self, plan: Plan, idea: Idea, fix_hint: str = "") -> str:
        names = ", ".join(c.name for c in plan.cast)
        product = f" The {plan.product.name} must stay exactly as in the first frame." if plan.product else ""
        text = (f"Continue from the provided first frame. {idea.motion} "
                f"People: {names}; keep their faces, clothes and masks unchanged throughout.{product} "
                f"{self.brand.video_style}")
        return text + (f" Correction: {fix_hint}" if fix_hint else "")

    def negative(self) -> str:
        return "text, captions, subtitles, watermark, logos, morphing faces, melting objects, extra limbs, distorted hands"

    def run(self, plan: Plan, idea: Idea, first_frame: bytes, fix_hint: str = "") -> tuple[bytes, str]:
        prompt = self.prompt(plan, idea, fix_hint)
        return self.llm.generate_video(prompt, first_frame, aspect_ratio="9:16", negative_prompt=self.negative()), prompt


# ───────────────────────── 4. Review agent ─────────────────────────

class ReviewAgent:
    """An independent critic: it sees only the references, the candidate and the brief."""

    SCHEMA = {
        "type": "object",
        "properties": {
            "score": {"type": "number", "description": "Overall quality and realism 0-10"},
            "identity_match": {"type": "number", "description": "0-10: same people as the references (hair, build, skin, clothes). 10 if there are no person references, or if faces are covered and nothing contradicts them"},
            "product_match": {"type": "number", "description": "0-10: the product looks exactly like its reference photos. 10 if there is no product reference"},
            "issues": {"type": "array", "items": {"type": "string"}},
            "fix_hint": {"type": "string", "description": "One concrete instruction that fixes the biggest problem"},
            "rule_violation": {"type": "boolean"},
        },
        "required": ["score", "identity_match", "product_match", "issues", "fix_hint", "rule_violation"],
    }

    def __init__(self, llm: LLM, brand: Brand):
        self.llm, self.brand = llm, brand

    def _ask(self, media: bytes, kind: str, plan: Plan, idea: Idea, refs: References, extra: str = "") -> Review:
        legend = refs.legend() + f"\nThe LAST attachment is the candidate {kind}." if refs.images \
            else f"The only attachment is the candidate {kind}."
        product = f"{plan.product.name}: {plan.product.description}" if plan.product else "none"
        prompt = f"""You are a strict editor approving content for a real brand's Instagram account.
{legend}

Brief: {idea.setting} | {idea.action}
People expected: {", ".join(f"{c.name} ({c.appearance})" for c in plan.cast)}
Product expected: {product}

Check carefully:
1. Does the product look exactly like its reference (print, colors, shape)? It must be clearly visible.
2. Are these the same people as their references? Is the number of people right?
3. Anatomy: hands, fingers, limbs, eyes, teeth. Any distortion or melting?
4. Does it look like a real phone {kind}, not CGI or plastic?
5. Any text, logos, watermarks or artifacts?{extra}
6. Does it break any content rule?
{_rules(self.brand)}

Be strict: 8+ only for content you would happily post today."""
        data = self.llm.generate_json(prompt, self.SCHEMA, images=[*refs.images, media])
        score = _clamp(data.get("score"))
        identity = _clamp(data.get("identity_match", 10))
        product_score = _clamp(data.get("product_match", 10))
        violation = bool(data.get("rule_violation", False))
        m = self.brand.min_score
        approved = (not violation and score >= m
                    and (product_score >= m or not refs.has_product)
                    and (identity >= m or not refs.has_people))
        issues = [str(i) for i in data.get("issues", [])]
        if violation:
            issues.insert(0, "İçerik kuralı ihlali")
        return Review(approved, score, identity, product_score, issues, str(data.get("fix_hint", "")))

    def image(self, image: bytes, plan: Plan, idea: Idea, refs: References) -> Review:
        return self._ask(image, "photo", plan, idea, refs)

    def video(self, video: bytes, plan: Plan, idea: Idea, refs: References) -> Review:
        return self._ask(video, "video", plan, idea, refs,
                         extra="\n   For video also: do faces, masks or objects morph or flicker? Is motion natural?")


# ───────────────────────── 5. Caption agent ─────────────────────────

class CaptionAgent:
    SCHEMA = {
        "type": "object",
        "properties": {
            "caption": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["caption", "hashtags"],
    }

    def __init__(self, llm: LLM, brand: Brand):
        self.llm, self.brand = llm, brand

    def run(self, plan: Plan, idea: Idea, image: bytes, recent_captions: Sequence[str] = ()) -> Caption:
        b = self.brand
        recent = "\n".join(f"- {c[:120]}" for c in recent_captions[:5] if c) or "- (none)"
        product = ""
        if plan.product:
            p = plan.product
            product = f"Product: {p.name}" + (f", price {p.price}" if p.price else "") + (f", sizes {p.sizes}" if p.sizes else "")
        n_tags = max(0, b.hashtag_count - len(b.always_hashtags))
        prompt = f"""You write Instagram captions for "{b.name}".
About: {b.about}
Voice: {b.voice}
Language: {b.language}

The {'reel' if plan.format == 'reel' else 'photo'} (attached) shows: {idea.action} — {idea.setting}
Suggested hook: {idea.hook}
{product}

Recent captions. Do not reuse their openings:
{recent}

Rules:
- Start with the hook or a better one. 2-4 short lines total.
- Mention the product name once, and the price/sizes on one line if given. Keep placeholders like [FİYAT] exactly as written.
- No hashtags and no call to action inside the caption text (they are added automatically).
- Never mention AI (a disclosure is added automatically).
- Return {n_tags} specific hashtags (mix of {b.language} and English), each starting with #."""
        data = self.llm.generate_json(prompt, self.SCHEMA, images=[image])
        text = re.sub(r"(?:\s*#\S+)+\s*$", "", str(data.get("caption", ""))).strip()
        if not text:
            raise LLMError("Açıklama ajanı boş metin döndürdü.")
        return Caption(text=text, hashtags=merge_hashtags(b.always_hashtags, data.get("hashtags", []), b.hashtag_count))


def merge_hashtags(always: Sequence[str], generated: Sequence[object], limit: int) -> list[str]:
    limit = min(limit, INSTAGRAM_HASHTAG_LIMIT)
    seen: set[str] = set()
    result: list[str] = []
    for raw in [*always, *generated]:
        tag = "#" + re.sub(r"[^\w]", "", str(raw).lstrip("#"), flags=re.UNICODE)
        key = tag.lower()
        if len(tag) < 2 or key in seen:
            continue
        seen.add(key)
        result.append(tag)
        if len(result) >= limit:
            break
    return result


def to_dict(obj) -> dict:
    return asdict(obj)
