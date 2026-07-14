"""Wikimedia Commons search must survive a burst 429/503 (a shorts batch fires many
searches back-to-back). Without a retry the beat silently falls through to SDXL and the
short loses its real archival photo."""

from unittest.mock import MagicMock, patch

import requests

from ai_operator.media import stock_clients as sc


def _http_error(status: int, retry_after: str | None = None):
    err = requests.HTTPError()
    err.response = MagicMock(status_code=status, headers={} if retry_after is None else {"Retry-After": retry_after})
    return err


def _ok_response(pages=None):
    m = MagicMock()
    m.raise_for_status.return_value = None
    m.json.return_value = {"query": {"pages": pages or {}}}
    return m


def _run_search(side_effects):
    """Drive search_wikimedia_commons with a scripted sequence of get() outcomes."""
    calls = {"n": 0}

    def fake_get(*_a, **_k):
        i = calls["n"]
        calls["n"] += 1
        outcome = side_effects[i]
        if isinstance(outcome, Exception):
            m = MagicMock()
            m.raise_for_status.side_effect = outcome
            return m
        return outcome

    sess = MagicMock()
    sess.get.side_effect = fake_get
    with patch.object(sc, "_commons_client", return_value=sess), patch.object(sc.time, "sleep") as slept:
        out = sc.search_wikimedia_commons("RMS Lusitania")
    return out, calls["n"], slept


def test_search_retries_on_429_then_succeeds():
    out, n_calls, _ = _run_search([_http_error(429, "0"), _ok_response()])
    assert n_calls == 2  # one retry
    assert out == []


def test_search_gives_up_after_three_attempts():
    out, n_calls, _ = _run_search([_http_error(503), _http_error(503), _http_error(503)])
    assert n_calls == 3  # capped, no infinite loop
    assert out == []


def test_non_rate_limit_error_is_not_retried():
    out, n_calls, _ = _run_search([_http_error(404)])
    assert n_calls == 1  # 404 -> give up immediately
    assert out == []


def test_retry_after_header_respected_and_capped():
    e = _http_error(429, "7")
    assert sc._retry_after_seconds(e, default=2) == 7.0
    assert sc._retry_after_seconds(_http_error(429, "999"), default=2) == 30.0  # capped
    assert sc._retry_after_seconds(_http_error(429), default=3) == 3  # no header -> default
