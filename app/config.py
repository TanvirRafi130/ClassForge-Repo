# Copyright (c) 2026 Tanvir. ClassForge project source.
"""Paths and settings shared across the app."""
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# override: the app's .profile wins over machine-wide variables
load_dotenv(ROOT / ".profile", override=True)

DATA_DIR = Path(os.environ.get("CLASSFORGE_DATA_DIR") or ROOT / "data")
JOBS_DIR = DATA_DIR / "jobs"
MODELS_DIR = DATA_DIR / "models"
LIBRARY_DB = DATA_DIR / "library.json"
STATIC_DIR = ROOT / "static"

for _d in (JOBS_DIR, MODELS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Keep model downloads inside the project instead of the user profile.
os.environ.setdefault("HF_HOME", str(MODELS_DIR / "hf"))

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "").strip()
OLLAMA_CTX = int(os.environ.get("OLLAMA_CTX", "8192"))

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")

APP_NAME = "ClassForge"
TAGLINE = "Turn hours of learning into structured knowledge."
COPYRIGHT_OWNER = "Tanvir"

OLLAMA_EXE = os.environ.get("OLLAMA_EXE", "") or shutil.which("ollama") or ""
OLLAMA_MODELS_DIR = os.environ.get("OLLAMA_MODELS", "")

# Minimum gap (seconds) between two detected chapter boundaries.
MIN_CHAPTER_GAP = int(os.environ.get("CLASSFORGE_MIN_CHAPTER_GAP", "180"))


def ai_provider() -> str | None:
    """Which AI writes notes/quizzes: "ollama" (local), "gemini", "claude", or None.
    AI_PROVIDER in .profile forces one; otherwise whichever is configured wins."""
    forced = os.environ.get("AI_PROVIDER", "").strip().lower()
    if forced in ("ollama", "gemini", "claude"):
        return forced
    if forced in ("none", "basic"):
        return None
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "claude"
    if OLLAMA_EXE and os.path.exists(OLLAMA_EXE):
        return "ollama"
    return None


def missing_tools() -> list[str]:
    """Programs the pipeline shells out to."""
    return [t for t in ("ffmpeg", "ffprobe") if not shutil.which(t)]
