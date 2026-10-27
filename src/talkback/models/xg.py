"""Expected-goals model shared by the simulator and the Stats Desk."""

from __future__ import annotations

import math

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0
GOAL_WIDTH = 7.32


def goal_geometry(x: float, y: float, attacking_right: bool) -> tuple[float, float]:
    """Distance to the goal centre and the angle the goal mouth subtends."""
    gx = PITCH_LENGTH if attacking_right else 0.0
    dx = abs(gx - x)
    dy = y - PITCH_WIDTH / 2
    dist = math.hypot(dx, dy)
    a1 = math.atan2(dy - GOAL_WIDTH / 2, dx)
    a2 = math.atan2(dy + GOAL_WIDTH / 2, dx)
    return dist, abs(a2 - a1)


def shot_xg(distance_m: float, angle_rad: float, under_pressure: bool, header: bool,
            from_set_piece: bool) -> float:
    z = (-1.0 - 0.13 * distance_m + 1.4 * angle_rad - 0.45 * under_pressure
         - 0.9 * header + 0.1 * from_set_piece)
    return min(0.95, max(0.01, 1.0 / (1.0 + math.exp(-z))))


def penalty_xg() -> float:
    return 0.76
