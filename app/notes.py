# Copyright (c) 2026 Tanvir. ClassForge project source.
"""Turn a chapter's raw transcript text into a title, structured notes,
key concepts, and revision material (quiz + flashcards).

Uses the configured AI provider (local Ollama model by default) when one is
available, with a dependency-free extractive fallback so the app still
produces something useful offline and without any model installed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import config, local_llm

NOTES_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "definitions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"term": {"type": "string"}, "definition": {"type": "string"}},
                "required": ["term", "definition"],
            },
        },
        "formulas": {"type": "array", "items": {"type": "string"}},
        "quiz": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "answer_index": {"type": "integer"},
                    "explanation": {"type": "string"},
                },
                "required": ["question", "options", "answer_index", "explanation"],
            },
        },
        "flashcards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"front": {"type": "string"}, "back": {"type": "string"}},
                "required": ["front", "back"],
            },
        },
    },
    "required": ["title", "summary", "key_points", "definitions", "formulas", "quiz", "flashcards"],
}

_SYSTEM = (
    "You are ClassForge, an assistant that turns a raw lecture transcript segment into clean study "
    "material for a student revising for exams. Write directly and plainly, no filler, no repeating "
    "the question. Keep notes faithful to the transcript: never invent facts, numbers, or formulas that "
    "are not implied by the text. If the segment has no real formulas or named definitions, return empty "
    "lists for those fields rather than inventing some. Base every quiz question strictly on this segment."
)


@dataclass
class ChapterNotes:
    title: str
    summary: str
    key_points: list[str] = field(default_factory=list)
    definitions: list[dict] = field(default_factory=list)
    formulas: list[str] = field(default_factory=list)
    quiz: list[dict] = field(default_factory=list)
    flashcards: list[dict] = field(default_factory=list)


def generate(chapter_text: str, chapter_index: int, model: str | None = None) -> ChapterNotes:
    provider = config.ai_provider()
    text = chapter_text.strip()
    if not text:
        return ChapterNotes(title=f"Section {chapter_index + 1}", summary="(No speech detected in this section.)")

    if provider == "ollama":
        try:
            raw = local_llm.chat_json(
                _SYSTEM,
                f"Lecture transcript segment (section {chapter_index + 1}):\n\n{text[:12000]}\n\n"
                "Produce: a short descriptive title (max 8 words), a 2-4 sentence summary, 4-8 key "
                "points, any genuine definitions, any genuine formulas (as plain text, e.g. 'E = mc^2'), "
                "3-5 multiple-choice quiz questions (4 options each, one correct answer_index), and "
                "4-6 flashcards (front = question/term, back = answer).",
                NOTES_SCHEMA,
                model=model,
            )
            data = json.loads(raw)
            return ChapterNotes(
                title=data.get("title") or f"Section {chapter_index + 1}",
                summary=data.get("summary", ""),
                key_points=data.get("key_points", []) or [],
                definitions=data.get("definitions", []) or [],
                formulas=data.get("formulas", []) or [],
                quiz=data.get("quiz", []) or [],
                flashcards=data.get("flashcards", []) or [],
            )
        except Exception:
            # Do not silently disguise local-model failures as successful notes.
            # The job should report missing models, runtime errors, and OOMs.
            raise

    return _extractive_fallback(text, chapter_index)


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_DEF_PATTERN = re.compile(r"\b([A-Z][a-zA-Z0-9 ]{2,30}?)\s+(?:is|are|means|refers to)\s+(.{10,140}?)[.!?]")
_FORMULA_PATTERN = re.compile(r"[A-Za-z]\w*\s*=\s*[^.,;\n]{2,60}")


def _sentences(text: str) -> list[str]:
    # faster-whisper output has little punctuation; split on long pauses already
    # baked into chapter boundaries, so fall back to naive chunking by length.
    if _SENT_SPLIT.search(text):
        return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    words = text.split()
    chunk = 18
    return [" ".join(words[i:i + chunk]) for i in range(0, len(words), chunk)]


def _extractive_fallback(text: str, chapter_index: int) -> ChapterNotes:
    """No AI provider configured: still produce real notes, built directly
    from the transcript (first sentences as summary, longer sentences as key
    points, naive definition/formula pattern matching, cloze-style quiz)."""
    sentences = _sentences(text)
    summary = " ".join(sentences[:3])[:500] or text[:300]
    key_points = sorted(sentences, key=len, reverse=True)[:6]

    definitions = [{"term": m.group(1).strip(), "definition": m.group(2).strip()} for m in _DEF_PATTERN.finditer(text)][:6]
    formulas = list(dict.fromkeys(m.group(0).strip() for m in _FORMULA_PATTERN.finditer(text)))[:6]

    quiz = []
    for s in key_points[:5]:
        words = [w for w in re.findall(r"[A-Za-z]{4,}", s)]
        if not words:
            continue
        target = max(words, key=len)
        blanked = re.sub(rf"\b{re.escape(target)}\b", "_____", s, count=1)
        options = [target] + [w for w in dict.fromkeys(words) if w != target][:3]
        while len(options) < 4:
            options.append("none of the above")
        quiz.append({
            "question": f"Fill in the blank: {blanked}",
            "options": options[:4],
            "answer_index": 0,
            "explanation": f"The original sentence reads: \"{s}\"",
        })

    flashcards = [{"front": f"Explain: {s[:80]}", "back": s} for s in key_points[:6]]

    title = f"Section {chapter_index + 1}: {' '.join(text.split()[:6])}..." if text else f"Section {chapter_index + 1}"
    return ChapterNotes(
        title=title[:90],
        summary=summary,
        key_points=key_points,
        definitions=definitions,
        formulas=formulas,
        quiz=quiz,
        flashcards=flashcards,
    )
