import numpy as np
import pytest

from talkback.schemas.models import EventType, Outcome
from talkback.sim.engine import MatchEngine, simulate_match
from talkback.sim.fast import select_xi
from talkback.world.league import generate_league
from talkback.world.storylines import ForcedBeat


@pytest.fixture(scope="module")
def clubs():
    lg = generate_league(7)
    return lg.club("C03"), lg.club("C11")


@pytest.fixture(scope="module")
def match(clubs):
    h, a = clubs
    return simulate_match("F01", h, a, seed=3)


def test_deterministic(clubs, match):
    h, a = clubs
    events2, _ = simulate_match("F01", h, a, seed=3)
    assert [e.model_dump() for e in match[0]] == [e.model_dump() for e in events2]


def test_frames_10hz(match):
    _, frames = match
    ts = np.array([f.t for f in frames])
    assert np.all(np.diff(ts) == 100)
    for f in frames[::50]:
        assert 18 <= len(f.ids) <= 22
        assert np.all(f.pos[:, 0] >= -2) and np.all(f.pos[:, 0] <= 107)
        assert np.all(f.pos[:, 1] >= -2) and np.all(f.pos[:, 1] <= 70)


def test_speed_limits(match):
    _, frames = match
    assert max(float(f.speed.max()) for f in frames) <= 9.6


def test_goal_chain(match):
    events, _ = match
    for i, e in enumerate(events):
        if e.type == EventType.goal:
            shot = next(p for p in reversed(events[:i]) if p.match_id == e.match_id)
            assert shot.type == EventType.shot and shot.outcome == Outcome.goal
            assert shot.possession_id == e.possession_id
            assert 0 < float(shot.qualifiers["xg"]) <= 0.95
            attacking_right = (e.team_id == "C03") == (e.period == 1)
            assert (shot.x > 52.5) if attacking_right else (shot.x < 52.5)


def test_snapshot_restore(clubs):
    h, a = clubs
    eng = MatchEngine("F02", h, a, seed=5)
    while eng.t < 30 * 60_000:
        eng.step()
    snap = eng.snapshot()

    def run_two_minutes():
        out = []
        end = eng.t + 120_000
        while eng.t < end:
            out.extend(eng.step()[1])
        return [e.model_dump() for e in out]

    first = run_two_minutes()
    eng.restore(snap)
    assert run_two_minutes() == first


@pytest.mark.slow
def test_forced_beat(clubs):
    h, a = clubs
    striker = max((p for p in h.squad if p.position == "FW"), key=lambda p: p.attrs.finishing)
    hits = 0
    rng = np.random.default_rng(0)
    hx, _ = select_xi(h, rng)
    ax, _ = select_xi(a, rng)
    home_xi = [p.id for p in hx]
    if striker.id not in home_xi:
        out = next(pid for pid in reversed(home_xi) if pid.split("-")[0] == h.id and
                   next(p for p in h.squad if p.id == pid).position == "FW")
        home_xi = [striker.id if pid == out else pid for pid in home_xi]
    for seed in range(1, 21):
        beat = ForcedBeat(player_id=striker.id, kind="goal", window_ms=(55 * 60_000, 85 * 60_000), prob=0.85)
        events, _ = simulate_match("F03", h, a, seed=seed, beats=[beat], frames=False,
                                   start_xi=(home_xi, [p.id for p in ax]))
        if any(e.type == EventType.goal and e.player_id == striker.id and 55 * 60_000 <= e.t <= 87 * 60_000
               for e in events):
            hits += 1
    assert hits >= 12, hits
