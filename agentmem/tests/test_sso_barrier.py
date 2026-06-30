"""
SSO -> barrier mapping: an API key's barrier_group (chosen by the SSO gateway from
the caller's IdP group) scopes both writes (tagging) and reads (isolation).
"""
from __future__ import annotations

import hashlib
import pytest
import pytest_asyncio
from datetime import datetime, timezone

from httpx import AsyncClient, ASGITransport

from src.lians.main import app
from src.lians.db import get_db
from src.lians.models import ApiKey

NS = "sso-ns"
AGENT = "sso-agent"
T = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _sha(k):
    return hashlib.sha256(k.encode()).hexdigest()


@pytest_asyncio.fixture
async def client(db):
    # Three keys in one namespace: two walled desks + one unbarriered (compliance).
    db.add(ApiKey(hashed_key=_sha("kA"), namespace=NS, scopes=["read", "write"], barrier_group="deskA"))
    db.add(ApiKey(hashed_key=_sha("kB"), namespace=NS, scopes=["read", "write"], barrier_group="deskB"))
    db.add(ApiKey(hashed_key=_sha("kC"), namespace=NS, scopes=["read", "write"]))  # unbarriered
    await db.commit()

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


def _h(key):
    return {"X-API-Key": key}


async def _add(client, key, content):
    r = await client.post("/v1/memories", headers=_h(key),
                          json={"agent_id": AGENT, "content": content, "event_time": T.isoformat()})
    assert r.status_code == 200, r.text
    return r.json()


async def _recall(client, key):
    r = await client.post("/v1/recall", headers=_h(key),
                          json={"agent_id": AGENT, "query": "trade idea NVDA", "k": 10})
    assert r.status_code == 200
    return [(m.get("content") or "") for m in r.json()["memories"]]


@pytest.mark.asyncio
async def test_write_tagged_with_key_barrier(client):
    out = await _add(client, "kA", "deskA trade idea NVDA long")
    assert out["barrier_group"] == "deskA"


@pytest.mark.asyncio
async def test_reads_isolated_by_barrier(client):
    await _add(client, "kA", "deskA trade idea NVDA long")
    await _add(client, "kB", "deskB trade idea NVDA short")

    a_sees = await _recall(client, "kA")
    assert any("deskA" in c for c in a_sees)
    assert not any("deskB" in c for c in a_sees)   # cannot cross the wall

    b_sees = await _recall(client, "kB")
    assert any("deskB" in c for c in b_sees)
    assert not any("deskA" in c for c in b_sees)


@pytest.mark.asyncio
async def test_unbarriered_key_sees_all(client):
    await _add(client, "kA", "deskA trade idea NVDA long")
    await _add(client, "kB", "deskB trade idea NVDA short")
    c_sees = await _recall(client, "kC")
    assert any("deskA" in c for c in c_sees) and any("deskB" in c for c in c_sees)
