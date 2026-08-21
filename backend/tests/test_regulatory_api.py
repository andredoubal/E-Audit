"""End-to-end walk over the regulatory endpoints via FastAPI's TestClient. No API key is set
in the test environment (conftest.py), so the streamed answer exercises the deterministic
fallback path — the live path is covered by test_regulatory_llm_path.py's SDK stub."""
from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client(reg_seeded):
    return TestClient(app)


def test_query_returns_a_trace_id_and_citations(client):
    r = client.post("/api/regulatory/query", json={
        "question": "What does Article 49 say about adjustments?",
        "regulation_code": "TEST-IR",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["trace_id"]
    assert body["cited_units"]
    assert any(u["unit_id"] == "TEST-IR-A49" for u in body["cited_units"])


def test_trace_endpoint_returns_the_persisted_candidates(client):
    q = client.post("/api/regulatory/query", json={
        "question": "credit or debit note evidencing an altered consideration",
        "regulation_code": "TEST-IR",
    }).json()
    r = client.get(f"/api/regulatory/trace/{q['trace_id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "credit or debit note evidencing an altered consideration"
    assert body["candidates"]
    assert body["chosen_chunks"]


def test_unknown_trace_id_is_404(client):
    assert client.get("/api/regulatory/trace/999999").status_code == 404
    assert client.get("/api/regulatory/ask/999999").status_code == 404


def test_ask_streams_the_deterministic_fallback_with_no_api_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_PROFILE", raising=False)
    q = client.post("/api/regulatory/query", json={
        "question": "What does Article 49 say about adjustments?",
        "regulation_code": "TEST-IR",
    }).json()
    r = client.get(f"/api/regulatory/ask/{q['trace_id']}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "event: fallback" in r.text or "event: done" in r.text
    assert "deterministic-fallback" in r.text


def test_tax_period_resolves_version_and_flags_gaps(client):
    r = client.post("/api/regulatory/query", json={
        "question": "What does Article 49 say?",
        "regulation_code": "TEST-IR",
        "tax_period": "2019-01-01",  # before the fixture's effective_from (2020-01-01)
    })
    body = r.json()
    a49 = next(u for u in body["cited_units"] if u["unit_id"] == "TEST-IR-A49")
    assert a49["status"] == "NEEDS_LEGAL_VALIDATION"
