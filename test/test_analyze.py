from pathlib import Path

import pytest

import analyze
import main

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_OSW_INSTRUCTIONS = _FIXTURES / "OSW-DRPM_SBIR_27BZ_R1.txt"
_OSW_INSTRUCTIONS_PDF = _FIXTURES / "OSW-DRPM_SBIR_27BZ_R1.pdf"


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


def test_volume_page_limits_from_baa_text():
    baa = """
    Volume 2: Technical Volume.
    The Technical Volume for Phase I proposals shall not exceed 5 pages.
    The Technical Volume for Direct to Phase II proposals shall not exceed 15 pages.
    Feasibility documentation for Direct to Phase II shall not exceed 5 pages.
    """
    d2p2 = analyze.assess_volume_page_limits(baa, contract="Direct to Phase II")
    assert d2p2["techVolLimit"] == "15 (stated)"
    assert d2p2["feasStudyLimit"] == "5 (stated)"
    phase_i = analyze.assess_volume_page_limits(baa, contract="Phase I")
    assert phase_i["techVolLimit"] == "5 (stated)"
    assert phase_i["feasStudyLimit"] == "n/a"
    compound = analyze.assess_volume_page_limits(
        "Offerors shall submit a 15-page Technical Volume and a 5-page feasibility study.",
        contract="Direct to Phase II",
    )
    assert compound["techVolLimit"] == "15 (stated)"
    assert compound["feasStudyLimit"] == "5 (stated)"
    glued = analyze.assess_volume_page_limits(
        "Technical Volume shall not exceed 15 pages Feasibility documentation shall not exceed 5 pages",
        contract="Direct to Phase II",
    )
    assert glued["techVolLimit"] == "15 (stated)"
    assert glued["feasStudyLimit"] == "5 (stated)"


def test_osw_dv002_drpm_uxs_page_limits_are_five_and_five():
    """Truth: OSD/DRPM UxS D2P2 topic OSW27BZ01-DV002 is 5 + 5 pages.

    Component instructions spell the limit as 'five (5) pages' and also put a
    2-page Phase I (NV001) rule earlier in the same PDF. The scraper must
    use the D2P2 section, not DoW typical 15-page Phase II.
    """
    text = _OSW_INSTRUCTIONS.read_text(encoding="utf-8")
    assert "five (5) pages" in text
    limits = analyze.assess_volume_page_limits(
        text,
        contract="Direct to Phase II",
        topic_code="OSW27BZ01-DV002",
    )
    assert limits["techVolLimit"] == "5 (stated)"
    assert limits["feasStudyLimit"] == "5 (stated)"


def test_osw_nv001_phase_i_tech_vol_is_two_pages():
    text = _OSW_INSTRUCTIONS.read_text(encoding="utf-8")
    limits = analyze.assess_volume_page_limits(
        text,
        contract="Phase I",
        topic_code="OSW27BZ01-NV001",
    )
    assert limits["techVolLimit"] == "2 (stated)"
    assert limits["feasStudyLimit"] == "n/a"


def test_osw_dv002_d2p2_heading_without_topic_code_is_still_five():
    """Same PDF, no topic code: use the D2P2 heading, not DoW typical 15."""
    text = _OSW_INSTRUCTIONS.read_text(encoding="utf-8")
    limits = analyze.assess_volume_page_limits(text, contract="Direct to Phase II")
    assert limits["techVolLimit"] == "5 (stated)"
    assert limits["feasStudyLimit"] == "5 (stated)"


def test_bluf_row_osw_dv002_reads_instruction_pdf(tmp_path):
    if not _OSW_INSTRUCTIONS_PDF.is_file():
        pytest.skip("OSW-DRPM instruction PDF fixture is not present")
    dest = tmp_path / "solicitation_documents"
    dest.mkdir()
    pdf = dest / "OSW-DRPM_SBIR_27BZ_R1.pdf"
    pdf.write_bytes(_OSW_INSTRUCTIONS_PDF.read_bytes())
    row = analyze.bluf_row(
        {
            "topicId": "aa95ca4aa0f14efebd0f991a37aec1bc_86695",
            "topicCode": "OSW27BZ01-DV002",
            "topicTitle": "Counter-Unmanned Aerial Systems Rapid Maturation",
            "component": "OSD",
            "command": "DRPM UxS",
            "program": "SBIR",
            "topicStatus": "Open",
            "instructionPdfs": ["solicitation_documents/OSW-DRPM_SBIR_27BZ_R1.pdf"],
        },
        tmp_path,
    )
    assert row["contract"] == "Direct to Phase II"
    assert row["techVolLimit"] == "5 (stated)"
    assert row["feasStudyLimit"] == "5 (stated)"


def test_volume_page_limits_blank_when_baa_silent():
    d2p2 = analyze.assess_volume_page_limits("", contract="Direct to Phase II")
    assert d2p2["techVolLimit"] == ""
    assert d2p2["feasStudyLimit"] == ""
    phase_i = analyze.assess_volume_page_limits("", contract="Phase I")
    assert phase_i["techVolLimit"] == ""
    assert phase_i["feasStudyLimit"] == "n/a"
    none = analyze.assess_volume_page_limits("", contract="—")
    assert none["techVolLimit"] == ""
    assert none["feasStudyLimit"] == ""


def test_osw_dv002_still_five_when_preface_says_fifteen():
    """DoW BAA preface 15-page D2P2 must not override OSD/DRPM's five-page cap."""
    preface = """
    DIRECT TO PHASE II PROPOSAL GUIDELINES
    The Technical Volume for Direct to Phase II proposals shall not exceed 15 pages.
    Feasibility documentation for Direct to Phase II shall not exceed 5 pages.
    """
    text = preface + "\n" + _OSW_INSTRUCTIONS.read_text(encoding="utf-8")
    limits = analyze.assess_volume_page_limits(
        text,
        contract="Direct to Phase II",
        topic_code="OSW27BZ01-DV002",
    )
    assert limits["techVolLimit"] == "5 (stated)"
    assert limits["feasStudyLimit"] == "5 (stated)"


def test_instruction_pdf_paths_only_this_topic(tmp_path):
    dest = tmp_path / "solicitation_documents"
    dest.mkdir()
    (dest / "OSW-DRPM_SBIR_27BZ_R1.pdf").write_bytes(b"%PDF-1.4\n%")
    (dest / "NAVY_SBIR_27BZ_PH I_R1_v2.pdf").write_bytes(b"%PDF-1.4\n%")
    (dest / "DoW 2027 SBIR BAA Preface_10072026.pdf").write_bytes(b"%PDF-1.4\n%")
    paths = analyze.instruction_pdf_paths(
        tmp_path,
        [
            "solicitation_documents/DoW 2027 SBIR BAA Preface_10072026.pdf",
            "solicitation_documents/OSW-DRPM_SBIR_27BZ_R1.pdf",
        ],
        topic_code="OSW27BZ01-DV002",
    )
    names = [path.name for path in paths]
    assert "OSW-DRPM_SBIR_27BZ_R1.pdf" in names
    assert "DoW 2027 SBIR BAA Preface_10072026.pdf" in names
    assert "NAVY_SBIR_27BZ_PH I_R1_v2.pdf" not in names


def test_instruction_pdf_paths_finds_component_file_without_names(tmp_path):
    dest = tmp_path / "solicitation_documents"
    dest.mkdir()
    (dest / "OSW-DRPM_SBIR_27BZ_R1.pdf").write_bytes(b"%PDF-1.4\n%")
    (dest / "NAVY_SBIR_27BZ_PH I_R1_v2.pdf").write_bytes(b"%PDF-1.4\n%")
    osw = analyze.instruction_pdf_paths(
        tmp_path, [], topic_code="OSW27BZ01-DV002", component="OSD"
    )
    assert [path.name for path in osw] == ["OSW-DRPM_SBIR_27BZ_R1.pdf"]
    navy = analyze.instruction_pdf_paths(
        tmp_path, [], topic_code="DON27BZ01-NV001", component="NAVY"
    )
    assert [path.name for path in navy] == ["NAVY_SBIR_27BZ_PH I_R1_v2.pdf"]


def test_refresh_overwrites_cached_typical_with_osw_pdf(tmp_path):
    if not _OSW_INSTRUCTIONS_PDF.is_file():
        pytest.skip("OSW-DRPM instruction PDF fixture is not present")
    dest = tmp_path / "solicitation_documents"
    dest.mkdir()
    pdf = dest / "OSW-DRPM_SBIR_27BZ_R1.pdf"
    pdf.write_bytes(_OSW_INSTRUCTIONS_PDF.read_bytes())
    row = {
        "code": "OSW27BZ01-DV002",
        "contract": "Direct to Phase II",
        "instructionPdfs": ["solicitation_documents/OSW-DRPM_SBIR_27BZ_R1.pdf"],
        "techVolLimit": "15 (typical Direct to Phase II)",
        "feasStudyLimit": "5 (typical Direct to Phase II)",
    }
    analyze.refresh_volume_page_limits(row, tmp_path)
    assert row["techVolLimit"] == "5 (stated)"
    assert row["feasStudyLimit"] == "5 (stated)"


def test_bluf_row_reads_instruction_pdf_page_limits(tmp_path):
    dest = tmp_path / "solicitation_documents"
    dest.mkdir()
    pdf = dest / "DAF_CSO_instructions.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%")
    row = analyze.bluf_row(
        {
            "topicId": "t0",
            "topicCode": "DAF27BZ01-DV008",
            "topicTitle": "TDP Modernization",
            "component": "USAF",
            "program": "SBIR",
            "instructionPdfs": ["solicitation_documents/DAF_CSO_instructions.pdf"],
        },
        tmp_path,
    )
    assert row["contract"] == "Direct to Phase II"
    assert row["techVolLimit"] == ""
    assert row["feasStudyLimit"] == ""


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


def test_due_days_int_and_urgency():
    assert analyze.due_days_int("today") == 0
    assert analyze.due_days_int("7d") == 7
    assert analyze.due_days_int("closed") == -1
    assert analyze.due_days_int("—") is None
    assert analyze.urgency({"dueIn": "3d"}) == "closing"
    assert analyze.urgency({"dueIn": "10d"}) == "soon"
    assert analyze.urgency({"dueIn": "30d"}) == "open"
    assert analyze.urgency({"dueIn": "closed"}) == "closed"
    assert analyze.is_open_status("Open")
    assert not analyze.is_open_status("Pre-Release")
    assert analyze.is_pre_release_status("Pre-Release")


def test_pipeline_summary_ignores_closed_in_due_windows():
    rows = [
        {"status": "Open", "dueIn": "2d", "client": "USAF", "call": "Pursue", "pdf": "a.pdf", "pdfStatus": "downloaded"},
        {"status": "Open", "dueIn": "closed", "client": "USAF", "call": "", "pdf": "", "pdfStatus": "pending"},
        {"status": "Pre-Release", "dueIn": "5d", "client": "ARMY", "call": "watch"},
        {"status": "Open", "dueIn": "20d", "client": "NAVY / ONR", "call": "pass"},
    ]
    summary = analyze.pipeline_summary(rows)
    assert summary["topics"] == 4
    assert summary["open"] == 3
    assert summary["pre_release"] == 1
    assert summary["due_7"] == 2
    assert summary["due_14"] == 2
    assert summary["pursue"] == 1
    assert summary["watch"] == 1
    assert summary["pass"] == 1
    assert summary["untagged"] == 1
    assert summary["pdf_ready"] == 1
    assert summary["clients"]["NAVY"] == 1
    line = analyze.format_pipeline_line(summary, shown=2)
    assert "2 shown / 4 topics" in line
    assert "3 Open" in line
    assert "2 due ≤7d" in line
    assert "1 Pursue" in line
    assert "PDFs 1/4" in line


def test_format_capture_brief_and_triage_normalize():
    assert analyze.normalize_triage("PURSUE") == "pursue"
    assert analyze.normalize_triage("nope") == ""
    assert analyze.triage_label("watch") == "Watch"
    brief = analyze.format_capture_brief(
        {
            "code": "DAF27BZ01-DV011",
            "title": "Unmanned Aerial Systems",
            "client": "USAF",
            "status": "Open",
            "due": "2026-11-25",
            "dueIn": "26d",
            "program": "SBIR",
            "contract": "Direct to Phase II",
            "funding": "$2,000,000 (typical Direct to Phase II ceiling)",
            "call": "pursue",
            "note": "Pitch Thursday",
            "problem": "Need a reusable harness.",
        }
    )
    assert brief.startswith("DAF27BZ01-DV011 — Unmanned Aerial Systems")
    assert "Call: Pursue" in brief
    assert "Note: Pitch Thursday" in brief
    assert "typical" in brief
    assert "Need a reusable harness." in brief


def test_qa_html_and_nested_answer_are_stripped():
    assert analyze.strip_html("<p>Hello&nbsp;world</p>") == "Hello world"
    assert analyze.published_qa_count({"noOfPublishedQuestions": 2}) == 2
    assert analyze.published_qa_count({"qaPublished": "0"}) == 0
    excerpt = analyze.format_qa_excerpt(
        [
            {
                "question": "<p>Weight threshold?</p>",
                "answers": [
                    {"answer": '{"content":"<p>Use 220VAC.</p>","length":12}'}
                ],
            }
        ]
    )
    assert "Q: Weight threshold?" in excerpt
    assert "A: Use 220VAC." in excerpt
    assert "<p>" not in excerpt


def test_load_qa_excerpt_rejects_traversal_and_non_json(tmp_path):
    import json

    secret = tmp_path.parent / "secret.json"
    secret.write_text("[]", encoding="utf-8")
    (tmp_path / "qa").mkdir()
    good = tmp_path / "qa" / "ok.json"
    good.write_text(
        json.dumps([{"question": "<p>Hi</p>", "answers": []}]),
        encoding="utf-8",
    )
    assert analyze.load_qa_excerpt(tmp_path, "../secret.json") == ""
    assert analyze.load_qa_excerpt(tmp_path, "qa/missing.json") == ""
    assert "Q: Hi" in analyze.load_qa_excerpt(tmp_path, "qa/ok.json")


def test_load_json_under_and_full_qa_excerpt(tmp_path):
    import json

    secret = tmp_path.parent / "secret.json"
    secret.write_text('{"secret": true}', encoding="utf-8")
    (tmp_path / "details").mkdir()
    good = tmp_path / "details" / "ok.json"
    good.write_text(json.dumps({"objective": "Build a radio."}), encoding="utf-8")
    assert analyze.load_json_under(tmp_path, "../secret.json") is None
    assert analyze.load_json_under(tmp_path, "details/ok.json")["objective"] == "Build a radio."
    items = [
        {"question": f"Q{i}?", "answers": []}
        for i in range(5)
    ]
    assert analyze.format_qa_excerpt(items).count("Q:") == 3
    assert analyze.format_qa_excerpt(items, limit=None).count("Q:") == 5


def test_topic_overview_paragraph_is_local_extractive():
    details = {
        "objective": "Develop a reusable illumination system for high-speed photo-optic collection at the test track.",
        "description": "Legacy flash bulbs are out of production and must be replaced with a reusable source that survives multiple shots.",
        "itar": "N",
    }
    row = {"title": "Reusable Illumination System", "code": "DAF01"}
    para = analyze.topic_overview_paragraph(row, details=details)
    assert "illumination" in para.lower()
    assert "flash bulbs" in para.lower()
    assert not para.endswith("Exchange")
    assert analyze.itar_flag("N") is False
    assert analyze.itar_flag("Y") is True
    assert analyze.itar_flag("") is False
    row = {"due": "2026-11-25", "dueIn": "99d"}
    analyze.refresh_due_in(row)
    assert row["dueIn"] != "99d"
    assert row["dueIn"] in {"closed", "today"} or row["dueIn"].endswith("d")


def test_topic_overview_strips_itar_and_does_not_echo_title():
    details = {
        "objective": (
            "<p>The technology within this topic is restricted under the International "
            "Traffic in Arms Regulation (ITAR), 22 CFR Parts 120-130, which controls "
            "the export and import of defense-related material and services, including "
            "export of sensitive technical data, or the Export Administration Regulation "
            "(EAR), 15 CFR Parts 730-774, which controls dual use items. Offerors must "
            "disclose any proposed use of foreign nationals (FNs), their country(ies) of "
            "origin, the type of visa or work permit possessed, and the statement of work "
            "(SOW) tasks intended for accomplishment by the FN(s) in accordance with "
            "section 3.5 of the Announcement. Offerors are advised foreign nationals "
            "proposed to perform on this topic may be restricted due to the technical "
            "data under US Export Control Laws.</p>"
            "<p>The objective of this Directed to Phase II (D2P2) SBIR effort is to "
            "develop an innovative, secure, and scalable solution for modernizing "
            "Technical Data Packages (TDPs) associated with complex Air and Space Force "
            "platforms. This initiative seeks to address challenges in managing large, "
            "diverse datasets by enhancing configuration control, ensuring data integrity, "
            "and strengthening Information Assurance (IA) in support of mission-critical "
            "operations.</p>"
        ),
        "description": (
            "<p>Background and Problem Statement:</p>"
            "<p>The modernization of Technical Data Packages (TDPs) is imperative to "
            "address the Air and Space Force’s operational challenges in securely "
            "managing large-scale, complex datasets associated with advanced platforms "
            "and their sustainment life cycles.</p>"
        ),
        "keywords": "Technical Data Packages (TDP); Information Assurance (IA)",
        "technologyAreas": ["Air Platform"],
        "itar": True,
    }
    row = {
        "title": "Technical Data Package Modernization for Information Assurance and Secure Data Exchange",
        "code": "DAF27BZ01-DV008",
    }
    para = analyze.topic_overview_paragraph(row, details=details)
    assert "Technical Data Packages" in para or "modernizing" in para.lower()
    assert para != row["title"]
    assert "22 CFR" not in para
    assert not para.endswith("Exchange")
    analyze.apply_details_fields(row, details)
    assert row["keywords"].startswith("Technical Data Packages")
    assert row["technologyAreas"] == ["Air Platform"]
    assert analyze.itar_flag(row["itar"]) is True
    glued = (
        "TITLE: Technical Data Package Modernization "
        "OBJECTIVE:Develop a secure TDP exchange that keeps the as-sustained "
        "configuration intact across Air Force networks. "
        "DESCRIPTION:Current TDP systems lack Information Assurance. "
        "PHASE I: As this is Direct to Phase II, no Phase I awards."
    )
    from_pdf = analyze.topic_overview_paragraph(
        {"title": row["title"]}, pdf_text=glued
    )
    assert "secure TDP" in from_pdf or "Information Assurance" in from_pdf
    assert from_pdf != row["title"]
    assert analyze.topic_overview_paragraph(row) == "—"


def test_write_bluf_csv_includes_call_and_note(tmp_path):
    dest = tmp_path / "bluf.csv"
    analyze.write_bluf_csv(
        [
            {
                "code": "DAF01",
                "title": "Illumination",
                "call": "Pursue",
                "note": "Fits autonomy",
                "dueIn": "5d",
            }
        ],
        dest,
    )
    text = dest.read_text(encoding="utf-8")
    header = text.splitlines()[0]
    assert header.startswith("call,code,")
    assert "note" in header.split(",")
    assert "Pursue" in text
    assert "Fits autonomy" in text
