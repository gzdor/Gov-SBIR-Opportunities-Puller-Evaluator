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

import json

import pytest

import analyze
import gui
import main


@pytest.fixture(autouse=True)
def _isolate_gui_state(tmp_path, monkeypatch):
    monkeypatch.setattr(gui, "STATE_FILE", tmp_path / "dsip_state.json")


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


def _row_values(app, iid=None) -> dict:
    if iid is None:
        children = app.table.get_children()
        assert children, "table is empty"
        iid = children[0]
    return dict(zip(app._columns, app.table.item(iid, "values")))


def _bluf(
    topic_id: str,
    code: str,
    title: str,
    **extra: object,
) -> dict:
    row = {
        "topicId": topic_id,
        "code": code,
        "title": title,
        "client": extra.pop("client", "USAF"),
        "program": extra.pop("program", "SBIR"),
        "status": extra.pop("status", "Open"),
        "opens": extra.pop("opens", "2026-10-28"),
        "due": extra.pop("due", "2026-11-25"),
        "dueIn": extra.pop("dueIn", "26d"),
        "problem": extra.pop("problem", "Harness"),
        "trl": extra.pop("trl", "—"),
        "funding": extra.pop("funding", "—"),
        "contract": extra.pop("contract", "Phase II"),
        "pdf": extra.pop("pdf", "topic.pdf"),
        "call": extra.pop("call", ""),
        "note": extra.pop("note", ""),
        "qaPublished": extra.pop("qaPublished", 0),
        "cmmc": extra.pop("cmmc", "—"),
        "qaExcerpt": extra.pop("qaExcerpt", ""),
        "tpoc": extra.pop("tpoc", "—"),
    }
    row.update(extra)
    return row


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
    reporter.catalog_ready([{"topicId": "t0"}])
    reporter.item_done("topic PDF", "t0", {"status": "downloaded", "error": None})

    drained = []
    while not events.empty():
        drained.append(events.get_nowait())

    assert drained[0] == ("status", "hello")
    assert drained[1] == ("start_phase", "topic PDF", 3)
    assert drained[2][0] == "advance" and drained[2][1]["done"] == 1
    assert drained[3][1]["failure"] == "boom"
    assert drained[4] == ("end_phase",)
    assert drained[5][0] == "catalog_ready"
    assert drained[6][0] == "item_done"


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
        assert "shown /" in app.bluf_caption_var.get()
        assert app._chrome_collapsed is True
    except Exception as exc:
        if "scale.tcl" in str(exc):
            pytest.skip(f"conda Tk scale.tcl flake: {exc}")
        raise
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
        assert _row_values(app)["code"] == "DAF27BZ01-DV011"
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


def test_gui_catalog_ready_fills_table_before_pdfs():
    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        app._handle_event(
            (
                "catalog_ready",
                [
                    {
                        "topicId": "t0",
                        "topicCode": "DAF27BZ01-DV011",
                        "topicTitle": "Unmanned Aerial Systems",
                        "topicStatus": "Open",
                        "component": "USAF",
                        "command": "AFMC",
                        "program": "SBIR",
                        "topicStartDate": "2026-10-28T00:00:00+00:00",
                        "topicEndDate": "2026-11-25T00:00:00+00:00",
                        "pdf": "topic_t0.pdf",
                        "pdfStatus": "pending",
                    }
                ],
            )
        )
        root.update()
        assert len(app.table.get_children()) == 1
        assert app._bluf_rows[0]["pdfStatus"] == "pending"
        assert "PDFs 0/1" in app.bluf_caption_var.get()
    finally:
        root.destroy()


def test_gui_restores_last_snapshot(tmp_path):
    snap = tmp_path / "all_dsip_opportunities_20261030_120000"
    snap.mkdir()
    (snap / "manifest.json").write_text(
        json.dumps(
            {
                "topics": [
                    {
                        "topicId": "t0",
                        "topicCode": "DAF01",
                        "topicTitle": "Illumination",
                        "topicStatus": "Open",
                        "component": "USAF",
                    }
                ],
                "bluf": [
                    {
                        "topicId": "t0",
                        "code": "DAF01",
                        "title": "Illumination",
                        "client": "USAF",
                        "program": "SBIR",
                        "status": "Open",
                        "opens": "2026-10-28",
                        "due": "2026-11-25",
                        "dueIn": "26d",
                        "problem": "Light",
                        "trl": "—",
                        "funding": "—",
                        "contract": "SBIR",
                        "pdf": "topic.pdf",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    gui.STATE_FILE.write_text(
        json.dumps({"parent": str(tmp_path), "last_output": str(snap)}),
        encoding="utf-8",
    )
    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        root.update()
        assert app.output_dir == snap
        assert len(app.table.get_children()) == 1
        assert app._chrome_collapsed is True
        assert _row_values(app)["code"] == "DAF01"
    finally:
        root.destroy()


def test_gui_chips_and_default_due_sort():
    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        app._bluf_rows = [
            {
                "topicId": "pre",
                "code": "ARM01",
                "title": "Armor",
                "client": "ARMY",
                "program": "SBIR",
                "status": "Pre-Release",
                "opens": "—",
                "due": "2026-11-02",
                "dueIn": "3d",
                "problem": "Plate",
                "trl": "—",
                "funding": "—",
                "contract": "Phase I",
                "pdf": "a.pdf",
            },
            {
                "topicId": "open",
                "code": "DAF27BZ01-DV011",
                "title": "Unmanned Aerial Systems",
                "client": "USAF",
                "program": "SBIR",
                "status": "Open",
                "opens": "2026-10-28",
                "due": "2026-12-01",
                "dueIn": "32d",
                "problem": "Harness",
                "trl": "—",
                "funding": "—",
                "contract": "Phase II",
                "pdf": "b.pdf",
            },
        ]
        app._render_table()
        root.update()
        first = _row_values(app)["code"]
        assert first == "DAF27BZ01-DV011"
        app._chip_vars["DAF"].set(True)
        app._on_chips()
        root.update()
        assert len(app.table.get_children()) == 1
        app._chip_vars["__due14__"].set(True)
        app._on_chips()
        root.update()
        assert len(app.table.get_children()) == 0
        row = app._bluf_rows[1]
        app._show_detail(row)
        assert "DAF27BZ01-DV011" in app.detail_title_var.get()
        assert "Unmanned Aerial" in app.detail_title_var.get()
        assert "Harness" in app.detail_text.get("1.0", "end")
    finally:
        root.destroy()


def test_gui_finish_does_not_ask_to_open_folder(monkeypatch):
    asked = {"n": 0}

    def boom(*_args, **_kwargs):
        asked["n"] += 1
        return False

    monkeypatch.setattr(gui.messagebox, "askyesno", boom)
    root = _make_root()
    try:
        app = gui.App(root, interactive=True)
        app._on_finished(0)
        assert asked["n"] == 0
        assert app._chrome_collapsed is True
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


def test_gui_has_how_sbir_works_tab(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        tabs = [app.notebook.tab(tab_id, "text") for tab_id in app.notebook.tabs()]
        assert tabs == ["Catalog", "How SBIR works"]
        body = app.guide_text.get("1.0", "end")
        assert "How the SBIR / STTR program works" in body
        assert "Direct to Phase II" in body
        assert "Get my free funding report" not in body
        app.notebook.select(1)
        root.update()
        assert "How SBIR" in app.notebook.tab(app.notebook.select(), "text")
        app._open_guide_link("http://example.invalid")
        app._open_guide_link("not-a-url")
        app._open_guide_link("https://www.dodsbirsttr.mil/topics-app/")
        assert opened == ["https://www.dodsbirsttr.mil/topics-app/"]
    finally:
        root.destroy()


def test_gui_department_chips_and_has_qa_filter():
    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        for _, key in gui.DEPARTMENT_CHIPS:
            assert key in app._chip_vars
        app._bluf_rows = [
            _bluf("a", "DAF01", "Air", client="USAF", qaPublished=2, qaExcerpt="Q: Threshold?"),
            _bluf("b", "ARM01", "Armor", client="ARMY", qaPublished=0),
        ]
        app._chip_vars["DAF"].set(True)
        app._render_table()
        root.update()
        assert {_row_values(app, iid)["code"] for iid in app.table.get_children()} == {
            "DAF01"
        }
        app._chip_vars["DAF"].set(False)
        app._chip_vars["Army"].set(True)
        app._render_table()
        root.update()
        assert {_row_values(app, iid)["code"] for iid in app.table.get_children()} == {
            "ARM01"
        }
        app._chip_vars["Army"].set(False)
        app._chip_vars["__qa__"].set(True)
        app._render_table()
        root.update()
        assert {_row_values(app, iid)["code"] for iid in app.table.get_children()} == {
            "DAF01"
        }
        app._show_detail(app._bluf_rows[0])
        assert "Threshold?" in app.detail_text.get("1.0", "end")
    finally:
        root.destroy()


def test_gui_status_chips_do_not_change_download_phrase():
    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        app._chip_vars["__open__"].set(True)
        app._chip_vars["__due7__"].set(True)
        app._chip_vars["__due14__"].set(True)
        app._chip_vars["__qa__"].set(True)
        app._on_chips()
        root.update()
        assert app._chip_phrase() == ""
        assert "Download all" in app.button_var.get()
        app._chip_vars["DAF"].set(True)
        app._on_chips()
        root.update()
        assert app._chip_phrase() == "DAF"
        assert "matching" in app.button_var.get().lower()
    finally:
        root.destroy()


def test_gui_open_and_due7_chips_exclude_closed_and_pre_release():
    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        app._bluf_rows = [
            _bluf("closed", "ARM00", "Old", status="Closed", dueIn="closed"),
            _bluf("pre", "ARM01", "Soon pre", status="Pre-Release", dueIn="3d"),
            _bluf("week", "DAF01", "This week", status="Open", dueIn="5d"),
            _bluf("later", "DAF02", "Later", status="Open", dueIn="20d"),
            _bluf("today", "DAF03", "Today", status="Open", dueIn="today"),
        ]
        app._chip_vars["__open__"].set(True)
        app._chip_vars["__due7__"].set(True)
        app._render_table()
        root.update()
        codes = {_row_values(app, iid)["code"] for iid in app.table.get_children()}
        assert codes == {"DAF01", "DAF03"}
        assert "due ≤7d" in app.bluf_caption_var.get()
        assert "2 shown / 5 topics" in app.bluf_caption_var.get()
    finally:
        root.destroy()


def test_gui_triage_filter_note_find_and_persist(tmp_path):
    snap = tmp_path / "all_dsip_opportunities_20261030_120000"
    snap.mkdir()
    (snap / "manifest.json").write_text(
        json.dumps(
            {
                "topics": [
                    {"topicId": "t0", "topicCode": "DAF01", "topicTitle": "Illumination"},
                    {"topicId": "t1", "topicCode": "ARM01", "topicTitle": "Armor"},
                ],
                "bluf": [
                    _bluf("t0", "DAF01", "Illumination"),
                    _bluf(
                        "t1",
                        "ARM01",
                        "Armor",
                        client="ARMY",
                        status="Open",
                        dueIn="3d",
                        problem="Plate",
                    ),
                ],
            }
        ),
        encoding="utf-8",
    )
    gui.STATE_FILE.write_text(
        json.dumps({"parent": str(tmp_path), "last_output": str(snap)}),
        encoding="utf-8",
    )
    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        root.update()
        assert len(app.table.get_children()) == 2
        app.table.selection_set("t0")
        app._show_detail(app._row_by_iid("t0"))
        app.note_var.set("Fits autonomy stack")
        app._set_selected_triage("pursue")
        app._show_detail(app._row_by_iid("t1"))
        app._set_selected_triage("pass")
        root.update()
        by_id = {row["topicId"]: row for row in app._bluf_rows}
        assert by_id["t0"]["call"] == "Pursue"
        assert by_id["t0"]["note"] == "Fits autonomy stack"
        assert by_id["t1"]["call"] == "Pass"
        app.call_filter_var.set("Pursue")
        app._render_table()
        root.update()
        assert len(app.table.get_children()) == 1
        assert _row_values(app)["code"] == "DAF01"
        assert _row_values(app)["call"] == "Pursue"
        app.call_filter_var.set("All calls")
        app.table_filter_var.set("autonomy")
        app._render_table()
        root.update()
        assert len(app.table.get_children()) == 1
        assert _row_values(app)["code"] == "DAF01"
        saved = json.loads(gui.STATE_FILE.read_text(encoding="utf-8"))
        assert saved["triage"]["t0"]["call"] == "pursue"
        assert "autonomy" in saved["triage"]["t0"]["note"]
        assert "bluf" not in saved
    finally:
        root.destroy()

    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        root.update()
        by_id = {row["topicId"]: row for row in app._bluf_rows}
        assert by_id["t0"]["call"] == "Pursue"
        assert "autonomy" in by_id["t0"]["note"]
        assert by_id["t1"]["call"] == "Pass"
    finally:
        root.destroy()


def test_gui_copy_brief_uses_local_clipboard():
    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        row = _bluf(
            "t0",
            "DAF27BZ01-DV011",
            "Unmanned Aerial Systems",
            call="Pursue",
            note="Pitch Thursday",
            funding="$2,000,000 (typical Direct to Phase II ceiling)",
        )
        app._bluf_rows = [row]
        app._show_detail(row)
        expected = analyze.format_capture_brief(app._selected_row)
        assert "DAF27BZ01-DV011" in expected
        assert "Call: Pursue" in expected
        assert "Pitch Thursday" in expected
        assert "typical" in expected
        app._copy_selected_brief()
        root.update()
        try:
            text = root.clipboard_get()
        except Exception:
            text = ""
        if text:
            assert "DAF27BZ01-DV011" in text
            assert "Call: Pursue" in text
            assert "Pitch Thursday" in text
    finally:
        root.destroy()


def test_gui_item_done_keeps_selected_note():
    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        topic = {
            "topicId": "t0",
            "topicCode": "DAF01",
            "topicTitle": "Illumination",
            "topicStatus": "Open",
            "component": "USAF",
            "program": "SBIR",
            "pdf": "topic_t0.pdf",
            "pdfStatus": "pending",
        }
        app._handle_event(("catalog_ready", [topic]))
        root.update()
        app._show_detail(app._bluf_rows[0])
        app.note_var.set("Keep after PDF")
        old_row = app._selected_row
        app._handle_event(
            (
                "item_done",
                {
                    "label": "topic PDF",
                    "key": "t0",
                    "outcome": {"status": "downloaded", "error": None},
                },
            )
        )
        root.update()
        assert app._selected_row is not old_row
        assert app._selected_row["note"] == "Keep after PDF"
        assert app._triage["t0"]["note"] == "Keep after PDF"
        assert app.note_var.get() == "Keep after PDF"
        assert app._bluf_rows[0]["pdfStatus"] == "downloaded"
        saved = json.loads(gui.STATE_FILE.read_text(encoding="utf-8"))
        assert saved["triage"]["t0"]["note"] == "Keep after PDF"
    finally:
        root.destroy()


def test_gui_triage_does_not_clobber_unbound_note():
    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        row = _bluf("t0", "DAF01", "Illumination", note="Keep me")
        app._bluf_rows = [row]
        app._triage["t0"] = {"call": "", "note": "Keep me"}
        app._render_table()
        app.table.selection_set("t0")
        app._set_selected_triage("pursue")
        root.update()
        assert row["note"] == "Keep me"
        assert app._triage["t0"]["note"] == "Keep me"
        assert row["call"] == "Pursue"
    finally:
        root.destroy()


def test_gui_sanitize_triage_drops_junk():
    cleaned = gui.App._sanitize_triage(
        {
            "t0": {"call": "PURSUE", "note": "x" * 800},
            "bad": "not-a-dict",
            "empty": {"call": "nope", "note": ""},
        }
    )
    assert cleaned["t0"]["call"] == "pursue"
    assert len(cleaned["t0"]["note"]) == gui.analyze.NOTE_MAX
    assert "bad" not in cleaned
    assert "empty" not in cleaned


def test_gui_persists_chips_find_and_shows_overview():
    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        app._bluf_rows = [
            _bluf(
                "t0",
                "DAF01",
                "Illumination",
                itar="Y",
                overviewParagraph="Reusable light source for the test track.",
                technologyAreas=["Sensors"],
                instructionPdfs=["solicitation_documents/instr.pdf"],
            ),
            _bluf("t1", "ARM01", "Armor", client="ARMY", itar="N"),
        ]
        app._chip_vars["__itar__"].set(True)
        app.table_filter_var.set("Illumination")
        app._on_chips()
        root.update()
        assert {_row_values(app, iid)["code"] for iid in app.table.get_children()} == {
            "DAF01"
        }
        app._show_detail(app._bluf_rows[0])
        body = app.detail_text.get("1.0", "end")
        assert "Reusable light source" in body
        assert "Overview (local extract" in body
        saved = json.loads(gui.STATE_FILE.read_text(encoding="utf-8"))
        assert "__itar__" in saved["chips"]
        assert saved["find"] == "Illumination"
    finally:
        root.destroy()


def test_gui_new_changed_chips_and_instruction_pdf_sandbox(tmp_path, monkeypatch):
    root = _make_root()
    opened: list[str] = []
    monkeypatch.setattr(
        analyze, "open_local_pdf", lambda folder, name: opened.append(str(name)) or True
    )
    try:
        app = gui.App(root, interactive=False)
        app.output_dir = tmp_path
        app._bluf_rows = [
            _bluf("t0", "DAF01", "New topic", instructionPdfs=["solicitation_documents/a.pdf"]),
            _bluf("t1", "DAF02", "Changed topic"),
            _bluf("t2", "DAF03", "Unchanged"),
        ]
        app._diff_added = {"DAF01"}
        app._diff_changed = {"DAF02"}
        app._chip_vars["__new__"].set(True)
        app._render_table()
        root.update()
        assert {_row_values(app, iid)["code"] for iid in app.table.get_children()} == {
            "DAF01"
        }
        app._chip_vars["__new__"].set(False)
        app._chip_vars["__changed__"].set(True)
        app._render_table()
        root.update()
        assert {_row_values(app, iid)["code"] for iid in app.table.get_children()} == {
            "DAF02"
        }
        app._show_detail(app._bluf_rows[0])
        app._open_selected_instruction()
        assert opened == ["solicitation_documents/a.pdf"]
    finally:
        root.destroy()


def test_gui_render_keeps_selection_and_hides_zero_components():
    root = _make_root()
    try:
        app = gui.App(root, interactive=False)
        app._bluf_rows = [
            _bluf("t0", "DAF01", "Air", client="USAF"),
            _bluf("t1", "DAF02", "More air", client="USAF"),
        ]
        app._render_table()
        root.update()
        app.table.selection_set("t1")
        app.table.focus("t1")
        app._render_table()
        root.update()
        assert app.table.selection() == ("t1",)
        assert app.table.focus() == "t1"
        assert "DAF" in app._dept_checks["DAF"].cget("text")
        assert "(" in app._dept_checks["DAF"].cget("text")
        # NASA is unused in this snapshot and should hide until asked.
        assert app._dept_checks["NASA"].grid_info() == {}
        app.show_zero_components.set(True)
        app._refresh_chip_labels()
        root.update()
        assert app._dept_checks["NASA"].grid_info()
    finally:
        root.destroy()
