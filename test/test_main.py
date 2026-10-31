"""Tests for the DSIP open-topics downloader. Network calls are stubbed."""

import json
from datetime import datetime, timezone

import main


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        current = cls(2026, 10, 21, 21, 44, 5)
        if tz is not None:
            return current.replace(tzinfo=tz)
        return current


class FakeResponse:
    def __init__(self, payload: bytes, max_chunk: int | None = None):
        self._payload = payload
        self._offset = 0
        self._max_chunk = max_chunk

    def read(self, size=-1):
        remaining = self._payload[self._offset :]
        if size is None or size < 0:
            chunk = remaining
        else:
            limit = size if self._max_chunk is None else min(size, self._max_chunk)
            chunk = remaining[:limit]
        self._offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def topic(index, **extra):
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


def test_safe_filename_replaces_windows_reserved_characters():
    cleaned = main.safe_filename('xTech|Search: "10" <final>?.pdf')
    assert "|" not in cleaned
    assert ":" not in cleaned
    assert '"' not in cleaned
    assert "<" not in cleaned
    assert ">" not in cleaned
    assert "?" not in cleaned
    assert cleaned.endswith(".pdf")


def test_topic_pdf_name_uses_code_and_shortens_long_titles():
    named = main.topic_pdf_name(
        {"topicCode": "DAF27BZ01-NV005", "topicTitle": "A" * 150}
    )
    assert named.startswith("topic_DAF27BZ01-NV005_")
    assert named.endswith(".pdf")
    title = named.removeprefix("topic_DAF27BZ01-NV005_").removesuffix(".pdf")
    assert len(title) == 100


def test_assign_topic_names_disambiguates_collisions():
    topics = [
        {"topicId": "aaaaaaaaaaaa111", "topicCode": "SAME", "topicTitle": "Shared"},
        {"topicId": "bbbbbbbbbbbb222", "topicCode": "SAME", "topicTitle": "Shared"},
    ]
    names = main.assign_topic_names(topics)
    assert names["aaaaaaaaaaaa111"] == "topic_SAME_Shared.pdf"
    assert names["bbbbbbbbbbbb222"] != names["aaaaaaaaaaaa111"]
    assert "bbbbbbbb" in names["bbbbbbbbbbbb222"]


def test_epoch_ms_to_iso_converts_milliseconds():
    assert main.epoch_ms_to_iso(1780488000000) == datetime.fromtimestamp(
        1780488000, tz=timezone.utc
    ).isoformat()
    assert main.epoch_ms_to_iso(None) is None


def test_default_output_directory_is_timestamped(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(main, "datetime", FrozenDateTime)

    first = main.default_output_dir()
    assert first == tmp_path / "all_dsip_opportunities_20261021_214405"
    first.mkdir()

    second = main.default_output_dir()
    assert second.name == "all_dsip_opportunities_20261021_214405_2"


def test_search_page_asks_for_one_hundred_records(monkeypatch):
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"total": 0, "data": []}

    monkeypatch.setattr(main, "fetch_json", fake_fetch)
    main.search_page(2)

    assert "size=100" in captured["url"]
    assert "page=2" in captured["url"]
    assert "openTopics" in captured["url"]


def test_fetch_all_topics_continues_after_a_short_page(monkeypatch):
    monkeypatch.setattr(main, "REQUEST_PAUSE_SECONDS", 0)
    pages = {
        0: {"total": 25, "data": [topic(i) for i in range(10)]},
        1: {"total": 25, "data": [topic(i) for i in range(10, 20)]},
        2: {"total": 25, "data": [topic(i) for i in range(20, 25)]},
    }
    monkeypatch.setattr(main, "search_page", lambda page: pages[page])

    topics, total = main.fetch_all_topics()

    assert total == 25
    assert [item["topicId"] for item in topics] == [f"topic{i}" for i in range(25)]


def test_fetch_all_topics_keeps_paging_when_a_page_is_full(monkeypatch):
    monkeypatch.setattr(main, "REQUEST_PAUSE_SECONDS", 0)
    requested = []

    def fake_search(page):
        requested.append(page)
        if page == 0:
            return {"total": 150, "data": [topic(i) for i in range(100)]}
        if page == 1:
            return {"total": 150, "data": [topic(i) for i in range(100, 150)]}
        return {"total": 150, "data": []}

    monkeypatch.setattr(main, "search_page", fake_search)
    topics, total = main.fetch_all_topics()

    assert requested == [0, 1]
    assert total == 150
    assert len(topics) == 150


def test_download_pdf_rejects_non_pdf_and_removes_partial(monkeypatch, tmp_path):
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        main,
        "open_url",
        lambda url, timeout: FakeResponse(b"<html>denied</html>"),
    )
    dest = tmp_path / "topic.pdf"

    try:
        main.download_pdf("https://example.test/bad", dest)
    except RuntimeError as exc:
        assert "Expected a PDF" in str(exc)
    else:
        raise AssertionError("non-PDF response was saved")

    assert not dest.exists()
    assert list(tmp_path.glob("*.part")) == []


def test_download_pdf_retries_a_transient_empty_response(monkeypatch, tmp_path):
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def flaky_open(url, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResponse(b"")  # transient empty 200
        return FakeResponse(b"%PDF-1.7\nbody")

    monkeypatch.setattr(main, "open_url", flaky_open)
    dest = tmp_path / "topic.pdf"
    assert main.download_pdf("https://example.test/flaky", dest) == "downloaded"
    assert calls["n"] == 2
    assert dest.read_bytes().startswith(b"%PDF-")


def test_download_pdf_skips_an_existing_valid_pdf(tmp_path):
    dest = tmp_path / "topic.pdf"
    dest.write_bytes(b"%PDF-1.7\nexisting")

    status = main.download_pdf("https://example.test/unused", dest)

    assert status == "skipped"
    assert dest.read_bytes().startswith(b"%PDF-")


def test_solicitation_documents_reads_preface_and_instructions():
    documents = main.solicitation_documents(
        {
            "baaPrefaceUploadId": 10,
            "baaPrefaceUploadTitle": "Preface.pdf",
            "baaInstructions": [
                {"uploadId": 20, "fileName": "Army.pdf"},
                {"uploadId": None, "fileName": "ignored.pdf"},
            ],
        }
    )
    assert documents == [
        {"upload_id": 10, "file_name": "Preface.pdf", "kind": "preface"},
        {"upload_id": 20, "file_name": "Army.pdf", "kind": "instructions"},
    ]


def test_run_downloads_every_topic_across_short_pages(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "REQUEST_PAUSE_SECONDS", 0)
    shared = {
        "baaPrefaceUploadId": 1805441,
        "baaPrefaceUploadTitle": "DoW Preface.pdf",
        "baaInstructions": [{"uploadId": 1758532, "fileName": "ARMY_26BX_R3"}],
    }
    pages = {
        0: {"total": 3, "data": [topic(0, **shared), topic(1, **shared)]},
        1: {
            "total": 3,
            "data": [
                topic(
                    2,
                    baaPrefaceUploadId=1805445,
                    baaPrefaceUploadTitle="DoW Preface.pdf",
                )
            ],
        },
    }
    monkeypatch.setattr(main, "search_page", lambda page: pages[page])

    def fake_open(url, timeout):
        return FakeResponse(b"%PDF-1.4\n" + url.encode("ascii"))

    monkeypatch.setattr(main, "open_url", fake_open)

    assert main.run(tmp_path) == 0

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["apiTotal"] == 3
    assert manifest["topicsRetrieved"] == 3
    assert manifest["topicPdfsDownloaded"] == 3
    assert manifest["failures"] == []
    saved_pdfs = list(tmp_path.glob("topic_*.pdf"))
    assert len(saved_pdfs) == 3
    solicitation = list((tmp_path / "solicitation_documents").glob("*.pdf"))
    assert len(solicitation) == 3
    names = sorted(path.name for path in solicitation)
    assert "ARMY_26BX_R3.pdf" in names
    assert any(name.startswith("DoW Preface_") for name in names)


def test_run_exits_with_failure_when_the_catalog_is_short(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "REQUEST_PAUSE_SECONDS", 0)
    pages = {
        0: {"total": 3, "data": [topic(0)]},
        1: {"total": 3, "data": []},
    }
    monkeypatch.setattr(main, "search_page", lambda page: pages[page])
    monkeypatch.setattr(
        main,
        "open_url",
        lambda url, timeout: FakeResponse(b"%PDF-1.4\n"),
    )

    assert main.run(tmp_path) == 1
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["topicsRetrieved"] == 1
    assert manifest["apiTotal"] == 3
    assert any(item["kind"] == "catalog" for item in manifest["failures"])


def test_main_writes_to_the_requested_directory(monkeypatch, tmp_path):
    captured = {}

    def fake_run(output_dir, workers=None, reporter=None, search_phrase=""):
        captured["output_dir"] = output_dir
        captured["workers"] = workers
        return 0 if output_dir == tmp_path.resolve() else 1

    monkeypatch.setattr(main, "run", fake_run)
    assert main.main(["--output", str(tmp_path), "--workers", "7"]) == 0
    assert captured["workers"] == 7


def test_default_workers_is_bounded(monkeypatch):
    monkeypatch.setattr(main.os, "cpu_count", lambda: 1)
    assert main.default_workers() == 5
    monkeypatch.setattr(main.os, "cpu_count", lambda: None)
    assert main.default_workers() == 20
    monkeypatch.setattr(main.os, "cpu_count", lambda: 100)
    assert main.default_workers() == 64
    monkeypatch.setattr(main.os, "cpu_count", lambda: 8)
    assert main.default_workers() == 40


def test_read_exactly_handles_short_reads():
    response = FakeResponse(b"%PDF-1.7 body", max_chunk=1)
    assert main._read_exactly(response, 5) == b"%PDF-"


def test_download_pdf_accepts_a_pdf_delivered_in_tiny_chunks(monkeypatch, tmp_path):
    monkeypatch.setattr(
        main,
        "open_url",
        lambda url, timeout: FakeResponse(b"%PDF-1.7\n" + b"x" * 100, max_chunk=1),
    )
    dest = tmp_path / "topic.pdf"
    assert main.download_pdf("https://example.test/ok", dest) == "downloaded"
    assert dest.read_bytes().startswith(b"%PDF-")


def test_plan_topic_tasks_presets_failure_for_bad_topic_id(tmp_path):
    topics = [topic(0, topicId="bad id with spaces"), topic(1)]
    names = main.assign_topic_names(topics)
    tasks, preset = main.plan_topic_tasks(topics, names, tmp_path)
    assert [task.key for task in tasks] == ["topic1"]
    assert preset["bad id with spaces"]["status"] == "failed"


def test_download_tasks_runs_concurrently_and_records_failures(monkeypatch, tmp_path):
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)

    def fake_open(url, timeout):
        if "bad" in url:
            return FakeResponse(b"<html>denied</html>")
        return FakeResponse(b"%PDF-1.4\n" + url.encode("ascii"))

    monkeypatch.setattr(main, "open_url", fake_open)
    tasks = [
        main.DownloadTask(key="ok", url="https://x/ok", dest=tmp_path / "ok.pdf", describe="ok"),
        main.DownloadTask(key="bad", url="https://x/bad", dest=tmp_path / "bad.pdf", describe="bad"),
    ]
    results = main.download_tasks(tasks, workers=8, label="test")
    assert results["ok"]["status"] == "downloaded"
    assert results["bad"]["status"] == "failed"
    assert (tmp_path / "ok.pdf").exists()
    assert not (tmp_path / "bad.pdf").exists()


def test_run_records_worker_count_in_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "REQUEST_PAUSE_SECONDS", 0)
    monkeypatch.setattr(
        main, "search_page", lambda page: {"total": 1, "data": [topic(0)]} if page == 0 else {"total": 1, "data": []}
    )
    monkeypatch.setattr(main, "open_url", lambda url, timeout: FakeResponse(b"%PDF-1.4\n"))
    assert main.run(tmp_path, workers=3) == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["workers"] == 3
    assert isinstance(manifest["downloadSeconds"], (int, float))
    assert isinstance(manifest["totalSeconds"], (int, float))
    assert manifest["totalSeconds"] >= manifest["downloadSeconds"]


def test_format_duration_switches_units():
    assert main.format_duration(0) == "0.0s"
    assert main.format_duration(12.34) == "12.3s"
    assert main.format_duration(75) == "1m 15.0s"
    assert main.format_duration(3725).startswith("1h 02m")


def test_format_clock_minutes_and_hours():
    assert main.format_clock(0) == "00:00"
    assert main.format_clock(65) == "01:05"
    assert main.format_clock(3661) == "1:01:01"


def test_progress_bar_counts_and_closes(capsys):
    bar = main.ProgressBar(total=2, label="test")
    bar.update(1)
    bar.write("a note")
    bar.update(1)
    bar.close()
    assert bar.count == 2
    out = capsys.readouterr().out
    assert "test" in out
    assert "a note" in out
    assert "2/2" in out


def test_fetch_topic_questions_rejects_invalid_id(monkeypatch):
    called = {"n": 0}

    def boom(url, timeout):
        called["n"] += 1
        raise AssertionError(f"open_url must not run for invalid ids: {url}")

    monkeypatch.setattr(main, "open_url", boom)
    for bad in ("../secret", "topic id", "", "%2e%2e", "a/b"):
        try:
            main.fetch_topic_questions(bad)
        except RuntimeError as exc:
            assert "invalid topic id" in str(exc).lower()
        else:
            raise AssertionError(f"expected invalid topic id to fail for {bad!r}")
    assert called["n"] == 0


def test_save_published_questions_writes_json(tmp_path, monkeypatch):
    items = [
        {
            "questionId": 1,
            "question": "<p>Threshold?</p>",
            "answers": [{"answer": '{"content":"<p>220VAC</p>","length":6}'}],
        }
    ]
    monkeypatch.setattr(main, "fetch_topic_questions", lambda _tid: items)
    topics = [
        topic(0, noOfPublishedQuestions=2),
        topic(1, noOfPublishedQuestions=0),
    ]
    saved = main.save_published_questions(topics, tmp_path)
    assert saved == 1
    qa_path = tmp_path / "qa" / "ARM26BX00.json"
    assert qa_path.is_file()
    assert topics[0]["qaFile"] == "qa/ARM26BX00.json"
    assert "Threshold?" in topics[0]["qaExcerpt"]
    assert topics[1].get("qaFile") in (None, "")
