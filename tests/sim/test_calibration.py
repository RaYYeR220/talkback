import numpy as np
import pytest

from talkback.sim.calibrate import calibration_stats


@pytest.mark.slow
def test_calibration_200():
    s = calibration_stats(n=200, seed=1)
    ranges = {
        "goals": (2.3, 3.3), "shots": (20, 30), "on_target_share": (0.28, 0.42),
        "passes": (750, 1100), "pass_completion": (0.76, 0.87), "ppda": (7, 15),
        "fouls": (15, 26), "corners": (7, 13), "yellows": (2.5, 5), "outfield_km": (9.0, 12.0),
    }
    for k, (lo, hi) in ranges.items():
        assert lo <= s[k]["mean"] <= hi, (k, s[k]["mean"])
