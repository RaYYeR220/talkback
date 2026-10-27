"""Command line entry point: `talkback matchday --seed 2026 --out runs/md-2026`."""

from __future__ import annotations

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="talkback")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("matchday", help="generate and play a full synthetic matchday offline")
    m.add_argument("--seed", type=int, default=2026)
    m.add_argument("--out", type=Path, default=Path("runs/md-2026"))
    a = ap.parse_args(argv)
    if a.cmd == "matchday":
        from talkback.world.matchday import prepare_matchday, run_matchday_offline
        out = run_matchday_offline(prepare_matchday(a.seed), a.out)
        print(f"matchday written to {out}")


if __name__ == "__main__":
    main()
