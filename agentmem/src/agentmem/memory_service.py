"""
Core memory service: add, recall, recall(as_of), used by API routes.
"""
from __future__ import annotations
import asyncio
import hashlib
import math
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select, and_, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Memory, EventLog, SubjectKey
from .schemas import MemoryAdd, MemoryOut, RecallRequest, RecallResult
from .embeddings import get_embedding_provider
from .crypto import encrypt_content, decrypt_content, unwrap_subject_key
from .pii import get_or_create_subject_key, destroy_subject_key
from .supersession import run_supersession
from .ranking import hybrid_recall

_IMPORTANCE_RECENCY_HALF_LIFE_DAYS = 90.0


def _write_lock_keys(namespace: str, agent_id: str) -> tuple[int, int]:
    """Two stable int4 values for pg_advisory_xact_lock(int, int)."""
    h = hashlib.sha256(f"{namespace}\x00{agent_id}".encode()).digest()
    return int.from_bytes(h[:4], "big"), int.from_bytes(h[4:8], "big")


# ── In-process lock registry ────────────────────────────────────────────────
# One asyncio.Lock per (event_loop, namespace, agent_id).
# Keyed by loop identity so test-generated loops each get fresh locks.
# No mutex needed: asyncio is cooperative — no interleaving between the
# `if key not in` check and the `_write_locks[key] = ...` assignment.
_write_locks: dict[tuple[int, str, str], asyncio.Lock] = {}


async def _get_in_process_lock(namespace: str, agent_id: str) -> asyncio.Lock:
    """Return (creating if needed) the asyncio.Lock for this (namespace, agent_id)."""
    loop = asyncio.get_running_loop()
    key = (id(loop), namespace, agent_id)
    if key not in _write_locks:
        _write_locks[key] = asyncio.Lock()
    return _write_locks[key]


async def _acquire_pg_advisory_lock(db: AsyncSession, namespace: str, agent_id: str) -> None:
    """
    Layer 2: PostgreSQL transaction-level advisory lock — cross-process guard.

    Released automatically on commit or rollback.  A second writer (in a different
    worker process) with the same namespace+agent_id blocks here until the first
    writer's transaction commits, then re-reads candidates with updated valid_to.

    No-op on SQLite (unit tests) — Layer 1 (asyncio.Lock) covers in-process races.
    """
    try:
        engine = db.sync_session.get_bind()
        if engine.dialect.name != "postgresql":
            return
    except Exception:
        return
    k1, k2 = _write_lock_keys(namespace, agent_id)
    await db.execute(text("SELECT pg_advisory_xact_lock(:k1, :k2)"), {"k1": k1, "k2": k2})


def _compute_importance(event_time: datetime, caller_salience: float) -> float:
    """Blend caller-provided salience with event-time recency."""
    now = datetime.now(timezone.utc)
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    age_days = (now - event_time).total_seconds() / 86400
    recency = math.exp(-math.log(2) * age_days / _IMPORTANCE_RECENCY_HALF_LIFE_DAYS)
    return round(0.4 * recency + 0.6 * caller_salience, 4)


async def _load_namespace_subject_keys(db: AsyncSession, namespace: str) -> dict[str, bytes]:
    """Load all active subject keys for a namespace (for decrypting recalled memories)."""
    stmt = select(SubjectKey).where(
        and_(
            SubjectKey.namespace == namespace,
            SubjectKey.destroyed_at.is_(None),
        )
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    keys: dict[str, bytes] = {}
    for row in rows:
        try:
            keys[row.subject_id] = unwrap_subject_key(bytes(row.enc_key))
        except Exception:
            pass
    return keys


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _memory_to_out(mem: Memory, content: Optional[str]) -> MemoryOut:
    return MemoryOut(
        id=mem.id,
        namespace=mem.namespace,
        agent_id=mem.agent_id,
        content=content,
        subject_id=mem.subject_id,
        event_time=mem.event_time,
        ingestion_time=mem.ingestion_time,
        valid_from=mem.valid_from,
        valid_to=mem.valid_to,
        superseded_by=mem.superseded_by,
        supersession_confidence=mem.supersession_confidence,
        importance=mem.importance,
        source=mem.source,
        content_hash=mem.content_hash,
        erased_at=mem.erased_at,
        metadata=dict(mem.metadata_ or {}),
    )


async def add_memory(
    db: AsyncSession,
    namespace: str,
    req: MemoryAdd,
) -> MemoryOut:
    provider = get_embedding_provider()
    embedding = await provider.embed_one(req.content)

    # Resolve subject key if PII
    subject_key: Optional[bytes] = None
    if req.subject_id:
        subject_key = await get_or_create_subject_key(db, req.subject_id, namespace)

    # Encrypt content outside the lock (pure CPU, no DB I/O)
    stored_bytes = (
        encrypt_content(req.content, subject_key) if subject_key else req.content.encode()
    )

    # ── Critical section ────────────────────────────────────────────────────
    # Two-layer write serialisation for (namespace, agent_id):
    #   Layer 1 — asyncio.Lock: in-process (single worker or test)
    #   Layer 2 — pg_advisory_xact_lock: cross-process (multi-worker)
    # Both are acquired before reading supersession candidates; Layer 2 is
    # released automatically on db.commit() / rollback.
    in_process_lock = await _get_in_process_lock(namespace, req.agent_id)
    async with in_process_lock:
        await _acquire_pg_advisory_lock(db, namespace, req.agent_id)

        supersession = await run_supersession(
            db=db,
            namespace=namespace,
            agent_id=req.agent_id,
            new_content=req.content,
            new_meta=req.metadata,
            new_embedding=embedding,
            new_event_time=req.event_time,
            subject_key=subject_key,
        )

        now = datetime.now(timezone.utc)
        mem = Memory(
            namespace=namespace,
            agent_id=req.agent_id,
            content_encrypted=stored_bytes,
            subject_id=req.subject_id,
            embedding=embedding,
            metadata_=req.metadata,
            event_time=req.event_time,
            ingestion_time=now,
            valid_from=req.event_time,
            valid_to=None,
            importance=_compute_importance(req.event_time, req.importance),
            source=req.source,
            content_hash=_content_hash(req.content),
        )
        db.add(mem)
        await db.flush()  # get mem.id

        for old_id in supersession.superseded_ids:
            old = await db.get(Memory, old_id)
            if old:
                old.valid_to = req.event_time
                old.superseded_by = mem.id
                old.supersession_confidence = supersession.confidence
                db.add(EventLog(
                    namespace=namespace,
                    agent_id=req.agent_id,
                    op="supersede",
                    memory_id=old.id,
                    content_hash=old.content_hash,
                    payload={
                        "superseded_by": str(mem.id),
                        "confidence": supersession.confidence,
                        "relation": supersession.relation,
                        "rationale": supersession.rationale,
                        "adjudication_stage": 3 if supersession.rationale else 2,
                    },
                ))

        db.add(EventLog(
            namespace=namespace,
            agent_id=req.agent_id,
            op="add",
            memory_id=mem.id,
            content_hash=mem.content_hash,
            payload={
                "source": req.source,
                "event_time": req.event_time.isoformat(),
                "metadata": req.metadata,
                "supersession_relation": supersession.relation,
                "supersession_confidence": supersession.confidence,
            },
        ))

        await db.commit()
    # ── End critical section ────────────────────────────────────────────────

    await db.refresh(mem)
    return _memory_to_out(mem, req.content)


async def recall_memories(
    db: AsyncSession,
    namespace: str,
    req: RecallRequest,
) -> RecallResult:
    provider = get_embedding_provider()
    query_embedding = await provider.embed_one(req.query)
    subject_keys = await _load_namespace_subject_keys(db, namespace)

    results = await hybrid_recall(
        db=db,
        namespace=namespace,
        agent_id=req.agent_id,
        query=req.query,
        query_embedding=query_embedding,
        k=req.k,
        as_of=req.as_of,
        filters=req.filters,
        subject_keys=subject_keys,
    )

    # Audit log the recall
    db.add(EventLog(
        namespace=namespace,
        agent_id=req.agent_id,
        op="recall",
        memory_id=None,
        content_hash=None,
        payload={
            "query_hash": _content_hash(req.query),
            "k": req.k,
            "as_of": req.as_of.isoformat() if req.as_of else None,
            "filters": req.filters,
            "result_ids": [str(m.id) for m, _, _ in results],
            "scores": [round(float(s), 4) for _, s, _ in results],
        },
    ))
    await db.commit()

    memories_out = [_memory_to_out(mem, content) for mem, _, content in results]
    return RecallResult(
        memories=memories_out,
        as_of=req.as_of,
        total_candidates=len(results),
    )


async def erase_subject(
    db: AsyncSession,
    namespace: str,
    subject_id: str,
    request_ref: str,
) -> int:
    """
    Crypto-shred a data subject: null out content, destroy their key, write
    an immutable erase event to the audit log.  Returns count of erased rows.
    """
    stmt = select(Memory).where(
        and_(
            Memory.namespace == namespace,
            Memory.subject_id == subject_id,
            Memory.erased_at.is_(None),
        )
    )
    result = await db.execute(stmt)
    memories = result.scalars().all()

    now = datetime.now(timezone.utc)
    for mem in memories:
        mem.content_encrypted = None
        mem.erased_at = now
        db.add(EventLog(
            namespace=namespace,
            agent_id=mem.agent_id,
            op="erase",
            memory_id=mem.id,
            content_hash=mem.content_hash,
            payload={"subject_id": subject_id, "request_ref": request_ref},
        ))

    await destroy_subject_key(db, subject_id)
    await db.commit()
    return len(memories)
