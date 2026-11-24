# Copyright (c) 2026 Tanvir. ClassForge project source.
"""Render a processed lecture's chapters + notes to Markdown, DOCX, or PDF."""
from __future__ import annotations

from pathlib import Path

from .chapters import clock


def _chapter_markdown(ch: dict) -> str:
    lines = [f"## {clock(ch['start'])} – {ch['title']}", "", ch["summary"], ""]
    if ch["key_points"]:
        lines.append("**Key points**")
        lines += [f"- {p}" for p in ch["key_points"]]
        lines.append("")
    if ch["definitions"]:
        lines.append("**Definitions**")
        lines += [f"- **{d['term']}** — {d['definition']}" for d in ch["definitions"]]
        lines.append("")
    if ch["formulas"]:
        lines.append("**Formulas**")
        lines += [f"- `{f}`" for f in ch["formulas"]]
        lines.append("")
    if ch["quiz"]:
        lines.append("**Revision questions**")
        for i, q in enumerate(ch["quiz"], 1):
            lines.append(f"{i}. {q['question']}")
            for j, opt in enumerate(q["options"]):
                mark = "x" if j == q["answer_index"] else " "
                lines.append(f"   - [{mark}] {opt}")
            lines.append(f"   > {q['explanation']}")
        lines.append("")
    if ch["flashcards"]:
        lines.append("**Flashcards**")
        for fc in ch["flashcards"]:
            lines.append(f"- Q: {fc['front']}  \n  A: {fc['back']}")
        lines.append("")
    return "\n".join(lines)


def to_markdown(title: str, duration_clock: str, chapters: list[dict]) -> str:
    out = [f"# {title}", "", f"*Total length: {duration_clock} · {len(chapters)} sections*", ""]
    out.append("## Table of contents")
    for ch in chapters:
        out.append(f"- {clock(ch['start'])} — {ch['title']}")
    out.append("")
    for ch in chapters:
        out.append(_chapter_markdown(ch))
    return "\n".join(out)


def to_docx(title: str, duration_clock: str, chapters: list[dict], out_path: Path) -> Path:
    from docx import Document
    from docx.shared import Pt, RGBColor

    doc = Document()
    doc.add_heading(title, level=0)
    doc.add_paragraph(f"Total length: {duration_clock} · {len(chapters)} sections").italic = True

    doc.add_heading("Table of contents", level=1)
    for ch in chapters:
        doc.add_paragraph(f"{clock(ch['start'])} — {ch['title']}", style="List Bullet")

    for ch in chapters:
        doc.add_heading(f"{clock(ch['start'])} – {ch['title']}", level=1)
        if ch["summary"]:
            doc.add_paragraph(ch["summary"])
        if ch["key_points"]:
            doc.add_heading("Key points", level=2)
            for p in ch["key_points"]:
                doc.add_paragraph(p, style="List Bullet")
        if ch["definitions"]:
            doc.add_heading("Definitions", level=2)
            for d in ch["definitions"]:
                para = doc.add_paragraph(style="List Bullet")
                run = para.add_run(f"{d['term']}: ")
                run.bold = True
                para.add_run(d["definition"])
        if ch["formulas"]:
            doc.add_heading("Formulas", level=2)
            for f in ch["formulas"]:
                run = doc.add_paragraph(style="List Bullet").add_run(f)
                run.font.name = "Consolas"
        if ch["quiz"]:
            doc.add_heading("Revision questions", level=2)
            for i, q in enumerate(ch["quiz"], 1):
                doc.add_paragraph(f"{i}. {q['question']}")
                for j, opt in enumerate(q["options"]):
                    mark = "(correct) " if j == q["answer_index"] else ""
                    doc.add_paragraph(f"   {mark}{opt}", style="List Bullet 2")
                note = doc.add_paragraph()
                note.add_run(q["explanation"]).italic = True
        if ch["flashcards"]:
            doc.add_heading("Flashcards", level=2)
            for fc in ch["flashcards"]:
                p = doc.add_paragraph()
                p.add_run(f"Q: {fc['front']}").bold = True
                doc.add_paragraph(f"A: {fc['back']}")

    doc.save(out_path)
    return out_path


def to_pdf(title: str, duration_clock: str, chapters: list[dict], out_path: Path) -> Path:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    def reset_x() -> None:
        pdf.set_x(pdf.l_margin)

    pdf.set_font("Helvetica", "B", 20)
    reset_x(); pdf.multi_cell(0, 10, title)
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_text_color(100, 100, 100)
    reset_x(); pdf.multi_cell(0, 6, f"Total length: {duration_clock} - {len(chapters)} sections")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 13)
    reset_x(); pdf.cell(0, 8, "Table of contents", ln=1)
    pdf.set_font("Helvetica", "", 11)
    for ch in chapters:
        reset_x()
        pdf.cell(0, 6, f"{clock(ch['start'])} - {ch['title']}"[:100], ln=1)
    pdf.ln(4)

    def h(level: int, text: str) -> None:
        pdf.set_font("Helvetica", "B", {1: 15, 2: 12}.get(level, 11))
        pdf.ln(2)
        reset_x(); pdf.multi_cell(0, 7, text)
        pdf.set_font("Helvetica", "", 11)

    def body(text: str) -> None:
        pdf.set_font("Helvetica", "", 11)
        reset_x(); pdf.multi_cell(0, 6, text)

    def _ascii(s: str) -> str:
        return s.encode("latin-1", "replace").decode("latin-1")

    for ch in chapters:
        pdf.add_page()
        h(1, _ascii(f"{clock(ch['start'])} - {ch['title']}"))
        if ch["summary"]:
            body(_ascii(ch["summary"]))
        if ch["key_points"]:
            h(2, "Key points")
            for p in ch["key_points"]:
                body(_ascii(f"- {p}"))
        if ch["definitions"]:
            h(2, "Definitions")
            for d in ch["definitions"]:
                body(_ascii(f"- {d['term']}: {d['definition']}"))
        if ch["formulas"]:
            h(2, "Formulas")
            for f in ch["formulas"]:
                body(_ascii(f"- {f}"))
        if ch["quiz"]:
            h(2, "Revision questions")
            for i, q in enumerate(ch["quiz"], 1):
                body(_ascii(f"{i}. {q['question']}"))
                for j, opt in enumerate(q["options"]):
                    mark = "*" if j == q["answer_index"] else "-"
                    body(_ascii(f"   {mark} {opt}"))
                body(_ascii(f"   Explanation: {q['explanation']}"))
        if ch["flashcards"]:
            h(2, "Flashcards")
            for fc in ch["flashcards"]:
                body(_ascii(f"Q: {fc['front']}"))
                body(_ascii(f"A: {fc['back']}"))

    pdf.output(str(out_path))
    return out_path
