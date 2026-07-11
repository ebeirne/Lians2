"""
LongMemEval — Lians retrieval dump for the mem0ai/memory-benchmarks harness.

Same play as ``locomo_dump_mem0.py``: for each of the 500 LongMemEval-S
questions, embed its haystack (per-message, arctic), score with the engine's
tuned blend (0.50·sem with temporal-context smoothing 0.3 + 0.05·BM25 +
temporal query grounding 0.1), and write the top-200 as a per-question JSON
in the harness's predict format. Their ``--evaluate-only`` then runs the
unmodified answer+judge pipeline (gpt-5) over these files.

The scoring pipeline is the validated engine replica (100% agreement vs live
recall on all 1,982 LOCOMO questions); spot-verify per-question here the same
way if a claim needs it.

Per-question embedding caches land in results/longmemeval_cache/ so the run
is resumable at question granularity (skips questions whose output exists).

Usage (from agentmem root):
    python -m benchmarks.longmemeval_lians --out ../memory-benchmarks/results/longmemeval/predicted_lians_arctic
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from benchmarks.locomo_replay import _bm25_tokens, _BM25_K1, _BM25_B, _BM25_AVG_DOC_LEN  # noqa: E402
from src.lians.ranking import query_time_windows  # noqa: E402

_DATASET = _REPO.parent / "memory-benchmarks" / "datasets" / "longmemeval" / "longmemeval_s_cleaned.json"
_CACHE = _REPO / "results" / "longmemeval_cache"

MODEL = "Snowflake/snowflake-arctic-embed-l-v2.0"
QUERY_PREFIX = "query: "
W_SEM, W_LEX, SMOOTH, T_BONUS = 0.50, 0.05, 0.3, 0.1
TOP_K = 200


def _parse_session_date(raw: str) -> datetime:
    """LongMemEval date: '2023/05/20 (Sat) 02:21'."""
    for fmt in ("%Y/%m/%d (%a) %H:%M", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime(2023, 1, 1, tzinfo=timezone.utc)


def _bm25_scores(query: str, doc_tf: list[dict], doc_len: list[int]) -> np.ndarray:
    q_tokens = set(_bm25_tokens(query))
    out = np.zeros(len(doc_tf), dtype=np.float32)
    if not q_tokens:
        return out
    for i, (tf, dl) in enumerate(zip(doc_tf, doc_len)):
        if not dl:
            continue
        denom_len = _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / _BM25_AVG_DOC_LEN)
        s = 0.0
        for t in q_tokens:
            f = tf.get(t, 0)
            if f:
                s += (f * (_BM25_K1 + 1)) / (f + denom_len)
        out[i] = s / len(q_tokens)
    return out


def build_docs(question: dict):
    """Flatten haystack sessions into (content, iso_time, ts) doc lists."""
    contents, times, ts = [], [], []
    for sess, date_str in zip(question["haystack_sessions"], question["haystack_dates"]):
        when = _parse_session_date(date_str)
        for j, msg in enumerate(sess):
            text = (msg.get("content") or "").strip()
            if not text:
                continue
            t = when + timedelta(seconds=j)
            contents.append(f"{msg.get('role', 'user')}: {text}")
            times.append(t.isoformat())
            ts.append(t.timestamp())
    return contents, times, np.array(ts, dtype=np.float64)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    from sentence_transformers import SentenceTransformer

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    _CACHE.mkdir(parents=True, exist_ok=True)
    dataset = json.loads(_DATASET.read_text(encoding="utf-8"))
    if args.limit:
        dataset = dataset[: args.limit]
    model = SentenceTransformer(MODEL)

    for qn, question in enumerate(dataset):
        qid = question["question_id"]
        out_path = out_dir / f"{qid}.json"
        if out_path.exists():
            continue

        contents, times, ts = build_docs(question)

        cache = _CACHE / f"{qid}.npz"
        if cache.exists():
            z = np.load(cache)
            doc_embs, q_emb = z["doc_embs"], z["q_emb"]
        else:
            doc_embs = model.encode(contents, normalize_embeddings=True,
                                    batch_size=32, show_progress_bar=False)
            q_emb = model.encode([QUERY_PREFIX + question["question"]],
                                 normalize_embeddings=True,
                                 show_progress_bar=False)[0]
            np.savez_compressed(cache, doc_embs=doc_embs.astype(np.float32),
                                q_emb=q_emb.astype(np.float32))

        sem = doc_embs @ q_emb.astype(np.float32)

        # temporal-context smoothing over event_time adjacency (same-session
        # messages are seconds apart; sessions are days apart)
        order_t = np.argsort(ts, kind="stable")
        nb_best = np.zeros_like(sem)
        for pos, i in enumerate(order_t):
            for nb_pos in (pos - 1, pos + 1):
                if 0 <= nb_pos < len(order_t):
                    j = order_t[nb_pos]
                    if abs(ts[i] - ts[j]) <= 3600 and sem[j] > nb_best[i]:
                        nb_best[i] = sem[j]

        doc_tf, doc_len = [], []
        for c in contents:
            toks = _bm25_tokens(c)
            tf: dict[str, int] = {}
            for tkn in toks:
                tf[tkn] = tf.get(tkn, 0) + 1
            doc_tf.append(tf)
            doc_len.append(len(toks))

        scores = W_SEM * (sem + SMOOTH * nb_best) + W_LEX * _bm25_scores(question["question"], doc_tf, doc_len)
        wins = query_time_windows(question["question"])
        if wins:
            scores = scores + np.array(
                [T_BONUS if any(lo <= t <= hi for lo, hi in wins) else 0.0 for t in ts],
                dtype=np.float32)

        top = np.argsort(-scores, kind="stable")[:TOP_K]
        search_results = [{
            "memory": contents[i],
            "score": round(float(scores[i]), 6),
            "id": f"{qid}_{i}",
            "created_at": times[i],
        } for i in top]

        out_path.write_text(json.dumps({
            "question_id": qid,
            "question_type": question["question_type"],
            "question": question["question"],
            "ground_truth_answer": str(question["answer"]),
            "question_date": question.get("question_date", ""),
            "is_abstention": qid.endswith("_abs"),
            "user_id": f"lians_lme_{qid}",
            "answer_session_ids": question.get("answer_session_ids", []),
            "retrieval": {
                "search_query": question["question"],
                "search_results": search_results,
                "search_latency_ms": 0.0,
                "total_results": len(search_results),
            },
        }, indent=1), encoding="utf-8")

        if (qn + 1) % 10 == 0:
            print(f"{qn + 1}/{len(dataset)} questions dumped "
                  f"(last: {qid}, {len(contents)} docs)", flush=True)

    print(f"done -> {out_dir}")


if __name__ == "__main__":
    main()
