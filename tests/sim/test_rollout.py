import os
import time

import pytest

from talkback.sim.rollout import FlipEvent, Tactic, is_supported, run_counterfactual
from tests.sim.fixtures import factory, final_third_snapshot


def test_null_intervention():
    snap, attacking, _ = final_third_snapshot()
    k = 0 if attacking == "C03" else 1
    st = snap.styles[k]
    base, cf, stats = run_counterfactual(snap, factory(), Tactic(team_id=attacking, press=float(st[0]),
                                         line=float(st[1])), attacking, n=24, horizon_s=10, seed=1)
    assert stats["effect_goal_for"] == 0.0 and stats["effect_xt"] == 0.0
    assert stats["ci95_xt"] == (0.0, 0.0)


def test_serial_equals_parallel():
    snap, attacking, defending = final_third_snapshot()
    iv = FlipEvent(event_type="interception", team_id=defending)
    a = run_counterfactual(snap, factory(), iv, attacking, n=40, horizon_s=10, seed=2, workers=0)
    b = run_counterfactual(snap, factory(), iv, attacking, n=40, horizon_s=10, seed=2, workers=2)
    assert a == b


def test_flip_interception_helps():
    snap, attacking, defending = final_third_snapshot()
    iv = FlipEvent(event_type="interception", team_id=defending)
    base, cf, stats = run_counterfactual(snap, factory(), iv, attacking, n=120, horizon_s=20, seed=3)
    assert stats["effect_goal_for"] >= 0
    assert stats["effect_xt"] > 0
    assert is_supported(stats["ci95_xt"])
    assert "interception" in iv.describe()


@pytest.mark.slow
def test_timing():
    snap, attacking, defending = final_third_snapshot()
    iv = FlipEvent(event_type="interception", team_id=defending)
    t0 = time.time()
    run_counterfactual(snap, factory(), iv, attacking, n=240, horizon_s=20, seed=4,
                       workers=max(1, (os.cpu_count() or 2) - 1))
    assert time.time() - t0 < 6.0
