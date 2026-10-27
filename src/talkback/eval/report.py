"""Aggregate per-matchday eval results into one scorecard."""

from __future__ import annotations

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
