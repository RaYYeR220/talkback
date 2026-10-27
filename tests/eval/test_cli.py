import json

import pytest

import talkback.eval.baseline as baseline_mod
import talkback.gallery.llm as llm
from talkback import cli
from talkback.eval.baseline import save_lines
from talkback.eval.score import Context, Line

MIN = 60_000


def _cue(match_id: str, t: int, text: str) -> dict:
    return {"kind": "cue", "sim_t": t, "data": {"match_id": match_id, "text": text, "audience": "fan", "moment_t": t,
                                                "latency_ms": 0, "verdicts": {"uk": {"verdict": "ON_AIR", "text": text}}}}


def _broadcast(path, cues: list[dict]):
    path.write_text("".join(json.dumps(c) + "\n" for c in cues), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def fixture_id(run_dir):
    return Context.load(run_dir).world.fixtures[0][0]


@pytest.mark.slow
def test_baseline_cache_is_kept_per_cut(run_dir, fixture_id, tmp_path, monkeypatch):
    cuts = []

    async def fake_baseline(ctx, client):
        last = max(e.t for e in ctx.events)
        cuts.append(last)
        return [Line(system="baseline", match_id=fixture_id, sim_t=last, text="Full time.")]

    monkeypatch.setattr(baseline_mod, "run_baseline", fake_baseline)
    monkeypatch.setattr(llm, "make_client", lambda tier: None)
    broadcast = _broadcast(tmp_path / "broadcast.jsonl", [_cue(fixture_id, 10 * MIN, "Kick-off.")])
    cli._eval(run_dir, broadcast, None, 25, None)
    cli._eval(run_dir, broadcast, None, None, None)
    cli._eval(run_dir, broadcast, None, 25, None)
    assert len(cuts) == 2, "a cut eval must neither reuse nor overwrite the full baseline"
    assert cuts[0] <= 25 * MIN < cuts[1]
    assert (tmp_path / "broadcast-baseline-until25.jsonl").exists()
    assert (tmp_path / "broadcast-baseline.jsonl").exists()


@pytest.mark.slow
def test_until_cuts_every_system_alike(run_dir, fixture_id, tmp_path):
    early, late = 10 * MIN, 80 * MIN
    cached = tmp_path / "cached-baseline.jsonl"
    save_lines([Line(system="baseline", match_id=fixture_id, sim_t=t, text="A line.") for t in (early, late)], cached)
    broadcast = _broadcast(tmp_path / "broadcast.jsonl", [_cue(fixture_id, t, "A line.") for t in (early, late)])
    res = cli._eval(run_dir, broadcast, cached, 25, None)
    assert res["talkback"]["lines"] == 1
    assert res["talkback_without_clearance"]["lines"] == 1
    assert res["baseline"]["lines"] == 1
