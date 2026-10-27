import json

import pytest

import talkback.eval.baseline as baseline_mod
import talkback.gallery.llm as llm
import talkback.gallery.runner as runner_mod
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


class _Runner:
    """Stands in for the gallery: records one numbered message per run and crashes when told to."""

    runs = 0
    crash = False

    def __init__(self, run, gate, client_for, bc, speed, lab_pool):
        self.bc = bc

    async def run(self, until_ms=None):
        _Runner.runs += 1
        self.bc.publish("run", 0, {"id": "r", "n": _Runner.runs})
        if _Runner.crash:
            raise RuntimeError("model provider went away")
        return {"aired": 0}


@pytest.fixture
def fake_gallery(monkeypatch):
    monkeypatch.setattr(runner_mod, "MatchdayRunner", _Runner)
    monkeypatch.setattr(llm, "make_client", lambda tier: None)
    monkeypatch.setenv("TALKBACK_ENV", "dev")
    monkeypatch.delenv("CONTENT_SAFETY_ENDPOINT", raising=False)
    monkeypatch.setattr(_Runner, "runs", 0)
    monkeypatch.setattr(_Runner, "crash", False)
    return _Runner


def _runs(path) -> list[int]:
    return [json.loads(l)["data"]["n"] for l in path.read_text(encoding="utf-8").splitlines()]


def test_a_crashed_gallery_run_leaves_no_broadcast(fake_gallery, tmp_path):
    out = tmp_path / "broadcast-eval.jsonl"
    fake_gallery.crash = True
    with pytest.raises(RuntimeError, match="provider went away"):
        cli._gallery(tmp_path, 20.0, None, out)
    assert not out.exists()


def test_a_gallery_rerun_replaces_the_broadcast(fake_gallery, tmp_path):
    out = tmp_path / "broadcast-eval.jsonl"
    fake_gallery.crash = True
    with pytest.raises(RuntimeError, match="provider went away"):
        cli._gallery(tmp_path, 20.0, None, out)
    fake_gallery.crash = False
    cli._gallery(tmp_path, 20.0, None, out)
    cli._gallery(tmp_path, 20.0, None, out)
    assert _runs(out) == [3]
    assert list(tmp_path.iterdir()) == [out]


def test_eval_all_reruns_a_gallery_that_did_not_complete(fake_gallery, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs" / "md-2026").mkdir(parents=True)
    scored = []
    monkeypatch.setattr(cli, "_eval", lambda run, broadcast, *rest: scored.append(_runs(broadcast)) or {})
    fake_gallery.crash = True
    with pytest.raises(RuntimeError, match="provider went away"):
        cli._eval_all([2026], 20.0, tmp_path / "summary.json")
    fake_gallery.crash = False
    cli._eval_all([2026], 20.0, tmp_path / "summary.json")
    cli._eval_all([2026], 20.0, tmp_path / "summary.json")
    assert scored == [[2], [2]], "only the completed run is scored, and it is reused once complete"
