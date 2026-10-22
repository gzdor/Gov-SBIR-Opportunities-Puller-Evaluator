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
    def __init__(self, payload: bytes):
        self._payload = payload
        self._offset = 0

    def read(self, size=-1):
        remaining = self._payload[self._offset :]
        if size is None or size < 0:
            chunk = remaining
        else:
            chunk = remaining[:size]
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
    assert not dest.with_name(dest.name + ".part").exists()


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
    monkeypatch.setattr(main, "run", lambda output_dir: 0 if output_dir == tmp_path.resolve() else 1)
    assert main.main(["--output", str(tmp_path)]) == 0
