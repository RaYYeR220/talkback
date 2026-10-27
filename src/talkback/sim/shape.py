"""Formation slots and where each player wants to stand this tick.

Slots are team-relative and normalised: x runs 0 (own goal) to 1 (opponent
goal), y runs 0 to 1 across the pitch. Targets come back in absolute metres.
"""

from __future__ import annotations

import numpy as np

from talkback.models.xg import PITCH_LENGTH, PITCH_WIDTH

SLOTS: dict[str, list[tuple[float, float]]] = {
    "4-3-3": [(0.05, 0.5), (0.28, 0.15), (0.22, 0.38), (0.22, 0.62), (0.28, 0.85),
              (0.45, 0.30), (0.38, 0.50), (0.45, 0.70), (0.68, 0.15), (0.72, 0.50), (0.68, 0.85)],
    "4-2-3-1": [(0.05, 0.5), (0.28, 0.15), (0.22, 0.38), (0.22, 0.62), (0.28, 0.85),
                (0.38, 0.38), (0.38, 0.62), (0.58, 0.20), (0.60, 0.50), (0.58, 0.80), (0.74, 0.50)],
    "4-4-2": [(0.05, 0.5), (0.28, 0.15), (0.22, 0.38), (0.22, 0.62), (0.28, 0.85),
              (0.45, 0.15), (0.42, 0.38), (0.42, 0.62), (0.45, 0.85), (0.70, 0.40), (0.70, 0.60)],
    "3-5-2": [(0.05, 0.5), (0.22, 0.30), (0.20, 0.50), (0.22, 0.70), (0.45, 0.08),
              (0.40, 0.35), (0.38, 0.50), (0.40, 0.65), (0.45, 0.92), (0.70, 0.40), (0.70, 0.60)],
}

KICKOFF_SCALE = 0.48  # squeeze the shape into the own half at kick-off


def to_team(x: np.ndarray, y: np.ndarray, attacking_right: bool) -> tuple[np.ndarray, np.ndarray]:
    if attacking_right:
        return x / PITCH_LENGTH, y / PITCH_WIDTH
    return 1 - x / PITCH_LENGTH, 1 - y / PITCH_WIDTH


def to_abs(xn: np.ndarray, yn: np.ndarray, attacking_right: bool) -> np.ndarray:
    if attacking_right:
        return np.stack([xn * PITCH_LENGTH, yn * PITCH_WIDTH], axis=-1)
    return np.stack([(1 - xn) * PITCH_LENGTH, (1 - yn) * PITCH_WIDTH], axis=-1)


def kickoff_positions(slots: np.ndarray, attacking_right: bool) -> np.ndarray:
    xn = slots[:, 0] * KICKOFF_SCALE + 0.01
    return to_abs(xn, slots[:, 1], attacking_right)


def team_targets(slots: np.ndarray, is_gk: np.ndarray, ball: np.ndarray, attacking_right: bool,
                 in_possession: bool, line: float, width: float, offsets: np.ndarray) -> np.ndarray:
    """Target positions (n, 2) in metres for one team's active players."""
    bx, by = to_team(np.array(ball[0]), np.array(ball[1]), attacking_right)
    sx, sy = slots[:, 0], slots[:, 1]
    if in_possession:
        tx = sx + (bx - 0.5) * 0.45 + 0.08 * (line - 0.5) + 0.04
        ty = 0.5 + (sy - 0.5) * (0.9 + 0.3 * width)
    else:
        deep = np.clip((0.4 - bx) / 0.4, 0, 1)          # ball in our defensive third
        tx = sx + (bx - 0.5) * 0.40 - 0.06 + 0.12 * (line - 0.5) - 0.08 * deep
        ty = 0.5 + (sy - 0.5) * (0.7 - 0.25 * deep) + (by - 0.5) * 0.25
    tx = np.where(is_gk, np.clip(0.02 + 0.08 * bx, 0.01, 0.12), tx)
    ty = np.where(is_gk, 0.5 + (by - 0.5) * 0.3, ty)
    tx = np.clip(tx, 0.02, 0.98)
    ty = np.clip(ty, 0.03, 0.97)
    out = to_abs(tx, ty, attacking_right)
    return out + np.where(is_gk[:, None], 0.0, offsets)
