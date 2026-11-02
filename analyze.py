"""Local catalog filter and BLUF extraction. No cloud APIs, no model downloads.

Filter and ranking use only the in-memory catalog JSON plus, after download,
bounded pypdf reads of *topic* PDFs already on disk. HuggingFace / OpenAI /
Gemini are never imported. Opening a PDF is restricted to a real .pdf file
inside the run's output directory.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

# Word-like tokens only. Never compile the user's phrase as a regex (ReDoS).
_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_TRL_STATED = re.compile(
    r"\b(?:TRL|technology readiness levels?)\s*(?:of\s+|level\s*|[:\-]\s*)?"
    r"(1[0-9]|[1-9])(?:\s*(?:-|–|to)\s*(1[0-9]|[1-9]))?",
    re.IGNORECASE,
)
_MONEY = re.compile(
    r"\$\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)\s*(million|billion|K|M|B|k|m|b)?",
    re.IGNORECASE,
)
_ITAR_NOISE = re.compile(
    r"The technology within this topic is restricted under the International "
    r"Traffic in Arms Regulation[\s\S]{0,900}?Export Control Laws\.?",
    re.IGNORECASE,
)
_CMMC_NOISE = re.compile(r"CMMC|PROJECTED CMMC|Level 2 \(Self\)", re.IGNORECASE)
_STOP = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "at", "by",
    "with", "from", "this", "that", "is", "are", "be", "as", "into", "their",
}

# Public DoW FY27 typical award ceilings used only when the topic sheet does
# not state a dollar amount. Labeled "typical" so they are not mistaken for
# a quote from that PDF.
_TYPICAL_AWARD = {
    ("USAF", "Direct to Phase II"): 2_000_000,
    ("DAF", "Direct to Phase II"): 2_000_000,
    ("AIR FORCE", "Direct to Phase II"): 2_000_000,
    ("NAVY", "Direct to Phase II"): 2_000_000,
    ("DON", "Direct to Phase II"): 2_000_000,
    ("ARMY", "Direct to Phase II"): 2_000_000,
    ("OSW", "Direct to Phase II"): 2_000_000,
    ("USAF", "Phase I"): 300_000,
    ("DAF", "Phase I"): 300_000,
    ("AIR FORCE", "Phase I"): 300_000,
    ("NAVY", "Phase I"): 315_000,
    ("DON", "Phase I"): 315_000,
    ("ARMY", "Phase I"): 250_000,
    ("OSW", "Phase I"): 300_000,
}

MAX_PDF_BYTES = 2_500_000
MAX_PDF_PAGES = 12
# Component-instruction / BAA preface PDFs are larger; page limits live there.
MAX_BAA_PDF_BYTES = 12_000_000
MAX_BAA_PDF_PAGES = 40


def phrase_tokens(phrase: str) -> list[str]:
    return _TOKEN.findall((phrase or "").lower())


# Frozen in-repo glossary. Never downloaded. Each user token expands to an
# OR-group; groups are ANDed. See docs/design-decisions/001-search-aliases.md.
_CODE_PREFIX_ALIASES = {
    "DAF": ["daf", "usaf", "air force", "airforce", "afmc"],
    "ARM": ["arm", "army", "asa"],
    "DON": ["don", "navy", "onr", "navsea"],
    "NAV": ["navy", "don"],
    "OSW": ["osw", "osd", "drpm"],
    "OSD": ["osd", "osw"],
    "DPA": ["dpa", "darpa"],
    "SOC": ["socom", "ussocom"],
    "MDA": ["mda"],
    "DTR": ["dtra"],
    "DLA": ["dla"],
    "CBD": ["cbd"],
    "DHP": ["dhp", "dha"],
    "NGA": ["nga"],
    "NAS": ["nasa"],
    "NOA": ["noaa"],
    "NSF": ["nsf"],
}
_QUERY_ALIASES = {
    "daf": ["daf", "usaf", "air force", "airforce"],
    "usaf": ["daf", "usaf", "air force", "airforce"],
    "airforce": ["daf", "usaf", "air force", "airforce"],
    "air": ["air"],  # merged with "force" below when adjacent
    "army": ["arm", "army"],
    "arm": ["arm", "army"],
    "navy": ["don", "navy", "onr"],
    "don": ["don", "navy"],
    "onr": ["onr", "navy", "don"],
    "osw": ["osw", "osd"],
    "osd": ["osw", "osd"],
    "darpa": ["dpa", "darpa"],
    "dpa": ["dpa", "darpa"],
    "socom": ["socom", "ussocom"],
    "ussocom": ["socom", "ussocom"],
    "mda": ["mda", "missile defense"],
    "dtra": ["dtra"],
    "dla": ["dla"],
    "cbd": ["cbd", "chem bio"],
    "dhp": ["dhp", "dha", "defense health"],
    "dha": ["dhp", "dha", "defense health"],
    "nga": ["nga"],
    "nasa": ["nasa"],
    "noaa": ["noaa"],
    "nsf": ["nsf"],
    "uas": [
        "uas", "uav", "uxs", "drone", "drones",
        "unmanned aerial", "unmanned aircraft", "uncrewed air", "uncrewed aerial",
    ],
    "uav": [
        "uas", "uav", "uxs", "drone", "drones",
        "unmanned aerial", "unmanned aircraft", "uncrewed air", "uncrewed aerial",
    ],
    "uxs": ["uas", "uav", "uxs", "drone"],
    "drone": [
        "uas", "uav", "drone", "drones",
        "unmanned aerial", "unmanned aircraft", "uncrewed air", "uncrewed aerial",
    ],
    "drones": [
        "uas", "uav", "drone", "drones",
        "unmanned aerial", "unmanned aircraft", "uncrewed air", "uncrewed aerial",
    ],
    "cuas": [
        "cuas", "counter-unmanned", "counter unmanned",
        "counter-unmanned aerial", "counter unmanned aerial",
    ],
    "d2p2": ["d2p2", "direct to phase ii", "direct-to-phase-ii"],
    "sbir": ["sbir"],
    "sttr": ["sttr"],
}
_MERGE_PAIRS = {
    ("air", "force"): "airforce",
    ("unmanned", "aerial"): "uas",
    ("unmanned", "aircraft"): "uas",
    ("uncrewed", "air"): "uas",
    ("uncrewed", "aerial"): "uas",
    ("counter", "uas"): "cuas",
    ("counter", "uav"): "cuas",
    ("counter", "drone"): "cuas",
}
_CODE_PREFIX = re.compile(r"^([A-Za-z]{2,4})")
_UAS_TITLE = re.compile(
    r"\b(unmanned|uncrewed)\b.{0,40}\b(aerial|air|aircraft)\b",
    re.IGNORECASE,
)
_CUAS_TITLE = re.compile(
    r"\bcounter[\s\-]*unmanned|\bcounter[\s\-]*uas|\bcuas\b",
    re.IGNORECASE,
)


def _normalize_query(phrase: str) -> str:
    raw = (phrase or "").lower()
    raw = raw.replace("c-uas", "cuas").replace("counter-uas", "cuas")
    raw = raw.replace("department of the air force", "airforce")
    raw = raw.replace("department of air force", "airforce")
    raw = raw.replace("air force", "airforce")
    return raw


def query_groups(phrase: str) -> list[list[str]]:
    """AND-of-OR groups. Never AND of every synonym."""
    tokens = [
        token
        for token in phrase_tokens(_normalize_query(phrase))
        if token not in _STOP
    ]
    merged: list[str] = []
    skip = False
    for i, token in enumerate(tokens):
        if skip:
            skip = False
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt and (token, nxt) in _MERGE_PAIRS:
            merged.append(_MERGE_PAIRS[(token, nxt)])
            skip = True
        else:
            merged.append(token)
    groups = []
    for token in merged:
        alts = list(_QUERY_ALIASES.get(token, [token]))
        if token not in alts:
            alts.append(token)
        groups.append(alts)
    return groups


def parse_code_prefix(code: str) -> str:
    hit = _CODE_PREFIX.match(code or "")
    return hit.group(1).upper() if hit else ""


def tagged_blob(topic: dict) -> str:
    """Catalog fields plus canonical tags derived from code/title/component."""
    parts = [catalog_blob(topic)]
    code = str(topic.get("topicCode") or "")
    prefix = parse_code_prefix(code)
    parts.extend(_CODE_PREFIX_ALIASES.get(prefix, []))
    component = str(topic.get("component") or "").upper()
    if component in _CODE_PREFIX_ALIASES:
        parts.extend(_CODE_PREFIX_ALIASES[component])
    title = str(topic.get("topicTitle") or "")
    command = str(topic.get("command") or "")
    hay = f"{title} {command}"
    if (
        _UAS_TITLE.search(hay)
        or re.search(r"\b(uxs|uas|uav|drones?)\b", hay, re.I)
    ):
        parts.extend(_QUERY_ALIASES["uas"])
    if _CUAS_TITLE.search(hay):
        parts.extend(_QUERY_ALIASES["cuas"])
        parts.extend(_QUERY_ALIASES["uas"])
    program = str(topic.get("program") or "").lower()
    if program:
        parts.append(program)
    dash = code.upper()
    if "-DV" in dash or "-DP" in dash:
        parts.extend(_QUERY_ALIASES["d2p2"])
    return " ".join(parts).lower()


def _alt_hits(alt: str, blob: str, code: str) -> bool:
    needle = alt.lower().strip()
    if not needle:
        return False
    if " " in needle:
        return needle in blob
    if len(needle) <= 3:
        if code.lower().startswith(needle):
            return True
        return re.search(rf"(^|[^a-z0-9]){re.escape(needle)}([^a-z0-9]|$)", blob) is not None
    return needle in blob


def topic_matches_groups(topic: dict, groups: list[list[str]]) -> bool:
    if not groups:
        return True
    blob = tagged_blob(topic)
    code = str(topic.get("topicCode") or "")
    for group in groups:
        if not any(_alt_hits(alt, blob, code) for alt in group):
            return False
    return True


def catalog_blob(topic: dict) -> str:
    parts = [
        topic.get("topicCode"),
        topic.get("topicTitle"),
        topic.get("topicStatus"),
        topic.get("component"),
        topic.get("command"),
        topic.get("program"),
        topic.get("solicitationNumber"),
        topic.get("solicitationTitle"),
        topic.get("cycleName"),
        topic.get("topicObjective"),
        topic.get("topicDescription"),
        topic.get("keywords"),
        topic.get("cmmcLevel") or topic.get("cmmc"),
        topic.get("qaExcerpt"),
        topic.get("overviewParagraph"),
        " ".join(str(p) for p in (topic.get("technologyAreas") or []) if p),
        topic.get("itar"),
        topic.get("techVolLimit"),
        topic.get("feasStudyLimit"),
    ]
    return " ".join(str(p) for p in parts if p)


_HTML_TAG = re.compile(r"<[^>]+>")


def strip_html(text: str | None) -> str:
    raw = str(text or "")
    raw = _HTML_TAG.sub(" ", raw)
    return re.sub(r"\s+", " ", raw).replace("&nbsp;", " ").replace("&amp;", "&").strip()


def published_qa_count(topic: dict) -> int:
    for key in ("noOfPublishedQuestions", "qaPublished"):
        raw = topic.get(key)
        if raw in (None, "", "—"):
            continue
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            continue
    return 0


def qa_answer_text(answer: dict | str | None) -> str:
    raw: object = answer
    if isinstance(answer, dict):
        raw = answer.get("answer") or answer.get("content") or ""
    if isinstance(raw, str) and raw.lstrip().startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            raw = parsed.get("content") or raw
    return strip_html(str(raw or ""))


def format_qa_excerpt(items: list[dict] | None, limit: int | None = 3) -> str:
    lines: list[str] = []
    pool = list(items or [])
    if limit is not None:
        pool = pool[:limit]
    for item in pool:
        question = strip_html(str(item.get("question") or ""))
        answers = item.get("answers") or []
        answer = qa_answer_text(answers[0] if answers else "")
        if question:
            lines.append(f"Q: {question}")
        if answer:
            lines.append(f"A: {answer}")
    return "\n".join(lines)


def matches_all_tokens(topic: dict, tokens: list[str]) -> bool:
    if not tokens:
        return True
    haystack = catalog_blob(topic).lower()
    return all(token in haystack for token in tokens)


def _ngrams(text: str, n: int = 3) -> Counter:
    compact = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
    if len(compact) < n:
        return Counter([compact] if compact else [])
    return Counter(compact[i : i + n] for i in range(len(compact) - n + 1))


def cosine(left: Counter, right: Counter) -> float:
    if not left or not right:
        return 0.0
    keys = set(left) | set(right)
    dot = sum(left[k] * right[k] for k in keys)
    n1 = math.sqrt(sum(v * v for v in left.values()))
    n2 = math.sqrt(sum(v * v for v in right.values()))
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / (n1 * n2)


def semantic_score(topic: dict, phrase: str) -> float:
    """Stdlib char-ngram cosine between the phrase and catalog fields.

    This is local, dependency-free 'semantic' ranking. It is not a neural
    embedding and never phones home.
    """
    tokens = phrase_tokens(phrase)
    if not tokens:
        return 1.0
    query = _ngrams(phrase)
    doc = _ngrams(catalog_blob(topic))
    score = cosine(query, doc)
    if matches_all_tokens(topic, tokens):
        score = max(score, 0.99)
    return score


def filter_topics(topics: list[dict], phrase: str, min_score: float = 0.28) -> list[dict]:
    """Keep topics that match every query group (AND of OR-alias groups).

    Cosine `min_score` is ignored: n-gram similarity is not a keep/drop gate.
    An empty phrase returns the catalog unchanged. DSIP searchText is unused.
    """
    del min_score
    groups = query_groups(phrase)
    if not groups:
        return list(topics)
    return [topic for topic in topics if topic_matches_groups(topic, groups)]


def format_day(iso: str | None) -> str:
    if not iso:
        return "—"
    return str(iso)[:10]


def refresh_due_in(row: dict) -> dict:
    """Recompute dueIn from the stored due date so a restored snapshot ages."""
    due = row.get("due") or row.get("topicEndDate")
    if due in (None, "", "—"):
        row["dueIn"] = row.get("dueIn") or "—"
        return row
    row["dueIn"] = days_until(str(due))
    return row


def days_until(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        from datetime import date

        due = date.fromisoformat(str(iso)[:10])
        delta = (due - date.today()).days
    except ValueError:
        return "—"
    if delta < 0:
        return "closed"
    if delta == 0:
        return "today"
    return f"{delta}d"


def extract_pdf_text(
    path: Path,
    max_bytes: int | None = None,
    max_pages: int | None = None,
) -> str:
    """Bounded text extract from a local PDF. Returns '' on any failure."""
    limit_bytes = MAX_PDF_BYTES if max_bytes is None else max_bytes
    limit_pages = MAX_PDF_PAGES if max_pages is None else max_pages
    try:
        if not path.is_file():
            return ""
        stat = path.stat()
        if stat.st_size > limit_bytes:
            return ""
        from pypdf import PdfReader  # optional; GUI still works without it
    except Exception:
        return ""
    try:
        return _extract_pdf_text_cached(
            str(path.resolve()),
            int(stat.st_size),
            int(stat.st_mtime),
            limit_bytes,
            limit_pages,
        )
    except Exception:
        return ""


@lru_cache(maxsize=48)
def _extract_pdf_text_cached(
    resolved: str, size: int, mtime: int, max_bytes: int, max_pages: int
) -> str:
    del size, mtime, max_bytes  # identity for cache invalidation only
    from pypdf import PdfReader

    reader = PdfReader(resolved, strict=False)
    chunks = [page.extract_text() or "" for page in reader.pages[:max_pages]]
    return "\n".join(chunks)


_SECTION_STOP = re.compile(
    r"(?:\n\s*)?(?:ITAR|DESCRIPTION|PHASE\s*I|PHASE\s*II|DUAL USE|"
    r"REFERENCES|KEYWORDS|BACKGROUND)\b",
    re.IGNORECASE,
)
_PDF_HEADING_BREAK = re.compile(
    r"(?<!\n)(?=(?:OBJECTIVE|DESCRIPTION|PHASE\s*I|PHASE\s*II|"
    r"DUAL USE|REFERENCES|KEYWORDS)\s*:)",
    re.IGNORECASE,
)
_LABEL_PREFIX = re.compile(
    r"^(?:Background and Problem Statement|Opportunity and Desired Outcome|"
    r"Required Efforts(?: and Phase Activities)?|The objective of this topic|"
    r"OBJECTIVE|DESCRIPTION)\s*:?\s*",
    re.IGNORECASE,
)


def normalize_pdf_text(text: str) -> str:
    """Insert heading breaks pypdf often glues onto one line."""
    raw = str(text or "")
    raw = _PDF_HEADING_BREAK.sub("\n", raw)
    return raw


def _section_after(text: str, heading: str, limit: int = 900) -> str:
    blob = normalize_pdf_text(text)
    upper = blob.upper()
    key = heading.upper()
    idx = upper.find(key)
    if idx < 0:
        return ""
    rest = blob[idx + len(heading) :].lstrip(":\n\r\t ")
    rest = _ITAR_NOISE.sub(" ", rest)
    cut = _SECTION_STOP.split(rest, maxsplit=1)
    body = cut[0] if cut else rest
    body = re.sub(r"\s+", " ", body).strip()
    return body[:limit].rstrip()


def _sentences(text: str) -> list[str]:
    blob = re.sub(r"\s+", " ", text or "").strip()
    if not blob:
        return []
    parts = _SENTENCE.split(blob)
    out = []
    for part in parts:
        sentence = part.strip()
        if len(sentence) < 40:
            continue
        if _CMMC_NOISE.search(sentence) or _ITAR_NOISE.search(sentence):
            continue
        if sentence.upper().startswith("THE TECHNOLOGY WITHIN THIS TOPIC"):
            continue
        out.append(sentence)
    return out


def _content_tokens(text: str) -> set[str]:
    return {t for t in phrase_tokens(text) if t not in _STOP and len(t) > 2}


def summarize_problem(title: str, pdf_text: str) -> str:
    """Extractive BLUF: title plus the PDF sentences that overlap it most.

    No neural model and no network. OBJECTIVE sentences are preferred over
    DESCRIPTION; ITAR/CMMC boilerplate is dropped.
    """
    clean = _ITAR_NOISE.sub(" ", pdf_text or "")
    objective = _section_after(clean, "OBJECTIVE", limit=1200)
    description = _section_after(clean, "DESCRIPTION", limit=1200)
    pool = _sentences(objective) + _sentences(description)
    title_tokens = _content_tokens(title)
    if not pool:
        fallback = objective or description or title
        return re.sub(r"\s+", " ", fallback).strip()[:360] or "—"

    ranked = []
    for index, sentence in enumerate(pool):
        sent_tokens = _content_tokens(sentence)
        overlap = len(title_tokens & sent_tokens) / max(1, len(title_tokens))
        # Prefer OBJECTIVE (earlier) and title overlap.
        score = overlap * 3.0 + (1.2 if index < len(_sentences(objective)) else 0.0)
        score += 0.15 * math.cos(index / max(1, len(pool)))
        ranked.append((score, index, sentence))
    ranked.sort(key=lambda row: (-row[0], row[1]))

    chosen: list[str] = []
    seen = set()
    for _score, _index, sentence in ranked:
        key = sentence[:80].lower()
        if key in seen:
            continue
        seen.add(key)
        chosen.append(sentence)
        if len(chosen) == 2:
            break
    summary = " ".join(chosen)
    title_clean = re.sub(r"\s+", " ", title or "").strip()
    if title_clean and not summary.lower().startswith(title_clean.lower()):
        summary = f"{title_clean}: {summary}"
    return summary[:420].rstrip() or "—"


def infer_contract(text: str, topic_code: str = "") -> str:
    upper = (text or "").upper()
    code = (topic_code or "").upper()
    if (
        "DIRECT-TO-PHASE-II" in upper
        or "DIRECT TO PHASE II" in upper
        or "D2P2" in upper
        or "-DV" in code
        or "-DP" in code
    ):
        return "Direct to Phase II"
    if "PHASE I" in upper:
        return "Phase I"
    if "PHASE II" in upper:
        return "Phase II"
    return "—"


def assess_trl(text: str, contract: str) -> str:
    """Stated TRL if the topic sheet names one; otherwise a contract-based range.

    CMMC 'Level 2' is ignored so it cannot be mistaken for TRL 2.
    """
    stripped = _CMMC_NOISE.sub(" ", text or "")
    for hit in _TRL_STATED.finditer(stripped):
        window = stripped[max(0, hit.start() - 40) : hit.end() + 20].upper()
        if "CMMC" in window:
            continue
        low, high = hit.group(1), hit.group(2)
        if high and high != low:
            return f"{low}–{high} (stated)"
        return f"{low} (stated)"
    upper = stripped.upper()
    if contract == "Direct to Phase II":
        if "PROTOTYPE" in upper or "PILOT" in upper:
            return "5–6 (assessed, D2P2 prototype)"
        return "4–6 (assessed, D2P2 feasibility already shown)"
    if contract == "Phase I":
        return "2–4 (assessed, Phase I feasibility)"
    if contract == "Phase II":
        return "5–7 (assessed, Phase II prototype)"
    return "—"


def _money_to_int(amount: str, suffix: str) -> int | None:
    try:
        value = float(amount.replace(",", ""))
    except ValueError:
        return None
    token = (suffix or "").lower()
    if token in {"k"}:
        value *= 1_000
    elif token in {"m", "million"}:
        value *= 1_000_000
    elif token in {"b", "billion"}:
        value *= 1_000_000_000
    if value < 20_000 or value > 20_000_000:
        return None
    return int(round(value))


def _format_dollars(value: int) -> str:
    return f"${value:,}"


def assess_funding(text: str, contract: str, component: str) -> str:
    """Prefer dollar amounts next to award language; else typical FY27 ceilings."""
    stated: list[int] = []
    for match in _MONEY.finditer(text or ""):
        start = max(0, match.start() - 80)
        window = text[start : match.end() + 40].lower()
        if any(bad in window for bad in ("cmmc", "level 2", "fy20", "page ")):
            continue
        if not any(
            key in window
            for key in (
                "award",
                "funded",
                "funding",
                "not to exceed",
                "up to",
                "maximum",
                "phase i",
                "phase ii",
                "d2p2",
                "ceiling",
            )
        ):
            continue
        parsed = _money_to_int(match.group(1), match.group(2) or "")
        if parsed:
            stated.append(parsed)
    unique = sorted(set(stated), reverse=True)
    if unique:
        if len(unique) == 1:
            return f"{_format_dollars(unique[0])} (stated)"
        return f"{_format_dollars(unique[-1])}–{_format_dollars(unique[0])} (stated)"

    agency = (component or "").upper()
    typical = _TYPICAL_AWARD.get((agency, contract))
    if typical is None and agency:
        for key, value in _TYPICAL_AWARD.items():
            if key[1] == contract and key[0] in agency:
                typical = value
                break
    if typical is None and contract == "Direct to Phase II":
        typical = 2_000_000
    elif typical is None and contract == "Phase I":
        typical = 300_000
    if typical:
        return f"{_format_dollars(typical)} (typical {contract} ceiling)"
    return "—"


# Known contract kinds for page-limit scoring. Do not fill these in as defaults.
_TYPICAL_TECH_VOL_PAGES = {
    "Phase I": 5,
    "Phase II": 15,
    "Direct to Phase II": 15,
}

_TECH_VOL_ANCHOR = re.compile(
    r"technical\s+volume|volume\s*(?:2|ii)\b|tech(?:nical)?\s+vol\b",
    re.IGNORECASE,
)
_FEAS_STUDY_ANCHOR = re.compile(
    r"feasibility\s+(?:documentation|study|volume|evidence|package)|"
    r"phase\s*i\s+feasibility|"
    r"direct(?:ed)?(?:\s+to)?\s+phase\s*ii\s+feasibility|"
    r"d2p2\s+feasibility",
    re.IGNORECASE,
)
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}
_WORD_NUM = "|".join(_NUMBER_WORDS)
_LIMIT_LEAD = (
    r"(?:not\s+to\s+exceed|not\s+exceed(?:ing)?|shall\s+not\s+exceed|"
    r"must\s+not\s+exceed|no\s+more\s+than|limited\s+to|limit(?:ed)?\s+of|"
    r"maximum\s+of|up\s+to|page\s+limit(?:\s+of)?)\s*(?:of\s+)?"
)
# OSD/DRPM writes "five (5) pages"; DoW BAA writes "15 pages".
_LIMIT_PHRASE = re.compile(
    _LIMIT_LEAD
    + r"(?:(?P<word>" + _WORD_NUM + r")\s*)?"
    + r"(?:\((?P<paren>\d{1,2})\)\s*)?"
    + r"(?:(?P<digits>\d{1,2})\s*)?"
    + r"pages?",
    re.IGNORECASE,
)
_N_PAGES = re.compile(
    r"(\d{1,2})\s*[\-–]?\s*pages?(?:\s+(?:maximum|max|limit|total))?",
    re.IGNORECASE,
)
_PAREN_PAGES = re.compile(r"\((\d{1,2})\)\s*pages?", re.IGNORECASE)
_PAGE_MAXIMUM = re.compile(
    r"(\d{1,2})\s*page(?:s)?\s+maximum",
    re.IGNORECASE,
)
_COMPOUND_TECH_PAGES = re.compile(
    r"(\d{1,2})-page(?:s)?\s+technical\s+volume",
    re.IGNORECASE,
)
_COMPOUND_FEAS_PAGES = re.compile(
    r"(\d{1,2})-page(?:s)?\s+feasibility",
    re.IGNORECASE,
)
_D2P2_SECTION = re.compile(
    r"direct(?:ed)?\s+to\s+phase\s*ii\s*(?:\(d2p2\))?\s*proposal\s+guidelines",
    re.IGNORECASE,
)


def _limit_match_count(match: re.Match) -> int | None:
    groups = match.groupdict()
    if groups.get("paren"):
        n = int(groups["paren"])
    elif groups.get("digits"):
        n = int(groups["digits"])
    elif groups.get("word"):
        n = _NUMBER_WORDS.get(groups["word"].lower(), 0)
    else:
        try:
            n = int(match.group(1))
        except (IndexError, TypeError, ValueError):
            return None
    if 1 <= n <= 40:
        return n
    return None


def _iter_page_counts(text: str) -> list[tuple[int, re.Match]]:
    found: list[tuple[int, re.Match]] = []
    seen: set[tuple[int, int]] = set()
    for pattern in (_LIMIT_PHRASE, _PAGE_MAXIMUM, _PAREN_PAGES, _N_PAGES):
        for match in pattern.finditer(text or ""):
            n = _limit_match_count(match)
            if n is None:
                continue
            key = (match.start(), n)
            if key in seen:
                continue
            seen.add(key)
            found.append((n, match))
    return found


_APPLY_TO_TOPIC = re.compile(
    r"(?:apply(?:\s+to)?(?:\s+topic)?|guidelines below apply to)\s+",
    re.IGNORECASE,
)
# Cover-sheet teasers ("Guidelines below apply to CODE") are a sentence; the
# real section ("guidelines in this section apply to topic CODE") is pages long.
_MIN_TOPIC_SCOPE_CHARS = 300


def _topic_guideline_slices(blob: str, code: str) -> list[str]:
    """Each 'apply to <this topic>' span until the next apply-to-<any topic>."""
    slices: list[str] = []
    for match in re.finditer(
        rf"{_APPLY_TO_TOPIC.pattern}{re.escape(code)}",
        blob,
        re.IGNORECASE,
    ):
        nxt = _APPLY_TO_TOPIC.search(blob, match.end())
        while nxt and not re.match(r"[A-Z]{2,4}\d", blob[nxt.end() :], re.IGNORECASE):
            nxt = _APPLY_TO_TOPIC.search(blob, nxt.end())
        end = nxt.start() if nxt else len(blob)
        slices.append(blob[match.start() : end])
    return slices


def _instruction_scope(text: str, topic_code: str = "", contract: str = "") -> str:
    """Prefer the D2P2 (or Phase I) slice of a combined component-instruction PDF."""
    blob = text or ""
    heading = _D2P2_SECTION.search(blob)
    code = (topic_code or "").strip()
    if code:
        slices = _topic_guideline_slices(blob, code)
        if slices:
            best = max(slices, key=len)
            if len(best) >= _MIN_TOPIC_SCOPE_CHARS:
                return best
    if heading:
        if contract == "Direct to Phase II":
            return blob[heading.start() :]
        if contract == "Phase I":
            return blob[: heading.start()]
    return blob


def _text_windows(text: str, pattern: re.Pattern, before: int = 20, after: int = 160) -> list[str]:
    blob = text or ""
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+|\n+", blob)
        if part.strip() and pattern.search(part)
    ]
    if sentences:
        return sentences
    windows = []
    for match in pattern.finditer(blob):
        start = max(0, match.start() - before)
        end = min(len(blob), match.end() + after)
        windows.append(blob[start:end])
    return windows


def _page_numbers(window: str) -> list[int]:
    found: list[int] = []
    for match in _LIMIT_PHRASE.finditer(window):
        n = int(match.group(1))
        if 1 <= n <= 40:
            found.append(n)
    if found:
        return found
    for match in _N_PAGES.finditer(window):
        n = int(match.group(1))
        if 1 <= n <= 40:
            found.append(n)
    return found


def _contract_window_score(window: str, contract: str) -> int:
    lower = window.lower()
    d2p2 = bool(
        re.search(r"direct(?:ed)?(?:\s+to)?\s+phase\s*ii|\bd2p2\b", lower)
    )
    phase_ii = bool(re.search(r"phase\s*ii\b", lower))
    phase_i = bool(re.search(r"phase\s*i\b(?!\s*i)", lower)) and not phase_ii
    if contract == "Direct to Phase II":
        if d2p2:
            return 5
        if phase_ii and not phase_i:
            return 2
        if phase_i and not d2p2:
            return -4
        return 0
    if contract == "Phase I":
        if d2p2:
            return -3
        if phase_i and not phase_ii:
            return 5
        if phase_ii and not phase_i:
            return -3
        return 1
    if contract == "Phase II":
        if d2p2:
            return -1
        if phase_ii:
            return 5
        if phase_i:
            return -3
        return 1
    return 0


def _best_page_limit(
    text: str,
    anchors: re.Pattern,
    contract: str,
    compounds: re.Pattern | None = None,
    rival: re.Pattern | None = None,
    prefer: int | None = None,
) -> int | None:
    scored: list[tuple[int, int]] = []
    blob = text or ""
    if compounds:
        for match in compounds.finditer(blob):
            n = int(match.group(1))
            if 1 <= n <= 40:
                local = blob[max(0, match.start() - 80) : match.end() + 80]
                score = 6 + _contract_window_score(local, contract)
                scored.append((score, n))
    for window in _text_windows(blob, anchors):
        hits = _iter_page_counts(window)
        our = anchors.search(window)
        rival_hit = rival.search(window) if rival else None
        for n, match in hits:
            if rival_hit and our:
                dist_our = abs(match.start() - our.start())
                dist_rival = abs(match.start() - rival_hit.start())
                if dist_rival < dist_our:
                    continue
            elif rival_hit and not our:
                continue
            score = _contract_window_score(window, contract)
            if _LIMIT_PHRASE.search(window) or _PAREN_PAGES.search(window):
                score += 3
            scored.append((score, n))
    for match in anchors.finditer(blob):
        slice_end = min(len(blob), match.end() + 160)
        slice_text = blob[match.end() : slice_end]
        hits = _iter_page_counts(slice_text)
        if rival:
            rival_hit = rival.search(slice_text)
            if rival_hit and hits and rival_hit.start() < hits[0][1].start():
                continue
            if rival_hit and not hits:
                continue
        if not hits:
            continue
        n, limit_hit = hits[0]
        local = blob[match.start() : match.end() + limit_hit.end()]
        score = _contract_window_score(local, contract) + 3
        scored.append((score, n))
    if not scored:
        return None
    scored.sort(
        key=lambda row: (
            -row[0],
            abs(row[1] - prefer) if prefer is not None else row[1],
            row[1],
        )
    )
    best_score, best_n = scored[0]
    if best_score <= 0:
        return None
    return best_n


def _format_page_limit(n: int | None) -> str:
    if n is None:
        return ""
    return f"{n} (stated)"


def assess_volume_page_limits(
    instruction_text: str = "",
    topic_text: str = "",
    contract: str = "",
    topic_code: str = "",
) -> dict[str, str]:
    """Tech-volume and feasibility-study page limits from BAA / instruction text.

    Extractive only. If the PDFs do not state a number, the field is left blank
    — DoW typical ceilings are never filled in. Combined component PDFs
    (Phase I plus D2P2) are scoped to the matching section.
    """
    scoped = _instruction_scope(instruction_text or "", topic_code, contract)
    blob = f"{scoped}\n{topic_text or ''}"
    kind = contract if contract in _TYPICAL_TECH_VOL_PAGES else ""
    tech_n = _best_page_limit(
        blob,
        _TECH_VOL_ANCHOR,
        kind,
        _COMPOUND_TECH_PAGES,
        rival=_FEAS_STUDY_ANCHOR,
    )
    feas_n = _best_page_limit(
        blob,
        _FEAS_STUDY_ANCHOR,
        kind,
        _COMPOUND_FEAS_PAGES,
        rival=_TECH_VOL_ANCHOR,
    )
    tech = _format_page_limit(tech_n)
    if feas_n is not None:
        feas = _format_page_limit(feas_n)
    elif kind == "Phase I":
        feas = "n/a"
    else:
        feas = ""
    return {"techVolLimit": tech, "feasStudyLimit": feas}


_COMPONENT_PDF_HINTS = {
    "ARMY": ("ARMY",),
    "NAVY": ("NAVY",),
    "USAF": ("DAF",),
    "OSD": ("OSW", "DRPM"),
    "DARPA": ("DARPA",),
}


def instruction_pdf_hints(topic_code: str = "", component: str = "") -> list[str]:
    """Filename fragments that identify this topic's component instruction PDF."""
    hints: list[str] = []
    code = (topic_code or "").strip().upper()
    if code:
        hints.append(code.split("-", 1)[0])
        if len(code) >= 3:
            hints.append(code[:3])
    agency = (component or "").strip().upper().split("/", 1)[0].strip()
    hints.extend(_COMPONENT_PDF_HINTS.get(agency, ()))
    seen: set[str] = set()
    ordered: list[str] = []
    for hint in hints:
        if hint and hint not in seen:
            seen.add(hint)
            ordered.append(hint)
    return ordered


def instruction_pdf_paths(
    output_dir: Path | None,
    names: list[str],
    topic_code: str = "",
    component: str = "",
) -> list[Path]:
    """This topic's instruction / preface PDFs only — not every file in the folder."""
    if output_dir is None:
        return []
    seen: set[Path] = set()
    ordered: list[Path] = []

    def _add(path: Path | None) -> None:
        if path is None:
            return
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        ordered.append(path)

    for name in names or []:
        path = resolve_pdf(output_dir, str(name))
        if path is None:
            path = resolve_pdf(
                output_dir, str(Path("solicitation_documents") / Path(str(name)).name)
            )
        _add(path)
    extra = output_dir / "solicitation_documents"
    hints = instruction_pdf_hints(topic_code, component)
    if extra.is_dir() and hints:
        extras = [
            path
            for path in extra.glob("*.pdf")
            if "preface" not in path.name.lower()
            and any(hint in path.name.upper() for hint in hints)
        ]
        extras.sort(key=lambda p: p.name.lower())
        for path in extras:
            _add(resolve_pdf(output_dir, str(path.relative_to(output_dir))))
    ordered.sort(
        key=lambda p: ("preface" in p.name.lower(), p.name.lower())
    )
    return ordered


def instruction_pdf_text(
    output_dir: Path | None,
    names: list[str],
    topic_code: str = "",
    component: str = "",
) -> str:
    """Concat bounded text from local instruction / preface PDFs. Prefers non-preface."""
    chunks: list[str] = []
    for path in instruction_pdf_paths(output_dir, names, topic_code, component):
        text = extract_pdf_text(
            path, max_bytes=MAX_BAA_PDF_BYTES, max_pages=MAX_BAA_PDF_PAGES
        )
        if text:
            chunks.append(text)
    return "\n".join(chunks)


def refresh_volume_page_limits(
    row: dict, output_dir: Path | None, topic_text: str = ""
) -> dict:
    """Overwrite page-limit fields from local instruction PDFs. Never keeps typicals."""
    if output_dir is None and not topic_text:
        for key in ("techVolLimit", "feasStudyLimit"):
            if "typical" in str(row.get(key) or "").lower():
                row[key] = ""
        return row
    code = str(row.get("code") or row.get("topicCode") or "")
    component = str(row.get("component") or row.get("client") or "")
    names = [
        str(item)
        for item in (row.get("instructionPdfs") or row.get("solicitationDocuments") or [])
        if item
    ]
    paths = instruction_pdf_paths(output_dir, names, topic_code=code, component=component)
    if output_dir and paths:
        base = output_dir.resolve()
        rels: list[str] = []
        for path in paths:
            try:
                rels.append(path.resolve().relative_to(base).as_posix())
            except ValueError:
                continue
        if rels:
            row["instructionPdfs"] = rels
    pdf_text = topic_text
    pdf_name = str(row.get("pdf") or "")
    if not pdf_text and output_dir and pdf_name and pdf_name not in {"Failed", "—"}:
        path = resolve_pdf(output_dir, pdf_name)
        if path is not None:
            pdf_text = extract_pdf_text(path)
    limits = assess_volume_page_limits(
        instruction_text=instruction_pdf_text(
            output_dir, names, topic_code=code, component=component
        ),
        topic_text=pdf_text,
        contract=str(row.get("contract") or ""),
        topic_code=code,
    )
    row["techVolLimit"] = limits["techVolLimit"]
    row["feasStudyLimit"] = limits["feasStudyLimit"]
    return row


def extract_bluf_from_text(
    text: str,
    title: str = "",
    component: str = "",
    topic_code: str = "",
    program: str = "",
) -> dict[str, str]:
    clean = _ITAR_NOISE.sub(" ", text or "")
    inferred = infer_contract(clean, topic_code)
    contract = inferred if inferred != "—" else (program or "—")
    problem = summarize_problem(title, clean)
    return {
        "overview": problem,
        "problem": problem,
        "trl": assess_trl(clean, inferred),
        "funding": assess_funding(clean, inferred, component),
        "contract": contract,
    }


def tpoc_label(topic: dict) -> str:
    ready = topic.get("tpoc")
    if ready:
        return str(ready)
    if topic.get("showTpoc") is False:
        return "—"
    managers = topic.get("topicManagers") or []
    names = []
    for manager in managers:
        if not isinstance(manager, dict):
            continue
        name = str(manager.get("name") or "").strip()
        if name:
            names.append(name)
    return ", ".join(names) or "—"


def bluf_row(topic: dict, output_dir: Path | None = None) -> dict:
    pdf_name = topic.get("pdf") or ""
    title = str(topic.get("topicTitle") or "")
    component = str(topic.get("component") or "")
    code = str(topic.get("topicCode") or "")
    program = str(topic.get("program") or "")
    extracted = {
        "overview": "—",
        "problem": "—",
        "trl": "—",
        "funding": "—",
        "contract": program or "—",
    }
    pdf_text = ""
    if output_dir and pdf_name:
        path = resolve_pdf(output_dir, pdf_name)
        if path is not None:
            pdf_text = extract_pdf_text(path)
    extracted.update(
        extract_bluf_from_text(
            pdf_text,
            title=title,
            component=component,
            topic_code=code,
            program=program,
        )
    )
    if extracted["contract"] == "—":
        extracted["contract"] = program or "—"
    if extracted["problem"] == "—" and title:
        extracted["problem"] = title
        extracted["overview"] = title
    command = topic.get("command") or ""
    client = " / ".join(p for p in (component, command) if p) or "—"
    row = {
        "topicId": topic.get("topicId") or "",
        "code": code or "—",
        "title": title or "—",
        "component": component,
        "client": client,
        "program": program or "—",
        "status": topic.get("topicStatus") or "—",
        "opens": format_day(topic.get("topicStartDate")),
        "due": format_day(topic.get("topicEndDate")),
        "dueIn": days_until(topic.get("topicEndDate")),
        "overview": extracted["overview"],
        "problem": extracted["problem"],
        "trl": extracted["trl"],
        "funding": extracted["funding"],
        "contract": extracted["contract"],
        "pdf": pdf_name,
        "pdfStatus": topic.get("pdfStatus") or "",
        "qaPublished": published_qa_count(topic),
        "qaAsked": topic.get("topicQuestionCount") or topic.get("qaAsked") or 0,
        "qaStatus": topic.get("topicQAStatusDisplay") or topic.get("qaStatus") or "—",
        "qaFile": topic.get("qaFile") or "",
        "qaExcerpt": topic.get("qaExcerpt") or "",
        "cmmc": topic.get("cmmcLevel") or topic.get("cmmc") or "—",
        "tpoc": tpoc_label(topic),
        "keywords": topic.get("keywords") or "",
        "technologyAreas": list(topic.get("technologyAreas") or []),
        "itar": topic.get("itar") or "",
        "detailsFile": topic.get("detailsFile") or "",
        "instructionPdfs": list(
            topic.get("instructionPdfs")
            or topic.get("solicitationDocuments")
            or []
        ),
        "overviewParagraph": topic.get("overviewParagraph") or "",
        "techVolLimit": "",
        "feasStudyLimit": "",
    }
    refresh_volume_page_limits(row, output_dir, topic_text=pdf_text)
    details = load_topic_details(output_dir, row)
    if isinstance(details, dict):
        apply_details_fields(row, details)
    excerpt = load_qa_excerpt(
        output_dir, row.get("qaFile") or "", limit=None
    )
    if excerpt:
        row["qaExcerpt"] = excerpt
    pdf_for_overview = pdf_text
    if not pdf_for_overview and output_dir and pdf_name:
        path = resolve_pdf(output_dir, pdf_name)
        if path is not None:
            pdf_for_overview = extract_pdf_text(path)
    row["overviewParagraph"] = topic_overview_paragraph(
        row, pdf_text=pdf_for_overview, details=details if isinstance(details, dict) else None
    )
    refresh_due_in(row)
    return row


def load_json_under(output_dir: Path | None, relative: str) -> object | None:
    if output_dir is None or not relative or not isinstance(relative, str):
        return None
    if "\x00" in relative or ":" in Path(relative).name:
        return None
    base = output_dir.resolve()
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    if candidate.suffix.lower() != ".json" or not candidate.is_file():
        return None
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_qa_excerpt(
    output_dir: Path | None, relative: str, limit: int | None = 3
) -> str:
    payload = load_json_under(output_dir, relative)
    if not isinstance(payload, list):
        return ""
    return format_qa_excerpt(payload, limit=limit)


def itar_flag(value: object) -> bool:
    if value in (True, 1, "1", "true", "True", "Y", "yes"):
        return True
    text = strip_html(str(value or "")).strip()
    if not text or text.lower() in {"—", "-", "n", "false", "0", "none", "null", "no"}:
        return False
    return True


def apply_details_fields(row: dict, details: dict) -> None:
    payload = unwrap_details(details)
    if payload.get("keywords"):
        row["keywords"] = payload.get("keywords") or ""
    areas = payload.get("technologyAreas") or payload.get("focusAreas") or []
    if isinstance(areas, list):
        row["technologyAreas"] = [str(item) for item in areas if item]
    if payload.get("itar") not in (None, ""):
        row["itar"] = payload.get("itar")
    if payload.get("cmmcLevel"):
        row["cmmc"] = payload.get("cmmcLevel")


def unwrap_details(details: object) -> dict:
    if not isinstance(details, dict):
        return {}
    inner = details.get("data")
    if isinstance(inner, dict) and (
        inner.get("objective") or inner.get("description") or inner.get("keywords")
    ):
        return inner
    return details


def _details_field(details: dict, *names: str) -> str:
    for name in names:
        raw = details.get(name)
        if isinstance(raw, dict):
            raw = raw.get("content") or raw.get("text") or ""
        text = strip_html(str(raw or ""))
        if text.strip():
            return text
    return ""


def clean_topic_prose(text: str) -> str:
    blob = strip_html(str(text or ""))
    blob = _ITAR_NOISE.sub(" ", blob)
    blob = re.sub(r"\s+", " ", blob).strip()
    blob = _LABEL_PREFIX.sub("", blob).strip()
    return blob


def _trim_paragraph(text: str, limit: int = 720) -> str:
    blob = re.sub(r"\s+", " ", text or "").strip()
    if len(blob) <= limit:
        return blob
    cut = blob[:limit]
    for sep in (". ", "? ", "! "):
        idx = cut.rfind(sep)
        if idx >= 160:
            return cut[: idx + 1].strip()
    idx = cut.rfind(" ")
    return (cut[:idx] if idx > 80 else cut).rstrip(" ,;:") + "…"


def _is_title_only(text: str, title: str) -> bool:
    left = re.sub(r"\s+", " ", text or "").strip().rstrip(".:").lower()
    right = re.sub(r"\s+", " ", title or "").strip().rstrip(".:").lower()
    return bool(left) and left == right


def load_topic_details(output_dir: Path | None, row: dict) -> dict | None:
    """Load details JSON from the stamped path or details/{code}.json."""
    candidates = [str(row.get("detailsFile") or "")]
    code = str(row.get("code") or row.get("topicCode") or "").strip()
    if code and code != "—":
        slug = re.sub(r'[<>:"/\\|?*]', "_", code)[:80]
        candidates.append(f"details/{slug}.json")
    for rel in candidates:
        payload = load_json_under(output_dir, rel)
        if isinstance(payload, dict):
            return unwrap_details(payload)
    return None


def topic_overview_paragraph(
    row: dict,
    pdf_text: str = "",
    details: dict | None = None,
) -> str:
    """One-paragraph local extractive overview. No cloud model, no network.

    Prefers `/details` objective + description (ITAR boilerplate stripped),
    then the PDF OBJECTIVE / DESCRIPTION sections. Truncates on a sentence
    boundary instead of mid-word.
    """
    title = str(row.get("title") or row.get("topicTitle") or "").strip()
    payload = unwrap_details(details) if details else {}
    objective = clean_topic_prose(
        _details_field(payload, "objective", "topicObjective", "topic_objective")
    )
    description = clean_topic_prose(
        _details_field(
            payload,
            "description",
            "topicDescription",
            "topic_description",
            "phase2Description",
        )
    )
    pdf_blob = normalize_pdf_text(pdf_text)
    if pdf_blob:
        if not objective:
            objective = clean_topic_prose(_section_after(pdf_blob, "OBJECTIVE", limit=1600))
        if not description:
            description = clean_topic_prose(
                _section_after(pdf_blob, "DESCRIPTION", limit=1400)
            )
    pool = _sentences(objective) + _sentences(description)
    chosen: list[str] = []
    seen: set[str] = set()
    for sentence in pool:
        if _is_title_only(sentence, title):
            continue
        key = sentence[:80].lower()
        if key in seen:
            continue
        seen.add(key)
        chosen.append(sentence)
        if len(chosen) == 3:
            break
    if chosen:
        para = " ".join(chosen)
    else:
        fallback = objective or description or ""
        if _is_title_only(fallback, title):
            fallback = ""
        para = fallback
    para = _trim_paragraph(para, 720)
    if not para or _is_title_only(para, title):
        stored = str(row.get("overviewParagraph") or "").strip()
        if stored and stored != "—" and not _is_title_only(stored, title):
            return _trim_paragraph(stored, 720)
        return "—"
    return para


def resolve_pdf(output_dir: Path, relative: str) -> Path | None:
    """Return a real .pdf inside output_dir, or None.

    The path is resolved and must stay under output_dir. Only suffix .pdf is
    allowed; the file must exist and start with %PDF-.
    """
    if not relative or not isinstance(relative, str):
        return None
    if "\x00" in relative or ":" in Path(relative).name:
        return None
    base = output_dir.resolve()
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    if candidate.suffix.lower() != ".pdf" or not candidate.is_file():
        return None
    try:
        with candidate.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                return None
    except OSError:
        return None
    return candidate


def open_local_pdf(output_dir: Path, relative: str) -> bool:
    path = resolve_pdf(output_dir, relative)
    if path is None:
        return False
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


NOTE_MAX = 400
TRIAGE_VALUES = ("", "pursue", "watch", "pass")
TRIAGE_LABELS = {
    "": "",
    "pursue": "Pursue",
    "watch": "Watch",
    "pass": "Pass",
}


def due_days_int(due_in: str | None) -> int | None:
    """Parse a `days_until` label. Closed is -1; unknown is None."""
    val = str(due_in or "").strip().lower()
    if val in {"", "—", "-"}:
        return None
    if val == "today":
        return 0
    if val == "closed":
        return -1
    if val.endswith("d") and val[:-1].isdigit():
        return int(val[:-1])
    return None


def is_open_status(status: str | None) -> bool:
    return str(status or "").strip().lower().startswith("open")


def is_pre_release_status(status: str | None) -> bool:
    return str(status or "").strip().lower().startswith("pre")


def normalize_triage(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw in TRIAGE_LABELS:
        return raw
    for key, label in TRIAGE_LABELS.items():
        if label.lower() == raw:
            return key
    return ""


def triage_label(value: str | None) -> str:
    return TRIAGE_LABELS.get(normalize_triage(value), "")


def urgency(row: dict) -> str:
    days = due_days_int(row.get("dueIn"))
    if days is None:
        return "unknown"
    if days < 0:
        return "closed"
    if days <= 7:
        return "closing"
    if days <= 14:
        return "soon"
    return "open"


def pipeline_summary(rows: list[dict]) -> dict:
    """Counts a BD manager glances at before opening a row."""
    calls = Counter(normalize_triage(row.get("call")) for row in rows)
    agencies: Counter[str] = Counter()
    for row in rows:
        client = str(row.get("client") or "—").split("/")[0].strip() or "—"
        agencies[client] += 1
    return {
        "topics": len(rows),
        "open": sum(1 for row in rows if is_open_status(row.get("status"))),
        "pre_release": sum(1 for row in rows if is_pre_release_status(row.get("status"))),
        "due_7": sum(
            1
            for row in rows
            if (days := due_days_int(row.get("dueIn"))) is not None and 0 <= days <= 7
        ),
        "due_14": sum(
            1
            for row in rows
            if (days := due_days_int(row.get("dueIn"))) is not None and 0 <= days <= 14
        ),
        "pursue": calls.get("pursue", 0),
        "watch": calls.get("watch", 0),
        "pass": calls.get("pass", 0),
        "untagged": calls.get("", 0),
        "clients": agencies,
        "pdf_ready": sum(
            1
            for row in rows
            if row.get("pdf") and row.get("pdfStatus") not in {"failed", "pending", None, ""}
        ),
        "pdf_failed": sum(1 for row in rows if row.get("pdfStatus") == "failed"),
        "qa_published": sum(1 for row in rows if published_qa_count(row) > 0),
    }


def format_pipeline_line(
    summary: dict, shown: int, pending: bool = False
) -> str:
    n = int(summary.get("topics") or 0)
    if n == 0:
        return "No topics in this snapshot."
    mix = " · ".join(
        f"{count} {name}" for name, count in summary["clients"].most_common(6)
    )
    pdfs = f"PDFs {summary['pdf_ready']}/{n}"
    if summary.get("pdf_failed"):
        pdfs += f", {summary['pdf_failed']} failed"
    extra = " · fetching PDFs" if pending and summary["pdf_ready"] < n else ""
    return (
        f"{shown} shown / {n} topics · {summary['open']} Open · "
        f"{summary['due_7']} due ≤7d · {summary['due_14']} due ≤14d · "
        f"{summary['pre_release']} Pre-Release · {summary['pursue']} Pursue · "
        f"{summary.get('qa_published', 0)} with Q&A · "
        f"{pdfs} · {mix}{extra}"
    )


def format_capture_brief(row: dict) -> str:
    """Paste-ready capture note for email or a BD tracker. Local only."""
    call = triage_label(row.get("call"))
    note = str(row.get("note") or "").strip()[:NOTE_MAX]
    lines = [
        f"{row.get('code') or '—'} — {row.get('title') or '—'}",
        f"Client: {row.get('client') or '—'}",
        (
            f"Status: {row.get('status') or '—'} · "
            f"Due: {row.get('due') or '—'} ({row.get('dueIn') or '—'})"
        ),
        (
            f"Program: {row.get('program') or '—'} · "
            f"Contract: {row.get('contract') or '—'}"
        ),
        f"Funding: {row.get('funding') or '—'}",
        (
            f"Tech vol page limit: {row.get('techVolLimit') or ''} · "
            f"Feasibility study page limit: {row.get('feasStudyLimit') or ''}"
        ),
        f"CMMC: {row.get('cmmc') or '—'} · Q&A published: {published_qa_count(row)}",
    ]
    if call:
        lines.append(f"Call: {call}")
    if note:
        lines.append(f"Note: {note}")
    problem = str(row.get("problem") or row.get("overview") or "").strip()
    if problem:
        lines.extend(["", problem])
    return "\n".join(lines)


BLUF_CSV_COLUMNS = (
    "call",
    "code",
    "title",
    "client",
    "program",
    "status",
    "opens",
    "due",
    "dueIn",
    "problem",
    "trl",
    "funding",
    "contract",
    "techVolLimit",
    "feasStudyLimit",
    "pdf",
    "qaPublished",
    "cmmc",
    "note",
)


def write_bluf_csv(rows: list[dict], dest: Path) -> None:
    import csv

    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BLUF_CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in BLUF_CSV_COLUMNS})


def snapshot_diff(current: list[dict], previous: list[dict]) -> dict[str, list[str]]:
    """Compare two topic lists by topicCode. SaaS tools do not diff DSIP folders."""
    cur = {str(row.get("topicCode") or ""): row for row in current if row.get("topicCode")}
    prev = {str(row.get("topicCode") or ""): row for row in previous if row.get("topicCode")}
    added = sorted(code for code in cur if code not in prev)
    removed = sorted(code for code in prev if code not in cur)
    changed = []
    for code in sorted(set(cur) & set(prev)):
        left, right = cur[code], prev[code]
        if (left.get("topicTitle"), left.get("topicStatus"), left.get("topicEndDate")) != (
            right.get("topicTitle"),
            right.get("topicStatus"),
            right.get("topicEndDate"),
        ):
            changed.append(code)
    return {"added": added, "removed": removed, "changed": changed}
