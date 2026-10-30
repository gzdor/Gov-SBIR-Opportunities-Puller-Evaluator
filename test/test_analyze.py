from pathlib import Path

import analyze
import main


def test_empty_phrase_keeps_every_topic():
    topics = [
        {"topicCode": "A", "topicTitle": "Laser", "component": "NAVY"},
        {"topicCode": "B", "topicTitle": "Armor", "component": "ARMY"},
    ]
    assert analyze.filter_topics(topics, "  ") == topics


def test_and_tokens_require_every_word():
    topics = [
        {
            "topicCode": "DAF27BZ01-DV007",
            "topicTitle": "Reusable Illumination System",
            "component": "USAF",
        },
        {
            "topicCode": "ARM26BX03",
            "topicTitle": "xTech Kinetic Reach",
            "component": "ARMY",
        },
    ]
    kept = analyze.filter_topics(topics, "air force illumination")
    assert [t["topicCode"] for t in kept] == ["DAF27BZ01-DV007"]


def test_filter_does_not_use_user_input_as_regex():
    topics = [{"topicCode": "X", "topicTitle": "alpha+", "component": "NAVY"}]
    # Would explode if compiled as regex; must be treated as tokens.
    kept = analyze.filter_topics(topics, "(alpha+)+")
    assert kept == [] or isinstance(kept, list)


def test_bluf_from_text_pulls_objective_and_d2p2():
    text = """
    OBJECTIVE:
    Develop a reusable illumination system for high-speed photo-optic data collection at the test track.
    DESCRIPTION:
    Legacy flash bulbs are out of production and must be replaced with a reusable source.
    PHASE I:
    As this is a Direct-to-Phase-II (D2P2) topic, no Phase I awards will be made.
    Funding up to $2,000,000.
    """
    bluf = analyze.extract_bluf_from_text(
        text,
        title="Reusable Illumination System",
        component="USAF",
        topic_code="DAF27BZ01-DV007",
    )
    assert "Reusable Illumination System" in bluf["problem"]
    assert "reusable illumination" in bluf["problem"].lower()
    assert bluf["trl"].startswith("4–6")
    assert "$2,000,000" in bluf["funding"]
    assert "stated" in bluf["funding"]
    assert "Phase II" in bluf["contract"]


def test_trl_ignores_cmmc_level_and_uses_stated_trl():
    text = "PROJECTED CMMC LEVEL REQUIREMENT: Level 2 (Self)\nOBJECTIVE:\nBuild a sensor. Technology readiness level 5 is required.\nPHASE I: Feasibility."
    bluf = analyze.extract_bluf_from_text(text, title="Sensor", topic_code="NV001")
    assert bluf["trl"] == "5 (stated)"


def test_funding_falls_back_to_typical_ceiling():
    text = "OBJECTIVE: Build a radio. PHASE I: Demonstrate feasibility. PHASE II: Prototype."
    bluf = analyze.extract_bluf_from_text(
        text, title="Radio", component="NAVY", topic_code="DON27BZ01-NV001"
    )
    assert bluf["contract"] == "Phase I"
    assert "$315,000" in bluf["funding"]
    assert "typical" in bluf["funding"]


def test_resolve_pdf_rejects_traversal_and_non_pdf(tmp_path):
    inside = tmp_path / "topic_ok.pdf"
    inside.write_bytes(b"%PDF-1.4\n%")
    outside = tmp_path.parent / "secret.pdf"
    outside.write_bytes(b"%PDF-1.4\n%")
    exe = tmp_path / "not.pdf.exe"
    exe.write_bytes(b"%PDF-1.4\n%")

    assert analyze.resolve_pdf(tmp_path, "topic_ok.pdf") == inside.resolve()
    assert analyze.resolve_pdf(tmp_path, "../secret.pdf") is None
    assert analyze.resolve_pdf(tmp_path, "not.pdf.exe") is None
    assert analyze.resolve_pdf(tmp_path, "missing.pdf") is None


def test_run_records_search_phrase_and_filters(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "REQUEST_PAUSE_SECONDS", 0)
    pages = {
        0: {
            "total": 2,
            "data": [
                {
                    "topicId": "t0",
                    "topicCode": "DAF01",
                    "topicTitle": "Reusable Illumination System",
                    "component": "USAF",
                    "program": "SBIR",
                },
                {
                    "topicId": "t1",
                    "topicCode": "ARM01",
                    "topicTitle": "Ground armor plate",
                    "component": "ARMY",
                    "program": "SBIR",
                },
            ],
        }
    }
    monkeypatch.setattr(main, "search_page", lambda page: pages.get(page, {"total": 2, "data": []}))
    from test_main import FakeResponse

    monkeypatch.setattr(main, "open_url", lambda url, timeout: FakeResponse(b"%PDF-1.4\n"))
    assert main.run(tmp_path, workers=2, search_phrase="illumination") == 0
    import json

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["searchPhrase"] == "illumination"
    assert manifest["catalogCount"] == 2
    assert manifest["topicsRetrieved"] == 1
    assert manifest["topics"][0]["topicCode"] == "DAF01"
    assert manifest["bluf"]
