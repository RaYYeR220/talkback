"""Pass completion model; pass difficulty is one minus completion."""

from __future__ import annotations

import math


def pass_completion(distance_m: float, lane_clearance_m: float, passer_pressure_m: float,
                    passing_attr: int, lofted: bool) -> float:
    z = (-0.07 * distance_m + 0.55 * min(lane_clearance_m, 6.0) + 0.12 * min(passer_pressure_m, 5.0)
         + 0.02 * (passing_attr - 60) + 1.5 - 0.35 * lofted)
    return min(0.99, max(0.03, 1.0 / (1.0 + math.exp(-z))))


def pass_difficulty(completion: float) -> float:
    return 1.0 - completion
