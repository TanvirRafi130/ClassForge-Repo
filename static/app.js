// ClassForge frontend — vanilla JS, no build step.
(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  const views = { process: $("#view-process"), result: $("#view-result"), library: $("#view-library") };
  function showView(name) {
    Object.entries(views).forEach(([k, el]) => el.classList.toggle("hidden", k !== name));
    $("#nav-process").classList.toggle("active", name === "process");
    $("#nav-library").classList.toggle("active", name === "library");
  }
  $("#nav-process").addEventListener("click", () => showView("process"));
  $("#nav-library").addEventListener("click", () => { showView("library"); loadLibrary(); });
  $("#back-btn").addEventListener("click", () => showView("process"));

  // --- status / engine badge ---
  fetch("/api/status").then(r => r.json()).then(s => {
    const badge = $("#provider-badge");
    if (s.missing_tools && s.missing_tools.length) {
      badge.textContent = `Missing: ${s.missing_tools.join(", ")}`;
      badge.classList.add("off");
    } else if (s.ai_provider) {
      badge.textContent = `Notes engine: ${s.ai_provider}`;
      badge.classList.add("ok");
    } else {
      badge.textContent = "No AI engine — using built-in notes";
    }
  }).catch(() => {});

  // --- model dropdown: populate from Ollama and persist selection in .profile ---
  async function loadModels() {
    const select = $("#model-select");
    const note = $("#model-note");
    select.innerHTML = "";
    try {
      const response = await fetch("/api/models");
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not load models.");
      if (data.provider !== "ollama") {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = data.provider ? `Ollama unavailable (active engine: ${data.provider})` : "No AI engine configured";
        select.appendChild(opt);
        select.disabled = true;
        note.textContent = data.note || "";
        return;
      }

      // Keep an explicit None option even when no models are installed.
      const none = document.createElement("option");
      none.value = "none";
      none.textContent = "None — disable local LLM";
      select.appendChild(none);
      (data.models || []).forEach(model => {
        const opt = document.createElement("option");
        opt.value = model;
        opt.textContent = model;
        select.appendChild(opt);
      });
      select.disabled = false;
      const selected = data.selected || data.default || "none";
      select.value = (data.models || []).includes(selected) ? selected : "none";
      note.textContent = data.note || "Selection is saved automatically to .profile.";
    } catch (err) {
      select.innerHTML = '<option value="none">None — model list unavailable</option>';
      select.disabled = false;
      note.textContent = err.message || "Could not load Ollama models.";
    }
  }

  $("#model-select").addEventListener("change", async (event) => {
    const select = event.currentTarget;
    const note = $("#model-note");
    select.disabled = true;
    try {
      const response = await fetch("/api/settings/model", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: select.value })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not save model selection.");
      note.textContent = data.note;
    } catch (err) {
      note.textContent = err.message;
      await loadModels();
    } finally {
      select.disabled = false;
    }
  });
  loadModels();

  // --- upload tabs ---
  $$(".tab").forEach(tab => tab.addEventListener("click", () => {
    $$(".tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    $$(".tab-pane").forEach(p => p.classList.toggle("active", p.dataset.pane === tab.dataset.tab));
  }));

  // --- drag & drop / file picker ---
  const dropzone = $("#dropzone"), fileInput = $("#file-input"), fileChosen = $("#file-chosen");
  dropzone.addEventListener("click", (e) => { if (e.target !== fileInput) fileInput.click(); });
  fileInput.addEventListener("change", () => updateChosenFile());
  ["dragenter", "dragover"].forEach(ev => dropzone.addEventListener(ev, e => { e.preventDefault(); dropzone.classList.add("drag"); }));
  ["dragleave", "drop"].forEach(ev => dropzone.addEventListener(ev, e => { e.preventDefault(); dropzone.classList.remove("drag"); }));
  dropzone.addEventListener("drop", e => {
    if (e.dataTransfer.files.length) { fileInput.files = e.dataTransfer.files; updateChosenFile(); }
  });
  function updateChosenFile() {
    const f = fileInput.files[0];
    fileChosen.textContent = f ? `${f.name} (${(f.size / 1e6).toFixed(1)} MB)` : "mp4, mov, mkv, mp3, wav, m4a and more — up to 2 GB";
  }

  // --- submit job ---
  let pollTimer = null;
  $("#job-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("#error-card").classList.add("hidden");
    const form = new FormData(e.target);
    const usingFile = $(".tab.active").dataset.tab === "file";
    if (!usingFile) form.delete("file");
    if (usingFile) form.delete("url");

    if (usingFile && !fileInput.files.length) return showError("Choose a file to upload first.");
    if (!usingFile && !form.get("url").trim()) return showError("Paste a lecture URL first.");

    $("#submit-btn").disabled = true;
    $("#progress-card").classList.remove("hidden");
    setProgress(0, "Starting…");

    try {
      const res = await fetch("/api/jobs", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not start the job.");
      pollJob(data.id);
    } catch (err) {
      $("#submit-btn").disabled = false;
      showError(err.message);
    }
  });

  function showError(msg) {
    $("#error-card").classList.remove("hidden");
    $("#error-text").textContent = msg;
    $("#progress-card").classList.add("hidden");
  }
  function setProgress(pct, stage) {
    $("#progress-fill").style.width = `${pct}%`;
    $("#progress-pct").textContent = `${Math.round(pct)}%`;
    $("#progress-stage").textContent = stage;
  }

  function pollJob(jobId) {
    clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      const res = await fetch(`/api/jobs/${jobId}`);
      const job = await res.json();
      setProgress(job.progress || 0, job.stage || job.status);
      if (job.status === "done") {
        clearInterval(pollTimer);
        $("#submit-btn").disabled = false;
        $("#progress-card").classList.add("hidden");
        const result = await (await fetch(`/api/jobs/${jobId}/result`)).json();
        renderResult(jobId, result);
      } else if (job.status === "error") {
        clearInterval(pollTimer);
        $("#submit-btn").disabled = false;
        showError(job.error || "Processing failed.");
      }
    }, 1200);
  }

  // --- result rendering ---
  function clock(t) {
    t = Math.max(0, Math.round(t));
    const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
    const mm = h ? String(m).padStart(2, "0") : m;
    const ss = String(s).padStart(2, "0");
    return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
  }

  function renderResult(jobId, result) {
    showView("result");
    $("#result-title").textContent = result.title;
    $("#result-duration").textContent = result.duration_clock;
    $("#result-chapters").textContent = `${result.chapter_count} section${result.chapter_count === 1 ? "" : "s"}`;
    $("#result-source").textContent = result.transcript_source === "whisper" ? "Transcribed with Whisper" : "Captions";

    $("#export-md").href = `/api/jobs/${jobId}/export/md`;
    $("#export-docx").href = `/api/jobs/${jobId}/export/docx`;
    $("#export-pdf").href = `/api/jobs/${jobId}/export/pdf`;

    const toc = $("#toc"); toc.innerHTML = "";
    const chaptersEl = $("#chapters"); chaptersEl.innerHTML = "";
    const tpl = $("#tpl-chapter");

    result.chapters.forEach(ch => {
      const anchorId = `chapter-${ch.index}`;

      const tocLink = document.createElement("a");
      tocLink.href = `#${anchorId}`;
      tocLink.innerHTML = `<span class="toc-time">${clock(ch.start)}</span>${ch.title}`;
      toc.appendChild(tocLink);

      const node = tpl.content.cloneNode(true);
      const article = node.querySelector(".chapter");
      article.id = anchorId;
      node.querySelector(".chapter-time").textContent = `${clock(ch.start)} – ${clock(ch.end)}`;
      node.querySelector(".chapter-title").textContent = ch.title;
      node.querySelector(".chapter-summary").textContent = ch.summary || "No summary available.";

      const kp = node.querySelector(".kp-list");
      (ch.key_points || []).forEach(p => { const li = document.createElement("li"); li.textContent = p; kp.appendChild(li); });
      if (!ch.key_points || !ch.key_points.length) node.querySelector(".kp-block").classList.add("empty");

      const defs = node.querySelector(".def-list");
      (ch.definitions || []).forEach(d => {
        const dt = document.createElement("dt"); dt.textContent = d.term;
        const dd = document.createElement("dd"); dd.textContent = d.definition;
        defs.appendChild(dt); defs.appendChild(dd);
      });
      if (!ch.definitions || !ch.definitions.length) node.querySelector(".def-block").classList.add("empty");

      const formulas = node.querySelector(".formula-list");
      (ch.formulas || []).forEach(f => { const li = document.createElement("li"); li.textContent = f; formulas.appendChild(li); });
      if (!ch.formulas || !ch.formulas.length) node.querySelector(".formula-block").classList.add("empty");

      const quizList = node.querySelector(".quiz-list");
      (ch.quiz || []).forEach((q, qi) => {
        const item = document.createElement("div"); item.className = "quiz-item";
        const question = document.createElement("div"); question.className = "quiz-q"; question.textContent = `${qi + 1}. ${q.question}`;
        item.appendChild(question);
        const explain = document.createElement("p"); explain.className = "quiz-explain"; explain.textContent = q.explanation;
        (q.options || []).forEach((opt, oi) => {
          const row = document.createElement("div"); row.className = "quiz-opt"; row.textContent = opt;
          row.addEventListener("click", () => {
            if (item.dataset.answered) return;
            item.dataset.answered = "1";
            [...item.querySelectorAll(".quiz-opt")].forEach((r, ri) => {
              if (ri === q.answer_index) r.classList.add("correct");
              else if (r === row) r.classList.add("wrong");
            });
            explain.classList.add("show");
          });
          item.appendChild(row);
        });
        item.appendChild(explain);
        quizList.appendChild(item);
      });
      if (!ch.quiz || !ch.quiz.length) quizList.innerHTML = '<p class="muted">No quiz questions for this section.</p>';

      const flashGrid = node.querySelector(".flash-grid");
      (ch.flashcards || []).forEach(fc => {
        const card = document.createElement("div"); card.className = "flashcard";
        card.innerHTML = `<div class="flashcard-inner">
          <div class="flash-face front">${escapeHtml(fc.front)}</div>
          <div class="flash-face back">${escapeHtml(fc.back)}</div>
        </div>`;
        card.addEventListener("click", () => card.classList.toggle("flipped"));
        flashGrid.appendChild(card);
      });
      if (!ch.flashcards || !ch.flashcards.length) flashGrid.innerHTML = '<p class="muted">No flashcards for this section.</p>';

      node.querySelector(".transcript-text").textContent = ch.transcript || "(empty)";

      const ctabs = node.querySelectorAll(".ctab");
      const cpanes = node.querySelectorAll(".cpane");
      ctabs.forEach(tab => tab.addEventListener("click", () => {
        ctabs.forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        cpanes.forEach(p => p.classList.toggle("active", p.dataset.cpane === tab.dataset.ctab));
      }));

      chaptersEl.appendChild(node);
    });

    // highlight active TOC entry on scroll
    const tocLinks = $$("a", toc);
    window.onscroll = () => {
      let current = tocLinks[0];
      $$(".chapter").forEach(ch => { if (ch.getBoundingClientRect().top < 140) current = toc.querySelector(`a[href="#${ch.id}"]`); });
      tocLinks.forEach(l => l.classList.toggle("active", l === current));
    };
  }

  function escapeHtml(s) {
    return (s || "").replace(/[&<>"']/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  }

  // --- library ---
  async function loadLibrary() {
    const lib = await (await fetch("/api/library")).json();
    const grid = $("#library-grid"); grid.innerHTML = "";
    $("#library-empty").classList.toggle("hidden", lib.length > 0);
    lib.forEach(entry => {
      const card = document.createElement("div"); card.className = "lib-card";
      card.innerHTML = `
        <h3>${escapeHtml(entry.title)}</h3>
        <div class="lib-meta">${entry.duration_clock} · ${entry.chapter_count} sections</div>
        <div class="lib-chapters">${entry.chapter_titles.slice(0, 4).map(escapeHtml).join(" · ")}</div>
        <button class="lib-delete">Remove</button>`;
      card.addEventListener("click", async (e) => {
        if (e.target.classList.contains("lib-delete")) {
          e.stopPropagation();
          await fetch(`/api/jobs/${entry.job_id}`, { method: "DELETE" });
          loadLibrary();
          return;
        }
        const result = await (await fetch(`/api/jobs/${entry.job_id}/result`)).json();
        renderResult(entry.job_id, result);
      });
      grid.appendChild(card);
    });
  }

  // --- library search (sidebar) ---
  let searchTimer = null;
  $("#search-input").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    const q = e.target.value.trim();
    const box = $("#search-results");
    if (!q) { box.innerHTML = ""; return; }
    searchTimer = setTimeout(async () => {
      const hits = await (await fetch(`/api/library/search?q=${encodeURIComponent(q)}`)).json();
      box.innerHTML = "";
      hits.forEach(hit => {
        const div = document.createElement("div"); div.className = "search-hit";
        div.innerHTML = `<strong>${escapeHtml(hit.title)}</strong>` +
          hit.matches.slice(0, 2).map(m => `<span class="match">${clock(m.start)} — ${escapeHtml(m.title)}</span>`).join("");
        div.addEventListener("click", async () => {
          const result = await (await fetch(`/api/jobs/${hit.job_id}/result`)).json();
          renderResult(hit.job_id, result);
        });
        box.appendChild(div);
      });
      if (!hits.length) box.innerHTML = '<span class="muted">No matches.</span>';
    }, 300);
  });
})();
