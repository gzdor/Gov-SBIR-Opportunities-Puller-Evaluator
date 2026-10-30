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
import theme

APP_TITLE = "DSIP Opportunities Downloader"


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

        root.title(APP_TITLE)
        root.minsize(960, 620)
        theme.apply_dark_theme(root)

        self.folder_var = tk.StringVar(value=str(Path.home() / "Downloads"))
        self.phase_var = tk.StringVar(value="Idle")
        self.filter_var = tk.StringVar(value="")
        self.table_filter_var = tk.StringVar(value="")
        self.bluf_caption_var = tk.StringVar(
            value="BLUF summary appears after a download."
        )
        self.button_var = tk.StringVar(value="Download all opportunities")
        self._bluf_rows: list[dict] = []
        self._topics_for_diff: list[dict] = []
        self._sort_column = ""
        self._sort_reverse = False
        self._zoom = 1.0

        self._build_widgets()
        self._bind_zoom()
        self.filter_var.trace_add("write", self._sync_button_label)
        self.table_filter_var.trace_add("write", lambda *_: self._render_table())

    # ---- UI construction -------------------------------------------------
    def _build_widgets(self) -> None:
        pad = {"padx": 10, "pady": 6}
        accent = tk.Frame(self.root, bg=theme.ACCENT, height=3)
        accent.pack(fill="x", side="top")
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(
            frame,
            text="Download all open DoD SBIR/STTR DSIP opportunities",
            style="Title.TLabel",
        ).grid(row=0, column=0, columnspan=3, sticky="w", **pad)

        ttk.Label(frame, text="Save in folder:").grid(
            row=1, column=0, sticky="w", **pad
        )
        self.folder_entry = ttk.Entry(frame, textvariable=self.folder_var)
        self.folder_entry.grid(row=1, column=1, sticky="ew", **pad)
        self.browse_btn = ttk.Button(frame, text="Browse...", command=self.browse)
        self.browse_btn.grid(row=1, column=2, sticky="e", **pad)

        ttk.Label(
            frame,
            text=(
                "A timestamped subfolder (all_dsip_opportunities_YYYYMMDD_HHMMSS)\n"
                "will be created inside the folder above."
            ),
            style="Hint.TLabel",
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=10)

        ttk.Label(frame, text="Filter phrase (optional):").grid(
            row=3, column=0, sticky="w", **pad
        )
        self.filter_entry = ttk.Entry(frame, textvariable=self.filter_var)
        self.filter_entry.grid(row=3, column=1, columnspan=2, sticky="ew", **pad)
        self.filter_entry.bind("<Return>", lambda _e: self.start_download())

        ttk.Label(
            frame,
            text=(
                "Leave blank for every open topic. Try DAF, UAS, or Air Force — "
                "aliases match locally (never sent to DSIP)."
            ),
            style="Hint.TLabel",
        ).grid(row=4, column=0, columnspan=3, sticky="w", padx=10)

        self.download_btn = ttk.Button(
            frame,
            textvariable=self.button_var,
            command=self.start_download,
            style="Accent.TButton",
        )
        self.download_btn.grid(row=5, column=0, columnspan=3, sticky="ew", **pad)

        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self.progress.grid(row=6, column=0, columnspan=3, sticky="ew", **pad)

        ttk.Label(frame, textvariable=self.phase_var).grid(
            row=7, column=0, columnspan=3, sticky="w", padx=10
        )

        log_frame = ttk.Frame(frame)
        log_frame.grid(row=8, column=0, columnspan=3, sticky="nsew", **pad)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log = tk.Text(
            log_frame,
            height=5,
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
        scrollbar = ttk.Scrollbar(log_frame, command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

        ttk.Label(frame, textvariable=self.bluf_caption_var).grid(
            row=9, column=0, columnspan=2, sticky="w", padx=10
        )
        ttk.Label(
            frame,
            text="Click a PDF filename to open it.  Ctrl + / Ctrl − zoom text.",
            style="Hint.TLabel",
        ).grid(row=9, column=2, sticky="e", padx=10)

        tool = ttk.Frame(frame)
        tool.grid(row=10, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 4))
        tool.columnconfigure(1, weight=1)
        ttk.Label(tool, text="Find in table:").grid(row=0, column=0, sticky="w")
        self.table_filter_entry = ttk.Entry(tool, textvariable=self.table_filter_var)
        self.table_filter_entry.grid(row=0, column=1, sticky="ew", padx=8)
        self.export_btn = ttk.Button(tool, text="Export CSV", command=self.export_csv)
        self.export_btn.grid(row=0, column=2, padx=4)
        self.diff_btn = ttk.Button(tool, text="Diff previous folder…", command=self.diff_previous)
        self.diff_btn.grid(row=0, column=3, padx=4)

        table_frame = ttk.Frame(frame)
        table_frame.grid(row=11, column=0, columnspan=3, sticky="nsew", **pad)
        frame.rowconfigure(11, weight=1)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = (
            "code",
            "title",
            "client",
            "program",
            "status",
            "opens",
            "due",
            "dueIn",
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
            "code": ("Code", 130),
            "title": ("Topic", 200),
            "client": ("Client", 110),
            "program": ("Program", 60),
            "status": ("Status", 90),
            "opens": ("Opens", 90),
            "due": ("Due", 90),
            "dueIn": ("Due in", 70),
            "problem": ("Problem / objective", 220),
            "trl": ("TRL", 45),
            "funding": ("Funding", 80),
            "contract": ("Contract", 110),
            "pdf": ("PDF", 180),
        }
        for key, (label, width) in headings.items():
            self.table.heading(key, text=label, command=lambda c=key: self._sort_by(c))
            stretch = key in {"title", "problem"}
            self.table.column(key, width=width, minwidth=50, stretch=stretch)
        self.table.tag_configure("pdflink", foreground=theme.LINK)
        self.table.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        xscroll = ttk.Scrollbar(
            table_frame, orient="horizontal", command=self.table.xview
        )
        self.table.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.table.bind("<Button-1>", self._on_table_click)
        theme.apply_zoom(self.root, self._zoom, self.log)

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

    # ---- actions ---------------------------------------------------------
    def browse(self) -> None:
        start = self.folder_var.get() or str(Path.home())
        chosen = filedialog.askdirectory(
            title="Choose where to save the opportunities", initialdir=start
        )
        if chosen:
            self.folder_var.set(chosen)

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
        self._set_running(True)
        self._bluf_rows = []
        self._topics_for_diff = []
        self._clear_log()
        self._clear_table()
        self.bluf_caption_var.set("Downloading…")
        self.phase_var.set("Starting...")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self._indeterminate = True  # bar is animating until the first phase begins

        phrase = self.filter_var.get().strip()
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
        elif kind == "finished":
            self._on_finished(event[1])

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
        if self.interactive:
            self._offer_open_folder(code)
        if self.on_finished:
            self.on_finished(code)

    def _offer_open_folder(self, code: int) -> None:
        where = self.output_dir
        message = (
            f"Download complete.\n\nSaved to:\n{where}\n\nOpen the folder now?"
            if code == 0
            else (
                f"Finished with some failures. See manifest.json.\n\n"
                f"Saved to:\n{where}\n\nOpen the folder now?"
            )
        )
        if messagebox.askyesno(APP_TITLE, message):
            self._open_folder(where)

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
        self.table_filter_entry.configure(state=state)
        self.export_btn.configure(state=state)
        self.diff_btn.configure(state=state)

    def _sync_button_label(self, *_args: object) -> None:
        if self.filter_var.get().strip():
            self.button_var.set("Download matching opportunities")
        else:
            self.button_var.set("Download all opportunities")

    def _clear_table(self) -> None:
        for item in self.table.get_children():
            self.table.delete(item)

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
        self._bluf_rows = rows
        self._topics_for_diff = payload.get("topics") or []
        self._render_table()
        n = len(rows)
        failed = sum(1 for row in rows if row.get("pdfStatus") == "failed")
        phrase = payload.get("searchPhrase")
        if n == 0 and phrase:
            self.bluf_caption_var.set(f'No topics matched "{phrase}".')
        elif failed:
            self.bluf_caption_var.set(f"BLUF summary ({n} topics, {failed} failed)")
        else:
            self.bluf_caption_var.set(f"BLUF summary ({n} topics)")

    def _row_matches_find(
        self, row: dict, needle: str, groups: list[list[str]]
    ) -> bool:
        blob = " ".join(str(row.get(col) or "") for col in self._columns).lower()
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

    def _visible_rows(self) -> list[dict]:
        needle = self.table_filter_var.get().strip()
        rows = list(self._bluf_rows)
        if needle:
            groups = analyze.query_groups(needle)
            rows = [row for row in rows if self._row_matches_find(row, needle, groups)]
        if self._sort_column:
            rows.sort(
                key=lambda row: self._sort_key(row, self._sort_column),
                reverse=self._sort_reverse,
            )
        return rows

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

    def _render_table(self) -> None:
        self._clear_table()
        for index, row in enumerate(self._visible_rows()):
            tags = ("pdflink",) if row.get("pdf") and row.get("pdfStatus") != "failed" else ()
            self.table.insert(
                "",
                "end",
                iid=str(row.get("topicId") or f"row-{index}"),
                values=tuple(row.get(col) or "—" for col in self._columns),
                tags=tags,
            )

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
        chosen = filedialog.askdirectory(title="Choose a previous download folder (with manifest.json)")
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
            self._warn("Run a download in this window first so there is a current snapshot.")
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

    def _on_table_click(self, event: tk.Event) -> None:
        if self.table.identify_region(event.x, event.y) != "cell":
            return
        column = self.table.identify_column(event.x)
        try:
            index = int(column.replace("#", "")) - 1
        except ValueError:
            return
        if index < 0 or index >= len(self._columns) or self._columns[index] != "pdf":
            return
        item = self.table.identify_row(event.y)
        if not item:
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
