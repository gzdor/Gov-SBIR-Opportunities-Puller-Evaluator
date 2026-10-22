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
import queue
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import main as core

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
        root.minsize(620, 380)

        self.folder_var = tk.StringVar(value=str(Path.home() / "Downloads"))
        self.phase_var = tk.StringVar(value="Idle")

        self._build_widgets()

    # ---- UI construction -------------------------------------------------
    def _build_widgets(self) -> None:
        pad = {"padx": 10, "pady": 6}
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(
            frame,
            text="Download all open DoD SBIR/STTR DSIP opportunities",
            font=("Segoe UI", 12, "bold"),
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
            foreground="#555555",
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=10)

        self.download_btn = ttk.Button(
            frame,
            text="Download all opportunities",
            command=self.start_download,
        )
        self.download_btn.grid(row=3, column=0, columnspan=3, sticky="ew", **pad)

        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self.progress.grid(row=4, column=0, columnspan=3, sticky="ew", **pad)

        ttk.Label(frame, textvariable=self.phase_var).grid(
            row=5, column=0, columnspan=3, sticky="w", padx=10
        )

        log_frame = ttk.Frame(frame)
        log_frame.grid(row=6, column=0, columnspan=3, sticky="nsew", **pad)
        frame.rowconfigure(6, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log = tk.Text(log_frame, height=10, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

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
        self._clear_log()
        self.phase_var.set("Starting...")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self._indeterminate = True  # bar is animating until the first phase begins

        reporter = QueueReporter(self.events)
        self.worker = threading.Thread(
            target=self._run_download, args=(self.output_dir, reporter), daemon=True
        )
        self.worker.start()
        self._poll_events()

    def _run_download(self, output_dir: Path, reporter: QueueReporter) -> None:
        try:
            code = core.run(output_dir, reporter=reporter)
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
