# Copyright (c) 2026 Tanvir. ClassForge project source.
"""Web server: accepts a lecture (URL, video upload, or audio upload), runs the
transcribe -> detect chapters -> generate notes/quiz pipeline in the
background, keeps a searchable library of everything processed, and serves
Markdown / DOCX / PDF exports."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from . import chapters as chaptermod
from . import local_llm
from . import config, export, notes as notesmod, source

app = FastAPI(title=config.APP_NAME, description=config.TAGLINE)

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"} | {
    h.strip().lower() for h in os.environ.get("CLASSFORGE_ALLOWED_HOSTS", "").split(",") if h.strip()
}


def _hostname(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):
        return host[1:host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


@app.middleware("http")
async def same_origin_only(request: Request, call_next):
    """Only this computer's own web pages may use the app (host check against
    DNS rebinding, origin check against cross-site POST/DELETE)."""
    if _hostname(request.headers.get("host", "")) not in _LOCAL_HOSTS:
        return JSONResponse({"detail": f"Open {config.APP_NAME} at http://127.0.0.1:8080."}, status_code=403)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Request from another website refused."}, status_code=403)
    return await call_next(request)


_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=1)  # one lecture at a time

_JOB_ID = re.compile(r"[0-9a-f]{10}")


def _job_dir(job_id: str) -> Path:
    if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
        raise ValueError("Not a valid job ID.")
    root = os.path.realpath(config.JOBS_DIR)
    path = os.path.realpath(os.path.join(root, job_id))
    if not path.startswith(root + os.sep):
        raise ValueError("Not a valid job ID.")
    return Path(path)


def _save(job: dict) -> None:
    d = _job_dir(job["id"])
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "job.json.tmp"
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / "job.json")


def _update(job_id: str, **fields) -> None:
    with _lock:
        job = _jobs[job_id]
        job.update(fields)
        _save(job)


def _load_existing() -> None:
    for f in config.JOBS_DIR.glob("*/job.json"):
        try:
            job = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not _JOB_ID.fullmatch(str(job.get("id", ""))):
            continue
        if job.get("status") in ("queued", "running"):
            job["status"] = "error"
            job["error"] = "The app was closed while this was processing."
        _jobs[job["id"]] = job


_load_existing()


def friendly_error(exc: BaseException) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(exc)).strip()
    text = re.sub(r"^ERROR:\s*", "", text)
    low = text.lower()
    if "getaddrinfo" in low or "failed to resolve" in low or "connection refused" in low or "timed out" in low:
        return "Could not reach the source. Check your internet connection and try again."
    if "429" in low or "too many requests" in low:
        return "The source is rate-limiting requests. Wait a few minutes and try again."
    return text or type(exc).__name__


class JobRequest(BaseModel):
    url: str = Field(default="", max_length=2000)
    title: str = Field(default="", max_length=200)
    ai_model: str = ""
    min_chapter_minutes: int = Field(default=3, ge=1, le=60)


def _run(job_id: str, req: JobRequest, upload_path: Path | None, upload_name: str | None) -> None:
    workdir = _job_dir(job_id)
    last = {"pct": -1.0}

    def progress(pct: float, message: str) -> None:
        pct = round(min(pct, 99), 1)
        if pct == last["pct"]:
            return
        last["pct"] = pct
        _update(job_id, progress=pct, stage=message)

    try:
        if config.ai_provider() == "ollama":
            selected_model = req.ai_model.strip() if req.ai_model else config.OLLAMA_MODEL
            if selected_model.lower() == "none" or not selected_model:
                raise RuntimeError("No local LLM model is selected. Install a model in Ollama and choose it from the Notes engine model dropdown.")
            installed = local_llm.installed_models()
            if selected_model not in installed:
                raise RuntimeError(f"Selected Ollama model '{selected_model}' is not installed or Ollama is unavailable. Install/pull the model, then select an available model in the dropdown.")
        if upload_path is not None:
            lec = source.from_local_file(upload_path, workdir, progress, title=req.title or upload_name)
        elif req.url.strip():
            lec = source.from_url(req.url.strip(), workdir, progress)
        else:
            raise ValueError("Give a lecture URL or upload a recording.")

        if not lec.words:
            raise ValueError("No speech was detected in this recording.")

        progress(82, "Finding chapter breaks")
        chs = chaptermod.build_chapters(lec.words, lec.duration, min_gap=req.min_chapter_minutes * 60)

        progress(86, "Writing notes and quizzes")
        chapter_results = []
        for i, ch in enumerate(chs):
            n = notesmod.generate(ch.text, i, model=req.ai_model or None)
            chapter_results.append({
                "index": i,
                "start": ch.start,
                "end": ch.end,
                "title": n.title,
                "summary": n.summary,
                "key_points": n.key_points,
                "definitions": n.definitions,
                "formulas": n.formulas,
                "quiz": n.quiz,
                "flashcards": n.flashcards,
                "transcript": ch.text,
            })
            progress(86 + 12 * (i + 1) / max(1, len(chs)), "Writing notes and quizzes")

        result = {
            "title": req.title or lec.title,
            "duration": lec.duration,
            "duration_clock": chaptermod.clock(lec.duration),
            "language": lec.language,
            "transcript_source": lec.transcript_source,
            "chapter_count": len(chapter_results),
            "chapters": chapter_results,
        }
        (workdir / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        _add_to_library(job_id, result)
        _update(job_id, status="done", progress=100.0, stage="Done")
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _update(job_id, status="error", error=friendly_error(exc))
    finally:
        if upload_path is not None and upload_path.exists():
            try:
                upload_path.unlink()
            except OSError:
                pass


def _library() -> list[dict]:
    if not config.LIBRARY_DB.exists():
        return []
    try:
        return json.loads(config.LIBRARY_DB.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _add_to_library(job_id: str, result: dict) -> None:
    lib = _library()
    lib = [e for e in lib if e["job_id"] != job_id]
    lib.insert(0, {
        "job_id": job_id,
        "title": result["title"],
        "duration_clock": result["duration_clock"],
        "chapter_count": result["chapter_count"],
        "processed_at": time.time(),
        "chapter_titles": [c["title"] for c in result["chapters"]],
    })
    config.LIBRARY_DB.write_text(json.dumps(lib[:500], ensure_ascii=False), encoding="utf-8")


@app.post("/api/jobs")
async def create_job(
    url: str = Form(default=""),
    title: str = Form(default=""),
    ai_model: str = Form(default=""),
    min_chapter_minutes: int = Form(default=3),
    file: UploadFile | None = File(default=None),
):
    req = JobRequest(url=url, title=title, ai_model=ai_model, min_chapter_minutes=min_chapter_minutes)
    job_id = uuid.uuid4().hex[:10]
    workdir = _job_dir(job_id)
    workdir.mkdir(parents=True, exist_ok=True)

    upload_path: Path | None = None
    upload_name: str | None = None
    if file is not None and file.filename:
        ext = Path(file.filename).suffix.lower()
        allowed = source.AUDIO_EXTS | source.VIDEO_EXTS
        if ext not in allowed:
            raise HTTPException(400, f"Unsupported file type {ext!r}. Allowed: {', '.join(sorted(allowed))}")
        upload_path = workdir / f"upload{ext}"
        data = await file.read()
        if len(data) > 2 * 1024 * 1024 * 1024:
            raise HTTPException(400, "File too large (2 GB limit).")
        upload_path.write_bytes(data)
        upload_name = Path(file.filename).stem
    elif not url.strip():
        raise HTTPException(400, "Give a lecture URL or upload a recording.")

    job = {"id": job_id, "status": "queued", "progress": 0.0, "stage": "Queued", "created_at": time.time()}
    with _lock:
        _jobs[job_id] = job
    _save(job)
    _pool.submit(_run, job_id, req, upload_path, upload_name)
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job.")
    return job


@app.get("/api/jobs/{job_id}/result")
def job_result(job_id: str):
    d = _job_dir(job_id)
    f = d / "result.json"
    if not f.exists():
        raise HTTPException(404, "No result yet for this job.")
    return json.loads(f.read_text(encoding="utf-8"))


@app.get("/api/jobs/{job_id}/export/{fmt}")
def job_export(job_id: str, fmt: str):
    d = _job_dir(job_id)
    f = d / "result.json"
    if not f.exists():
        raise HTTPException(404, "No result yet for this job.")
    result = json.loads(f.read_text(encoding="utf-8"))
    safe_title = re.sub(r"[^\w\- ]", "", result["title"])[:60].strip() or "lecture"

    if fmt == "md":
        text = export.to_markdown(result["title"], result["duration_clock"], result["chapters"])
        out = d / f"{safe_title}.md"
        out.write_text(text, encoding="utf-8")
        return FileResponse(out, filename=out.name, media_type="text/markdown")
    if fmt == "docx":
        out = export.to_docx(result["title"], result["duration_clock"], result["chapters"], d / f"{safe_title}.docx")
        return FileResponse(out, filename=out.name,
                             media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if fmt == "pdf":
        out = export.to_pdf(result["title"], result["duration_clock"], result["chapters"], d / f"{safe_title}.pdf")
        return FileResponse(out, filename=out.name, media_type="application/pdf")
    raise HTTPException(400, "Unknown export format. Use md, docx, or pdf.")


def _save_ollama_model(model: str) -> None:
    """Persist the selected Ollama tag in .profile and update live config."""
    profile = config.ROOT / ".profile"
    lines = profile.read_text(encoding="utf-8").splitlines() if profile.exists() else []
    replacement = f"OLLAMA_MODEL={model}" if model else "OLLAMA_MODEL="
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith("OLLAMA_MODEL="):
            lines[i] = replacement
            found = True
            break
    if not found:
        lines.extend(["", "# Selected local Ollama model (managed by ClassForge)", replacement])
    tmp = profile.with_suffix(profile.suffix + ".tmp")
    tmp.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    tmp.replace(profile)
    if model:
        os.environ["OLLAMA_MODEL"] = model
    else:
        os.environ.pop("OLLAMA_MODEL", None)
    config.OLLAMA_MODEL = model


@app.get("/api/models")
def get_models():
    """List locally installed Ollama models and the saved selection."""
    provider = config.ai_provider()
    if provider != "ollama":
        return {"provider": provider, "models": [], "default": "", "selected": "",
                "note": "Local model selection is available when Ollama is the active notes engine."}
    models = local_llm.installed_models()
    selected = config.OLLAMA_MODEL
    note = "Choose an installed model. Your selection is saved to .profile."
    if not models:
        selected = ""
        note = "No Ollama models found or Ollama is unavailable. Install/pull a model, then refresh this page."
    elif selected and selected not in models:
        note = f"Saved model '{selected}' is not installed. Select an available model or None."
    return {"provider": provider, "models": models, "default": selected, "selected": selected, "note": note}


class ModelSelection(BaseModel):
    model: str = Field(default="", max_length=200)


@app.post("/api/settings/model")
def save_model_selection(selection: ModelSelection):
    if config.ai_provider() != "ollama":
        raise HTTPException(400, "Ollama is not the active notes engine.")
    model = selection.model.strip()
    if model and model.lower() != "none":
        installed = local_llm.installed_models()
        if model not in installed:
            raise HTTPException(400, f"Model '{model}' is not installed in Ollama.")
    else:
        model = ""
    try:
        _save_ollama_model(model)
    except OSError as exc:
        raise HTTPException(500, f"Could not save .profile: {exc}") from exc
    return {"ok": True, "model": model, "note": "Selection saved to .profile." if model else "No model selected. Local LLM processing will return an error until you select an installed model."}


@app.get("/api/library")
def library():
    return _library()


@app.get("/api/library/search")
def library_search(q: str = ""):
    q = q.strip().lower()
    if not q:
        return []
    hits = []
    for entry in _library():
        job_id = entry["job_id"]
        f = _job_dir(job_id) / "result.json"
        if not f.exists():
            continue
        result = json.loads(f.read_text(encoding="utf-8"))
        matches = []
        for ch in result["chapters"]:
            haystack = " ".join([ch["title"], ch["summary"], ch["transcript"]]).lower()
            if q in haystack:
                matches.append({"index": ch["index"], "start": ch["start"], "title": ch["title"]})
        if q in result["title"].lower() or matches:
            hits.append({"job_id": job_id, "title": result["title"], "matches": matches[:8]})
    return hits


@app.get("/api/status")
def status():
    return {
        "app": config.APP_NAME,
        "tagline": config.TAGLINE,
        "ai_provider": config.ai_provider(),
        "missing_tools": config.missing_tools(),
        "whisper_model": config.WHISPER_MODEL,
        "ollama_model": config.OLLAMA_MODEL,
        "ollama_runtime": local_llm.runtime_info() if config.ai_provider() == "ollama" else None,
    }


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    d = _job_dir(job_id)
    import shutil as _shutil
    if d.exists():
        _shutil.rmtree(d, ignore_errors=True)
    with _lock:
        _jobs.pop(job_id, None)
    lib = [e for e in _library() if e["job_id"] != job_id]
    config.LIBRARY_DB.write_text(json.dumps(lib, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


app.mount("/", StaticFiles(directory=str(config.STATIC_DIR), html=True), name="static")
