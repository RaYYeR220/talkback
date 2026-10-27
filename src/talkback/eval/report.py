"""Aggregate per-matchday eval results into one scorecard."""

from __future__ import annotations

SYSTEMS = ("talkback", "talkback_without_clearance", "baseline")
COUNTS = ("lines", "stories_hit", "stories_late", "stories_missed", "must", "numbers", "unverifiable_numbers",
          "overclaims_in_thin_windows", "trivia_intrusions", "mena_spoilers")


def aggregate(results: list[dict]) -> dict:
    systems = {}
    for name in SYSTEMS:
        rows = [r[name] for r in results if name in r]
        if not rows:
            continue
        tot = {k: sum(r.get(k, 0) for r in rows) for k in COUNTS}
        tot["story_recall"] = round(tot["stories_hit"] / max(1, tot["must"]), 3)
        tot["unverifiable_rate"] = round(tot["unverifiable_numbers"] / max(1, tot["numbers"]), 3)
        tot["matchdays"] = len(rows)
        systems[name] = tot
    return {"systems": systems, "matchdays": [r.get("_meta", {}) for r in results]}
