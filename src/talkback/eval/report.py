"""Aggregate per-matchday eval results into one scorecard."""

from __future__ import annotations

import math

from talkback.eval.score import SYSTEMS

COUNTS = ("lines", "stories_hit", "stories_late", "stories_missed", "must", "numbers", "unverifiable_numbers",
          "overclaims_in_thin_windows", "trivia_intrusions", "mena_spoilers")


def _row(result: dict, name: str) -> dict:
    """A system's scores on one matchday; a system missing from it aired nothing and missed every must story."""
    if name in result:
        return result[name]
    must = next((r["must"] for k, r in result.items() if not k.startswith("_") and "must" in r), 0)
    return {"must": must, "stories_missed": must}


def aggregate(results: list[dict]) -> dict:
    systems = {}
    for name in SYSTEMS:
        rows = [_row(r, name) for r in results]
        tot = {k: sum(r.get(k, 0) for r in rows) for k in COUNTS}
        tot["story_recall"] = round(tot["stories_hit"] / max(1, tot["must"]), 3)
        tot["unverifiable_rate"] = round(tot["unverifiable_numbers"] / max(1, tot["numbers"]), 3)
        tot["matchdays"] = len(rows)
        systems[name] = tot
    return {"systems": systems, "matchdays": [r.get("_meta", {}) for r in results]}


_WEB_SYSTEMS = [
    ("talkback", "talkback", "Talkback", "The full crew: separate agents, code-enforced clearance, territory desks."),
    ("baseline", "baseline", "Single-model baseline",
     "One model call per match segment and one at full time, with the same season data sheet, events and model."),
    ("talkback_without_clearance", "negative_control", "Clearance off",
     "Every line Talkback drafted, counted as if it had aired everywhere: what the gate removes."),
]
# (metric id on the page, key in the aggregate, label, unit, better, description)
_WEB_METRICS = [
    ("story_recall", "story_recall", "Story Recall", "ratio", "higher",
     "Must-surface storylines from the sealed key that reached air in time (live or in the recap)."),
    ("unverifiable_numbers", "unverifiable_rate", "Unverifiable numbers", "ratio", "lower",
     "Share of numbers on air that match nothing the gallery could have cited at that time."),
    ("over_claims", "overclaims_in_thin_windows", "Over-claims in thin windows", "count", "lower",
     "Lines in the first 8 minutes whose wording reaches strength level 2 or more."),
    ("spoilers", "mena_spoilers", "Spoilers in the delayed territory", "count", "lower",
     "Lines aired to MENA naming a club from another match within two minutes of its goal."),
    ("distractor_intrusion", "trivia_intrusions", "Trivia intrusion", "count", "lower",
     "Lines that aired one of the planted trivial facts."),
]


def _percentile(values: list[int], q: float) -> int | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(q * len(s)) - 1)]


def to_web(summary: dict, latencies_ms: list[int], generated_at: str,
           seeds: tuple[int, ...] = (2031, 2032, 2033, 2034, 2035)) -> dict:
    """The scorecard the web Proof page reads: only what the evaluation measured."""
    systems = summary["systems"]
    present = [s for s in _WEB_SYSTEMS if s[0] in systems]
    metas = summary.get("matchdays", [])
    return {
        "provisional": False,
        "note": "Pre-registered evaluation (docs/preregistration.md); sealed keys verified before scoring.",
        "generated_at": generated_at,
        "setup": {"matchdays": len(metas), "matches_per_matchday": 10,
                  "seeds": [m.get("run", "") for m in metas],
                  "sealed_key_sha256": [m.get("key_sha256") for m in metas]},
        "systems": [{"id": web_id, "label": label, "description": desc} for _, web_id, label, desc in present],
        "metrics": [{"id": mid, "label": label, "description": desc, "unit": unit, "better": better,
                     "headline": mid == "story_recall",
                     "values": {web_id: systems[key][field] for key, web_id, _, _ in present}}
                    for mid, field, label, unit, better, desc in _WEB_METRICS],
        "latency": {"description": "Moment spotted to line on air, Talkback only.",
                    "p50_ms": _percentile(latencies_ms, 0.5), "p95_ms": _percentile(latencies_ms, 0.95)},
        "reproduce": [f"uv run talkback eval-all --seeds {' '.join(str(s) for s in seeds)} --speed 6"],
    }
