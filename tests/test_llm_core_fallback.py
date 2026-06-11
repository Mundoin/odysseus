"""Tests for the fallback indicator in stream_llm_with_fallback.

When the selected model fails *before output* and another candidate answers,
a `fallback` event must be emitted so the switch is never masked under the
selected model's name (which is how a misconfigured provider can look like it
works while a different model silently answers).
"""
import json
import asyncio

from src import llm_core


def _run_fallback(monkeypatch, per_model):
    """Drive stream_llm_with_fallback with a stubbed stream_llm that returns a
    canned SSE line list per candidate model. Returns the emitted chunks."""
    async def fake_stream(url, model, messages, **kw):
        for ln in per_model(model):
            yield ln
    monkeypatch.setattr(llm_core, "stream_llm", fake_stream)

    async def run():
        out = []
        async for c in llm_core.stream_llm_with_fallback(
            [("u1", "primary", {}), ("u2", "backup", {})], [{"role": "user", "content": "hi"}]
        ):
            out.append(c)
        return out

    return asyncio.run(run())


def test_fallback_emits_indicator_when_primary_fails(monkeypatch):
    def per_model(model):
        if model == "primary":
            return ['event: error\ndata: {"status": 400, "text": "Provider X returned HTTP 400"}\n\n']
        return ['data: {"delta": "hello"}\n\n', "data: [DONE]\n\n"]
    chunks = _run_fallback(monkeypatch, per_model)
    fb = [
        json.loads(c[6:])
        for c in chunks
        if c.startswith("data: ") and c[6:].lstrip().startswith("{") and json.loads(c[6:]).get("type") == "fallback"
    ]
    assert fb, f"no fallback event in {chunks}"
    assert fb[0]["type"] == "fallback"
    assert fb[0]["selected_model"] == "primary"
    assert fb[0]["answered_by"] == "backup"
    assert "400" in fb[0]["reason"]
    # the fallback notice must precede the answer content
    order = [i for i, c in enumerate(chunks) if '"fallback"' in c or '"delta": "hello"' in c]
    assert order == sorted(order)
    assert any('"delta": "hello"' in c for c in chunks)
    lifecycle = [json.loads(c[6:]) for c in chunks if c.startswith("data: ") and "provider_" in c]
    lifecycle_types = {event["type"] for event in lifecycle}
    assert "provider_request_start" in lifecycle_types
    assert "provider_stream_error" in lifecycle_types
    assert "provider_retry_start" in lifecycle_types
    assert "provider_fallback_selected" in lifecycle_types
    assert "provider_fallback_start" in lifecycle_types
    assert "provider_stream_end" in lifecycle_types


def test_fallback_runtime_events_carry_turn_metadata(monkeypatch):
    def per_model(model):
        if model == "deepseek-v4-flash":
            return ['event: error\ndata: {"status": 503, "error": "offline"}\n\n']
        return ['data: {"delta": "ok"}\n\n', "data: [DONE]\n\n"]

    async def fake_stream(url, model, messages, **kw):
        for ln in per_model(model):
            yield ln

    monkeypatch.setattr(llm_core, "stream_llm", fake_stream)

    async def run():
        out = []
        async for c in llm_core.stream_llm_with_fallback(
            [("https://api.deepseek.com/v1", "deepseek-v4-flash", {}), ("https://mimo.example/v1", "mimo-v2.5-pro", {})],
            [{"role": "user", "content": "hi"}],
            session_id="sess-1",
            turn_id="turn-1",
            stream_id="stream-1",
        ):
            out.append(c)
        return out

    chunks = asyncio.run(run())
    events = [json.loads(c[6:]) for c in chunks if c.startswith("data: ") and c[6:].lstrip().startswith("{")]
    switch = [e for e in events if e.get("type") == "model_switch_visible_event"]
    assert switch, chunks
    assert switch[0]["session_id"] == "sess-1"
    assert switch[0]["turn_id"] == "turn-1"
    assert switch[0]["stream_id"] == "stream-1"
    assert switch[0]["failed_model"] == "deepseek-v4-flash"
    assert switch[0]["model"] == "mimo-v2.5-pro"
    assert "Retrying with fallback model" in switch[0]["message"]
    fallback = [e for e in events if e.get("type") == "fallback"][0]
    assert fallback["answered_by_provider"]
    assert fallback["attempt"] == 2


def test_mid_stream_error_is_not_retried_silently(monkeypatch):
    def per_model(model):
        if model == "primary":
            return [
                'data: {"delta": "partial"}\n\n',
                'event: error\ndata: {"status": 502, "error": "stream died"}\n\n',
            ]
        return ['data: {"delta": "should-not-run"}\n\n', "data: [DONE]\n\n"]

    chunks = _run_fallback(monkeypatch, per_model)
    assert any('"delta": "partial"' in c for c in chunks)
    assert any(c.startswith("event: error") and "stream died" in c for c in chunks)
    assert not any("should-not-run" in c for c in chunks)
    assert any('"type": "provider_stream_error"' in c for c in chunks)


def test_no_fallback_event_when_primary_succeeds(monkeypatch):
    def per_model(model):
        return ['data: {"delta": "ok"}\n\n', "data: [DONE]\n\n"]
    chunks = _run_fallback(monkeypatch, per_model)
    assert not any('"fallback"' in c for c in chunks)


def test_dedupe_candidates_keeps_first_of_each_route():
    """(url, model) is the route key; later repeats are dropped, order preserved,
    the first tuple (with its headers) kept, malformed entries filtered."""
    cands = [
        ("u1", "m1", {"h": 1}),   # first u1/m1 — kept
        ("u1", "m1", {"h": 2}),   # repeat route — dropped (first headers win)
        ("u2", "m2", {}),         # distinct — kept
        ("u1", "m1", {}),         # repeat again — dropped
        (None, "x", {}),          # malformed (no url) — dropped
        ("u3", "", {}),           # malformed (no model) — dropped
    ]
    assert llm_core._dedupe_candidates(cands) == [("u1", "m1", {"h": 1}), ("u2", "m2", {})]
    assert llm_core._dedupe_candidates([]) == []
    assert llm_core._dedupe_candidates(None) == []


def test_duplicate_route_is_attempted_only_once(monkeypatch):
    """A fallback that repeats the primary's (url, model) must NOT make the chain
    sail back into the same dead route — each distinct route is tried once."""
    calls = []

    async def fake_stream(url, model, messages, **kw):
        calls.append((url, model))
        yield 'event: error\ndata: {"status": 503, "text": "down"}\n\n'

    monkeypatch.setattr(llm_core, "stream_llm", fake_stream)

    async def run():
        out = []
        cands = [("u1", "m1", {}), ("u1", "m1", {}), ("u2", "m2", {})]
        async for c in llm_core.stream_llm_with_fallback(cands, [{"role": "user", "content": "hi"}]):
            out.append(c)
        return out

    asyncio.run(run())
    assert calls == [("u1", "m1"), ("u2", "m2")], f"duplicate route re-attempted: {calls}"


def test_summarize_stream_error():
    assert "400" in llm_core._summarize_stream_error('event: error\ndata: {"status": 400, "text": "nope"}\n\n')
    assert llm_core._summarize_stream_error(None) == "primary model failed"
    assert llm_core._summarize_stream_error("garbage") == "primary model failed"
