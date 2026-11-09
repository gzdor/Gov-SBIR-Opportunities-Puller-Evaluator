from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import analyze
import main as core
import theme
from gui_ids import (
    APP_TITLE,
    CALL_FILTERS,
    CHIP_SPECS,
    DEPARTMENT_CHIPS,
    PINNED_COLUMNS,
    TABLE_HEADINGS,
    WORKFLOW_CHIPS,
)


class ChromeMixin:
    """Header, pills, pipeline, palette, status bar, settings chrome."""

    def _build_status_bar(self) -> None:
        status = ttk.Frame(self.root, style="Status.TFrame", padding=(10, 4))
        status.pack(fill="x", side="bottom")
        ttk.Label(status, textvariable=self.status_var, style="Status.TLabel").pack(
            side="left"
        )
        ttk.Label(
            status,
            text="Ctrl+K commands  ·  Ctrl+F find  ·  1/2/3/0 call",
            style="Status.TLabel",
        ).pack(side="right")

    def _build_catalog_header(self, frame: ttk.Frame) -> None:
        header = ttk.Frame(frame, style="Header.TFrame")
        header.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="DSIP Discovery", style="Brand.TLabel").grid(
            row=0, column=0, sticky="w", padx=(2, 12)
        )
        ttk.Label(
            header,
            text="local open topics  ·  no login  ·  extractive only  ·  PolyForm NC",
            style="HeaderHint.TLabel",
        ).grid(row=0, column=1, sticky="w")
        ttk.Label(
            header,
            textvariable=self.header_status_var,
            style="HeaderHint.TLabel",
        ).grid(row=0, column=2, sticky="e", padx=8)

    def _build_setup_and_progress(self, frame: ttk.Frame) -> None:
        pad = {"padx": 10, "pady": 6}
        self.setup_frame = ttk.Frame(frame)
        self.setup_frame.grid(row=1, column=0, columnspan=3, sticky="ew")
        self.setup_frame.columnconfigure(1, weight=1)

        ttk.Label(self.setup_frame, text="Save in folder:").grid(
            row=0, column=0, sticky="w", **pad
        )
        self.folder_entry = ttk.Entry(self.setup_frame, textvariable=self.folder_var)
        self.folder_entry.grid(row=0, column=1, sticky="ew", **pad)
        self.browse_btn = ttk.Button(
            self.setup_frame, text="Browse...", command=self.browse
        )
        self.browse_btn.grid(row=0, column=2, sticky="e", **pad)

        ttk.Label(
            self.setup_frame,
            text=(
                "A timestamped subfolder (all_dsip_opportunities_YYYYMMDD_HHMMSS)\n"
                "will be created inside the folder above."
            ),
            style="Hint.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=10)

        ttk.Label(self.setup_frame, text="Download filter (optional):").grid(
            row=2, column=0, sticky="w", **pad
        )
        self.filter_entry = ttk.Entry(self.setup_frame, textvariable=self.filter_var)
        self.filter_entry.grid(row=2, column=1, columnspan=2, sticky="ew", **pad)
        self.filter_entry.bind("<Return>", lambda _e: self.start_download())

        ttk.Label(
            self.setup_frame,
            text=(
                "Applied on the next download only (never sent to DSIP). "
                "Use chips or Find below to narrow a snapshot already on disk."
            ),
            style="Hint.TLabel",
        ).grid(row=3, column=0, columnspan=3, sticky="w", padx=10)

        ttk.Label(self.setup_frame, text="Snapshot:").grid(
            row=4, column=0, sticky="w", **pad
        )
        self.snapshot_combo = ttk.Combobox(
            self.setup_frame,
            textvariable=self.snapshot_var,
            state="readonly",
            width=48,
        )
        self.snapshot_combo.grid(row=4, column=1, sticky="ew", **pad)
        self.snapshot_combo.bind("<<ComboboxSelected>>", self._on_snapshot_chosen)
        ttk.Button(
            self.setup_frame, text="Browse folder…", command=self.open_snapshot
        ).grid(row=4, column=2, sticky="e", **pad)

        self.download_btn = ttk.Button(
            frame,
            textvariable=self.button_var,
            command=self.start_download,
            style="Accent.TButton",
        )
        self.download_btn.grid(row=2, column=0, columnspan=3, sticky="ew", **pad)

        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self.progress.grid(row=3, column=0, columnspan=3, sticky="ew", **pad)

        ttk.Label(frame, textvariable=self.phase_var).grid(
            row=4, column=0, columnspan=3, sticky="w", padx=10
        )

        self.log_frame = ttk.Frame(frame)
        self.log_frame.grid(row=5, column=0, columnspan=3, sticky="nsew", **pad)
        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(0, weight=1)

        self.log = tk.Text(
            self.log_frame,
            height=4,
            wrap="word",
            state="disabled",
            bg=theme.FIELD,
            fg=theme.FG,
            insertbackground=theme.FG,
            selectbackground=theme.SELECT,
            highlightthickness=0,
            borderwidth=0,
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self.log_frame, command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.tag_configure("ok", foreground=theme.OK)
        self.log.tag_configure("warn", foreground=theme.WARN)
        self.log.tag_configure("fail", foreground=theme.FAIL)

    def _build_pipeline_and_chips(self, frame: ttk.Frame) -> None:
        frame.rowconfigure(6, minsize=40)
        frame.rowconfigure(7, minsize=96)
        pipe = ttk.LabelFrame(frame, text="Pipeline", padding=(8, 4))
        pipe.grid(row=6, column=0, columnspan=3, sticky="ew", padx=10, pady=(4, 2))
        self._pipe_frame = pipe
        self._pipe_btns: dict[str, ttk.Button] = {}
        for index, label in enumerate(CALL_FILTERS):
            pipe.columnconfigure(index, weight=1, uniform="pipe")
            btn = ttk.Button(
                pipe,
                text=label,
                style="Call.TButton",
                command=lambda name=label: self._set_call_filter(name),
            )
            btn.grid(row=0, column=index, sticky="ew", padx=2)
            self._pipe_btns[label] = btn

        chips = ttk.LabelFrame(frame, text="Filters", padding=(8, 4))
        chips.grid(row=7, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 2))
        chips.columnconfigure(1, weight=1)
        self._chips_frame = chips
        ttk.Label(chips, text="Component:", style="Hint.TLabel").grid(
            row=0, column=0, sticky="nw"
        )
        dept = ttk.Frame(chips)
        dept.grid(row=0, column=1, sticky="ew")
        self._dept_frame = dept
        for index, (label, key) in enumerate(DEPARTMENT_CHIPS):
            button = self._make_pill(dept, label, self._chip_vars[key], self._on_chips)
            button.grid(row=index // 8, column=index % 8, sticky="w", padx=3, pady=2)
            self._dept_checks[key] = button
        ttk.Checkbutton(
            chips,
            text="Show empty",
            variable=self.show_zero_components,
            command=self._refresh_chip_labels,
        ).grid(row=0, column=2, sticky="e", padx=(8, 0))
        ttk.Label(chips, text="Narrow:", style="Hint.TLabel").grid(
            row=1, column=0, sticky="nw", pady=(4, 0)
        )
        work = ttk.Frame(chips)
        work.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(4, 0))
        self._work_frame = work
        self._work_checks: dict[str, tk.Widget] = {}
        for index, (label, key) in enumerate(WORKFLOW_CHIPS):
            button = self._make_pill(work, label, self._chip_vars[key], self._on_chips)
            button.grid(row=index // 8, column=index % 8, sticky="w", padx=3, pady=2)
            self._work_checks[key] = button
        ttk.Label(chips, text="Calls:").grid(row=2, column=0, sticky="w", pady=(4, 0))
        calls = ttk.Frame(chips)
        calls.grid(row=2, column=1, columnspan=2, sticky="w", pady=(4, 0))
        self.call_filter = ttk.Combobox(
            calls,
            textvariable=self.call_filter_var,
            values=CALL_FILTERS,
            state="readonly",
            width=12,
        )
        self.call_filter.grid(row=0, column=0, sticky="w")
        ttk.Label(calls, text="Tech area:").grid(
            row=0, column=1, sticky="w", padx=(12, 0)
        )
        self.tech_area_filter = ttk.Combobox(
            calls,
            textvariable=self.tech_area_var,
            values=("All tech areas",),
            state="readonly",
            width=22,
        )
        self.tech_area_filter.grid(row=0, column=2, sticky="w", padx=6)
        ttk.Label(
            calls,
            text="New = not in previous snapshot · Changed = title/status/due · New Q&A = published answers added",
            style="Hint.TLabel",
        ).grid(row=0, column=3, sticky="w", padx=(12, 0))

    def _build_find_toolbar(self, frame: ttk.Frame) -> None:
        ttk.Label(frame, textvariable=self.bluf_caption_var).grid(
            row=8, column=0, columnspan=2, sticky="w", padx=10
        )
        ttk.Label(
            frame,
            text="Pinned: Call, Code, Topic.  Ctrl++ / Ctrl+− zoom.",
            style="Hint.TLabel",
        ).grid(row=8, column=2, sticky="e", padx=10)

        tool = ttk.Frame(frame)
        tool.grid(row=9, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 4))
        tool.columnconfigure(1, weight=1)
        ttk.Label(tool, text="Find in snapshot:").grid(row=0, column=0, sticky="w")
        self.table_filter_entry = ttk.Entry(tool, textvariable=self.table_filter_var)
        self.table_filter_entry.grid(row=0, column=1, sticky="ew", padx=8)
        self.export_btn = ttk.Button(tool, text="Export CSV", command=self.export_csv)
        self.export_btn.grid(row=0, column=2, padx=2)
        self.diff_btn = ttk.Button(
            tool, text="Diff previous…", command=self.diff_previous
        )
        self.diff_btn.grid(row=0, column=3, padx=2)
        tools_wrap = ttk.Frame(tool)
        tools_wrap.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        self.open_folder_btn = ttk.Button(
            tools_wrap, text="Open folder", command=self.open_output_folder
        )
        self.open_folder_btn.grid(row=0, column=0, padx=(0, 2))
        self.open_snapshot_btn = ttk.Button(
            tools_wrap, text="Open snapshot…", command=self.open_snapshot
        )
        self.open_snapshot_btn.grid(row=0, column=1, padx=2)
        self.settings_btn = ttk.Button(
            tools_wrap, text="Hide settings", command=self.toggle_chrome
        )
        self.settings_btn.grid(row=0, column=2, padx=2)
        self.columns_btn = ttk.Button(
            tools_wrap, text="Columns…", command=self._show_column_menu
        )
        self.columns_btn.grid(row=0, column=3, padx=2)
        self.density_btn = ttk.Button(
            tools_wrap, text="Compact", command=self._toggle_density
        )
        self.density_btn.grid(row=0, column=4, padx=2)

    def _make_pill(
        self, parent: tk.Widget, text: str, var: tk.BooleanVar, command
    ) -> tk.Checkbutton:
        btn = tk.Checkbutton(
            parent,
            text=text,
            variable=var,
            command=lambda: (self._style_pills(), command()),
            indicatoron=False,
            selectcolor=theme.ACCENT,
            bg=theme.HEAD,
            fg=theme.FG,
            activebackground=theme.SELECT,
            activeforeground=theme.FG,
            highlightthickness=0,
            bd=0,
            padx=8,
            pady=3,
            font=("Segoe UI", 9),
            cursor="hand2",
        )
        return btn

    def _style_pills(self) -> None:
        widgets = list(self._dept_checks.values()) + list(
            getattr(self, "_work_checks", {}).values()
        )
        for btn in widgets:
            key = None
            for candidate, widget in {**self._dept_checks, **getattr(self, "_work_checks", {})}.items():
                if widget is btn:
                    key = candidate
                    break
            on = bool(key and self._chip_vars[key].get())
            if on:
                btn.configure(
                    bg=theme.ACCENT,
                    fg="#0b1a12",
                    activebackground="#5ef0ad",
                    activeforeground="#0b1a12",
                )
            else:
                btn.configure(
                    bg=theme.HEAD,
                    fg=theme.FG,
                    activebackground=theme.SELECT,
                    activeforeground=theme.FG,
                )

    def _set_call_filter(self, name: str) -> None:
        self.call_filter_var.set(name)

    def _refresh_header_status(self) -> None:
        n = len(self._bluf_rows)
        if self.output_dir and self._has_manifest(self.output_dir):
            stamp = self.output_dir.name.replace("all_dsip_opportunities_", "")
            self.header_status_var.set(f"{stamp}  ·  {n} topics  ·  local only")
        elif n:
            self.header_status_var.set(f"{n} topics  ·  local only")
        else:
            self.header_status_var.set("local only  ·  no login")
        pdf = "pypdf on" if analyze.pypdf_available() else "pypdf off"
        phase = self.phase_var.get()
        self.status_var.set(f"{phase}  ·  {pdf}  ·  workers {core.default_workers()}")

    def _update_empty_state(self) -> None:
        empty = getattr(self, "_empty", None)
        if empty is None:
            return
        if self.table.get_children():
            empty.place_forget()
        else:
            empty.place(relx=0.5, rely=0.42, anchor="center")

    def _show_column_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=0, bg=theme.PANEL, fg=theme.FG)
        for key, (label, _width) in TABLE_HEADINGS.items():
            if key in PINNED_COLUMNS:
                menu.add_command(label=f"{label}  (pinned)", state="disabled")
                continue
            shown = key not in self._hidden_columns

            def toggle(col=key, currently=shown) -> None:
                if currently:
                    self._hidden_columns.add(col)
                else:
                    self._hidden_columns.discard(col)
                self._apply_display_columns()
                self._save_state()

            menu.add_command(
                label=("✓  " if shown else "    ") + label, command=toggle
            )
        try:
            menu.tk_popup(
                self.columns_btn.winfo_rootx(),
                self.columns_btn.winfo_rooty() + self.columns_btn.winfo_height(),
            )
        finally:
            menu.grab_release()

    def _toggle_density(self) -> None:
        nxt = "compact" if self.density_var.get() != "compact" else "comfortable"
        self.density_var.set(nxt)
        self.density_btn.configure(
            text="Comfortable" if nxt == "compact" else "Compact"
        )
        self._set_zoom(self._zoom)
        self._save_state()

    def _palette_commands(self) -> list[tuple[str, object]]:
        return [
            ("Download all / matching", self.start_download),
            ("Open snapshot…", self.open_snapshot),
            ("Find in snapshot", self._focus_find),
            ("Export CSV", self.export_csv),
            ("Diff previous…", self.diff_previous),
            ("Copy brief", self._copy_selected_brief),
            ("Copy code", self._copy_selected_code),
            ("Open PDF", self._open_selected_pdf),
            ("Open instruction PDF", self._open_selected_instruction),
            ("Toggle download settings", self.toggle_chrome),
            ("Columns…", self._show_column_menu),
            ("Toggle compact density", self._toggle_density),
            ("How SBIR works", lambda: self.notebook.select(1)),
            ("Catalog", lambda: self.notebook.select(0)),
        ]

    def _open_palette(self, _event: tk.Event | None = None) -> str:
        commands = self._palette_commands()
        win = tk.Toplevel(self.root)
        win.title("Commands")
        win.configure(bg=theme.PANEL)
        win.transient(self.root)
        win.geometry("420x320")
        entry_var = tk.StringVar()
        box = ttk.Entry(win, textvariable=entry_var)
        box.pack(fill="x", padx=10, pady=10)
        listing = tk.Listbox(
            win,
            bg=theme.FIELD,
            fg=theme.FG,
            selectbackground=theme.SELECT,
            highlightthickness=0,
            borderwidth=0,
            font=("Segoe UI", 10),
        )
        listing.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        def filtered() -> list[tuple[str, object]]:
            needle = entry_var.get().strip().lower()
            if not needle:
                return commands
            return [item for item in commands if needle in item[0].lower()]

        def refresh(*_a: object) -> None:
            listing.delete(0, "end")
            for label, _fn in filtered():
                listing.insert("end", label)
            if listing.size():
                listing.selection_set(0)

        def run(_event: tk.Event | None = None) -> None:
            rows = filtered()
            sel = listing.curselection()
            index = int(sel[0]) if sel else 0
            win.destroy()
            if rows and 0 <= index < len(rows):
                rows[index][1]()

        entry_var.trace_add("write", refresh)
        box.bind("<Return>", run)
        listing.bind("<Return>", run)
        listing.bind("<Double-1>", run)
        win.bind("<Escape>", lambda _e: win.destroy())
        refresh()
        box.focus_set()
        return "break"

    def _bind_zoom(self) -> None:
        for seq in (
            "<Control-plus>",
            "<Control-equal>",
            "<Control-Key-plus>",
            "<Control-Key-equal>",
            "<Control-KP_Add>",
        ):
            self.root.bind_all(seq, self._on_zoom_in)
        for seq in (
            "<Control-minus>",
            "<Control-Key-minus>",
            "<Control-KP_Subtract>",
        ):
            self.root.bind_all(seq, self._on_zoom_out)

    def _bind_shortcuts(self) -> None:
        self.root.bind_all("<Control-f>", self._focus_find)
        self.root.bind_all("<Control-F>", self._focus_find)
        self.root.bind_all("<Control-b>", self._on_copy_brief)
        self.root.bind_all("<Control-B>", self._on_copy_brief)
        self.root.bind_all("<Control-k>", self._open_palette)
        self.root.bind_all("<Control-K>", self._open_palette)
        self.root.bind_all("<Control-p>", self._open_palette)
        self.root.bind_all("<Control-P>", self._open_palette)

    def _focus_find(self, _event: tk.Event | None = None) -> str:
        self.table_filter_entry.focus_set()
        self.table_filter_entry.selection_range(0, "end")
        return "break"

    def _on_zoom_in(self, _event: tk.Event | None = None) -> str:
        self._set_zoom(self._zoom + theme.ZOOM_STEP)
        return "break"

    def _on_zoom_out(self, _event: tk.Event | None = None) -> str:
        self._set_zoom(self._zoom - theme.ZOOM_STEP)
        return "break"

    def _set_zoom(self, scale: float) -> None:
        self._zoom = theme.apply_zoom(
            self.root, scale, self.log, self.density_var.get()
        )
        size = max(6, int(round(10 * self._zoom)))
        self.detail_text.configure(font=("Segoe UI", size))
        if getattr(self, "guide_text", None) is not None:
            self.guide_text.configure(font=("Segoe UI", size))
        self._style_pills()

    def toggle_chrome(self) -> None:
        self._set_chrome_collapsed(not self._chrome_collapsed)

    def _set_chrome_collapsed(self, collapsed: bool) -> None:
        self._chrome_collapsed = collapsed
        if collapsed:
            self.setup_frame.grid_remove()
            self.log_frame.grid_remove()
            self.settings_btn.configure(text="Download settings")
        else:
            self.setup_frame.grid()
            self.log_frame.grid()
            self.settings_btn.configure(text="Hide settings")
        # Pipeline/filters stay mapped in both views; re-grid so collapse cannot
        # leave them unmapped under the table or overlapping each other.
        pipe = getattr(self, "_pipe_frame", None)
        if pipe is not None:
            pipe.grid()
        chips = getattr(self, "_chips_frame", None)
        if chips is not None:
            chips.grid()
        self._refresh_pipeline()

    def _refresh_chip_labels(self) -> None:
        counts = {key: 0 for _, key in CHIP_SPECS}
        for row in self._bluf_rows:
            for _, key in DEPARTMENT_CHIPS:
                groups = analyze.query_groups(key)
                if self._row_matches_find(row, key, groups):
                    counts[key] += 1
            for _, key in WORKFLOW_CHIPS:
                if key.startswith("__"):
                    continue
                groups = analyze.query_groups(key)
                if self._row_matches_find(row, key, groups):
                    counts[key] += 1
            if analyze.is_open_status(row.get("status")):
                counts["__open__"] += 1
            if analyze.is_pre_release_status(row.get("status")):
                counts["__pre__"] += 1
            if self._due_in_window(row, 7):
                counts["__due7__"] += 1
            if self._due_in_window(row, 14):
                counts["__due14__"] += 1
            if analyze.published_qa_count(row) > 0:
                counts["__qa__"] += 1
            if analyze.itar_flag(row.get("itar")):
                counts["__itar__"] += 1
            if self._row_in_diff(row, self._diff_added):
                counts["__new__"] += 1
            if self._row_in_diff(row, self._diff_changed):
                counts["__changed__"] += 1
            if self._row_in_diff(row, getattr(self, "_diff_qa", set())):
                counts["__qa_delta__"] += 1
        show_zero = bool(self.show_zero_components.get())
        self._reflow_pills(
            DEPARTMENT_CHIPS,
            self._dept_checks,
            counts,
            hide_empty=bool(self._bluf_rows) and not show_zero,
        )
        self._reflow_pills(WORKFLOW_CHIPS, getattr(self, "_work_checks", {}), counts)
        self._style_pills()
        self._refresh_pipeline()

    def _reflow_pills(
        self,
        specs: tuple,
        widgets: dict,
        counts: dict[str, int],
        hide_empty: bool = False,
        per_row: int = 8,
    ) -> None:
        """Place visible pills left-to-right so hidden ones cannot leave holes."""
        col = 0
        row = 0
        for label, key in specs:
            button = widgets.get(key)
            if button is None:
                continue
            n = counts.get(key, 0)
            button.configure(text=f"{label} ({n})")
            hidden = hide_empty and n == 0 and not self._chip_vars[key].get()
            button.grid_forget()
            if hidden:
                continue
            button.grid(row=row, column=col, sticky="w", padx=3, pady=2)
            col += 1
            if col >= per_row:
                col = 0
                row += 1

    def _refresh_pipeline(self) -> None:
        summary = analyze.pipeline_summary(self._bluf_rows)
        labels = {
            "All calls": f"All {summary.get('topics', 0)}",
            "Pursue": f"Pursue {summary.get('pursue', 0)}",
            "Watch": f"Watch {summary.get('watch', 0)}",
            "Pass": f"Pass {summary.get('pass', 0)}",
            "Untagged": f"Untagged {summary.get('untagged', 0)}",
        }
        current = self.call_filter_var.get() or "All calls"
        for name, btn in getattr(self, "_pipe_btns", {}).items():
            btn.configure(text=labels.get(name, name))
            if name == current:
                btn.configure(style="CallOn.TButton")
            else:
                btn.configure(style="Call.TButton")

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        lower = message.lower()
        tag = ""
        if "403" in lower or "error" in lower or "fail" in lower or "traceback" in lower:
            tag = "fail"
        elif "warn" in lower or "could not" in lower:
            tag = "warn"
        elif "ok" in lower or "stated" in lower or "finished" in lower or "exported" in lower:
            tag = "ok"
        if tag:
            self.log.insert("end", message + "\n", tag)
        else:
            self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        self.status_var.set(message.splitlines()[0][:140] if message else self.status_var.get())

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _warn(self, message: str) -> None:
        if self.interactive:
            messagebox.showwarning(APP_TITLE, message)
        else:
            self._append_log(message)
