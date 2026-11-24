# Copyright (c) 2026 Tanvir. ClassForge project source.
"""Accept a lecture: a video URL, an uploaded video, or an uploaded audio file,
and produce a word-level transcript for it (YouTube captions when available,
Whisper otherwise)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import yt_dlp

from . import config

Progress = Callable[[float, str], None]

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Lecture:
    media_path: Path
    title: str
    duration: float
    language: str
    words: list[Word]
    transcript_source: str  # "captions" or "whisper"
    is_audio_only: bool


def _ydl_base() -> dict:
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
    if not shutil.which("deno") and shutil.which("node"):
        opts["js_runtimes"] = {"node": {}}
    return opts


def from_url(url: str, workdir: Path, progress: Progress) -> Lecture:
    """A lecture given as a link (YouTube, Vimeo, a direct video/audio URL, etc.)."""
    progress(2, "Reading source details")
    with yt_dlp.YoutubeDL(_ydl_base()) as ydl:
        info = ydl.extract_info(url, download=False)

    duration = float(info.get("duration") or 0)
    if info.get("is_live"):
        raise ValueError("Live streams can't be processed until they finish.")

    lang = (info.get("language") or "en").split("-")[0]

    def hook(d: dict) -> None:
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                progress(3 + 22 * d.get("downloaded_bytes", 0) / total, "Downloading source")

    opts = _ydl_base() | {
        "format": "bestaudio/best",
        "outtmpl": str(workdir / "source.%(ext)s"),
        "retries": 5,
        "progress_hooks": [hook],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    media_path = next((p for p in workdir.glob("source.*") if p.suffix.lower() != ".json3"), None)
    if not media_path:
        raise RuntimeError("Download finished but no media file was produced.")

    words: list[Word] = []
    transcript_source = "captions"
    track = pick_caption_track(info, lang)
    if track:
        progress(25, "Fetching captions")
        words = _fetch_captions(url, workdir, track)
    if not words:
        progress(26, "No captions available, transcribing audio with Whisper")
        words = whisper_transcribe(media_path, workdir, progress)
        transcript_source = "whisper"

    return Lecture(
        media_path=media_path,
        title=info.get("title") or "Untitled lecture",
        duration=duration or (words[-1].end if words else 0.0),
        language=lang,
        words=words,
        transcript_source=transcript_source,
        is_audio_only=True,
    )


def pick_caption_track(info: dict, lang: str) -> str | None:
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    for pool, codes in ((manual, [lang, "en"]), (auto, [f"{lang}-orig", lang, "en-orig", "en"])):
        for code in codes:
            if code in pool:
                return code
    return None


def _fetch_captions(url: str, workdir: Path, track: str) -> list[Word]:
    opts = _ydl_base() | {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": [track],
        "subtitlesformat": "json3",
        "outtmpl": str(workdir / "source.%(ext)s"),
        "retries": 3,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError:
        return []
    sub = workdir / f"source.{track}.json3"
    return parse_json3(sub) if sub.exists() else []


def from_local_file(path: Path, workdir: Path, progress: Progress, title: str | None = None) -> Lecture:
    """An uploaded lecture recording (video or audio): always transcribed with Whisper."""
    progress(2, "Reading file details")
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        duration = float(out.stdout.strip())
    except ValueError:
        raise ValueError("That file doesn't look like something ffmpeg can read.") from None

    progress(26, "Transcribing audio")
    words = whisper_transcribe(path, workdir, progress)
    return Lecture(
        media_path=path,
        title=title or path.stem or "Untitled lecture",
        duration=duration or (words[-1].end if words else 0.0),
        language="",
        words=words,
        transcript_source="whisper",
        is_audio_only=path.suffix.lower() in AUDIO_EXTS,
    )


_NOISE = re.compile(r"^\[.*\]$|^\(.*\)$|^>>+$|^♪+$|^[-–—]+$")


def _clean(token: str) -> str:
    token = token.replace("\n", " ").strip()
    token = token.replace(">>", "").strip()
    return "" if _NOISE.match(token) else token


def parse_json3(path: Path) -> list[Word]:
    data = json.loads(path.read_text(encoding="utf-8"))
    words: list[Word] = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        ev_start = ev.get("tStartMs", 0) / 1000
        ev_end = ev_start + ev.get("dDurationMs", 0) / 1000
        timed = any("tOffsetMs" in s for s in segs[1:])
        if not timed:
            segs = [{"utf8": " ".join(_clean(s.get("utf8", "")) for s in segs)}]
        if timed:
            for s in segs:
                tok = _clean(s.get("utf8", ""))
                if not tok:
                    continue
                start = ev_start + s.get("tOffsetMs", 0) / 1000
                for part in tok.split():
                    words.append(Word(part, start, ev_end))
        else:
            parts = [p for p in (_clean(t) for t in segs[0].get("utf8", "").split()) if p]
            if not parts:
                continue
            step = max(ev_end - ev_start, 0.2) / len(parts)
            for i, part in enumerate(parts):
                words.append(Word(part, ev_start + i * step, ev_start + (i + 1) * step))

    words.sort(key=lambda w: w.start)
    for i, w in enumerate(words):
        nxt = words[i + 1].start if i + 1 < len(words) else w.start + 0.6
        w.end = max(w.start + 0.08, min(nxt, w.start + 0.9))
    return words


def read_wav_16k(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


def whisper_transcribe(media_path: Path, workdir: Path, progress: Progress) -> list[Word]:
    from faster_whisper import WhisperModel

    wav = workdir / "audio.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(media_path), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
        check=True,
    )
    model = WhisperModel(
        config.WHISPER_MODEL, device="cpu", compute_type="int8", download_root=str(config.MODELS_DIR / "whisper")
    )
    segments, info = model.transcribe(read_wav_16k(wav), word_timestamps=True, vad_filter=True)
    total = info.duration or 1
    words: list[Word] = []
    for seg in segments:
        for w in seg.words or []:
            tok = w.word.strip()
            if tok:
                words.append(Word(tok, float(w.start), float(w.end)))
        progress(26 + 54 * min(seg.end / total, 1), "Transcribing audio")
    wav.unlink(missing_ok=True)
    return words
