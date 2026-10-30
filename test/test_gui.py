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
        assert "Download all opportunities" in app.button_var.get()
        app.filter_var.set("illumination")
        root.update()
        assert "matching" in app.button_var.get().lower()
        app.filter_var.set("")
        root.update()

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
        assert len(app.table.get_children()) == 2
        assert "BLUF summary" in app.bluf_caption_var.get()
    finally:
        root.destroy()


def test_gui_table_find_and_dark_theme():
    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        assert str(root.cget("bg")).lower() == gui.theme.BG
        app._bluf_rows = [
            {
                "topicId": "a",
                "code": "DAF27BZ01-DV011",
                "title": "Unmanned Aerial Systems",
                "client": "USAF",
                "program": "SBIR",
                "status": "Open",
                "opens": "2026-10-28",
                "due": "2026-11-25",
                "dueIn": "26d",
                "problem": "Harness",
                "trl": "4–6",
                "funding": "$2,000,000",
                "contract": "Phase II",
                "pdf": "topic_a.pdf",
            },
            {
                "topicId": "b",
                "code": "ARM26BX03",
                "title": "Armor",
                "client": "ARMY",
                "program": "SBIR",
                "status": "Open",
                "opens": "—",
                "due": "—",
                "dueIn": "—",
                "problem": "Plate",
                "trl": "—",
                "funding": "—",
                "contract": "Phase I",
                "pdf": "topic_b.pdf",
            },
        ]
        app._render_table()
        root.update()
        assert len(app.table.get_children()) == 2
        app.table_filter_var.set("UAS")
        root.update()
        assert len(app.table.get_children()) == 1
        assert app.table.item(app.table.get_children()[0], "values")[0] == "DAF27BZ01-DV011"
        app._sort_by("code")
        root.update()
        assert app._sort_column == "code"
    finally:
        root.destroy()


def test_gui_ctrl_plus_minus_zooms_text():
    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        assert app._zoom == 1.0
        app._on_zoom_in()
        assert app._zoom == pytest.approx(1.1)
        app._on_zoom_out()
        assert app._zoom == pytest.approx(1.0)
        for _ in range(20):
            app._on_zoom_out()
        assert app._zoom == gui.theme.ZOOM_MIN
        for _ in range(20):
            app._on_zoom_in()
        assert app._zoom == gui.theme.ZOOM_MAX
        app._on_zoom_out()
        assert app._zoom == pytest.approx(gui.theme.ZOOM_MAX - gui.theme.ZOOM_STEP)
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
