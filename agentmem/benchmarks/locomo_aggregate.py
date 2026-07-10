"""
Aggregate per-conversation LOCOMO reports (results/locomo/conv_*.json) into
one overall table, recomputed from the per-question detail.

Usage:  python -m benchmarks.locomo_aggregate [results/locomo]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from benchmarks.locomo_eval import CATEGORY_NAMES


def main() -> None:
    d = Path(sys.argv[1] if len(sys.argv) > 1 else "results/locomo")
    files = sorted(d.glob("conv_*.json"))
    if not files:
        print(f"no conv_*.json in {d}")
        return

    detail = []
    k = None
    for f in files:
        r = json.loads(f.read_text(encoding="utf-8"))
        k = r["k"]
        detail.extend(r["detail"])

    stats: dict[int, dict[str, int]] = {}
    for q in detail:
        s = stats.setdefault(int(q["category"]), {"n": 0, "any": 0, "all": 0})
        s["n"] += 1
        s["any"] += int(q["hit_any"])
        s["all"] += int(q["hit_all"])

    head = [c for c in stats if c != 5]
    hn = sum(stats[c]["n"] for c in head)
    hany = sum(stats[c]["any"] for c in head)
    hall = sum(stats[c]["all"] for c in head)

    print(f"LOCOMO aggregate · {len(files)} conversations · "
          f"{len(detail)} questions · k={k}")
    print(f"HEADLINE (cats 1-4, n={hn}): evidence_hit@{k} = {hany / hn:.1%}   "
          f"evidence_all@{k} = {hall / hn:.1%}")
    for c, s in sorted(stats.items()):
        print(f"  {CATEGORY_NAMES.get(c, str(c)):<12} n={s['n']:<5} "
              f"hit@k={s['any'] / s['n']:.1%}  all@k={s['all'] / s['n']:.1%}")

    out = d / "aggregate.json"
    out.write_text(json.dumps({
        "conversations": len(files), "questions": len(detail), "k": k,
        "headline": {"n": hn, "evidence_hit_at_k": round(hany / hn, 4),
                     "evidence_all_at_k": round(hall / hn, 4)},
        "by_category": {
            CATEGORY_NAMES.get(c, str(c)): {
                "n": s["n"],
                "evidence_hit_at_k": round(s["any"] / s["n"], 4),
                "evidence_all_at_k": round(s["all"] / s["n"], 4),
            } for c, s in sorted(stats.items())
        },
    }, indent=2), encoding="utf-8")
    print(f"\naggregate -> {out}")


if __name__ == "__main__":
    main()
