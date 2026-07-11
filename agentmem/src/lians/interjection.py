"""
Deterministic interjection extraction — sub-turn durable facts.

Conversational turns bury durable personal facts as mid-clause asides:
"...their whole team flying into my studio in Portland and they won't all
know each other", or "remind me I eat fish now" dropped mid-pricing-math.
Stored whole, the turn's embedding dilutes the fact — recall misses it, and
unkeyed supersession can never match a revision to it because turn-vs-turn
cosine stays below the cue threshold (the agent_sim finding, 2026-07-10).

When ``interjection_extraction_enabled`` is on, ``add_memory`` extracts such
clauses and stores each as a *derived* memory alongside the raw turn:

  * rule-based (clause splitting + cue lexicon) — deterministic, reproducible,
    no model call, same posture as auto_metadata;
  * derived rows are provenance-tagged (``metadata._derived`` /
    ``metadata._parent``) and drop structured keys, so a clause can never trip
    keyed supersession against its own parent;
  * the raw turn stays the auditable record — derived rows are a recall and
    supersession surface, closable and time-travelable like any memory.
"""
from __future__ import annotations

import re
from typing import Optional

_MAX_CLAUSES = 3
_MIN_LEN = 15
_MAX_LEN = 240

# Leading "Speaker: " attribution on conversational content; re-applied to
# extracted clauses so they stay self-attributing.
_SPEAKER_RE = re.compile(r"^([A-Za-z][\w .'&-]{0,24}):\s+(.*)$", re.DOTALL)

# Segment boundaries: sentence enders and spoken-style em/en dashes.
_SEGMENT_SPLIT = re.compile(r"(?<=[.!?…])\s+|\s+[—–]\s*|\s*[—–]\s+|\s+--\s+")

# Conservative intra-segment clause connectors. Splitting is only ever on
# these; a fact stated across a bare comma ("I eat fish now, I'm not
# vegetarian anymore") stays intact.
_CLAUSE_SPLIT = re.compile(
    r",\s+(?:so|since|because|but|although|though|anyway)\b\s*|\s+because\s+"
    # a first-person fact riding a conjunction ("...steakhouse and I'm
    # pescatarian now") splits off; "and they/it/..." stays joined.
    r"|,?\s+and\s+(?=I\b|I'm\b|my\b)",
    re.IGNORECASE,
)

# Aside markers: the clause is an explicit "store this" interjection — trim to
# the marker so the stored fact starts at the request, not the task chatter.
_ASIDE_CUES = re.compile(
    r"\b(?:remind me|reminder (?:to|for) (?:myself|me)|note to self|"
    r"don'?t forget|for the record|remember that|"
    r"I should (?:tell|mention|say)|I need to tell|by the way)\b",
    re.IGNORECASE,
)

# Durable personal-fact patterns: first-person state that outlives the task.
_FACT_CUES = re.compile(
    r"\bmy\s+(?:\w+\s+){0,3}?(?:is|are|was|were|went|now|changed|moved|renewed|"
    r"increased|decreased)\b"
    r"|\bmy\s+\w+(?:\s+\w+)?\s+in\s+[A-Z][a-z]"
    r"|\bI(?:'m| am)\s+(?:allergic|vegetarian|vegan|pescatarian|gluten|lactose|"
    r"based|located)\b"
    r"|\bI\s+(?:now\s+|just\s+|\w+ly\s+)?(?:eat|live|work|drive|prefer|use|go by)\b"
    r"|\bI(?:'m| am)\s+(?:at|with)\s+[A-Z][\w']"
    # habitual adverb + verb is a durable fact by construction
    # ("I usually do a day rate, which is $900")
    r"|\bI\s+(?:usually|typically|normally|always)\s+\w+",
)


def _clauses(body: str) -> list[tuple[str, str]]:
    """(clause, enclosing_segment) pairs. A cue clause that connector-splitting
    left too short ("my day rate is $900" before ", so we can build off that")
    falls back to its segment, so the fact is never dropped on a length gate."""
    out: list[tuple[str, str]] = []
    for segment in _SEGMENT_SPLIT.split(body):
        segment = (segment or "").strip(" ,;")
        if not segment:
            continue
        for clause in _CLAUSE_SPLIT.split(segment):
            clause = (clause or "").strip(" ,;")
            if clause:
                out.append((clause, segment))
    return out


def extract_interjections(content: str, max_clauses: int = _MAX_CLAUSES) -> list[str]:
    """Return durable-fact clauses buried in a conversational turn.

    Empty when the content is short/single-clause (the whole turn already IS
    the fact — extraction would just duplicate it) or when no cue fires.
    """
    if not content:
        return []

    speaker: Optional[str] = None
    body = content.strip()
    m = _SPEAKER_RE.match(body)
    if m:
        speaker, body = m.group(1), m.group(2).strip()

    clauses = _clauses(body)
    if len(clauses) < 2:
        return []

    found: list[str] = []
    seen: set[str] = set()
    for clause, segment in clauses:
        # An aside marker trims the clause to the request itself ("remind me I
        # eat fish now") — but a trailing marker ("my day rate is $900 by the
        # way") leaves nothing after it, so fall back to the fact-cue whole
        # clause in that case.
        aside = _ASIDE_CUES.search(clause)
        if aside:
            tail = clause[aside.start():].strip(" ,;")
            if len(tail) >= _MIN_LEN:
                clause = tail
            elif not _FACT_CUES.search(clause):
                continue
        elif not _FACT_CUES.search(clause):
            continue
        if len(clause) < _MIN_LEN:
            clause = segment  # cue fired but the split left a stub — keep its segment
        if not (_MIN_LEN <= len(clause) <= _MAX_LEN):
            continue
        if len(clause) >= 0.8 * len(body):
            continue  # not buried — the turn is essentially this clause already
        key = clause.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(f"{speaker}: {clause}" if speaker else clause)
        if len(found) >= max_clauses:
            break
    return found
