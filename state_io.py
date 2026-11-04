"""Atomic JSON read/write for ~/.dsip_downloader_state.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json_atomic(path: Path, payload: object) -> None:
    """Write JSON via a sibling .tmp file, then replace. Same-folder replace
    is atomic on NTFS and POSIX. A crash mid-write cannot truncate the live
    state file into invalid JSON.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
