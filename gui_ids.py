"""Shared Catalog identifiers. Imported by gui.py and the widget mixins."""

from __future__ import annotations

from pathlib import Path

APP_TITLE = "DSIP Opportunities — Discovery"
# Machine-local only: parent folder, last snapshot path, triage, chips, Find.
# Never written into a download folder or committed. Do not copy this file
# between machines expecting shared capture state.
STATE_FILE = Path.home() / ".dsip_downloader_state.json"
DEPARTMENT_CHIPS = (
    ("DAF", "DAF"),
    ("Army", "Army"),
    ("Navy", "Navy"),
    ("OSD", "OSD"),
    ("SOCOM", "SOCOM"),
    ("DARPA", "DARPA"),
    ("MDA", "MDA"),
    ("DTRA", "DTRA"),
    ("DLA", "DLA"),
    ("CBD", "CBD"),
    ("DHP", "DHP"),
    ("NGA", "NGA"),
    ("NASA", "NASA"),
    ("NOAA", "NOAA"),
    ("NSF", "NSF"),
)
WORKFLOW_CHIPS = (
    ("SBIR", "SBIR"),
    ("STTR", "STTR"),
    ("UAS", "UAS"),
    ("D2P2", "D2P2"),
    ("Open", "__open__"),
    ("Has Q&A", "__qa__"),
    ("New Q&A", "__qa_delta__"),
    ("ITAR", "__itar__"),
    ("New", "__new__"),
    ("Changed", "__changed__"),
    ("due < 7d", "__due7__"),
    ("due < 14d", "__due14__"),
)
CHIP_SPECS = DEPARTMENT_CHIPS + WORKFLOW_CHIPS
DOWNLOAD_CHIP_KEYS = {key for _, key in CHIP_SPECS if not str(key).startswith("__")}
CALL_FILTERS = ("All calls", "Pursue", "Watch", "Pass", "Untagged")
PINNED_COLUMNS = ("call", "code", "title")
DEFAULT_HIDDEN_COLUMNS = frozenset({"trl", "opens"})
TABLE_HEADINGS = {
    "call": ("Call", 70),
    "code": ("Code", 130),
    "title": ("Topic", 220),
    "client": ("Client", 110),
    "program": ("Program", 60),
    "status": ("Status", 90),
    "released": ("Released", 90),
    "opens": ("Opens", 90),
    "due": ("Due", 90),
    "dueIn": ("Due in", 70),
    "qaPublished": ("Q&A", 45),
    "cmmc": ("CMMC", 60),
    "problem": ("Problem / objective", 220),
    "trl": ("TRL", 45),
    "funding": ("Funding", 80),
    "contract": ("Contract", 110),
    "techVolLimit": ("Tech Vol Page Limit", 150),
    "feasStudyLimit": ("Feasibility Study Page Limit", 180),
    "pdf": ("PDF", 180),
}
