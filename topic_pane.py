from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

import analyze
import theme


class TopicPaneMixin:
    """Briefing card, triage keys, local notes, PDF actions."""

    def _build_topic_pane(self, pane: ttk.Panedwindow) -> ttk.LabelFrame:
        detail = ttk.LabelFrame(pane, text="Topic", padding=8)
        detail.columnconfigure(0, weight=1)
        ttk.Label(detail, textvariable=self.detail_title_var).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 4)
        )
        self.detail_text = tk.Text(
            detail,
            height=6,
            wrap="word",
            state="disabled",
            bg=theme.FIELD,
            fg=theme.FG,
            insertbackground=theme.FG,
            selectbackground=theme.SELECT,
            highlightthickness=0,
            borderwidth=0,
        )
        self.detail_text.grid(row=1, column=0, columnspan=3, sticky="nsew")
        self.detail_text.tag_configure(
            "h", foreground=theme.MUTED, font=("Segoe UI", 9, "bold")
        )
        self.detail_text.tag_configure("body", foreground=theme.FG)
        self.detail_text.tag_configure("limit", foreground=theme.ACCENT)
        self.detail_text.tag_configure("delta", foreground=theme.SOON)
        detail.rowconfigure(1, weight=1)
        actions = ttk.Frame(detail)
        actions.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.open_pdf_btn = ttk.Button(
            actions, text="Open PDF", command=self._open_selected_pdf
        )
        self.open_pdf_btn.grid(row=0, column=0, sticky="w")
        self.copy_code_btn = ttk.Button(
            actions, text="Copy code", command=self._copy_selected_code
        )
        self.copy_code_btn.grid(row=0, column=1, sticky="w", padx=6)
        self.copy_brief_btn = ttk.Button(
            actions, text="Copy brief", command=self._copy_selected_brief
        )
        self.copy_brief_btn.grid(row=0, column=2, sticky="w", padx=6)
        self.open_instruction_btn = ttk.Button(
            actions, text="Open instruction PDF", command=self._open_selected_instruction
        )
        self.open_instruction_btn.grid(row=0, column=3, sticky="w", padx=6)
        self.pursue_btn = ttk.Button(
            actions, text="Pursue", command=lambda: self._set_selected_triage("pursue")
        )
        self.pursue_btn.grid(row=0, column=4, sticky="w", padx=(16, 4))
        self.watch_btn = ttk.Button(
            actions, text="Watch", command=lambda: self._set_selected_triage("watch")
        )
        self.watch_btn.grid(row=0, column=5, sticky="w", padx=4)
        self.pass_btn = ttk.Button(
            actions, text="Pass", command=lambda: self._set_selected_triage("pass")
        )
        self.pass_btn.grid(row=0, column=6, sticky="w", padx=4)
        ttk.Label(detail, text="Note (stays on this machine):").grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )
        self.note_entry = ttk.Entry(detail, textvariable=self.note_var)
        self.note_entry.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(2, 0))
        self.note_entry.bind("<FocusOut>", lambda _e: self._commit_note())
        self.note_entry.bind("<Return>", lambda _e: self._commit_note())
        return detail

    def _show_detail(self, row: dict) -> None:
        self._commit_note()
        self._refresh_detail(row)

    def _refresh_detail(self, row: dict) -> None:
        self._stamp_triage(row)
        self._selected_row = row
        title = f"{row.get('code') or '—'}  ·  {row.get('title') or '—'}"
        self.detail_title_var.set(title)
        call = analyze.triage_label(row.get("call")) or "—"
        areas = ", ".join(str(item) for item in (row.get("technologyAreas") or []) if item) or "—"
        itar = "yes" if analyze.itar_flag(row.get("itar")) else (str(row.get("itar") or "—") if row.get("itar") not in (None, "", False) else "—")
        if itar in {"True", "true"}:
            itar = "yes"
        details = analyze.load_topic_details(self.output_dir, row)
        if isinstance(details, dict):
            analyze.apply_details_fields(row, details)
            areas = ", ".join(str(item) for item in (row.get("technologyAreas") or []) if item) or areas
            if analyze.itar_flag(row.get("itar")):
                itar = "yes"
        overview = str(row.get("overviewParagraph") or "").strip()
        topic_title = str(row.get("title") or "")
        cached_ok = bool(overview) and overview not in {"—", topic_title}
        pdf_text = ""
        pdf_name = str(row.get("pdf") or "")
        if not cached_ok:
            if self.output_dir and pdf_name and pdf_name not in {"Failed", "—"}:
                path = analyze.resolve_pdf(self.output_dir, pdf_name)
                if path is not None:
                    pdf_text = analyze.extract_pdf_text(path)
            analyze.refresh_volume_page_limits(
                row, self.output_dir, topic_text=pdf_text, include_topic_pdf=False
            )
            overview = analyze.topic_overview_paragraph(
                row, pdf_text=pdf_text, details=details
            )
            row["overviewParagraph"] = overview
        elif details:
            overview = analyze.topic_overview_paragraph(
                row, pdf_text="", details=details
            ) or overview
            row["overviewParagraph"] = overview
        problem = str(row.get("problem") or row.get("overview") or "").strip()
        extra_problem = ""
        if (
            problem
            and problem not in {"—", overview}
            and not analyze._is_title_only(problem, str(row.get("title") or ""))
            and problem not in overview
        ):
            extra_problem = problem
        limit_line = (
            f"Tech vol page limit: {row.get('techVolLimit') or ''}    "
            f"Feasibility study page limit: {row.get('feasStudyLimit') or ''}"
        )
        sections = [
            (
                "ACTIONS / META",
                "\n".join(
                    [
                        f"Client: {row.get('client') or '—'}    Call: {call}",
                        f"Released: {row.get('released') or '—'}    Opens: {row.get('opens') or '—'}",
                        f"Status: {row.get('status') or '—'}    Due: {row.get('due') or '—'} ({row.get('dueIn') or '—'})",
                        f"Program: {row.get('program') or '—'}    Contract: {row.get('contract') or '—'}",
                        f"TRL: {row.get('trl') or '—'}    Funding: {row.get('funding') or '—'}",
                    ]
                ),
            ),
            ("LIMITS", limit_line),
            (
                "CMMC / ITAR",
                f"CMMC: {row.get('cmmc') or '—'}    ITAR: {itar}",
            ),
            (
                "Q&A",
                f"Q&A: {row.get('qaPublished') or 0} published ({row.get('qaStatus') or '—'})",
            ),
            (
                "OBJECTIVE",
                "\n".join(
                    [
                        f"TPOC: {row.get('tpoc') or '—'}",
                        f"Keywords: {row.get('keywords') or '—'}",
                        f"Tech areas: {areas}",
                        f"PDF: {row.get('pdf') or '—'}",
                        "",
                        "Overview (from the topic details / PDF — local extract, not a cloud model)",
                        overview or "—",
                    ]
                ),
            ),
        ]
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        for heading, chunk in sections:
            self.detail_text.insert("end", f"{heading}\n", "h")
            tag = "limit" if heading == "LIMITS" else "body"
            self.detail_text.insert("end", f"{chunk}\n\n", tag)
        if extra_problem:
            self.detail_text.insert("end", extra_problem + "\n\n", "body")
        excerpt = str(row.get("qaExcerpt") or "").strip()
        code = str(row.get("code") or row.get("topicCode") or "")
        qa_note = str((getattr(self, "_qa_notes", {}) or {}).get(code) or "").strip()
        if qa_note:
            vs = str(getattr(self, "_diff_vs", "") or "last snapshot")
            self.detail_text.insert("end", f"Q&A since {vs}\n", "h")
            self.detail_text.insert("end", qa_note + "\n\n", "delta")
        if excerpt:
            self.detail_text.insert("end", "Published Q&A\n", "h")
            self.detail_text.insert("end", excerpt + "\n", "body")
        self.detail_text.configure(state="disabled")
        self._note_loading = True
        self.note_var.set(str(row.get("note") or ""))
        self._note_bound_key = self._triage_key(row)
        self._note_loading = False

    def _open_selected_pdf(self) -> None:
        row = self._selected_row
        if not row or not self.output_dir:
            return
        pdf_name = row.get("pdf") or ""
        if not pdf_name or pdf_name in {"Failed", "—"}:
            self._warn("That topic has no local PDF yet.")
            return
        if not analyze.open_local_pdf(self.output_dir, pdf_name):
            self._warn(
                "Could not open that PDF. The path must be a real .pdf file "
                "inside this download folder."
            )

    def _open_selected_instruction(self) -> None:
        row = self._selected_row
        if not row or not self.output_dir:
            return
        names = [str(item) for item in (row.get("instructionPdfs") or []) if item]
        if not names:
            self._warn("That topic has no local instruction PDF.")
            return
        name = names[0]
        if analyze.open_local_pdf(self.output_dir, name):
            return
        nested = str(Path("solicitation_documents") / Path(name).name)
        if analyze.open_local_pdf(self.output_dir, nested):
            return
        self._warn(
            "Could not open that instruction PDF. The path must be a real "
            ".pdf file inside this download folder."
        )

    def _copy_selected_code(self) -> None:
        row = self._selected_row
        if not row:
            return
        code = str(row.get("code") or "")
        if not code:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(code)
        self._append_log(f"Copied {code}")

    def _copy_selected_brief(self) -> None:
        self._commit_note()
        row = self._selected_row
        if not row:
            return
        brief = analyze.format_capture_brief(row)
        self.root.clipboard_clear()
        self.root.clipboard_append(brief)
        self._append_log(f"Copied brief for {row.get('code') or 'topic'}")

    def _selected_or_table_row(self) -> dict | None:
        if self._selected_row:
            return self._selected_row
        selection = self.table.selection()
        if selection:
            return self._row_by_iid(selection[0])
        return None

    def _set_selected_triage(self, call: str) -> str:
        row = self._selected_or_table_row()
        if not row:
            return "break"
        key = self._triage_key(row)
        if not key:
            return "break"
        rec = dict(self._triage.get(key) or {})
        rec["call"] = analyze.normalize_triage(call)
        rec["note"] = str(row.get("note") or rec.get("note") or "")[: analyze.NOTE_MAX]
        if not rec["call"] and not rec["note"]:
            self._triage.pop(key, None)
        else:
            self._triage[key] = rec
        row["call"] = analyze.triage_label(rec.get("call"))
        row["note"] = rec["note"]
        self._save_state()
        self._render_table()
        iid = str(row.get("topicId") or "")
        if iid and self.table.exists(iid):
            self.table.selection_set(iid)
            self.table.focus(iid)
        self._show_detail(row)
        return "break"

    def _commit_note(self) -> None:
        if self._note_loading:
            return
        row = self._selected_row
        if not row:
            return
        key = self._triage_key(row)
        if not key or key != self._note_bound_key:
            return
        note = self.note_var.get().strip()[: analyze.NOTE_MAX]
        rec = dict(self._triage.get(key) or {})
        rec["call"] = analyze.normalize_triage(rec.get("call") or row.get("call"))
        rec["note"] = note
        if not rec["call"] and not rec["note"]:
            self._triage.pop(key, None)
        else:
            self._triage[key] = rec
        row["note"] = note
        self._save_state()

    @staticmethod
    def _sanitize_triage(raw: object) -> dict[str, dict[str, str]]:
        if not isinstance(raw, dict):
            return {}
        cleaned: dict[str, dict[str, str]] = {}
        for key, rec in raw.items():
            if not isinstance(rec, dict):
                continue
            call = analyze.normalize_triage(rec.get("call"))
            note = str(rec.get("note") or "")[: analyze.NOTE_MAX]
            if call or note:
                cleaned[str(key)] = {"call": call, "note": note}
        return cleaned

    @staticmethod
    def _triage_key(row: dict) -> str:
        return str(row.get("topicId") or row.get("code") or "")

    def _stamp_triage(self, row: dict) -> None:
        rec = self._triage.get(self._triage_key(row)) or {}
        call = rec.get("call") or analyze.normalize_triage(row.get("call"))
        note = rec.get("note") if rec.get("note") not in (None, "") else str(row.get("note") or "")
        row["call"] = analyze.triage_label(call)
        row["note"] = str(note or "")[: analyze.NOTE_MAX]

    def _rebind_selected(self) -> None:
        """Point `_selected_row` at the current `_bluf_rows` object after a refresh."""
        if not self._selected_row:
            return
        key = self._triage_key(self._selected_row)
        if not key:
            return
        fresh = next(
            (row for row in self._bluf_rows if self._triage_key(row) == key),
            None,
        )
        if fresh is None:
            return
        self._selected_row = fresh
        iid = str(fresh.get("topicId") or "")
        if iid and self.table.exists(iid):
            self.table.selection_set(iid)
            self.table.focus(iid)
        self._refresh_detail(fresh)

    def _on_copy_brief(self, _event: tk.Event | None = None) -> str:
        self._copy_selected_brief()
        return "break"
