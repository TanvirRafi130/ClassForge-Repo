# Copyright (c) 2026 Tanvir. ClassForge project source.
"""Turn a flat, word-level transcript into timestamped chapters.

Boundaries are picked from two signals that tend to line up with a real
topic change in a lecture: a longer-than-usual pause in speech, and a shift
in the vocabulary being used (a simple bag-of-words dissimilarity between the
text just before and just after a candidate point). Each chapter is then
handed to the notes model for a short, descriptive title.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .source import Word

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "for", "with", "as", "by", "that", "this", "it", "its",
    "we", "you", "i", "so", "if", "then", "than", "from", "into", "about", "like", "just",
    "there", "here", "what", "which", "who", "when", "where", "why", "how", "can", "will",
    "would", "could", "should", "do", "does", "did", "have", "has", "had", "not", "no", "yes",
    "okay", "ok", "um", "uh", "basically", "actually", "really", "also", "going", "gonna",
}


@dataclass
class Chapter:
    index: int
    title: str
    start: float
    end: float
    words: list[Word] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def _tokens(words: list[Word]) -> set[str]:
    out = set()
    for w in words:
        tok = re.sub(r"[^a-z0-9']", "", w.text.lower())
        if tok and tok not in _STOPWORDS:
            out.add(tok)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 1.0


def detect_boundaries(
    words: list[Word],
    duration: float,
    min_gap: float = 180.0,
    target_gap: float = 420.0,
    window: int = 60,
) -> list[float]:
    """Return candidate chapter start times (seconds), always including 0."""
    if not words or duration <= 0:
        return [0.0]

    candidates: list[tuple[float, float]] = []  # (time, pause length)
    for i in range(1, len(words)):
        gap = words[i].start - words[i - 1].end
        if gap > 0.9:
            candidates.append((words[i].start, gap))

    if not candidates:
        # No usable pauses (e.g. very dense speech): fall back to even slices.
        n = max(1, round(duration / target_gap))
        step = duration / n
        return [round(i * step, 2) for i in range(n)]

    boundaries = [0.0]
    last = 0.0
    i = 0
    by_time = sorted(candidates, key=lambda c: c[0])
    while i < len(by_time):
        t, _ = by_time[i]
        if t - last < min_gap:
            i += 1
            continue
        # Look at a window of words before/after this pause for a topic shift.
        before = [w for w in words if t - window <= w.start < t]
        after = [w for w in words if t <= w.start < t + window]
        similarity = _jaccard(_tokens(before), _tokens(after))
        is_topic_shift = similarity < 0.22
        is_overdue = t - last >= target_gap
        if is_topic_shift or is_overdue:
            boundaries.append(round(t, 2))
            last = t
        i += 1

    return boundaries


def build_chapters(words: list[Word], duration: float, min_gap: int = 180) -> list[Chapter]:
    boundaries = detect_boundaries(words, duration, min_gap=float(min_gap))
    chapters: list[Chapter] = []
    for idx, start in enumerate(boundaries):
        end = boundaries[idx + 1] if idx + 1 < len(boundaries) else duration
        chapter_words = [w for w in words if start <= w.start < end]
        chapters.append(Chapter(index=idx, title=f"Section {idx + 1}", start=start, end=end, words=chapter_words))
    return [c for c in chapters if c.words or len(chapters) == 1]


def clock(t: float) -> str:
    t = max(0, int(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
