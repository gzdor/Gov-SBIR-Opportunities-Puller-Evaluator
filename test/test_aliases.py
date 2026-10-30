"""Alias search: DAF/UAS/Air Force must hit real catalog shapes, not cosine luck."""

from __future__ import annotations

import json
from pathlib import Path

import analyze

_FIXTURE = Path(__file__).parent / "fixtures" / "open_topics_sample.json"
TOPICS = json.loads(_FIXTURE.read_text(encoding="utf-8"))["topics"]


def _codes(phrase: str) -> list[str]:
    return [row["topicCode"] for row in analyze.filter_topics(TOPICS, phrase)]


def test_daf_returns_air_force_topics_not_army():
    kept = _codes("DAF")
    assert "DAF27BZ01-DV007" in kept
    assert "DAF27BZ01-DV011" in kept
    assert "ARM26BX03-DP007" not in kept
    assert "OSW27BZ01-DV002" not in kept


def test_air_force_and_usaf_match_daf_codes():
    assert set(_codes("Air Force")) == set(_codes("DAF"))
    assert set(_codes("USAF")) == set(_codes("DAF"))
    assert "DAF27BZ01-DV007" in _codes("department of the air force")


def test_uas_matches_unmanned_aerial_and_cuas_not_illumination():
    kept = _codes("UAS")
    assert "DAF27BZ01-DV011" in kept
    assert "OSW27BZ01-DV002" in kept
    assert "DAF27BZ01-DV007" not in kept
    assert "ARM26BX03-DP007" not in kept


def test_drone_is_an_alias_of_uas():
    assert "DAF27BZ01-DV011" in _codes("drone")
    assert "DAF27BZ01-DV011" in _codes("UAV")


def test_daf_uas_is_and_of_or_groups():
    kept = _codes("DAF UAS")
    assert kept == ["DAF27BZ01-DV011"]


def test_osw_and_osd_aliases():
    assert "OSW27BZ01-DV002" in _codes("OSW")
    assert "OSW27BZ01-DV002" in _codes("OSD")
    assert "DAF27BZ01-DV007" not in _codes("OSD")


def test_ai_word_boundary_does_not_match_domain_or_assurance():
    kept = _codes("AI")
    assert "DAF27TZ01-DV001" in kept
    assert "DAF27BZ01-DV008" not in kept


def test_and_tokens_still_require_every_group():
    kept = _codes("air force illumination")
    assert kept == ["DAF27BZ01-DV007"]


def test_cosine_is_not_a_keep_drop_gate():
    # Short acronym vs long title used to drop every row when min_score gated.
    assert analyze.filter_topics(TOPICS, "DAF", min_score=0.99)
    assert analyze.filter_topics(TOPICS, "UAS", min_score=0.99)


def test_snapshot_diff_by_code(tmp_path):
    current = TOPICS
    previous = [row for row in TOPICS if row["topicCode"] != "DAF27BZ01-DV011"]
    previous[0] = {**previous[0], "topicTitle": "Renamed illumination"}
    diff = analyze.snapshot_diff(current, previous)
    assert diff["added"] == ["DAF27BZ01-DV011"]
    assert "DAF27BZ01-DV007" in diff["changed"]
    dest = tmp_path / "bluf.csv"
    analyze.write_bluf_csv(
        [analyze.bluf_row(TOPICS[0], None)],
        dest,
    )
    text = dest.read_text(encoding="utf-8")
    assert "DAF27BZ01-DV007" in text
    assert "dueIn" in text.splitlines()[0]
