from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import analyze
import theme
from gui_ids import CHIP_SPECS, PINNED_COLUMNS, TABLE_HEADINGS


class CatalogTableMixin:
    """BLUF table, snapshot switcher, find, sort, CSV, diff."""

    def _build_table(self, pane: ttk.Panedwindow) -> ttk.Frame:
        table_frame = ttk.Frame(pane)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = tuple(TABLE_HEADINGS)
        self._columns = columns
        self.table = ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="browse"
        )
        for key, (label, width) in TABLE_HEADINGS.items():
            self.table.heading(key, text=label, command=lambda c=key: self._sort_by(c))
            stretch = key == "problem"
            pinned = key in PINNED_COLUMNS
            min_w = 120 if key in {"techVolLimit", "feasStudyLimit", "title", "code"} else 40
            self.table.column(
                key,
                width=width,
                minwidth=min_w,
                stretch=stretch and not pinned,
            )
        self.table.tag_configure("closing", foreground=theme.WARN)
        self.table.tag_configure("soon", foreground=theme.SOON)
        self.table.tag_configure("closed", foreground=theme.CLOSED)
        self.table.tag_configure("open", foreground=theme.FG)
        self.table.tag_configure("unknown", foreground=theme.FG)
        self.table.tag_configure("pursue", foreground=theme.ACCENT)
        self.table.tag_configure("odd", background=theme.ROW)
        self.table.tag_configure("even", background=theme.ROW_ALT)
        self.table.tag_configure("pdflink", foreground=theme.LINK)
        self.table.tag_configure("newtopic", foreground=theme.ACCENT)
        self.table.tag_configure("qadelta", foreground=theme.SOON)
        self.table.grid(row=0, column=0, sticky="nsew")
        self._empty = ttk.Frame(table_frame, padding=24)
        self._empty.place(relx=0.5, rely=0.45, anchor="center")
        ttk.Label(self._empty, text="No snapshot on screen", style="Title.TLabel").pack()
        ttk.Label(
            self._empty,
            text=(
                "Download this cycle, or pick a snapshot above.\n"
                "Nothing you type is sent to DSIP as searchText."
            ),
            style="Hint.TLabel",
            justify="center",
        ).pack(pady=8)
        empty_btns = ttk.Frame(self._empty)
        empty_btns.pack()
        ttk.Button(
            empty_btns, text="Download all opportunities", command=self.start_download,
            style="Accent.TButton",
        ).pack(side="left", padx=4)
        ttk.Button(
            empty_btns, text="Open snapshot…", command=self.open_snapshot
        ).pack(side="left", padx=4)
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        xscroll = ttk.Scrollbar(
            table_frame, orient="horizontal", command=self.table.xview
        )
        self.table.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.table.bind("<Button-1>", self._on_table_click)
        self.table.bind("<Double-1>", self._on_table_double)
        self.table.bind("<Return>", self._on_table_activate)
        self.table.bind("<Key-1>", lambda _e: self._set_selected_triage("pursue"))
        self.table.bind("<Key-2>", lambda _e: self._set_selected_triage("watch"))
        self.table.bind("<Key-3>", lambda _e: self._set_selected_triage("pass"))
        self.table.bind("<Key-0>", lambda _e: self._set_selected_triage(""))
        self._apply_display_columns()
        return table_frame

    def _refresh_snapshot_list(self) -> None:
        parent = Path(self.folder_var.get().strip() or "")
        names: list[str] = []
        current = ""
        if parent.is_dir():
            found = sorted(
                (
                    path
                    for path in parent.glob("all_dsip_opportunities_*")
                    if path.is_dir() and (path / "manifest.json").is_file()
                ),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            names = [path.name for path in found]
        if self.output_dir and self._has_manifest(self.output_dir):
            current = self.output_dir.name
        elif names:
            current = names[0]
        if getattr(self, "snapshot_combo", None) is not None:
            self.snapshot_combo.configure(values=tuple(names) or ("No snapshot",))
        self.snapshot_var.set(current or "No snapshot")

    def _on_snapshot_chosen(self, _event: tk.Event | None = None) -> None:
        name = self.snapshot_var.get().strip()
        parent = Path(self.folder_var.get().strip() or "")
        folder = parent / name
        if self._has_manifest(folder):
            self._load_snapshot(folder)

    def _apply_display_columns(self) -> None:
        visible = [
            key
            for key in self._columns
            if key in PINNED_COLUMNS or key not in self._hidden_columns
        ]
        self.table.configure(displaycolumns=visible)

    def _clear_table(self) -> None:
        for item in self.table.get_children():
            self.table.delete(item)

    def _load_snapshot(self, folder: Path) -> bool:
        manifest_path = folder / "manifest.json"
        if not manifest_path.is_file():
            self._warn("That folder has no manifest.json.")
            return False
        self.output_dir = folder
        self._load_bluf_table()
        self._set_chrome_collapsed(True)
        self._refresh_snapshot_list()
        self._refresh_header_status()
        self._save_state()
        return True

    def _load_bluf_table(self) -> None:
        self._clear_table()
        if self.output_dir is None:
            return
        folder_changed = self.output_dir != getattr(self, "_page_limit_dir", None)
        if folder_changed:
            # Drop in-flight instruction-PDF scans so a previous snapshot cannot
            # stamp its page limits onto this one by topicId.
            self._page_limit_gen += 1
            self._page_limit_dir = self.output_dir
        self._cancel_pending_table_refresh()
        manifest_path = self.output_dir / "manifest.json"
        if not manifest_path.is_file():
            self.bluf_caption_var.set("No manifest.json — BLUF table is empty.")
            return
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.bluf_caption_var.set("Could not read manifest.json.")
            return
        rows = payload.get("bluf") or [
            analyze.bluf_row(topic, None)
            for topic in payload.get("topics") or []
        ]
        self._commit_note()
        selected_key = self._triage_key(self._selected_row) if self._selected_row else ""
        self._bluf_rows = rows
        self._topics_for_diff = payload.get("topics") or []
        for row in self._bluf_rows:
            analyze.refresh_due_in(row)
            analyze.refresh_released(row)
            self._stamp_triage(row)
        self._fill_tech_areas()
        self._auto_diff_previous_snapshot()
        self._render_table()
        if not self.interactive:
            self._refresh_all_page_limits(force=False)
        elif folder_changed and getattr(self, "_first_paint_done", False):
            self._refresh_all_page_limits(force=False)
        if selected_key:
            rebound = next(
                (row for row in self._bluf_rows if self._triage_key(row) == selected_key),
                None,
            )
            if rebound is not None:
                self._selected_row = rebound
                self._refresh_detail(rebound)
        phrase = payload.get("searchPhrase")
        if not rows and phrase:
            self.bluf_caption_var.set(f'No topics matched "{phrase}".')
        else:
            self._refresh_caption()

    def _refresh_caption(self, pending: bool = False) -> None:
        if not self._bluf_rows:
            self.bluf_caption_var.set("No topics in this snapshot.")
            return
        self.bluf_caption_var.set(
            analyze.format_pipeline_line(
                analyze.pipeline_summary(self._bluf_rows),
                shown=len(self._visible_rows()),
                pending=pending,
            )
        )

    def _row_matches_find(
        self, row: dict, needle: str, groups: list[list[str]]
    ) -> bool:
        blob = " ".join(str(row.get(col) or "") for col in self._columns)
        extra = " ".join(
            str(row.get(key) or "")
            for key in (
                "note",
                "qaExcerpt",
                "keywords",
                "overviewParagraph",
                "itar",
            )
        )
        areas = " ".join(str(item) for item in (row.get("technologyAreas") or []) if item)
        blob = f"{blob} {extra} {areas}".lower()
        if needle.lower() in blob:
            return True
        fake = {
            "topicCode": row.get("code") or "",
            "topicTitle": row.get("title") or "",
            "component": row.get("client") or "",
            "command": "",
            "program": row.get("program") or "",
            "topicStatus": row.get("status") or "",
            "topicObjective": row.get("problem") or "",
        }
        return analyze.topic_matches_groups(fake, groups)

    def _due_in_window(self, row: dict, limit: int) -> bool:
        days = analyze.due_days_int(row.get("dueIn"))
        return days is not None and 0 <= days <= limit

    def _visible_rows(self) -> list[dict]:
        rows = list(self._bluf_rows)
        for _, key in CHIP_SPECS:
            if key.startswith("__") or not self._chip_vars[key].get():
                continue
            groups = analyze.query_groups(key)
            rows = [
                row for row in rows if self._row_matches_find(row, key, groups)
            ]
        if self._chip_vars["__open__"].get():
            rows = [row for row in rows if analyze.is_open_status(row.get("status"))]
        if self._chip_vars["__due7__"].get():
            rows = [row for row in rows if self._due_in_window(row, 7)]
        if self._chip_vars["__due14__"].get():
            rows = [row for row in rows if self._due_in_window(row, 14)]
        if self._chip_vars["__qa__"].get():
            rows = [row for row in rows if analyze.published_qa_count(row) > 0]
        if self._chip_vars["__itar__"].get():
            rows = [row for row in rows if analyze.itar_flag(row.get("itar"))]
        if self._chip_vars["__new__"].get():
            rows = [row for row in rows if self._row_in_diff(row, self._diff_added)]
        if self._chip_vars["__changed__"].get():
            rows = [row for row in rows if self._row_in_diff(row, self._diff_changed)]
        if self._chip_vars["__qa_delta__"].get():
            rows = [row for row in rows if self._row_in_diff(row, self._diff_qa)]
        wanted_area = self.tech_area_var.get()
        if wanted_area and wanted_area != "All tech areas":
            rows = [
                row
                for row in rows
                if wanted_area in [str(item) for item in (row.get("technologyAreas") or [])]
            ]
        wanted = self.call_filter_var.get()
        if wanted == "Pursue":
            rows = [
                row
                for row in rows
                if analyze.normalize_triage(row.get("call")) == "pursue"
            ]
        elif wanted == "Watch":
            rows = [
                row
                for row in rows
                if analyze.normalize_triage(row.get("call")) == "watch"
            ]
        elif wanted == "Pass":
            rows = [
                row
                for row in rows
                if analyze.normalize_triage(row.get("call")) == "pass"
            ]
        elif wanted == "Untagged":
            rows = [
                row for row in rows if not analyze.normalize_triage(row.get("call"))
            ]
        needle = self.table_filter_var.get().strip()
        if needle:
            groups = analyze.query_groups(needle)
            rows = [row for row in rows if self._row_matches_find(row, needle, groups)]
        if self._sort_column:
            rows.sort(
                key=lambda row: self._sort_key(row, self._sort_column),
                reverse=self._sort_reverse,
            )
        else:
            rows.sort(key=self._default_sort_key)
        return rows

    @staticmethod
    def _status_rank(row: dict) -> int:
        status = str(row.get("status") or "").lower()
        if status.startswith("pre"):
            return 1
        if "open" in status:
            return 0
        return 2

    def _default_sort_key(self, row: dict) -> tuple:
        return (self._status_rank(row),) + self._sort_key(row, "dueIn")

    @staticmethod
    def _sort_key(row: dict, column: str) -> tuple:
        val = str(row.get(column) or "")
        if column in {"techVolLimit", "feasStudyLimit"}:
            if val.lower().startswith("n/a"):
                return (2, 0, val.lower())
            digits = "".join(ch for ch in val if ch.isdigit())
            if digits:
                return (0, int(digits[:2]), val.lower())
            return (3, 0, val.lower())
        if column in {"released", "opens", "due"}:
            if val in {"", "—"}:
                return (1, "", "")
            return (0, val[:10], "")
        if column == "dueIn":
            if val == "today":
                return (0, 0, "")
            if val == "closed":
                return (2, 0, "")
            if val.endswith("d") and val[:-1].isdigit():
                return (1, int(val[:-1]), "")
            return (3, 0, val.lower())
        return (0, 0, val.lower())

    def _cell(self, row: dict, column: str) -> str:
        if column == "call":
            return analyze.triage_label(row.get("call"))
        if column in {"techVolLimit", "feasStudyLimit"}:
            return str(row.get(column) or "")
        return str(row.get(column) or "—")

    def _render_table(self) -> None:
        selected = list(self.table.selection())
        focused = self.table.focus()
        try:
            y0 = self.table.yview()[0]
        except tk.TclError:
            y0 = 0.0
        self._clear_table()
        for index, row in enumerate(self._visible_rows()):
            tags = [analyze.urgency(row), "even" if index % 2 else "odd"]
            call = analyze.normalize_triage(row.get("call"))
            if call == "pursue":
                tags.append("pursue")
            if self._row_in_diff(row, self._diff_added):
                tags.append("newtopic")
            if self._row_in_diff(row, getattr(self, "_diff_qa", set())):
                tags.append("qadelta")
            pdf_name = str(row.get("pdf") or "")
            if pdf_name and pdf_name not in {"Failed", "—"}:
                tags.append("pdflink")
            iid = str(row.get("topicId") or f"row-{index}")
            self.table.insert(
                "",
                "end",
                iid=iid,
                values=tuple(self._cell(row, col) for col in self._columns),
                tags=tuple(tags),
            )
        keep = focused if focused and self.table.exists(focused) else ""
        if keep:
            self.table.selection_set(keep)
            self.table.focus(keep)
        else:
            remain = [iid for iid in selected if self.table.exists(iid)]
            if remain:
                self.table.selection_set(remain)
        try:
            self.table.yview_moveto(y0)
        except tk.TclError:
            pass
        self._refresh_chip_labels()
        if self._bluf_rows:
            self._refresh_caption()
        self._update_empty_state()
        self._refresh_header_status()

    def _sort_by(self, column: str) -> None:
        if self._sort_column == column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            # Released / Opens: newest first on the first click.
            self._sort_reverse = column in {"released", "opens"}
        self._render_table()

    def export_csv(self) -> None:
        if not self._bluf_rows:
            self._warn("Download topics first, then export the BLUF table.")
            return
        dest = filedialog.asksaveasfilename(
            title="Export BLUF table",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="dsip_bluf.csv",
        )
        if not dest:
            return
        analyze.write_bluf_csv(self._visible_rows(), Path(dest))
        self._append_log(f"Exported BLUF CSV: {dest}")

    def diff_previous(self) -> None:
        chosen = filedialog.askdirectory(
            title="Choose a previous download folder (with manifest.json)"
        )
        if not chosen:
            return
        manifest = Path(chosen) / "manifest.json"
        if not manifest.is_file():
            self._warn("That folder has no manifest.json.")
            return
        try:
            previous = json.loads(manifest.read_text(encoding="utf-8")).get("topics") or []
        except (OSError, json.JSONDecodeError) as exc:
            self._warn(f"Could not read that manifest:\n{exc}")
            return
        current = getattr(self, "_topics_for_diff", [])
        if not current:
            self._warn("Load or download a snapshot first so there is something to compare.")
            return
        previous_dir = Path(chosen)
        diff = analyze.snapshot_diff(
            current,
            previous,
            current_dir=self.output_dir,
            previous_dir=previous_dir,
        )
        self._store_snapshot_diff(diff, previous_dir.name)
        self._refresh_chip_labels()
        self._render_table()
        if self._chrome_collapsed:
            self.log_frame.grid()

    def _clear_snapshot_diff(self) -> None:
        self._diff_added = set()
        self._diff_changed = set()
        self._diff_qa = set()
        self._qa_notes = {}
        self._diff_vs = ""

    def _store_snapshot_diff(self, diff: dict, vs_label: str) -> None:
        self._diff_added = set(diff.get("added") or [])
        self._diff_changed = set(diff.get("changed") or [])
        self._diff_qa = set(diff.get("qa_changed") or [])
        self._qa_notes = dict(diff.get("qa_notes") or {})
        self._diff_vs = vs_label
        if not (
            self._diff_added
            or self._diff_changed
            or self._diff_qa
            or diff.get("removed")
        ):
            return
        self._append_log(
            f"Snapshot diff vs {vs_label}: "
            f"+{len(self._diff_added)} new, -{len(diff.get('removed') or [])} gone, "
            f"{len(self._diff_changed)} changed, "
            f"{len(self._diff_qa)} with new Q&A."
        )
        if self._diff_added:
            self._append_log("  new: " + ", ".join(sorted(self._diff_added)[:12]))
        if diff.get("removed"):
            self._append_log("  gone: " + ", ".join(list(diff["removed"])[:12]))
        if self._diff_qa:
            self._append_log("  Q&A: " + ", ".join(sorted(self._diff_qa)[:12]))

    def _auto_diff_previous_snapshot(self) -> None:
        """Compare this snapshot to the next-older folder in the same parent."""
        self._clear_snapshot_diff()
        previous = analyze.previous_snapshot_folder(self.output_dir)
        if previous is None:
            return
        previous_rows = analyze.load_snapshot_compare_rows(previous)
        current = getattr(self, "_topics_for_diff", None) or self._bluf_rows
        if not current or not previous_rows:
            return
        diff = analyze.snapshot_diff(
            current,
            previous_rows,
            current_dir=self.output_dir,
            previous_dir=previous,
        )
        self._store_snapshot_diff(diff, previous.name)

    def _row_by_iid(self, iid: str) -> dict | None:
        for row in self._bluf_rows:
            if str(row.get("topicId")) == iid:
                return row
        return None

    def _on_table_activate(self, _event: tk.Event | None = None) -> str:
        selection = self.table.selection()
        if selection:
            row = self._row_by_iid(selection[0])
            if row:
                self._show_detail(row)
        return "break"

    def _on_table_double(self, event: tk.Event) -> str:
        if self.table.identify_region(event.x, event.y) != "cell":
            return "break"
        item = self.table.identify_row(event.y)
        if not item:
            return "break"
        row = self._row_by_iid(item)
        if row:
            self.table.selection_set(item)
            self._show_detail(row)
        return "break"

    def _on_table_click(self, event: tk.Event) -> None:
        if self.table.identify_region(event.x, event.y) != "cell":
            return
        column = self.table.identify_column(event.x)
        try:
            index = int(column.replace("#", "")) - 1
        except ValueError:
            return
        item = self.table.identify_row(event.y)
        if not item:
            return
        row = self._row_by_iid(item)
        if row:
            self.table.selection_set(item)
            self._show_detail(row)
        displayed = list(self.table.cget("displaycolumns"))
        if not displayed or displayed == ["#all"]:
            displayed = list(self._columns)
        if index < 0 or index >= len(displayed) or displayed[index] != "pdf":
            return
        values = self.table.item(item, "values")
        pdf_index = self._columns.index("pdf")
        if not values or pdf_index >= len(values):
            return
        pdf_name = values[pdf_index]
        if not self.output_dir or not pdf_name or pdf_name in {"Failed", "—"}:
            return
        if not analyze.open_local_pdf(self.output_dir, pdf_name):
            self._warn(
                "Could not open that PDF. The path must be a real .pdf file "
                "inside this download folder."
            )

    def _on_filter_change(self) -> None:
        self._render_table()
        self._save_state()

    def _on_chips(self) -> None:
        self._sync_button_label()
        self._render_table()
        self._save_state()

    def _row_in_diff(self, row: dict, codes: set[str]) -> bool:
        return analyze.topic_code_of(row) in codes

    def _fill_tech_areas(self) -> None:
        areas = sorted(
            {
                str(item)
                for row in self._bluf_rows
                for item in (row.get("technologyAreas") or [])
                if item
            }
        )
        values = ("All tech areas",) + tuple(areas)
        if getattr(self, "tech_area_filter", None) is not None:
            self.tech_area_filter.configure(values=values)
        if self.tech_area_var.get() not in values:
            self.tech_area_var.set("All tech areas")
