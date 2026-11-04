"""Honest DSIP HTTP client: public JSON plus a topics-app cookie warmup.

This is not a stealth scraper and it is not an authenticated DSIP login.
The public search / PDF / Q&A / details routes sit behind Akamai. The
topics-app browser sends a Chrome User-Agent, a topics-app Referer, and
first-party cookies. We do the same three things so this appliance can
read the same catalog a person sees in that tab.

What we impersonate, on purpose:
- User-Agent: desktop Chrome 131
- Referer: https://www.dodsbirsttr.mil/topics-app/
- One GET of that HTML page so Akamai can issue bot-management cookies

What we do not do:
- send typed filter text as searchText
- log in, post questions, or touch submissions
- retry a 403 in a tight loop (that looks like a flood)

Worker count is capped at 8. 64 parallel PDF fetches is enough for
Akamai to 403 the whole IP. Cookie warmup failures are recorded and
printed; they are not swallowed. A later 403 includes that warmup error.
"""

from __future__ import annotations

import html
import http.cookiejar
import os
import re
import threading
import time
import urllib.error
import urllib.request

TOPICS_APP_URL = "https://www.dodsbirsttr.mil/topics-app/"
SEARCH_URL = "https://www.dodsbirsttr.mil/topics/api/public/topics/search"
TOPIC_PDF_URL = (
    "https://www.dodsbirsttr.mil/topics/api/public/topics/{topic_id}/download/PDF"
)
QUESTIONS_URL = (
    "https://www.dodsbirsttr.mil/topics/api/public/topics/{topic_id}/questions"
)
DETAILS_URL = (
    "https://www.dodsbirsttr.mil/topics/api/public/topics/{topic_id}/details"
)
UPLOAD_PDF_URL = (
    "https://www.dodsbirsttr.mil/submissions/api/public/download?uploadId={upload_id}"
)

# Open-topics view captured from the topics app (status ids 591, 592).
SEARCH_PARAM = {
    "searchText": None,
    "components": None,
    "programYear": None,
    "solicitationCycleNames": ["openTopics"],
    "releaseNumbers": [],
    "topicReleaseStatus": [591, 592],
    "modernizationPriorities": [],
    "sortBy": "finalTopicCode,asc",
    "technologyAreaIds": [],
    "component": None,
    "program": None,
}

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_WORKERS = 8
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.dodsbirsttr.mil/topics-app/",
}

_cookie_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookie_jar))
_session_lock = threading.Lock()
_session_ready = False
_warmup_error: str | None = None
_print_lock = threading.Lock()


def log(message: str) -> None:
    with _print_lock:
        print(message, flush=True)


def default_workers() -> int:
    """I/O-bound pool size. Cap is 8; 64 parallel fetches triggered Akamai 403s."""
    cpus = os.cpu_count() or 4
    return max(4, min(MAX_WORKERS, cpus * 5))


def public_search_param() -> dict:
    """Catalog filter sent to DSIP. JSON nulls are omitted; some WAF rules flag them."""
    return {key: value for key, value in SEARCH_PARAM.items() if value is not None}


def warmup_error() -> str | None:
    """Last topics-app cookie warmup failure, or None if warmup succeeded."""
    return _warmup_error


def reset_session_for_tests() -> None:
    """Drop cookies and warmup state. Tests only."""
    global _session_ready, _warmup_error
    with _session_lock:
        _cookie_jar.clear()
        _session_ready = False
        _warmup_error = None


def ensure_session() -> None:
    """GET the topics app once so Akamai can issue cookies for later API calls.

    Failure is recorded and printed. The session is still marked ready so a
    dead topics-app page is not hit on every PDF. A later 403 includes the
    warmup error so the GUI/log is not silent.
    """
    global _session_ready, _warmup_error
    if _session_ready:
        return
    with _session_lock:
        if _session_ready:
            return
        headers = dict(HEADERS)
        headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        )
        request = urllib.request.Request(TOPICS_APP_URL, headers=headers)
        try:
            with _opener.open(request, timeout=30) as response:
                response.read(4096)
            _warmup_error = None
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            _warmup_error = (
                f"topics-app cookie warmup failed ({type(exc).__name__}): {exc}"
            )
            log(_warmup_error)
        _session_ready = True


def http_error_message(exc: urllib.error.HTTPError, url: str) -> str:
    detail = exc.read(400)
    exc.close()
    if exc.code != 403:
        return f"HTTP {exc.code} for {url}: {detail[:240]!r}"
    text = html.unescape(detail.decode("utf-8", "replace"))
    match = re.search(r"Reference\s*#\s*([0-9A-Za-z.]+)", text)
    ref = match.group(1) if match else ""
    target = url.split("?", 1)[0]
    extra = f" Cookie warmup: {_warmup_error}." if _warmup_error else ""
    return (
        f"HTTP 403 from DSIP (Akamai Access Denied) for {target}. "
        "This is a WAF/bot block, not a login. "
        f"In a browser on this PC open {TOPICS_APP_URL}. "
        "If that page also says Access Denied, this network is blocked "
        "(VPN, too many parallel downloads, or a temporary Akamai ban). "
        "Wait, try a phone hotspot, then download again."
        + (f" Akamai reference {ref}." if ref else "")
        + extra
    )


def open_url(url: str, timeout: int) -> object:
    ensure_session()
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            return _opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            last_error = RuntimeError(http_error_message(exc, url))
            if exc.code not in RETRYABLE_STATUS or attempt == 3:
                raise last_error from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt == 3:
                raise
        time.sleep(attempt)
    raise RuntimeError(f"Request failed for {url}") from last_error
