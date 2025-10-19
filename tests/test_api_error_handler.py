from __future__ import annotations

import asyncio

import pytest

from textual_cli_agent.error_handler import APIErrorHandler


async def _fast_sleep(*args, **kwargs):
    return None


@pytest.mark.asyncio
async def test_handle_error_with_retry_success(monkeypatch):
    handler = APIErrorHandler()

    async def fake_retry(*args, **kwargs):
        yield {"type": "text", "delta": "ok"}

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    error = Exception("429 rate_limit_exceeded try again in 1s")
    chunks = []
    async for chunk in handler.handle_error_with_retry(error, "key", fake_retry, 1, 2):
        chunks.append(chunk)
    assert chunks == [{"type": "text", "delta": "ok"}]


def test_analyze_error_variants():
    handler = APIErrorHandler()
    rate = handler.analyze_error(Exception("429 rate_limit_exceeded try again in 10s"))
    assert rate.wait_seconds == 10
    rpm = handler.analyze_error(Exception("429 rate_limit_exceeded rpm limit"))
    assert rpm.wait_seconds == 60.0
    token = handler.analyze_error(Exception("400 token limit exceeded"))
    assert token.should_prune_messages
    context = handler.analyze_error(
        Exception("context window exceeded maximum context length")
    )
    assert context.should_retry
    auth = handler.analyze_error(Exception("401 Unauthorized"))
    assert not auth.is_recoverable
    forbidden = handler.analyze_error(Exception("403 Forbidden"))
    assert forbidden.error_type == "forbidden"
    validation = handler.analyze_error(Exception("422 Input invalid"))
    assert validation.should_prune_messages
    server = handler.analyze_error(Exception("503 Service Unavailable"))
    assert server.wait_seconds == 5.0
    network = handler.analyze_error(Exception("Network timeout error"))
    assert network.wait_seconds == 2.0
    unknown = handler.analyze_error(Exception("strange failure"))
    assert unknown.error_type == "unknown"


@pytest.mark.asyncio
async def test_handle_error_with_retry_max_retries(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    handler = APIErrorHandler()
    handler.max_retries = 1

    async def failing_retry(*args, **kwargs):
        if False:
            yield {}
        raise RuntimeError("should not reach")

    error = Exception("500 server error")
    # first attempt
    with pytest.raises(RuntimeError):
        async for _ in handler.handle_error_with_retry(
            error, "retry_key", failing_retry
        ):
            pass

    # simulate exceeding retry count
    handler.retry_counts["retry_key"] = 1
    with pytest.raises(Exception):
        async for _ in handler.handle_error_with_retry(
            error, "retry_key", failing_retry
        ):
            pass


@pytest.mark.asyncio
async def test_handle_error_with_retry_non_recoverable(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    handler = APIErrorHandler()

    async def dummy_retry(*args, **kwargs):
        if False:
            yield {}

    with pytest.raises(Exception):
        async for _ in handler.handle_error_with_retry(
            Exception("401 Unauthorized"), "nr", dummy_retry
        ):
            pass

    with pytest.raises(Exception):
        async for _ in handler.handle_error_with_retry(
            Exception("422 Input invalid"), "nr2", dummy_retry
        ):
            pass


def test_prune_helpers():
    handler = APIErrorHandler()
    error = Exception("429 rate_limit_exceeded tokens per min")
    assert handler.should_prune_context(error)
    handler.reset_retry_count("missing")  # no-op
