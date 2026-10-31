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

APP_TITLE = "DSIP Opportunities — Puller & Evaluator"
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
    ("due < 7d", "__due7__"),
    ("due < 14d", "__due14__"),
)
CHIP_SPECS = DEPARTMENT_CHIPS + WORKFLOW_CHIPS
DOWNLOAD_CHIP_KEYS = {key for _, key in CHIP_SPECS if not str(key).startswith("__")}
CALL_FILTERS = ("All calls", "Pursue", "Watch", "Pass", "Untagged")


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
        self.on_finished = None  # optional callback for tests
        self._chrome_collapsed = False
        self._selected_row: dict | None = None

        root.title(APP_TITLE)
        root.minsize(960, 620)
        theme.apply_dark_theme(root)

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
        self._bluf_rows: list[dict] = []
        self._topics_for_diff: list[dict] = []
        self._triage: dict[str, dict[str, str]] = {}
        self._sort_column = ""
        self._sort_reverse = False
        self._zoom = 1.0
        self._note_loading = False
        self._note_bound_key = ""
        self._chip_vars: dict[str, tk.BooleanVar] = {
            key: tk.BooleanVar(value=False) for _, key in CHIP_SPECS
        }

        self._build_widgets()
        self._bind_zoom()
        self.filter_var.trace_add("write", self._sync_button_label)
        self.table_filter_var.trace_add("write", lambda *_: self._render_table())
        self.call_filter_var.trace_add("write", lambda *_: self._render_table())
        self._restore_state()

    # ---- UI construction -------------------------------------------------
    def _build_widgets(self) -> None:
        pad = {"padx": 10, "pady": 6}
        accent = tk.Frame(self.root, bg=theme.ACCENT, height=3)
        accent.pack(fill="x", side="top")
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text="Catalog")
        frame.columnconfigure(1, weight=1)
        self._frame = frame
        self._build_guide_tab()

        ttk.Label(
            frame,
            text="Pull and evaluate open DoD SBIR/STTR DSIP opportunities",
            style="Title.TLabel",
        ).grid(row=0, column=0, columnspan=3, sticky="w", **pad)

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

        chips = ttk.Frame(frame)
        chips.grid(row=6, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 2))
        ttk.Label(chips, text="Component:").grid(row=0, column=0, sticky="nw")
        dept = ttk.Frame(chips)
        dept.grid(row=0, column=1, columnspan=12, sticky="w")
        for index, (label, key) in enumerate(DEPARTMENT_CHIPS):
            ttk.Checkbutton(
                dept,
                text=label,
                variable=self._chip_vars[key],
                command=self._on_chips,
            ).grid(row=index // 8, column=index % 8, sticky="w", padx=4)
        ttk.Label(chips, text="Narrow:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        work = ttk.Frame(chips)
        work.grid(row=1, column=1, columnspan=12, sticky="w", pady=(4, 0))
        for index, (label, key) in enumerate(WORKFLOW_CHIPS):
            ttk.Checkbutton(
                work,
                text=label,
                variable=self._chip_vars[key],
                command=self._on_chips,
            ).grid(row=0, column=index, sticky="w", padx=4)
        ttk.Label(chips, text="Calls:").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.call_filter = ttk.Combobox(
            chips,
            textvariable=self.call_filter_var,
            values=CALL_FILTERS,
            state="readonly",
            width=12,
        )
        self.call_filter.grid(row=2, column=1, sticky="w", padx=6, pady=(4, 0))
        ttk.Label(
            chips,
            text="1 Pursue · 2 Watch · 3 Pass · 0 clear   (table focused)",
            style="Hint.TLabel",
        ).grid(row=2, column=2, columnspan=8, sticky="w", pady=(4, 0))

        ttk.Label(frame, textvariable=self.bluf_caption_var).grid(
            row=7, column=0, columnspan=2, sticky="w", padx=10
        )
        ttk.Label(
            frame,
            text="Select a row for details. Ctrl + / Ctrl − zoom.",
            style="Hint.TLabel",
        ).grid(row=7, column=2, sticky="e", padx=10)

        tool = ttk.Frame(frame)
        tool.grid(row=8, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 4))
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
        self.open_folder_btn = ttk.Button(
            tool, text="Open folder", command=self.open_output_folder
        )
        self.open_folder_btn.grid(row=0, column=4, padx=2)
        self.open_snapshot_btn = ttk.Button(
            tool, text="Open snapshot…", command=self.open_snapshot
        )
        self.open_snapshot_btn.grid(row=0, column=5, padx=2)
        self.settings_btn = ttk.Button(
            tool, text="Hide settings", command=self.toggle_chrome
        )
        self.settings_btn.grid(row=0, column=6, padx=2)

        pane = ttk.Panedwindow(frame, orient=tk.VERTICAL)
        pane.grid(row=9, column=0, columnspan=3, sticky="nsew", **pad)
        frame.rowconfigure(9, weight=1)

        table_frame = ttk.Frame(pane)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = (
            "call",
            "code",
            "title",
            "client",
            "program",
            "status",
            "opens",
            "due",
            "dueIn",
            "qaPublished",
            "cmmc",
            "problem",
            "trl",
            "funding",
            "contract",
            "pdf",
        )
        self._columns = columns
        self.table = ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="browse"
        )
        headings = {
            "call": ("Call", 70),
            "code": ("Code", 130),
            "title": ("Topic", 200),
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
            "pdf": ("PDF", 180),
        }
        for key, (label, width) in headings.items():
            self.table.heading(key, text=label, command=lambda c=key: self._sort_by(c))
            stretch = key in {"title", "problem"}
            self.table.column(key, width=width, minwidth=40, stretch=stretch)
        self.table.tag_configure("closing", foreground=theme.WARN)
        self.table.tag_configure("soon", foreground=theme.SOON)
        self.table.tag_configure("closed", foreground=theme.CLOSED)
        self.table.tag_configure("open", foreground=theme.FG)
        self.table.tag_configure("unknown", foreground=theme.FG)
        self.table.tag_configure("pursue", foreground=theme.ACCENT)
        self.table.grid(row=0, column=0, sticky="nsew")
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
        self.pursue_btn = ttk.Button(
            actions, text="Pursue", command=lambda: self._set_selected_triage("pursue")
        )
        self.pursue_btn.grid(row=0, column=3, sticky="w", padx=(16, 4))
        self.watch_btn = ttk.Button(
            actions, text="Watch", command=lambda: self._set_selected_triage("watch")
        )
        self.watch_btn.grid(row=0, column=4, sticky="w", padx=4)
        self.pass_btn = ttk.Button(
            actions, text="Pass", command=lambda: self._set_selected_triage("pass")
        )
        self.pass_btn.grid(row=0, column=5, sticky="w", padx=4)
        ttk.Label(detail, text="Note (stays on this machine):").grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )
        self.note_entry = ttk.Entry(detail, textvariable=self.note_var)
        self.note_entry.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(2, 0))
        self.note_entry.bind("<FocusOut>", lambda _e: self._commit_note())
        self.note_entry.bind("<Return>", lambda _e: self._commit_note())

        pane.add(table_frame, weight=4)
        pane.add(detail, weight=1)
        theme.apply_zoom(self.root, self._zoom, self.log)
        self.detail_text.configure(font=("Segoe UI", 10))
        self.guide_text.configure(font=("Segoe UI", 10))

    def _build_guide_tab(self) -> None:
        guide = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(guide, text="How SBIR works")
        guide.columnconfigure(0, weight=1)
        guide.rowconfigure(1, weight=1)
        ttk.Label(
            guide,
            text="How the SBIR / STTR program works",
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
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
            padx=8,
            pady=8,
        )
        scroll = ttk.Scrollbar(guide, command=self.guide_text.yview)
        self.guide_text.configure(yscrollcommand=scroll.set)
        self.guide_text.grid(row=1, column=0, sticky="nsew")
        scroll.grid(row=1, column=1, sticky="ns")
        self.guide_text.insert("1.0", sbir_guide.guide_plain_text())
        self.guide_text.configure(state="disabled")
        links = ttk.Frame(guide)
        links.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
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

    def _on_zoom_in(self, _event: tk.Event | None = None) -> str:
        self._set_zoom(self._zoom + theme.ZOOM_STEP)
        return "break"

    def _on_zoom_out(self, _event: tk.Event | None = None) -> str:
        self._set_zoom(self._zoom - theme.ZOOM_STEP)
        return "break"

    def _set_zoom(self, scale: float) -> None:
        self._zoom = theme.apply_zoom(self.root, scale, self.log)
        size = max(6, int(round(10 * self._zoom)))
        self.detail_text.configure(font=("Segoe UI", size))
        if getattr(self, "guide_text", None) is not None:
            self.guide_text.configure(font=("Segoe UI", size))

    # ---- actions ---------------------------------------------------------
    def browse(self) -> None:
        start = self.folder_var.get() or str(Path.home())
        chosen = filedialog.askdirectory(
            title="Choose where to save the opportunities", initialdir=start
        )
        if chosen:
            self.folder_var.set(chosen)
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

        self.output_dir = core.timestamped_dir(parent)
        self.finished = False
        self.exit_code = None
        self._set_chrome_collapsed(False)
        self._set_running(True)
        self._bluf_rows = []
        self._topics_for_diff = []
        self._clear_log()
        self._clear_table()
        self.bluf_caption_var.set("Fetching catalog…")
        self.phase_var.set("Starting...")
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
        except Exception:  # noqa: BLE001 - surface any crash to the UI
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
            self.progress.stop()  # stop() zeroes the value; we set it below
            self._indeterminate = False
            self.progress.configure(mode="determinate", maximum=max(1, total), value=0)
            self.phase_var.set(f"{label}: 0/{total}")
        elif kind == "advance":
            info = event[1]
            self.progress.configure(value=info["done"])
            label = self.phase_var.get().split(":", 1)[0]
            self.phase_var.set(f"{label}: {info['done']}/{info['total']}")
            if info["failure"]:
                self._append_log(info["failure"])
        elif kind == "end_phase":
            pass
        elif kind == "catalog_ready":
            self._apply_catalog(event[1])
        elif kind == "item_done":
            self._apply_item_done(event[1])
        elif kind == "finished":
            self._on_finished(event[1])

    def _apply_catalog(self, topics: list[dict]) -> None:
        self._topics_for_diff = list(topics)
        self._bluf_rows = [analyze.bluf_row(topic, None) for topic in topics]
        for row, topic in zip(self._bluf_rows, self._topics_for_diff):
            row["pdf"] = topic.get("pdf") or ""
            row["pdfStatus"] = topic.get("pdfStatus") or "pending"
            self._stamp_triage(row)
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
        self._load_bluf_table()
        self._set_running(False)
        self._set_chrome_collapsed(True)
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
            import os

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

    def _on_chips(self) -> None:
        self._sync_button_label()
        self._render_table()

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
        self._save_state()
        return True

    def _restore_state(self) -> None:
        try:
            payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        parent = payload.get("parent")
        if parent:
            self.folder_var.set(str(parent))
        self._triage = self._sanitize_triage(payload.get("triage"))
        last = payload.get("last_output")
        if last and (Path(last) / "manifest.json").is_file():
            self.output_dir = Path(last)
            self._load_bluf_table()
            self._set_chrome_collapsed(True)
            self.phase_var.set("Last snapshot")

    def _save_state(self) -> None:
        payload = {
            "parent": self.folder_var.get().strip(),
            "last_output": str(self.output_dir) if self.output_dir else "",
            "triage": self._triage,
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
            self._stamp_triage(row)
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
        blob = f"{blob} {row.get('note') or ''} {row.get('qaExcerpt') or ''}".lower()
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
        return str(row.get(column) or "—")

    def _render_table(self) -> None:
        self._clear_table()
        for index, row in enumerate(self._visible_rows()):
            tags = [analyze.urgency(row)]
            if analyze.normalize_triage(row.get("call")) == "pursue":
                tags.append("pursue")
            iid = str(row.get("topicId") or f"row-{index}")
            self.table.insert(
                "",
                "end",
                iid=iid,
                values=tuple(self._cell(row, col) for col in self._columns),
                tags=tuple(tags),
            )
        if self._bluf_rows:
            self._refresh_caption()

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
        body = "\n".join(
            [
                f"Client: {row.get('client') or '—'}",
                f"Status: {row.get('status') or '—'}    Due: {row.get('due') or '—'} ({row.get('dueIn') or '—'})",
                f"Program: {row.get('program') or '—'}    Contract: {row.get('contract') or '—'}",
                f"TRL: {row.get('trl') or '—'}    Funding: {row.get('funding') or '—'}",
                f"Call: {call}",
                f"CMMC: {row.get('cmmc') or '—'}    Q&A: {row.get('qaPublished') or 0} published ({row.get('qaStatus') or '—'})",
                f"TPOC: {row.get('tpoc') or '—'}",
                f"PDF: {row.get('pdf') or '—'}",
                "",
                str(row.get("problem") or row.get("overview") or "—"),
            ]
        )
        excerpt = str(row.get("qaExcerpt") or "").strip()
        if excerpt:
            body = f"{body}\n\nPublished Q&A\n{excerpt}"
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", body)
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
        if index < 0 or index >= len(self._columns) or self._columns[index] != "pdf":
            return
        values = self.table.item(item, "values")
        if not values or index >= len(values):
            return
        pdf_name = values[index]
        if not self.output_dir or not pdf_name or pdf_name in {"Failed", "—"}:
            return
        if not analyze.open_local_pdf(self.output_dir, pdf_name):
            self._warn(
                "Could not open that PDF. The path must be a real .pdf file "
                "inside this download folder."
            )

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

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
