import numpy as np

from talkback.sim.fast import simulate_fast, win_probability
from talkback.world.league import generate_league


def _mid_pair():
    lg = generate_league(7)
    clubs = sorted(lg.clubs, key=lambda c: c.strength)
    return clubs[9], clubs[10]


def test_fast_calibration():
    h, a = _mid_pair()
    rng = np.random.default_rng(1)
    res = [simulate_fast(h, a, rng) for _ in range(3000)]
    goals = np.mean([r.home_goals + r.away_goals for r in res])
    home_win = np.mean([r.home_goals > r.away_goals for r in res])
    assert 2.5 <= goals <= 3.1, goals
    assert 0.40 <= home_win <= 0.50, home_win


def test_win_prob_sums():
    h, a = _mid_pair()
    p = win_probability(h, a, minute=30, score=(0, 0), reds=(0, 0), n=2000, seed=0)
    assert abs(sum(p) - 1) < 1e-9
    late = win_probability(h, a, minute=89, score=(2, 0), reds=(0, 0), n=2000, seed=0)
    assert late[0] > 0.95


def test_fast_result_consistency():
    h, a = _mid_pair()
    r = simulate_fast(h, a, np.random.default_rng(3))
    assert len(r.scorers) == r.home_goals + r.away_goals
    squad_ids = {p.id for p in h.squad} | {p.id for p in a.squad}
    assert all(pid in squad_ids for pid, _ in r.scorers)
    assert all(pid in set(r.appearances) for pid, _ in r.scorers)
