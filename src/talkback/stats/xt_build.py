"""Learn an expected-threat grid from simulated matches and compare it with the working grid.

    python -m talkback.stats.xt_build --matches 300 --out src/talkback/models/xt_grid_learned.json

The engine and the Stats Desk keep using `xt_grid.json`; the learned grid is
published next to it so the two can be compared (docs/xt.md).
"""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from talkback.models.xg import PITCH_LENGTH, PITCH_WIDTH
from talkback.models.xt import compute_xt_grid, load_xt_grid, save_xt_grid
from talkback.schemas.models import Event
from talkback.sim.engine import simulate_match
from talkback.world.league import generate_league


def _normalise(e: Event, home_id: str) -> Event:
    if e.x is None or e.team_id is None:
        return e
    if (e.team_id == home_id) == (e.period == 1):
        return e
    upd = {"x": PITCH_LENGTH - e.x, "y": PITCH_WIDTH - e.y}
    if e.end_x is not None:
        upd.update(end_x=PITCH_LENGTH - e.end_x, end_y=PITCH_WIDTH - e.end_y)
    return e.model_copy(update=upd)


def _one(args) -> list[Event]:
    seed, hid, aid = args
    lg = generate_league(7)
    events, _ = simulate_match(f"XT{seed:04d}", lg.club(hid), lg.club(aid), seed=seed, frames=False)
    return [_normalise(e, hid) for e in events]


def build(matches: int, seed: int = 5) -> tuple[list[Event], int]:
    lg = generate_league(7)
    ids = [c.id for c in lg.clubs]
    rng = np.random.default_rng(seed)
    jobs = []
    for m in range(matches):
        h, a = rng.choice(len(ids), size=2, replace=False)
        jobs.append((seed * 10_000 + m, ids[h], ids[a]))
    with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 1)) as ex:
        events = [e for chunk in ex.map(_one, jobs, chunksize=2) for e in chunk]
    return events, matches


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, default=300)
    ap.add_argument("--out", type=Path, default=Path("src/talkback/models/xt_grid_learned.json"))
    ap.add_argument("--report", type=Path, default=Path("docs/xt.md"))
    a = ap.parse_args()
    events, n = build(a.matches)
    learned = compute_xt_grid(events)
    save_xt_grid(learned, a.out)
    working = load_xt_grid()
    la, wa = learned.array().ravel(), working.array().ravel()
    r = float(np.corrcoef(la, wa)[0, 1])
    a.report.write_text(
        "# Expected threat grid\n\n"
        f"The working grid (`models/xt_grid.json`) is a smooth prior peaking near the penalty spot. "
        f"Re-learning it by value iteration from {n} simulated matches "
        f"({len(events)} events) gives `models/xt_grid_learned.json`; the two correlate at r = {r:.2f}. "
        f"Peak cell value: working {wa.max():.3f}, learned {la.max():.3f}.\n",
        encoding="utf-8", newline="\n")
    print(f"events {len(events)}  r={r:.3f}  peak working {wa.max():.3f} learned {la.max():.3f}")


if __name__ == "__main__":
    main()
