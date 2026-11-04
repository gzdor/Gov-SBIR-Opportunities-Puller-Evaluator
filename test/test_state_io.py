"""Atomic state-file writes must not leave a truncated JSON file."""

import json

import state_io


def test_write_json_atomic_replaces_live_file(tmp_path):
    dest = tmp_path / "state.json"
    dest.write_text("{broken", encoding="utf-8")
    state_io.write_json_atomic(dest, {"ok": True, "n": 2})
    assert json.loads(dest.read_text(encoding="utf-8")) == {"ok": True, "n": 2}
    assert not dest.with_name("state.json.tmp").exists()


def test_read_json_returns_default_on_trash(tmp_path):
    dest = tmp_path / "state.json"
    dest.write_text("{broken", encoding="utf-8")
    assert state_io.read_json(dest, default={"empty": True}) == {"empty": True}
    assert state_io.read_json(tmp_path / "missing.json", default=None) is None


def test_run_gui_bat_does_not_invoke_expression_on_itself():
    from pathlib import Path

    bat = Path(__file__).resolve().parents[1] / "run-gui.bat"
    text = bat.read_text(encoding="utf-8")
    assert "Invoke-Expression" not in text
    assert "splash.ps1" in text
    assert (bat.parent / "splash.ps1").is_file()
