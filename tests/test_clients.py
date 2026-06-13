"""Unit tests for the retry/backoff wrappers (no network)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from tracker import clients


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Don't actually wait during backoff in tests."""
    monkeypatch.setattr(clients, "BACKOFF_BASE", 0)


def _http_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://example.test")
    resp = httpx.Response(status, request=req)
    return httpx.HTTPStatusError("boom", request=req, response=resp)


def test_is_retriable():
    assert clients._is_retriable(httpx.ConnectError("x"))
    assert clients._is_retriable(_http_error(503))
    assert not clients._is_retriable(_http_error(404))
    assert not clients._is_retriable(ValueError("nope"))


def test_sync_retry_recovers_after_transient_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("transient")
        return "ok"

    assert clients._retry(flaky) == "ok"
    assert calls["n"] == 3


def test_sync_retry_gives_up_and_reraises():
    def always_503():
        raise _http_error(503)

    with pytest.raises(httpx.HTTPStatusError):
        clients._retry(always_503)


def test_sync_retry_does_not_retry_non_retriable():
    calls = {"n": 0}

    def bad_request():
        calls["n"] += 1
        raise _http_error(400)

    with pytest.raises(httpx.HTTPStatusError):
        clients._retry(bad_request)
    assert calls["n"] == 1  # no retries on a 4xx


def test_async_retry_recovers():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("transient")
        return "ok"

    assert asyncio.run(clients._aretry(flaky)) == "ok"
    assert calls["n"] == 2
