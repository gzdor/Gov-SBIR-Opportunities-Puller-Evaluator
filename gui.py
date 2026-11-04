#!/usr/bin/env python3
"""Simple desktop UI for the DoD DSIP topics downloader.

A one-screen Tkinter app: pick a folder, click one button, watch a progress
bar. The actual download runs in a background thread so the window stays
responsive; progress events are marshaled back to the Tk main loop through a
thread-safe queue. All download logic lives in main.py, which this file drives
through its reporter callback interface, so there is no duplicated logic.

Tkinter ships with Python, so this adds no third-party runtime dependency.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import analyze
import main as core
import sbir_guide
import theme

APP_TITLE = "DSIP Opportunities — Discovery"
# Machine-local only: parent folder, last snapshot path, triage, chips, Find.
# Never written into a download folder or committed. Do not copy this file
# between machines expecting shared capture state.
STATE_FILE = Path.home() / ".dsip_downloader_state.json"
DEPARTMENT_CHIPS = (
    ("DAF", "DAF"),
    ("Army", "Army"),
    ("Navy", "Navy"),
    ("OSD", "OSD"),
    ("SOCOM", "SOCOM"),
    ("DARPA", "DARPA"),
    ("MDA", "MDA"),
    ("DTRA", "DTRA"),
    ("DLA", "DLA"),
    ("CBD", "CBD"),
    ("DHP", "DHP"),
    ("NGA", "NGA"),
    ("NASA", "NASA"),
    ("NOAA", "NOAA"),
    ("NSF", "NSF"),
)
WORKFLOW_CHIPS = (
    ("SBIR", "SBIR"),
    ("STTR", "STTR"),
    ("UAS", "UAS"),
    ("D2P2", "D2P2"),
    ("Open", "__open__"),
    ("Has Q&A", "__qa__"),
    ("ITAR", "__itar__"),
    ("New", "__new__"),
    ("Changed", "__changed__"),
    ("due < 7d", "__due7__"),
    ("due < 14d", "__due14__"),
)
CHIP_SPECS = DEPARTMENT_CHIPS + WORKFLOW_CHIPS
DOWNLOAD_CHIP_KEYS = {key for _, key in CHIP_SPECS if not str(key).startswith("__")}
CALL_FILTERS = ("All calls", "Pursue", "Watch", "Pass", "Untagged")
PINNED_COLUMNS = ("call", "code", "title")
DEFAULT_HIDDEN_COLUMNS = frozenset({"trl", "opens"})
TABLE_HEADINGS = {
    "call": ("Call", 70),
    "code": ("Code", 130),
    "title": ("Topic", 220),
    "client": ("Client", 110),
    "program": ("Program", 60),
    "status": ("Status", 90),
    "opens": ("Opens", 90),
    "due": ("Due", 90),
    "dueIn": ("Due in", 70),
    "qaPublished": ("Q&A", 45),
    "cmmc": ("CMMC", 60),
    "problem": ("Problem / objective", 220),
    "trl": ("TRL", 45),
    "funding": ("Funding", 80),
    "contract": ("Contract", 110),
    "techVolLimit": ("Tech Vol Page Limit", 150),
    "feasStudyLimit": ("Feasibility Study Page Limit", 180),
    "pdf": ("PDF", 180),
}


class QueueReporter:
    """A main.py reporter that forwards every event onto a queue.

    The worker thread calls these methods; the Tk main loop drains the queue.
    This keeps all widget updates on the Tk thread, which Tkinter requires.
    """

    def __init__(self, events: "queue.Queue[tuple]") -> None:
        self._events = events

    def status(self, message: str) -> None:
        self._events.put(("status", message))

    def start_phase(self, label: str, total: int) -> None:
        self._events.put(("start_phase", label, total))

    def advance(self, done: int, total: int, failure: str | None = None) -> None:
        self._events.put(
            ("advance", {"done": done, "total": total, "failure": failure})
        )

    def end_phase(self) -> None:
        self._events.put(("end_phase",))

    def catalog_ready(self, topics: list[dict]) -> None:
        self._events.put(("catalog_ready", topics))

    def item_done(self, label: str, key: object, outcome: dict) -> None:
        self._events.put(
            ("item_done", {"label": label, "key": key, "outcome": outcome})
        )


class App:
    """The single-window application."""

    def __init__(self, root: tk.Tk, interactive: bool = True) -> None:
        self.root = root
        self.interactive = interactive
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.worker: threading.Thread | None = None
        self.output_dir: Path | None = None
        self.exit_code: int | None = None
        self.finished = False
        self._indeterminate = False
        self._phase_label = ""
        self.on_finished = None  # optional callback for tests
        self._chrome_collapsed = False
        self._selected_row: dict | None = None

        root.title(APP_TITLE)
        root.minsize(1024, 680)
        theme.apply_dark_theme(root)
        try:
            root.iconphoto(True, theme.make_app_icon(root))
        except tk.TclError:
            pass

        self.folder_var = tk.StringVar(value=str(Path.home() / "Downloads"))
        self.phase_var = tk.StringVar(value="Idle")
        self.filter_var = tk.StringVar(value="")
        self.table_filter_var = tk.StringVar(value="")
        self.bluf_caption_var = tk.StringVar(
            value="Download this cycle, or open a previous snapshot."
        )
        self.button_var = tk.StringVar(value="Download all opportunities")
        self.detail_title_var = tk.StringVar(
            value="Select a row for the objective, then mark Pursue / Watch / Pass."
        )
        self.call_filter_var = tk.StringVar(value="All calls")
        self.note_var = tk.StringVar(value="")
        self.tech_area_var = tk.StringVar(value="All tech areas")
        self.show_zero_components = tk.BooleanVar(value=False)
        self.header_status_var = tk.StringVar(value="local only · no login")
        self.status_var = tk.StringVar(value="Ready · nothing typed is sent to DSIP as searchText")
        self.snapshot_var = tk.StringVar(value="No snapshot")
        self.density_var = tk.StringVar(value="comfortable")
        self._bluf_rows: list[dict] = []
        self._topics_for_diff: list[dict] = []
        self._triage: dict[str, dict[str, str]] = {}
        self._diff_added: set[str] = set()
        self._diff_changed: set[str] = set()
        self._dept_checks: dict[str, tk.Widget] = {}
        self._sort_column = ""
        self._sort_reverse = False
        self._zoom = 1.0
        self._zoom_from_state = False
        self._note_loading = False
        self._note_bound_key = ""
        self._resume_dir: Path | None = None
        self._hidden_columns: set[str] = set(DEFAULT_HIDDEN_COLUMNS)
        self._pdf_done = 0
        self._pdf_total = 0
        self._chip_vars: dict[str, tk.BooleanVar] = {
            key: tk.BooleanVar(value=False) for _, key in CHIP_SPECS
        }

        self._build_widgets()
        self._bind_zoom()
        self._bind_shortcuts()
        self.filter_var.trace_add("write", self._sync_button_label)
        self.table_filter_var.trace_add("write", lambda *_: self._on_filter_change())
        self.call_filter_var.trace_add("write", lambda *_: self._on_filter_change())
        self.tech_area_var.trace_add("write", lambda *_: self._on_filter_change())
        self._ensure_pdf_backend()
        self._restore_state()
        if self.interactive and not self._zoom_from_state:
            self._set_zoom(theme.display_zoom())
        self._style_pills()
        self._refresh_pipeline()
        self._refresh_snapshot_list()
        self._refresh_header_status()
        self._update_empty_state()

    # ---- UI construction -------------------------------------------------
    def _build_widgets(self) -> None:
        pad = {"padx": 10, "pady": 6}
        accent = tk.Frame(self.root, bg=theme.ACCENT, height=3)
        accent.pack(fill="x", side="top")
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)
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
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text="Catalog")
        frame.columnconfigure(1, weight=1)
        self._frame = frame
        self._build_guide_tab()

        header = ttk.Frame(frame, style="Header.TFrame")
        header.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="DSIP Discovery", style="Brand.TLabel").grid(
            row=0, column=0, sticky="w", padx=(2, 12)
        )
        ttk.Label(
            header,
            text="local open topics  ·  no login  ·  extractive only",
            style="HeaderHint.TLabel",
        ).grid(row=0, column=1, sticky="w")
        ttk.Label(
            header,
            textvariable=self.header_status_var,
            style="HeaderHint.TLabel",
        ).grid(row=0, column=2, sticky="e", padx=8)

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

        pipe = ttk.Frame(frame)
        pipe.grid(row=6, column=0, columnspan=3, sticky="ew", padx=10, pady=(4, 2))
        ttk.Label(pipe, text="Pipeline:", style="Hint.TLabel").pack(side="left", padx=(0, 8))
        self._pipe_btns: dict[str, ttk.Button] = {}
        for label in CALL_FILTERS:
            btn = ttk.Button(
                pipe,
                text=label,
                style="Call.TButton",
                command=lambda name=label: self._set_call_filter(name),
            )
            btn.pack(side="left", padx=2)
            self._pipe_btns[label] = btn

        chips = ttk.Frame(frame)
        chips.grid(row=7, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 2))
        ttk.Label(chips, text="Component:", style="Hint.TLabel").grid(
            row=0, column=0, sticky="nw"
        )
        dept = ttk.Frame(chips)
        dept.grid(row=0, column=1, columnspan=12, sticky="w")
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
        ).grid(row=0, column=13, sticky="e")
        ttk.Label(chips, text="Narrow:", style="Hint.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        work = ttk.Frame(chips)
        work.grid(row=1, column=1, columnspan=12, sticky="w", pady=(4, 0))
        self._work_checks: dict[str, tk.Widget] = {}
        for index, (label, key) in enumerate(WORKFLOW_CHIPS):
            button = self._make_pill(work, label, self._chip_vars[key], self._on_chips)
            button.grid(row=index // 8, column=index % 8, sticky="w", padx=3, pady=2)
            self._work_checks[key] = button
        ttk.Label(chips, text="Calls:").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.call_filter = ttk.Combobox(
            chips,
            textvariable=self.call_filter_var,
            values=CALL_FILTERS,
            state="readonly",
            width=12,
        )
        self.call_filter.grid(row=2, column=1, sticky="w", padx=6, pady=(4, 0))
        ttk.Label(chips, text="Tech area:").grid(
            row=2, column=2, sticky="w", padx=(12, 0), pady=(4, 0)
        )
        self.tech_area_filter = ttk.Combobox(
            chips,
            textvariable=self.tech_area_var,
            values=("All tech areas",),
            state="readonly",
            width=22,
        )
        self.tech_area_filter.grid(row=2, column=3, sticky="w", padx=6, pady=(4, 0))
        ttk.Label(
            chips,
            text="1 Pursue · 2 Watch · 3 Pass · 0 clear   (table focused)",
            style="Hint.TLabel",
        ).grid(row=2, column=4, columnspan=8, sticky="w", pady=(4, 0))

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

        pane = ttk.Panedwindow(frame, orient=tk.VERTICAL)
        pane.grid(row=10, column=0, columnspan=3, sticky="nsew", **pad)
        frame.rowconfigure(10, weight=1)
        self._vpane = pane

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

        pane.add(table_frame, weight=4)
        pane.add(detail, weight=1)
        theme.apply_zoom(self.root, self._zoom, self.log, self.density_var.get())
        self.detail_text.configure(font=("Segoe UI", 10))
        self.guide_text.configure(font=("Segoe UI", 10))

    def _build_guide_tab(self) -> None:
        guide = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(guide, text="How SBIR works")
        guide.columnconfigure(1, weight=1)
        guide.rowconfigure(1, weight=1)
        ttk.Label(
            guide,
            text="How the SBIR / STTR program works",
            style="Title.TLabel",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Label(
            guide,
            text="Jump",
            style="Hint.TLabel",
        ).grid(row=1, column=0, sticky="nw", padx=(0, 8))
        nav = tk.Listbox(
            guide,
            height=16,
            width=28,
            activestyle="dotbox",
            bg=theme.FIELD,
            fg=theme.FG,
            selectbackground=theme.SELECT,
            highlightthickness=0,
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        nav.grid(row=1, column=0, sticky="nsw", padx=(0, 8))
        self._guide_nav = nav
        self.guide_text = tk.Text(
            guide,
            wrap="word",
            state="normal",
            bg=theme.FIELD,
            fg=theme.FG,
            insertbackground=theme.FG,
            selectbackground=theme.SELECT,
            highlightthickness=0,
            borderwidth=0,
            padx=10,
            pady=10,
            spacing1=2,
            spacing3=6,
        )
        scroll = ttk.Scrollbar(guide, command=self.guide_text.yview)
        self.guide_text.configure(yscrollcommand=scroll.set)
        self.guide_text.grid(row=1, column=1, sticky="nsew")
        scroll.grid(row=1, column=2, sticky="ns")
        self.guide_text.tag_configure(
            "title", foreground=theme.FG, font=("Segoe UI", 14, "bold")
        )
        self.guide_text.tag_configure("lead", foreground=theme.MUTED)
        self.guide_text.tag_configure(
            "h", foreground=theme.ACCENT, font=("Segoe UI", 11, "bold")
        )
        self.guide_text.tag_configure("body", foreground=theme.FG)
        self.guide_text.tag_configure("mono", font=("Consolas", 9), foreground=theme.FG)
        self._fill_guide_text()
        nav.bind("<<ListboxSelect>>", self._on_guide_nav)
        links = ttk.Frame(guide)
        links.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Label(links, text="Open in browser:", style="Hint.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        for index, (label, url) in enumerate(sbir_guide.LINKS):
            ttk.Button(
                links,
                text=label,
                command=lambda dest=url: self._open_guide_link(dest),
            ).grid(row=index // 4, column=(index % 4) + 1, sticky="w", padx=4, pady=2)

    @staticmethod
    def _open_guide_link(url: str) -> None:
        if not url.startswith("https://"):
            return
        import webbrowser

        webbrowser.open(url)

    def _fill_guide_text(self) -> None:
        text = self.guide_text
        nav = self._guide_nav
        text.configure(state="normal")
        text.delete("1.0", "end")
        nav.delete(0, "end")
        text.insert("end", "How the SBIR / STTR program works\n", "title")
        text.insert(
            "end",
            "Local notes for a BD or capture analyst. Official rules win if they "
            "disagree with anything here.\n\n",
            "lead",
        )
        for title, body in sbir_guide.SECTIONS:
            mark = f"sec_{title[:24]}"
            text.mark_set(mark, "end")
            text.mark_gravity(mark, "left")
            nav.insert("end", title)
            text.insert("end", f"{title}\n", "h")
            tag = "mono" if title.startswith("FY27") else "body"
            text.insert("end", f"{body}\n\n", tag)
        text.insert("end", "Links (opens in your browser)\n", "h")
        for label, url in sbir_guide.LINKS:
            text.insert("end", f"• {label}\n  {url}\n", "body")
        text.configure(state="disabled")
        self._guide_marks = [f"sec_{title[:24]}" for title, _ in sbir_guide.SECTIONS]

    def _on_guide_nav(self, _event: tk.Event | None = None) -> None:
        selection = self._guide_nav.curselection()
        if not selection:
            return
        index = int(selection[0])
        marks = getattr(self, "_guide_marks", [])
        if 0 <= index < len(marks):
            self.guide_text.see(marks[index])

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

    def _apply_display_columns(self) -> None:
        visible = [
            key
            for key in self._columns
            if key in PINNED_COLUMNS or key not in self._hidden_columns
        ]
        self.table.configure(displaycolumns=visible)

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

    def _on_copy_brief(self, _event: tk.Event | None = None) -> str:
        self._copy_selected_brief()
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

    # ---- actions ---------------------------------------------------------
    def browse(self) -> None:
        start = self.folder_var.get() or str(Path.home())
        chosen = filedialog.askdirectory(
            title="Choose where to save the opportunities", initialdir=start
        )
        if chosen:
            self.folder_var.set(chosen)
            self._refresh_snapshot_list()
            self._save_state()

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

    def start_download(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        parent_text = self.folder_var.get().strip()
        if not parent_text:
            self._warn("Please choose a folder to save the downloads in.")
            return
        parent = Path(parent_text).expanduser()
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._warn(f"Cannot use that folder:\n{exc}")
            return

        self._resume_dir = (
            self.output_dir if self._has_manifest(self.output_dir) else None
        )
        self.output_dir = core.timestamped_dir(parent)
        self.finished = False
        self.exit_code = None
        self._set_chrome_collapsed(False)
        self._set_running(True)
        self._clear_log()
        self.bluf_caption_var.set("Fetching catalog…")
        self.phase_var.set("Starting catalog scan…")
        self._pdf_done = 0
        self._pdf_total = 0
        self._refresh_header_status()
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self._indeterminate = True  # bar is animating until the first phase begins

        phrase = self.filter_var.get().strip() or self._chip_phrase()
        reporter = QueueReporter(self.events)
        self.worker = threading.Thread(
            target=self._run_download,
            args=(self.output_dir, reporter, phrase),
            daemon=True,
        )
        self.worker.start()
        self._poll_events()

    def _run_download(
        self, output_dir: Path, reporter: QueueReporter, phrase: str
    ) -> None:
        try:
            code = core.run(output_dir, reporter=reporter, search_phrase=phrase)
            self.events.put(("finished", code))
        except Exception as exc:  # noqa: BLE001 - surface any crash to the UI
            self.events.put(("status", str(exc)))
            self.events.put(("status", traceback.format_exc()))
            self.events.put(("finished", 1))

    # ---- event pump ------------------------------------------------------
    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        if self.worker and self.worker.is_alive():
            self.root.after(100, self._poll_events)
        else:
            # Drain anything left after the thread ended.
            self._drain_remaining()

    def _drain_remaining(self) -> None:
        try:
            while True:
                self._handle_event(self.events.get_nowait())
        except queue.Empty:
            pass

    def _handle_event(self, event: tuple) -> None:
        kind = event[0]
        if kind == "status":
            if event[1]:
                self._append_log(event[1])
        elif kind == "start_phase":
            _, label, total = event
            self._phase_label = label
            self.progress.stop()  # stop() zeroes the value; we set it below
            self._indeterminate = False
            self.progress.configure(mode="determinate", maximum=max(1, total), value=0)
            if "topic PDF" in label.lower():
                self._pdf_total = total
                self._pdf_done = 0
            self.phase_var.set(f"{label}  0/{total}")
            self._refresh_header_status()
        elif kind == "advance":
            info = event[1]
            self.progress.configure(value=info["done"])
            label = self._phase_label or self.phase_var.get().split(":", 1)[0]
            if "topic PDF" in str(self._phase_label).lower():
                self._pdf_done = info["done"]
                self._pdf_total = info["total"]
            self.phase_var.set(f"{label}  {info['done']}/{info['total']}")
            self._refresh_header_status()
            if info["failure"]:
                self._append_log(info["failure"])
        elif kind == "end_phase":
            if getattr(self, "_phase_label", "") == "solicitation PDF":
                self._refresh_all_page_limits()
        elif kind == "catalog_ready":
            self._apply_catalog(event[1])
        elif kind == "item_done":
            self._apply_item_done(event[1])
        elif kind == "finished":
            self._on_finished(event[1])

    def _apply_catalog(self, topics: list[dict]) -> None:
        self._topics_for_diff = list(topics)
        self._bluf_rows = [
            analyze.bluf_row(topic, self.output_dir) for topic in topics
        ]
        for row, topic in zip(self._bluf_rows, self._topics_for_diff):
            row["pdf"] = topic.get("pdf") or ""
            row["pdfStatus"] = topic.get("pdfStatus") or "pending"
            self._stamp_triage(row)
        self._fill_tech_areas()
        self.phase_var.set(f"Catalog {len(self._bluf_rows)} topics")
        self._refresh_header_status()
        self._render_table()
        self._refresh_caption(pending=True)
        self._save_state()

    def _apply_item_done(self, info: dict) -> None:
        if info.get("label") != "topic PDF":
            return
        key = str(info.get("key") or "")
        outcome = info.get("outcome") or {}
        status = outcome.get("status") or "failed"
        error = outcome.get("error")
        topic = next(
            (row for row in self._topics_for_diff if str(row.get("topicId")) == key),
            None,
        )
        if topic is None:
            return
        topic["pdfStatus"] = "failed" if error else status
        if error:
            topic["pdf"] = None
            topic["pdfError"] = error
        self._commit_note()
        for index, row in enumerate(self._bluf_rows):
            if str(row.get("topicId")) == key:
                refreshed = analyze.bluf_row(topic, self.output_dir)
                refreshed["pdfStatus"] = topic.get("pdfStatus") or ""
                self._stamp_triage(refreshed)
                self._bluf_rows[index] = refreshed
                break
        self._render_table()
        self._rebind_selected()
        self._refresh_caption(pending=True)

    def _refresh_all_page_limits(self) -> None:
        """Fill tech-vol / feasibility cells from instruction PDFs already on disk."""
        if self.output_dir is None:
            return
        for row in self._bluf_rows:
            analyze.refresh_volume_page_limits(row, self.output_dir)
        self._render_table()
        self._rebind_selected()

    def _on_finished(self, code: int) -> None:
        self.exit_code = code
        self.finished = True
        if self._indeterminate:
            # Download ended before any phase started (e.g. an early error);
            # stop() here is safe because there is no determinate value to lose.
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
            self._indeterminate = False
        elif code == 0:
            # Fill the bar to 100% on a clean finish.
            self.progress.configure(value=self.progress["maximum"])
        self.phase_var.set("Done" if code == 0 else "Finished with issues")
        if self._has_manifest(self.output_dir):
            self._load_bluf_table()
            self._set_chrome_collapsed(True)
        else:
            if self._has_manifest(self._resume_dir):
                self.output_dir = self._resume_dir
                self._load_bluf_table()
            if code != 0:
                self.bluf_caption_var.set(
                    "Download failed. The previous snapshot is still shown. "
                    "See the log (Download settings) for the error."
                )
            self._set_chrome_collapsed(code == 0)
        self._refresh_snapshot_list()
        self._refresh_header_status()
        self._set_running(False)
        self._save_state()
        if self.on_finished:
            self.on_finished(code)

    def open_output_folder(self) -> None:
        self._open_folder(self.output_dir)

    def open_snapshot(self) -> None:
        start = self.output_dir or self.folder_var.get() or str(Path.home())
        chosen = filedialog.askdirectory(
            title="Choose a previous download folder (with manifest.json)",
            initialdir=start,
        )
        if chosen:
            self._load_snapshot(Path(chosen))

    @staticmethod
    def _open_folder(path: Path | None) -> None:
        if not path:
            return
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]  # Windows only
        except Exception:  # noqa: BLE001 - opening the folder is best-effort
            pass

    # ---- small helpers ---------------------------------------------------
    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.download_btn.configure(state=state)
        self.browse_btn.configure(state=state)
        self.folder_entry.configure(state=state)
        self.filter_entry.configure(state=state)
        self.open_snapshot_btn.configure(state=state)
        if getattr(self, "snapshot_combo", None) is not None:
            self.snapshot_combo.configure(state="disabled" if running else "readonly")

    def _sync_button_label(self, *_args: object) -> None:
        if self.filter_var.get().strip() or self._chip_phrase():
            self.button_var.set("Download matching opportunities")
        else:
            self.button_var.set("Download all opportunities")

    def _chip_phrase(self) -> str:
        parts = [
            key
            for _, key in CHIP_SPECS
            if key in DOWNLOAD_CHIP_KEYS and self._chip_vars[key].get()
        ]
        return " ".join(parts)

    def _on_filter_change(self) -> None:
        self._render_table()
        self._save_state()

    def _on_chips(self) -> None:
        self._sync_button_label()
        self._render_table()
        self._save_state()

    def _row_in_diff(self, row: dict, codes: set[str]) -> bool:
        return str(row.get("code") or "") in codes

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
        show_zero = bool(self.show_zero_components.get())
        for label, key in DEPARTMENT_CHIPS:
            button = self._dept_checks.get(key)
            if button is None:
                continue
            n = counts[key]
            button.configure(text=f"{label} ({n})")
            if (
                self._bluf_rows
                and n == 0
                and not show_zero
                and not self._chip_vars[key].get()
            ):
                button.grid_remove()
            else:
                button.grid()
        for label, key in WORKFLOW_CHIPS:
            button = getattr(self, "_work_checks", {}).get(key)
            if button is None:
                continue
            button.configure(text=f"{label} ({counts[key]})")
        self._style_pills()
        self._refresh_pipeline()

    def _refresh_pipeline(self) -> None:
        summary = analyze.pipeline_summary(self._bluf_rows)
        labels = {
            "All calls": f"All {summary.get('topics', 0)}",
            "Pursue": f"Pursue {summary.get('pursue', 0)}",
            "Watch": f"Watch {summary.get('watch', 0)}",
            "Pass": f"Pass {summary.get('pass', 0)}",
            "Untagged": f"Untagged {summary.get('untagged', 0)}",
        }
        for name, btn in getattr(self, "_pipe_btns", {}).items():
            btn.configure(text=labels.get(name, name))

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

    def _ensure_pdf_backend(self) -> None:
        """Page limits come from instruction PDFs; conda base often lacks pypdf."""
        if analyze.pypdf_available():
            return
        if analyze.ensure_pypdf(install=True):
            self._append_log("Installed pypdf so Tech Vol / Feasibility page limits can be read.")
            return
        self._append_log(
            "pypdf is not installed in this Python. "
            "Tech Vol and Feasibility page limits stay blank. "
            f"Fix: {sys.executable} -m pip install pypdf"
        )

    def _restore_state(self) -> None:
        try:
            payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        parent = payload.get("parent")
        if parent:
            self.folder_var.set(str(parent))
        self._triage = self._sanitize_triage(payload.get("triage"))
        for key in payload.get("chips") or []:
            if key in self._chip_vars:
                self._chip_vars[key].set(True)
        find = payload.get("find")
        if isinstance(find, str):
            self.table_filter_var.set(find)
        call = payload.get("call_filter")
        if call in CALL_FILTERS:
            self.call_filter_var.set(call)
        tech = payload.get("tech_area")
        if isinstance(tech, str) and tech:
            self.tech_area_var.set(tech)
        if payload.get("show_zero_components") is True:
            self.show_zero_components.set(True)
        density = payload.get("density")
        if density in {"comfortable", "compact"}:
            self.density_var.set(density)
            if getattr(self, "density_btn", None) is not None:
                self.density_btn.configure(
                    text="Comfortable" if density == "compact" else "Compact"
                )
        hidden = payload.get("hidden_columns")
        if isinstance(hidden, list):
            self._hidden_columns = {
                str(item) for item in hidden if str(item) not in PINNED_COLUMNS
            }
            self._apply_display_columns()
        zoom = payload.get("zoom")
        if isinstance(zoom, (int, float)) and zoom:
            self._zoom_from_state = True
            self._set_zoom(float(zoom))
        geom = payload.get("geometry")
        if isinstance(geom, str) and geom and self.interactive:
            try:
                self.root.geometry(geom)
            except tk.TclError:
                pass
        last = payload.get("last_output")
        folder = Path(last) if last else None
        if not self._has_manifest(folder):
            parent_text = self.folder_var.get().strip() or str(payload.get("parent") or "")
            folder = self._latest_snapshot(Path(parent_text)) if parent_text else None
        if self._has_manifest(folder):
            self.output_dir = folder
            self._load_bluf_table()
            self._set_chrome_collapsed(True)
            self.phase_var.set("Last snapshot")
            self._refresh_header_status()

    @staticmethod
    def _has_manifest(folder: Path | None) -> bool:
        return bool(folder) and (Path(folder) / "manifest.json").is_file()

    @staticmethod
    def _latest_snapshot(parent: Path) -> Path | None:
        if not parent.is_dir():
            return None
        found = [
            path
            for path in parent.glob("all_dsip_opportunities_*")
            if path.is_dir() and (path / "manifest.json").is_file()
        ]
        if not found:
            return None
        return max(found, key=lambda path: path.stat().st_mtime)

    def _save_state(self) -> None:
        last = ""
        if self._has_manifest(self.output_dir):
            last = str(self.output_dir)
        elif self._has_manifest(self._resume_dir):
            last = str(self._resume_dir)
        payload = {
            "parent": self.folder_var.get().strip(),
            "last_output": last,
            "triage": self._triage,
            "chips": [key for key, var in self._chip_vars.items() if var.get()],
            "find": self.table_filter_var.get(),
            "call_filter": self.call_filter_var.get(),
            "tech_area": self.tech_area_var.get(),
            "show_zero_components": bool(self.show_zero_components.get()),
            "zoom": self._zoom,
            "density": self.density_var.get(),
            "hidden_columns": sorted(self._hidden_columns),
            "geometry": self.root.geometry() if self.interactive else "",
        }
        try:
            STATE_FILE.write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8"
            )
        except OSError:
            pass

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

    def _load_bluf_table(self) -> None:
        self._clear_table()
        if self.output_dir is None:
            return
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
            analyze.bluf_row(topic, self.output_dir)
            for topic in payload.get("topics") or []
        ]
        self._commit_note()
        selected_key = self._triage_key(self._selected_row) if self._selected_row else ""
        self._bluf_rows = rows
        self._topics_for_diff = payload.get("topics") or []
        for row in self._bluf_rows:
            analyze.refresh_due_in(row)
            analyze.refresh_volume_page_limits(row, self.output_dir)
            self._stamp_triage(row)
        stated = sum(1 for row in self._bluf_rows if row.get("techVolLimit"))
        self._append_log(
            f"Page limits from instruction PDFs: {stated}/{len(self._bluf_rows)} topics stated."
        )
        self._fill_tech_areas()
        self._render_table()
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
            self._sort_reverse = False
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
        diff = analyze.snapshot_diff(current, previous)
        self._append_log(
            f"Snapshot diff vs {chosen}: "
            f"+{len(diff['added'])} new, -{len(diff['removed'])} gone, "
            f"{len(diff['changed'])} changed."
        )
        if diff["added"]:
            self._append_log("  new: " + ", ".join(diff["added"][:12]))
        if diff["removed"]:
            self._append_log("  gone: " + ", ".join(diff["removed"][:12]))
        self._diff_added = set(diff["added"])
        self._diff_changed = set(diff["changed"])
        self._refresh_chip_labels()
        self._render_table()
        if self._chrome_collapsed:
            self.log_frame.grid()

    def _row_by_iid(self, iid: str) -> dict | None:
        for row in self._bluf_rows:
            if str(row.get("topicId")) == iid:
                return row
        return None

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
        pdf_text = ""
        pdf_name = str(row.get("pdf") or "")
        if self.output_dir and pdf_name and pdf_name not in {"Failed", "—"}:
            path = analyze.resolve_pdf(self.output_dir, pdf_name)
            if path is not None:
                pdf_text = analyze.extract_pdf_text(path)
        analyze.refresh_volume_page_limits(row, self.output_dir, topic_text=pdf_text)
        overview = analyze.topic_overview_paragraph(row, pdf_text=pdf_text, details=details)
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
        if excerpt:
            self.detail_text.insert("end", "Published Q&A\n", "h")
            self.detail_text.insert("end", excerpt + "\n", "body")
        self.detail_text.configure(state="disabled")
        self._note_loading = True
        self.note_var.set(str(row.get("note") or ""))
        self._note_bound_key = self._triage_key(row)
        self._note_loading = False

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


def _selftest() -> int:
    """Build the window, pump one cycle, and exit. Used to smoke-test the exe."""
    sentinel = Path(
        __import__("tempfile").gettempdir()
    ) / "dsip_selftest_ok.txt"
    try:
        sentinel.unlink()
    except OSError:
        pass
    root = tk.Tk()
    root.withdraw()
    App(root, interactive=False)
    root.update()
    root.destroy()
    sentinel.write_text("ok", encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Build and tear down the window, then exit (for CI/exe smoke test).",
    )
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()

    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
