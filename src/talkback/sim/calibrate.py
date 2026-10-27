"""Calibration of the 10 Hz engine against public league-average aggregates.

    python -m talkback.sim.calibrate --n 500 --out docs/calibration.md
"""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from talkback.schemas.models import EventType, Outcome
from talkback.sim.engine import simulate_match
from talkback.world.league import generate_league

# Public per-match aggregates for a top European league (both teams combined).
TARGETS = {
    "goals": ("Goals", 2.8, (2.3, 3.3)),
    "shots": ("Shots", 25.0, (20, 30)),
    "on_target_share": ("Shots on target share", 0.34, (0.28, 0.42)),
    "passes": ("Passes", 950.0, (750, 1100)),
    "pass_completion": ("Pass completion", 0.82, (0.76, 0.87)),
    "ppda": ("PPDA (per team)", 11.0, (7, 15)),
    "fouls": ("Fouls", 21.0, (15, 26)),
    "corners": ("Corners", 10.0, (7, 13)),
    "yellows": ("Yellow cards", 3.6, (2.5, 5)),
    "outfield_km": ("Distance per outfield starter (km)", 10.5, (9.0, 12.0)),
}


def match_stats(args: tuple[int, str, str, int]) -> dict[str, float]:
    seed, hid, aid, league_seed = args
    lg = generate_league(league_seed)
    home, away = lg.club(hid), lg.club(aid)
    events, frames = simulate_match(f"CAL{seed:04d}", home, away, seed=seed, frames=True)
    by = lambda t: [e for e in events if e.type == t]
    passes = by(EventType.pass_)
    shots = by(EventType.shot)
    on_t = sum(e.outcome in (Outcome.goal, Outcome.saved) for e in shots)
    ppda = []
    for k, (team, opp) in enumerate(((hid, aid), (aid, hid))):
        opp_passes = 0
        actions = 0
        for e in events:
            if e.x is None:
                continue
            # opponent's own 60%: measured from the opponent's goal
            opp_attacks_right = (opp == hid) == (e.period == 1)
            xn = e.x / 105 if opp_attacks_right else 1 - e.x / 105
            if e.type == EventType.pass_ and e.team_id == opp and xn < 0.6:
                opp_passes += 1
            if e.team_id == team and e.type in (EventType.tackle, EventType.interception, EventType.foul) and xn < 0.6:
                actions += 1
        if actions:
            ppda.append(opp_passes / actions)
    # distance per outfield player who was on the pitch at least 85 minutes
    dist: dict[str, float] = {}
    seen: dict[str, int] = {}
    prev = None
    for fr in frames[::10]:
        if prev is not None:
            pmap = dict(zip(prev.ids, prev.pos))
            for pid, p in zip(fr.ids, fr.pos):
                if pid in pmap:
                    dist[pid] = dist.get(pid, 0.0) + float(np.linalg.norm(p - pmap[pid]))
                    seen[pid] = seen.get(pid, 0) + 1
        prev = fr
    gks = {p.id for c in (home, away) for p in c.squad if p.position == "GK"}
    full = [d / 1000 for pid, d in dist.items() if pid not in gks and seen[pid] >= 0.88 * (len(frames) // 10)]
    return {
        "goals": len(by(EventType.goal)), "shots": len(shots),
        "on_target_share": on_t / max(1, len(shots)), "passes": len(passes),
        "pass_completion": float(np.mean([e.outcome == Outcome.success for e in passes])) if passes else 0.0,
        "ppda": float(np.mean(ppda)) if ppda else 0.0, "fouls": len(by(EventType.foul)),
        "corners": len(by(EventType.corner)),
        "yellows": sum(e.outcome == Outcome.yellow for e in by(EventType.card)),
        "outfield_km": float(np.mean(full)) if full else 0.0,
        "throw_ins": len(by(EventType.throw_in)), "goal_kicks": len(by(EventType.goal_kick)),
        "penalties": len(by(EventType.penalty)), "pressures": len(by(EventType.pressure)),
        "tackles": len(by(EventType.tackle)),
    }


def calibration_stats(n: int = 200, seed: int = 1, workers: int | None = None, league_seed: int = 7) -> dict:
    lg = generate_league(league_seed)
    ids = [c.id for c in lg.clubs]
    rng = np.random.default_rng(seed)
    jobs = []
    for m in range(n):
        h, a = rng.choice(len(ids), size=2, replace=False)
        jobs.append((seed * 10_000 + m, ids[h], ids[a], league_seed))
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(match_stats, jobs, chunksize=1))
    out = {}
    for k in rows[0]:
        vals = np.array([r[k] for r in rows], float)
        out[k] = {"mean": float(vals.mean()), "sd": float(vals.std())}
    return out


def write_report(stats: dict, n: int, path: Path) -> None:
    lines = ["# Simulator calibration", "",
             f"{n} simulated matches between random pairs of the 20 fictional clubs, compared with public "
             "per-match averages for a top European league (both teams combined). The engine is never "
             "fitted to any real match data; only these aggregate levels were used as tuning targets.", "",
             "| Statistic | Simulated (mean ± sd) | Public average | Accepted range |", "|---|---|---|---|"]
    for k, (label, target, (lo, hi)) in TARGETS.items():
        m, sd = stats[k]["mean"], stats[k]["sd"]
        fmt = "{:.2f}" if target < 5 else "{:.1f}"
        lines.append(f"| {label} | {fmt.format(m)} ± {fmt.format(sd)} | {fmt.format(target)} | {lo}–{hi} |")
    extra = ", ".join(f"{k.replace('_', ' ')} {stats[k]['mean']:.1f}" for k in
                      ("throw_ins", "goal_kicks", "penalties", "pressures", "tackles"))
    lines += ["", f"Other per-match means: {extra}.", ""]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    stats = calibration_stats(a.n, a.seed)
    for k, v in stats.items():
        print(f"{k:16s} {v['mean']:9.3f} ± {v['sd']:.3f}")
    if a.out:
        write_report(stats, a.n, a.out)


if __name__ == "__main__":
    main()
