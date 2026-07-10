"""
A/B trial on the persisted diag db: score conversation 1's headline questions
with (a) present-time recall and (b) recall as_of the conversation's end.

Usage:  python -m benchmarks.locomo_asof_trial
"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "sdk" / "python"))

from benchmarks.locomo_eval import (  # noqa: E402
    _DATA, iter_sessions, _retrieved_ids,
)


def score(client, agent, qa, k=10, as_of=None):
    n = hit = 0
    by_cat: dict[int, list[int]] = {}
    for q in qa:
        cat = int(q.get("category", 0))
        if cat == 5:
            continue
        evidence = [str(e) for e in (q.get("evidence") or [])]
        if not evidence:
            continue
        kwargs = {"as_of": as_of} if as_of else {}
        res = client.recall(agent_id=agent, query=q["question"], k=k, **kwargs)
        ids = _retrieved_ids(res)
        ok = any(e in ids for e in evidence)
        n += 1
        hit += int(ok)
        by_cat.setdefault(cat, [0, 0])
        by_cat[cat][0] += int(ok)
        by_cat[cat][1] += 1
    return hit / n, n, {c: v[0] / v[1] for c, v in sorted(by_cat.items())}


def main() -> None:
    dataset = json.loads(Path(_DATA).read_text(encoding="utf-8"))
    sample = dataset[0]
    agent = f"diag-{sample['sample_id']}"

    last = max(when for _, when, _ in iter_sessions(sample["conversation"]))
    as_of = last + timedelta(days=1)
    print(f"conversation ends {last:%Y-%m-%d}; as_of = {as_of:%Y-%m-%d}")

    from lians import LocalLiansClient

    db = str(Path(__file__).parent / "data" / "locomo_diag.sqlite")
    with LocalLiansClient(db_path=db) as client:
        cur, n, cats_cur = score(client, agent, sample["qa"], k=10)
        pit, _, cats_pit = score(client, agent, sample["qa"], k=10, as_of=as_of)

    print(f"\nheadline (cats 1-4, n={n}), evidence_hit@10")
    print(f"  present-time recall : {cur:.1%}   by cat: "
          f"{ {c: round(v, 3) for c, v in cats_cur.items()} }")
    print(f"  as_of conversation  : {pit:.1%}   by cat: "
          f"{ {c: round(v, 3) for c, v in cats_pit.items()} }")


if __name__ == "__main__":
    main()
