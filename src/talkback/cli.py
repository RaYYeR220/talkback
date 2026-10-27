"""Command line entry point.

    talkback matchday --seed 2026 --out runs/md-2026      generate and play a matchday offline
    talkback gallery --run runs/md-2026 --speed 10        run the gallery over a generated matchday
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path


def _gallery(run: Path, speed: float, until_min: float | None, out: Path | None) -> dict:
    from concurrent.futures import ProcessPoolExecutor

    from talkback.clearance.gate import Gate
    from talkback.clearance.packs import PACKS_DIR, load_packs
    from talkback.gallery.bus import Broadcaster
    from talkback.gallery.llm import make_client
    from talkback.gallery.runner import MatchdayRunner
    from talkback.service.safety import make_safety

    record = out or run / f"broadcast-{int(time.time())}.jsonl"
    clients = {"fast": make_client("fast"), "strong": make_client("strong")}
    bc = Broadcaster(record)
    with ProcessPoolExecutor(max_workers=6) as pool:
        runner = MatchdayRunner(run, Gate(load_packs(PACKS_DIR), make_safety()), clients.__getitem__, bc,
                                speed=speed, lab_pool=pool)
        stats = asyncio.run(runner.run(until_ms=int(until_min * 60_000) if until_min else None))
    bc.close()
    print(json.dumps(stats))
    print(f"broadcast recorded to {record}")
    return stats


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="talkback")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("matchday", help="generate and play a full synthetic matchday offline")
    m.add_argument("--seed", type=int, default=2026)
    m.add_argument("--out", type=Path, default=Path("runs/md-2026"))
    g = sub.add_parser("gallery", help="run the gallery over a generated matchday")
    g.add_argument("--run", type=Path, default=Path("runs/md-2026"))
    g.add_argument("--speed", type=float, default=10.0)
    g.add_argument("--until", type=float, default=None, help="stop after this many match minutes")
    g.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.cmd == "matchday":
        from talkback.world.matchday import prepare_matchday, run_matchday_offline
        out = run_matchday_offline(prepare_matchday(a.seed), a.out)
        print(f"matchday written to {out}")
    elif a.cmd == "gallery":
        _gallery(a.run, a.speed, a.until, a.out)


if __name__ == "__main__":
    main()
