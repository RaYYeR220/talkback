"""Pass completion model; pass difficulty is one minus completion.

Works on scalars and on numpy arrays, so the simulator can score every
passing option in one call with the same formula the Stats Desk reports.
"""

from __future__ import annotations

import numpy as np


def pass_completion(distance_m, lane_clearance_m, passer_pressure_m, passing_attr, lofted):
    z = (-0.07 * np.asarray(distance_m, float) + 0.55 * np.minimum(lane_clearance_m, 6.0)
         + 0.12 * np.minimum(passer_pressure_m, 5.0) + 0.012 * (np.asarray(passing_attr, float) - 60)
         + 1.05 - 0.35 * np.asarray(lofted, float))
    p = np.clip(1.0 / (1.0 + np.exp(-z)), 0.03, 0.99)
    return float(p) if np.ndim(p) == 0 else p


def pass_difficulty(completion):
    return 1.0 - completion
