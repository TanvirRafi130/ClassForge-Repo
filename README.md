# ClassForge

**Turn hours of learning into structured knowledge.**

ClassForge takes a recorded lecture — a video link, an uploaded video, or an
uploaded audio file — and turns it into chaptered, searchable study material:
timestamped sections, a summary and key points per section, definitions,
formulas, a multiple-choice quiz, and flashcards. Everything runs locally on
your own machine; nothing is uploaded to a third-party server unless you
choose to use a cloud AI provider for the notes-writing step.

> Built by reusing a local-first media pipeline (download/ingest → Whisper
> transcription → FastAPI background jobs) and replacing the clip-selection
> and video-rendering pieces with lecture-specific modules: chapter/topic
> detection, notes + quiz generation, and document export.

---

## What it does

- **Accepts** lecture recordings as a pasted URL (YouTube, Vimeo, a direct
  video/audio link, etc.) **or** an uploaded file (`.mp4 .mov .mkv .webm
  .avi .m4v .mp3 .wav .m4a .aac .flac .ogg .opus .wma`).
- **Transcribes** the audio word-for-word with Whisper (via
  `faster-whisper`), reusing YouTube's own captions first when they exist,
  to save time.
- **Detects topic changes automatically** from a mix of long pauses in
  speech and a shift in vocabulary between what's said just before and just
  after a candidate break — no manual chapter marking needed.
- **Creates chapters with timestamps**, e.g.:
  ```
  00:00  – Introduction to databases
  12:30  – Relational database concepts
  35:20  – Normalization
  58:10  – SQL joins
  1:24:00 – Indexing
  ```
- **Generates, per chapter:** a short descriptive title, a summary, key
  points, definitions, formulas, a 3–5 question multiple-choice quiz (each
  with an explanation), and 4–6 flashcards.
- **Exports** the full set of notes to **Markdown**, **DOCX**, or **PDF**
  with one click.
- **Keeps a library** of everything you've processed, searchable across
  every chapter's title, summary and raw transcript.

## How it's built (architecture)

| Piece | File | Role |
|---|---|---|
| Ingestion | `app/source.py` | Downloads a URL (via `yt-dlp`) or reads an uploaded file; extracts audio; fetches existing captions when available |
| Transcription | `app/source.py` (`whisper_transcribe`) | Word-level transcript via `faster-whisper`, used whenever no captions exist |
| Topic/chapter detection | `app/chapters.py` | New module — pause + vocabulary-shift heuristic turns the flat transcript into chapters |
| Notes & quiz generation | `app/notes.py` | New module — calls the configured AI (local Ollama model by default) for structured notes/quiz/flashcards per chapter, with a dependency-free extractive fallback if no AI engine is configured |
| AI client | `app/local_llm.py` | Thin JSON-schema-constrained client for a local Ollama server (reused as-is) |
| Jobs & API | `app/main.py` | FastAPI app: background job queue, progress polling, library + search endpoints, export endpoints |
| Export | `app/export.py` | New module — renders the processed result to Markdown / DOCX (`python-docx`) / PDF (`fpdf2`) |
| Frontend | `static/index.html`, `static/app.css`, `static/app.js` | A from-scratch notebook/academic-themed UI (no framework, no build step) — upload flow, progress bar, chaptered notes reader with tabs (Notes / Quiz / Flashcards / Transcript), library with search |

The UI is deliberately a different visual language from a media-editing
tool: warm paper background, a serif display face for headings, a teal
"ink" accent, and a table-of-contents reading layout, because the job here
is reading and revising, not timeline scrubbing.

### Why local-first

Transcription (Whisper) always runs on your machine — no audio ever leaves
it. Note-writing can also run fully offline through a local [Ollama](https://ollama.com)
model, or you can point it at Gemini/Claude if you'd rather use a cloud
model for better-written notes. Either way, nothing is sent anywhere unless
you explicitly configure a cloud provider.

---

## Setup

### Requirements

- **Python 3.10+**
- **ffmpeg** and **ffprobe** on your `PATH` ([ffmpeg.org](https://ffmpeg.org/download.html))
- One notes engine (pick one — ClassForge still works with none, using a
  built-in extractive fallback):
  - [**Ollama**](https://ollama.com) installed locally (free, offline, slower on CPU), **or**
  - a **Gemini** API key, **or**
  - an **Anthropic (Claude)** API key

### 1. Get the files

Unzip this project anywhere on your machine.

### 2. Install

**macOS / Linux**
```bash
./setup.sh
```

**Windows**
```bat
setup.bat
```

Either script creates a Python virtual environment, installs everything in
`requirements.txt`, and copies `.profile.example` to `.profile` for you to
edit.

### 3. Configure your notes engine

Open `.profile` (created in step 2) and uncomment the block for whichever
engine you want:

```ini
# Local, free, offline — install Ollama first, then:
OLLAMA_EXE=/usr/local/bin/ollama
OLLAMA_MODEL=qwen3.5:4b

# or Gemini:
GEMINI_API_KEY=your-key-here

# or Claude:
ANTHROPIC_API_KEY=your-key-here
```

If you skip this entirely, ClassForge still runs — it falls back to a
built-in, transcript-only notes generator (no AI call) so you can try it out
with zero setup.

If you're using Ollama, pull at least one model first:
```bash
ollama pull qwen3.5:4b
```
You don't need to put the model name in `.profile` — see below.

### 4. Run it

**macOS / Linux**
```bash
./run.sh
```

**Windows**
```bat
run.bat
```

Then open **http://127.0.0.1:8080** in your browser.

---

## Using it

1. **New lecture** → paste a link or drag in a recording, optionally give it
   a title, pick a minimum chapter length (how close together chapter breaks
   are allowed to be), and pick a **model** from the dropdown — it's filled
   in live from whatever's actually available (every model you've pulled in
   Ollama, for example), so you never have to edit `.profile` just to try a
   different model. If nothing is configured, the dropdown says so and
   ClassForge uses its built-in notes generator instead. Then click
   **Process lecture**.
2. Watch the progress bar — downloading/reading → transcribing → finding
   chapter breaks → writing notes & quizzes.
3. When it's done, you land on the **reading view**: a table of contents on
   the left, and each chapter as a card with **Notes / Quiz / Flashcards /
   Transcript** tabs.
4. Use **Export** (top right) to download the whole set of notes as
   **Markdown**, **DOCX**, or **PDF**.
5. Everything you process is saved to your **Library** (left sidebar), and
   the search box above it searches titles, summaries and transcripts across
   every lecture you've processed.

## Configuration reference (`.profile`)

| Variable | Default | What it does |
|---|---|---|
| `AI_PROVIDER` | auto-detected | Force `ollama`, `gemini`, `claude`, or `none` |
| `OLLAMA_EXE` / `OLLAMA_URL` / `OLLAMA_MODEL` / `OLLAMA_MODELS` | — | Local Ollama setup |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | — | Gemini setup |
| `ANTHROPIC_API_KEY` / `CLAUDE_MODEL` | — | Claude setup |
| `WHISPER_MODEL` | `small` | Whisper model size: `tiny`, `base`, `small`, `medium`, `large-v3` |
| `CLASSFORGE_MIN_CHAPTER_GAP` | `180` | Minimum seconds between two chapter breaks |
| `CLASSFORGE_DATA_DIR` | `./data` | Where jobs, models, and your library are stored |
| `CLASSFORGE_ALLOWED_HOSTS` | — | Extra hostnames allowed to open the app besides `localhost`/`127.0.0.1` |

## Project layout

```
classforge/
├── app/
│   ├── main.py        # FastAPI app, job queue, API routes
│   ├── source.py       # URL/file ingestion + Whisper transcription
│   ├── chapters.py     # Topic/chapter boundary detection
│   ├── notes.py        # Notes/quiz/flashcard generation (AI + fallback)
│   ├── local_llm.py    # Ollama JSON-schema client
│   ├── export.py       # Markdown / DOCX / PDF rendering
│   └── config.py       # Paths, env/.profile loading, provider selection
├── static/
│   ├── index.html
│   ├── app.css          # Academic/notebook design system
│   └── app.js
├── data/                # Created on first run: jobs, downloaded models, library.json
├── requirements.txt
├── requirements-dev.txt
├── setup.sh / setup.bat
├── run.sh / run.bat
└── .profile.example
```

## Notes on accuracy & limits

- Chapter detection is heuristic (pauses + vocabulary shift), not a trained
  topic-segmentation model — it works well for lectures with a clear verbal
  structure, less well for very dense, pause-free speech (in which case it
  falls back to even time-based slices).
- With no AI engine configured, notes/quiz/flashcards are generated
  **extractively** straight from the transcript (longest sentences as key
  points, simple pattern-matching for definitions/formulas, cloze-style quiz
  questions) — useful, but noticeably less polished than an LLM-written set.
- Long lectures on CPU-only machines can take a while to transcribe;
  a smaller `WHISPER_MODEL` (e.g. `base`) trades accuracy for speed.
- Processing one lecture at a time (one background worker) keeps CPU/RAM use
  predictable on a typical laptop; queue several and they'll run in order.

## Business potential

Built for students revising from recorded lectures, and equally useful for
universities, online course platforms, and coaching centres that want to
turn raw classroom recordings into structured, exportable study material at
scale.

## License

See `LICENSE`. © Tanvir.
