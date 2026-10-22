"""Programmatic tests for gui.py.

These construct the real Tk window and drive the real widgets (clicking the
download button, pumping the event loop) with the network stubbed out, so the
whole button -> worker thread -> reporter -> queue -> UI path is exercised
without hitting the DSIP servers. If no display is available (headless CI),
the Tk tests skip instead of failing.
"""

from __future__ import annotations

import queue
import time

import pytest

import gui
import main


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            data, self._payload = self._payload, b""
            return data
        data, self._payload = self._payload[:size], self._payload[size:]
        return data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _topic(index: int, **extra: object) -> dict:
    record = {
        "topicId": f"topic{index}",
        "topicCode": f"ARM26BX{index:02d}",
        "topicTitle": f"Topic {index}",
        "topicStatus": "Open",
        "component": "ARMY",
        "program": "SBIR",
        "topicStartDate": 1780488000000,
    }
    record.update(extra)
    return record


def _make_root():
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError as exc:  # no display available
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    return root


def test_queue_reporter_emits_expected_events():
    events: "queue.Queue[tuple]" = queue.Queue()
    reporter = gui.QueueReporter(events)
    reporter.status("hello")
    reporter.start_phase("topic PDF", 3)
    reporter.advance(1, 3, None)
    reporter.advance(2, 3, "boom")
    reporter.end_phase()

    drained = []
    while not events.empty():
        drained.append(events.get_nowait())

    assert drained[0] == ("status", "hello")
    assert drained[1] == ("start_phase", "topic PDF", 3)
    assert drained[2][0] == "advance" and drained[2][1]["done"] == 1
    assert drained[3][1]["failure"] == "boom"
    assert drained[4] == ("end_phase",)


def test_gui_download_button_runs_full_flow(tmp_path, monkeypatch):
    shared = {
        "baaPrefaceUploadId": 555,
        "baaPrefaceUploadTitle": "Preface.pdf",
    }
    pages = {
        0: {"total": 2, "data": [_topic(0, **shared), _topic(1, **shared)]},
        1: {"total": 2, "data": []},
    }
    monkeypatch.setattr(main, "REQUEST_PAUSE_SECONDS", 0)
    monkeypatch.setattr(main, "search_page", lambda page: pages.get(page, {"total": 2, "data": []}))
    monkeypatch.setattr(main, "open_url", lambda url, timeout: FakeResponse(b"%PDF-1.4\n" + url.encode("ascii")))
    monkeypatch.setattr(main.time, "sleep", lambda s: None)

    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        app.folder_var.set(str(tmp_path))

        finished = {"code": None}
        app.on_finished = lambda code: finished.__setitem__("code", code)

        # Click the real button.
        app.download_btn.invoke()

        deadline = time.time() + 30
        while not app.finished and time.time() < deadline:
            root.update()
            time.sleep(0.02)
        root.update()

        assert app.finished, "download did not finish within timeout"
        assert app.exit_code == 0
        assert finished["code"] == 0
        assert app.output_dir is not None and app.output_dir.exists()
        assert (app.output_dir / "manifest.json").exists()
        # The final (topic) phase filled the bar completely.
        assert float(app.progress["value"]) == float(app.progress["maximum"])
        # Two topic PDFs were written.
        pdfs = list(app.output_dir.glob("topic_*.pdf"))
        assert len(pdfs) == 2
    finally:
        root.destroy()


def test_gui_rejects_empty_folder(monkeypatch):
    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        app.folder_var.set("   ")
        app.download_btn.invoke()
        root.update()
        # Nothing should have started.
        assert app.worker is None
        assert app.finished is False
    finally:
        root.destroy()
