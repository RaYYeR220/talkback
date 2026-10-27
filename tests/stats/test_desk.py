import numpy as np
import pytest

from talkback.models.xt import load_xt_grid
from talkback.schemas.models import Event, EventType, Outcome, event_id
from talkback.sim.engine import RawFrame, simulate_match
from talkback.stats.desk import StatsDesk
from talkback.stats.pitch_control import pitch_control
from talkback.world.league import generate_league


@pytest.fixture(scope="module")
def played():
    lg = generate_league(7)
    h, a = lg.club("C03"), lg.club("C11")
    events, frames = simulate_match("SD1", h, a, seed=9)
    desk = StatsDesk("SD1", h, a, load_xt_grid())
    for e in events:
        desk.ingest(e)
    for f in frames:
        desk.ingest_frame(f)
    return h, a, events, frames, desk


def test_counts_match_events(played):
    h, a, events, frames, desk = played
    shots = [e for e in events if e.type == EventType.shot and e.team_id == h.id]
    f = desk.fact("team.shots", h.id)
    assert f.value == len(shots)
    xg = desk.fact("team.xg", h.id)
    assert abs(xg.value - sum(float(e.qualifiers["xg"]) for e in shots)) < 1e-9
    assert xg.sample_size == len(shots)


def _ev(seq, t, etype, team, x, outcome=Outcome.success, period=1):
    return Event(id=event_id("PP", seq), match_id="PP", seq=seq, t=t, period=period, type=etype,
                 team_id=team, player_id=f"{team}-P05", x=x, y=34.0, end_x=x + 5, end_y=34.0,
                 outcome=outcome, possession_id=seq)


def test_ppda_definition():
    lg = generate_league(7)
    h, a = lg.club("C03"), lg.club("C11")
    desk = StatsDesk("PP", h, a, load_xt_grid())
    # away attacks left in period 1: its own 60% is x > 42
    for n in range(5):
        desk.ingest(_ev(n + 1, 1000 * n, EventType.pass_, a.id, 80.0))
    desk.ingest(_ev(6, 6000, EventType.tackle, h.id, 70.0))
    desk.ingest(_ev(7, 7000, EventType.interception, h.id, 60.0))
    assert desk.fact("team.ppda", h.id).value == 2.5


def test_empty_window(played):
    h, a, events, frames, desk = played
    f = desk.window_fact("team.pass_completion", h.id, 0, 50)
    assert f.sample_size == 0 and f.value == 0.0
    assert not np.isnan(f.value)


def test_distance_sane(played):
    h, a, events, frames, desk = played
    subbed = {str(e.qualifiers.get("player_out")) for e in events if e.type == EventType.substitution}
    subbed |= {e.player_id for e in events if e.type == EventType.substitution}
    starters = [pid for pid in frames[0].ids if pid not in subbed]
    gks = {p.id for c in (h, a) for p in c.squad if p.position == "GK"}
    for pid in starters:
        if pid in gks:
            continue
        km = desk.fact("player.distance_km", pid).value
        assert 7 <= km <= 14.0, (pid, km)
    assert desk.fact("player.top_speed_kmh", starters[5]).value <= 9.6 * 3.6


def test_pitch_control_symmetry(played):
    h, a, events, frames, desk = played
    fr = frames[len(frames) // 2]
    home_ids = {p.id for p in h.squad}
    away_ids = {p.id for p in a.squad}
    _, home_share = pitch_control(fr, home_ids)
    _, away_share = pitch_control(fr, away_ids)
    assert abs(home_share + away_share - 1) < 0.02


def test_evidence_ids_exist(played):
    h, a, events, frames, desk = played
    ids = {e.id for e in events}
    for f in desk.facts(events[-1].t):
        assert all(ev in ids for ev in f.evidence), f.metric
        assert f.sample_size >= 0 and not np.isnan(f.value)


def test_win_probability_fact(played):
    h, a, events, frames, desk = played
    hw = desk.fact("team.win_probability", h.id).value
    aw = desk.fact("team.win_probability", a.id).value
    assert 0 <= hw <= 1 and 0 <= aw <= 1 and hw + aw <= 1.0 + 1e-9
