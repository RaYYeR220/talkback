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
    # the broadcaster appends: record into a fresh partial file and move it into place only once the run has
    # completed, so a crashed run never leaves a broadcast behind and a re-run never adds to an earlier one
    partial = record.with_name(record.name + ".partial")
    partial.unlink(missing_ok=True)
    clients = {"fast": make_client("fast"), "strong": make_client("strong")}
    bc = Broadcaster(partial)
    try:
        with ProcessPoolExecutor(max_workers=6) as pool:
            runner = MatchdayRunner(run, Gate(load_packs(PACKS_DIR), make_safety()), clients.__getitem__, bc,
                                    speed=speed, lab_pool=pool)
            stats = asyncio.run(runner.run(until_ms=int(until_min * 60_000) if until_min else None))
    finally:
        bc.close()
    partial.replace(record)
    print(json.dumps(stats))
    print(f"broadcast recorded to {record}")
    return stats


def _eval(run: Path, broadcast: Path, baseline: Path | None, until_min: float | None, report: Path | None) -> dict:
    from talkback.eval.baseline import load_lines, run_baseline, save_lines
    from talkback.eval.score import Context, lines_from_broadcast, score
    from talkback.gallery.llm import make_client

    ctx = Context.load(run)
    sealed = (Path(run) / "key.sha256").read_text(encoding="utf-8").strip()
    if ctx.key.sha256() != sealed:
        raise SystemExit(f"answer key does not match its sealed hash in {run}")
    cut = int(until_min * 60_000) if until_min else None
    if cut is not None:
        ctx.events = [e for e in ctx.events if e.t <= cut]
        ctx.key = ctx.key.model_copy(update={"items": [i for i in ctx.key.items
                                                       if i.deadline == "live" and i.window_ms and i.window_ms[1] <= cut]})
    # the baseline is computed from the (cut) events, so each cut keeps its own cache
    suffix = "-baseline.jsonl" if cut is None else f"-baseline-until{until_min:g}.jsonl"
    baseline = baseline or broadcast.with_name(broadcast.stem + suffix)
    if baseline.exists():
        base_lines = load_lines(baseline)
    else:
        base_lines = asyncio.run(run_baseline(ctx, make_client("fast")))
        save_lines(base_lines, baseline)
    ours = lines_from_broadcast(broadcast, "talkback")
    ungated = lines_from_broadcast(broadcast, "talkback_without_clearance", include_killed=True)
    lines = ours + ungated + base_lines
    if cut is not None:
        lines = [l for l in lines if l.sim_t <= cut + 5 * 60_000]
    result = score(ctx, lines)
    result["_meta"] = {"run": str(run), "broadcast": str(broadcast), "key_sha256": sealed, "until_min": until_min}
    out = json.dumps(result, indent=1)
    if report:
        report.write_text(out, encoding="utf-8", newline="\n")
    print(out)
    return result


def _eval_all(seeds: list[int], speed: float, out: Path) -> dict:
    """Run the gallery and the baseline over each pre-registered matchday and aggregate the scores."""
    from talkback.eval.report import aggregate

    results = []
    for seed in seeds:
        run = Path(f"runs/md-{seed}")
        broadcast = run / "broadcast-eval.jsonl"
        if not broadcast.exists():  # _gallery moves it into place only once a run has completed
            _gallery(run, speed, None, broadcast)
        results.append(_eval(run, broadcast, None, None, run / "eval.json"))
    summary = aggregate(results)
    out.write_text(json.dumps(summary, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(summary["systems"], indent=1))
    return summary


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
    e = sub.add_parser("eval", help="score a recorded gallery run against the sealed key and the baseline")
    e.add_argument("--run", type=Path, default=Path("runs/md-2026"))
    e.add_argument("--broadcast", type=Path, required=True)
    e.add_argument("--baseline", type=Path, default=None, help="cached baseline lines (computed if missing)")
    e.add_argument("--until", type=float, default=None, help="score only the first N match minutes")
    e.add_argument("--report", type=Path, default=None)
    ea = sub.add_parser("eval-all", help="the pre-registered evaluation over several matchdays")
    ea.add_argument("--seeds", type=int, nargs="+", default=[2026, 2027, 2028, 2029, 2030])
    ea.add_argument("--speed", type=float, default=20.0)
    ea.add_argument("--out", type=Path, default=Path("docs/eval-summary.json"))
    a = ap.parse_args(argv)
    if a.cmd == "matchday":
        from talkback.world.matchday import prepare_matchday, run_matchday_offline
        out = run_matchday_offline(prepare_matchday(a.seed), a.out)
        print(f"matchday written to {out}")
    elif a.cmd == "gallery":
        _gallery(a.run, a.speed, a.until, a.out)
    elif a.cmd == "eval":
        _eval(a.run, a.broadcast, a.baseline, a.until, a.report)
    elif a.cmd == "eval-all":
        _eval_all(a.seeds, a.speed, a.out)


if __name__ == "__main__":
    main()
