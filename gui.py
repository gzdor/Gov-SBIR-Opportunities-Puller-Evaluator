#!/usr/bin/env python3
"""Desktop UI for the DoD DSIP open-topics Discovery appliance.

Catalog chrome, table, topic pane, and How-SBIR tab live in sibling modules.
This file owns the window, the download thread, and snapshot restore.
Nothing typed is sent to DSIP as searchText.
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import traceback
from pathlib import Path

# Keep the Tk loop alive while workers flood item_done / advance events.
_EVENT_BATCH = 12

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import analyze
import main as core
import state_io
import theme
from catalog_table import CatalogTableMixin
from chrome import ChromeMixin
from gui_ids import (
    APP_TITLE,
    CALL_FILTERS,
    CHIP_SPECS,
    DEFAULT_HIDDEN_COLUMNS,
    DEPARTMENT_CHIPS,
    DOWNLOAD_CHIP_KEYS,
    PINNED_COLUMNS,
    STATE_FILE,
    TABLE_HEADINGS,
    WORKFLOW_CHIPS,
)
from guide_tab import GuideTabMixin
from topic_pane import TopicPaneMixin


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


class App(ChromeMixin, CatalogTableMixin, TopicPaneMixin, GuideTabMixin):
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
        self._page_limit_gen = 0
        self._page_limit_thread: threading.Thread | None = None
        self._page_limit_dir: Path | None = None
        self._first_paint_done = False
        self._pump_armed = False
        self._table_refresh_after: str | None = None
        self._chip_vars: dict[str, tk.BooleanVar] = {
            key: tk.BooleanVar(value=False) for _, key in CHIP_SPECS
        }

        analyze.quiet_pypdf_loggers()
        self._build_widgets()
        self._bind_zoom()
        self._bind_shortcuts()
        self.filter_var.trace_add("write", self._sync_button_label)
        self.table_filter_var.trace_add("write", lambda *_: self._on_filter_change())
        self.call_filter_var.trace_add("write", lambda *_: self._on_filter_change())
        self.tech_area_var.trace_add("write", lambda *_: self._on_filter_change())
        self._restore_state()
        if self.interactive and not self._zoom_from_state:
            self._set_zoom(theme.display_zoom())
        self._style_pills()
        self._refresh_pipeline()
        self._refresh_snapshot_list()
        self._refresh_header_status()
        self._update_empty_state()
        if self.interactive:
            self.root.after_idle(self._after_first_paint)
        else:
            self._ensure_pdf_backend()

    def _build_widgets(self) -> None:
        pad = {"padx": 10, "pady": 6}
        accent = tk.Frame(self.root, bg=theme.ACCENT, height=3)
        accent.pack(fill="x", side="top")
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)
        self._build_status_bar()
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text="Catalog")
        frame.columnconfigure(1, weight=1)
        self._frame = frame
        self._build_guide_tab()
        self._build_catalog_header(frame)
        self._build_setup_and_progress(frame)
        self._build_pipeline_and_chips(frame)
        self._build_find_toolbar(frame)
        pane = ttk.Panedwindow(frame, orient=tk.VERTICAL)
        pane.grid(row=10, column=0, columnspan=3, sticky="nsew", **pad)
        frame.rowconfigure(10, weight=1)
        self._vpane = pane
        table_frame = self._build_table(pane)
        detail = self._build_topic_pane(pane)
        pane.add(table_frame, weight=4)
        pane.add(detail, weight=1)
        theme.apply_zoom(self.root, self._zoom, self.log, self.density_var.get())
        self.detail_text.configure(font=("Segoe UI", 10))
        self.guide_text.configure(font=("Segoe UI", 10))

    def browse(self) -> None:
        start = self.folder_var.get() or str(Path.home())
        chosen = filedialog.askdirectory(
            title="Choose where to save the opportunities", initialdir=start
        )
        if chosen:
            self.folder_var.set(chosen)
            self._refresh_snapshot_list()
            self._save_state()

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
        self._page_limit_gen += 1
        self._page_limit_dir = self.output_dir
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
        self._arm_event_pump()

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

    def _after_first_paint(self) -> None:
        """Run after the window exists so restore cannot block first paint."""
        self._first_paint_done = True
        self._ensure_pdf_backend()
        self._refresh_all_page_limits(force=False)

    def _cancel_pending_table_refresh(self) -> None:
        after_id = self._table_refresh_after
        if after_id is None:
            return
        try:
            self.root.after_cancel(after_id)
        except tk.TclError:
            pass
        self._table_refresh_after = None

    def _arm_event_pump(self) -> None:
        if self._pump_armed:
            return
        self._pump_armed = True
        self._poll_events()

    def _poll_events(self) -> None:
        processed = 0
        try:
            while processed < _EVENT_BATCH:
                event = self.events.get_nowait()
                self._handle_event(event)
                processed += 1
        except queue.Empty:
            pass
        alive = bool(self.worker and self.worker.is_alive())
        bg = bool(
            self._page_limit_thread is not None and self._page_limit_thread.is_alive()
        )
        pending = processed >= _EVENT_BATCH or not self.events.empty()
        if alive or pending or bg:
            self.root.after(1 if pending else 50, self._poll_events)
        else:
            self._pump_armed = False

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
                self._refresh_all_page_limits(force=True)
        elif kind == "catalog_ready":
            self._apply_catalog(event[1])
        elif kind == "item_done":
            self._apply_item_done(event[1])
        elif kind == "page_limits_ready":
            folder = event[3] if len(event) > 3 else None
            self._apply_page_limits_ready(event[1], event[2], folder)
        elif kind == "finished":
            self._on_finished(event[1])

    def _apply_catalog(self, topics: list[dict]) -> None:
        self._topics_for_diff = list(topics)
        # output_dir=None: catalog JSON only. Do not open PDFs on the Tk thread.
        self._bluf_rows = [analyze.bluf_row(topic, None) for topic in topics]
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
                # Stamp path/status only. Full pypdf BLUF waits for the
                # worker-side manifest / a later page-limit pass so the
                # Tk thread is not stuck in startxref recovery.
                refreshed = dict(row)
                refreshed["pdf"] = topic.get("pdf") or row.get("pdf") or ""
                refreshed["pdfStatus"] = topic.get("pdfStatus") or ""
                self._stamp_triage(refreshed)
                self._bluf_rows[index] = refreshed
                break
        self._schedule_table_refresh()

    def _schedule_table_refresh(self) -> None:
        if not self.interactive:
            self._flush_table_refresh()
            return
        if self._table_refresh_after is not None:
            return
        self._table_refresh_after = self.root.after(120, self._flush_table_refresh)

    def _flush_table_refresh(self) -> None:
        self._table_refresh_after = None
        self._render_table()
        self._rebind_selected()
        self._refresh_caption(pending=True)

    def _page_limits_need_refresh(self) -> bool:
        if not self._bluf_rows or self.output_dir is None:
            return False
        has_stated = False
        for row in self._bluf_rows:
            tech = str(row.get("techVolLimit") or "")
            feas = str(row.get("feasStudyLimit") or "")
            if "typical" in tech.lower() or "typical" in feas.lower():
                return True
            if "(stated)" in tech or "(stated)" in feas:
                has_stated = True
        return not has_stated

    def _refresh_all_page_limits(self, force: bool = False) -> None:
        """Fill tech-vol / feasibility cells from instruction PDFs.

        Interactive: background thread, Tk only applies the result.
        Tests (interactive=False): run synchronously.
        """
        if self.output_dir is None or not self._bluf_rows:
            return
        if not force and not self._page_limits_need_refresh():
            return
        if not self.interactive:
            self._page_limit_dir = self.output_dir
            for row in self._bluf_rows:
                analyze.refresh_volume_page_limits(
                    row, self.output_dir, include_topic_pdf=False
                )
            stated = sum(1 for row in self._bluf_rows if row.get("techVolLimit"))
            self._append_log(
                f"Page limits from instruction PDFs: {stated}/{len(self._bluf_rows)} topics stated."
            )
            self._render_table()
            return
        self._page_limit_gen += 1
        gen = self._page_limit_gen
        output_dir = self.output_dir
        self._page_limit_dir = output_dir
        snapshots = [
            {
                "topicId": row.get("topicId"),
                "code": row.get("code"),
                "topicCode": row.get("code"),
                "component": row.get("component"),
                "client": row.get("client"),
                "instructionPdfs": list(row.get("instructionPdfs") or []),
                "solicitationDocuments": list(row.get("solicitationDocuments") or []),
                "contract": row.get("contract") or "",
                "pdf": "",
                "techVolLimit": "",
                "feasStudyLimit": "",
            }
            for row in self._bluf_rows
        ]

        def work() -> None:
            updates = []
            try:
                for snap in snapshots:
                    if gen != self._page_limit_gen:
                        return
                    analyze.refresh_volume_page_limits(
                        snap, output_dir, include_topic_pdf=False
                    )
                    updates.append(
                        {
                            "topicId": snap.get("topicId"),
                            "techVolLimit": snap.get("techVolLimit") or "",
                            "feasStudyLimit": snap.get("feasStudyLimit") or "",
                            "instructionPdfs": list(snap.get("instructionPdfs") or []),
                        }
                    )
                if gen != self._page_limit_gen:
                    return
                self.events.put(("page_limits_ready", gen, updates, output_dir))
            except Exception as exc:  # noqa: BLE001 - surface worker crash in the log
                self.events.put(("status", f"Page limit scan failed: {exc}"))

        self._page_limit_thread = threading.Thread(target=work, daemon=True)
        self._page_limit_thread.start()
        self._arm_event_pump()

    def _apply_page_limits_ready(
        self,
        gen: int,
        updates: list[dict],
        folder: Path | None = None,
    ) -> None:
        if gen != self._page_limit_gen:
            return
        if folder is not None and self.output_dir != folder:
            return
        by_id = {str(row.get("topicId") or ""): row for row in self._bluf_rows}
        limit_i = self._columns.index("techVolLimit") if "techVolLimit" in self._columns else -1
        feas_i = self._columns.index("feasStudyLimit") if "feasStudyLimit" in self._columns else -1
        stated = 0
        for item in updates:
            row = by_id.get(str(item.get("topicId") or ""))
            if row is None:
                continue
            row["techVolLimit"] = item.get("techVolLimit") or ""
            row["feasStudyLimit"] = item.get("feasStudyLimit") or ""
            if item.get("instructionPdfs"):
                row["instructionPdfs"] = item["instructionPdfs"]
            if row["techVolLimit"]:
                stated += 1
            iid = str(row.get("topicId") or "")
            if iid and self.table.exists(iid) and limit_i >= 0:
                values = list(self.table.item(iid, "values"))
                if limit_i < len(values):
                    values[limit_i] = row["techVolLimit"] or ""
                if feas_i >= 0 and feas_i < len(values):
                    values[feas_i] = row["feasStudyLimit"] or ""
                self.table.item(iid, values=values)
        self._append_log(
            f"Page limits from instruction PDFs: {stated}/{len(self._bluf_rows)} topics stated."
        )
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
        except OSError as exc:
            print(f"Could not open folder {path}: {exc}", flush=True)

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
        payload = state_io.read_json(STATE_FILE)
        if not isinstance(payload, dict):
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
            state_io.write_json_atomic(STATE_FILE, payload)
        except OSError:
            pass



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
