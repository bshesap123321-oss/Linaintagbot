"""The five agents. Each has one job and talks to the model through the LLM protocol."""
from __future__ import annotations

import logging
import random
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Sequence

from .config import Persona, Theme
from .llm import LLM, LLMError

log = logging.getLogger(__name__)

INSTAGRAM_CAPTION_LIMIT = 2200
INSTAGRAM_HASHTAG_LIMIT = 30


# ───────────────────────── data passed between agents ─────────────────────────

@dataclass
class Idea:
    theme: str
    title: str
    scene: str
    outfit: str
    mood: str
    shot: str


@dataclass
class Review:
    approved: bool
    score: float
    face_match: float
    issues: list[str] = field(default_factory=list)
    fix_hint: str = ""


@dataclass
class Caption:
    text: str
    hashtags: list[str]

    def render(self, disclosure: str = "") -> str:
        parts = [self.text.strip()]
        if disclosure:
            parts.append(disclosure)
        if self.hashtags:
            parts.append(" ".join(self.hashtags))
        return "\n\n".join(parts)[:INSTAGRAM_CAPTION_LIMIT]


def _rules(persona: Persona) -> str:
    return "\n".join(f"- {r}" for r in persona.content_rules) or "- Keep it tasteful and brand-safe."


# ───────────────────────── 1. Idea agent ─────────────────────────

class IdeaAgent:
    """Picks today's theme and invents a fresh, specific post idea."""

    SCHEMA = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short internal title, max 8 words"},
            "scene": {"type": "string", "description": "Exact location and setting, in English"},
            "outfit": {"type": "string", "description": "Clothing and accessories, in English"},
            "mood": {"type": "string", "description": "Light, time of day, emotion, in English"},
            "shot": {"type": "string", "description": "Framing and camera angle, in English"},
        },
        "required": ["title", "scene", "outfit", "mood", "shot"],
    }

    def __init__(self, llm: LLM, persona: Persona, rng: random.Random | None = None):
        self.llm, self.persona, self.rng = llm, persona, rng or random.Random()

    def pick_theme(self, recent_themes: Sequence[str]) -> Theme:
        themes = self.persona.themes
        # Avoid repeating yesterday's theme when there is a choice.
        last = recent_themes[0] if recent_themes else None
        pool = [t for t in themes if t.name != last] or themes
        return self.rng.choices(pool, weights=[t.weight for t in pool], k=1)[0]

    def run(self, recent_titles: Sequence[str], recent_themes: Sequence[str], now: datetime) -> Idea:
        theme = self.pick_theme(recent_themes)
        recent = "\n".join(f"- {t}" for t in recent_titles) or "- (none yet)"
        prompt = f"""You are the creative director of an Instagram lifestyle account for a virtual character.

Character: {self.persona.name}
Personality: {self.persona.personality}
Today: {now.strftime('%A %d %B %Y')} (season matters: dress for the real weather of this month)
Theme for today: {theme.name}

Recent posts. Do NOT repeat these locations or concepts:
{recent}

Invent ONE specific, visually striking but believable everyday moment for today's post.
It must feel like a real person's candid photo, not an advertisement.
Content rules:
{_rules(self.persona)}

Write all fields in English."""
        data = self.llm.generate_json(prompt, self.SCHEMA)
        try:
            return Idea(theme=theme.name, **{k: str(data[k]).strip() for k in self.SCHEMA["required"]})
        except KeyError as exc:
            raise LLMError(f"Fikir ajanı eksik alan döndürdü: {exc}") from exc


# ───────────────────────── 2. Prompt agent ─────────────────────────

class PromptAgent:
    """Turns an idea into an image prompt. Deterministic: no model call needed,
    which keeps the character's look 100% consistent."""

    def __init__(self, persona: Persona):
        self.persona = persona

    def run(self, idea: Idea, has_reference: bool, fix_hint: str = "") -> str:
        p = self.persona
        identity = (
            "Use the woman in the reference image(s) as the subject and keep her face, hair and body identical. "
            if has_reference else ""
        )
        prompt = (
            f"{identity}Subject: {p.appearance}.\n"
            f"Outfit: {idea.outfit}.\n"
            f"Scene: {idea.scene}.\n"
            f"Mood and light: {idea.mood}.\n"
            f"Framing: {idea.shot}.\n"
            f"Style: {p.photo_style}.\n"
            "Anatomically correct hands with five fingers, natural proportions, sharp focus on the face.\n"
            "Strictly avoid: " + "; ".join(p.content_rules + ["text, watermarks, captions, borders"]) + "."
        )
        if fix_hint:
            prompt += f"\nImportant correction from the previous attempt: {fix_hint}"
        return prompt


# ───────────────────────── 3. Image agent ─────────────────────────

class ImageAgent:
    def __init__(self, llm: LLM, persona: Persona):
        self.llm, self.persona = llm, persona

    def run(self, prompt: str, references: Sequence[bytes]) -> bytes:
        return self.llm.generate_image(prompt, reference_images=references, aspect_ratio=self.persona.aspect_ratio)


# ───────────────────────── 4. Review agent ─────────────────────────

class ReviewAgent:
    """An independent critic: it sees only the images and the brief, never the prompt history."""

    SCHEMA = {
        "type": "object",
        "properties": {
            "score": {"type": "number", "description": "Overall quality 0-10"},
            "face_match": {"type": "number", "description": "0-10 how clearly the same person as the reference; 10 if no reference"},
            "issues": {"type": "array", "items": {"type": "string"}},
            "fix_hint": {"type": "string", "description": "One concrete instruction to fix the biggest problem"},
            "rule_violation": {"type": "boolean"},
        },
        "required": ["score", "face_match", "issues", "fix_hint", "rule_violation"],
    }

    def __init__(self, llm: LLM, persona: Persona):
        self.llm, self.persona = llm, persona

    def run(self, image: bytes, idea: Idea, references: Sequence[bytes]) -> Review:
        ref_note = (
            f"The first {len(references)} image(s) are the reference of the character. The LAST image is the candidate."
            if references else "There is no reference image; the single image is the candidate."
        )
        prompt = f"""You are a strict photo editor approving images for a real Instagram account.
{ref_note}

The candidate must show: {self.persona.appearance}
Brief: {idea.scene} | outfit: {idea.outfit} | mood: {idea.mood}

Check carefully:
1. Is it clearly the same woman as the reference (face shape, eyes, hair, skin, freckles)?
2. Anatomy: hands, fingers, limbs, teeth, eyes. Any distortion?
3. Does it look like a real photo, not plastic, CGI or over-smoothed?
4. Any text, logos, watermarks, warped objects or background artifacts?
5. Does it break any content rule?
{_rules(self.persona)}

Be honest and strict. Scores of 8+ only for images you would happily post."""
        data = self.llm.generate_json(prompt, self.SCHEMA, images=[*references, image])
        score = _clamp(data.get("score", 0))
        face = _clamp(data.get("face_match", 0 if references else 10))
        violation = bool(data.get("rule_violation", False))
        min_score = self.persona.min_score
        approved = not violation and score >= min_score and (face >= min_score or not references)
        issues = [str(i) for i in data.get("issues", [])]
        if violation:
            issues.insert(0, "İçerik kuralı ihlali")
        return Review(approved=approved, score=score, face_match=face, issues=issues, fix_hint=str(data.get("fix_hint", "")))


def _clamp(value: object) -> float:
    try:
        return max(0.0, min(10.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


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

    def __init__(self, llm: LLM, persona: Persona):
        self.llm, self.persona = llm, persona

    def run(self, idea: Idea, image: bytes, recent_captions: Sequence[str] = ()) -> Caption:
        p = self.persona
        recent = "\n".join(f"- {c[:120]}" for c in recent_captions[:5]) or "- (none)"
        prompt = f"""You write Instagram captions as {p.name}, in first person.
Language: {p.language}
Personality: {p.personality}
Voice: {p.voice}

The photo shows: {idea.scene}. Outfit: {idea.outfit}. Mood: {idea.mood}.
Look at the attached photo and write about what is really in it.

Recent captions. Do not reuse their openings or phrases:
{recent}

Rules:
- Sound like a real young woman, not a brand. No hashtags inside the caption text.
- Never claim to be human and never mention being AI (a disclosure is added automatically).
- Return {max(0, p.hashtag_count - len(p.always_hashtags))} relevant, specific hashtags (mix of {p.language} and English), each starting with #."""
        data = self.llm.generate_json(prompt, self.SCHEMA, images=[image])
        text = re.sub(r"(?:\s*#\S+)+\s*$", "", str(data.get("caption", ""))).strip()
        if not text:
            raise LLMError("Açıklama ajanı boş metin döndürdü.")
        return Caption(text=text, hashtags=merge_hashtags(p.always_hashtags, data.get("hashtags", []), p.hashtag_count))


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


def idea_to_dict(idea: Idea) -> dict:
    return asdict(idea)
