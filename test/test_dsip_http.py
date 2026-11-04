"""Contracts for the honest DSIP HTTP client. Network is stubbed."""

import urllib.error
from io import BytesIO

import dsip_http
import main


def test_main_reexports_http_helpers():
    assert main.default_workers is dsip_http.default_workers
    assert main.open_url is dsip_http.open_url
    assert main.public_search_param is dsip_http.public_search_param
    assert main._http_error_message is dsip_http.http_error_message


def test_public_search_param_omits_nulls():
    payload = dsip_http.public_search_param()
    assert "searchText" not in payload
    assert payload["solicitationCycleNames"] == ["openTopics"]
    assert None not in payload.values()


def test_warmup_failure_is_recorded(monkeypatch):
    dsip_http.reset_session_for_tests()

    def boom(_request, timeout=30):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(dsip_http._opener, "open", boom)
    dsip_http.ensure_session()
    err = dsip_http.warmup_error()
    assert err is not None
    assert "warmup failed" in err
    assert "URLError" in err

    body = b"<H1>Access Denied</H1>\nReference&#32;&#35;18.deadbeef.1\n"
    exc = urllib.error.HTTPError(
        "https://www.dodsbirsttr.mil/topics/api/public/topics/search?x=1",
        403,
        "Forbidden",
        None,
        BytesIO(body),
    )
    message = dsip_http.http_error_message(exc, exc.filename)
    assert "Cookie warmup" in message
    assert "URLError" in message
    dsip_http.reset_session_for_tests()


def test_workers_never_exceed_eight(monkeypatch):
    monkeypatch.setattr(dsip_http.os, "cpu_count", lambda: 64)
    assert dsip_http.default_workers() == 8
    assert dsip_http.MAX_WORKERS == 8
