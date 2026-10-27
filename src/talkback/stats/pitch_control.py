"""Pitch control from a tracking frame (time-to-intercept model)."""

from __future__ import annotations

import numpy as np

from talkback.models.xg import PITCH_LENGTH, PITCH_WIDTH

REACTION_S = 0.7
MAX_SPEED = 7.0
SIGMA_S = 0.45


def _cells(grid: tuple[int, int]) -> np.ndarray:
    nx, ny = grid
    xs = (np.arange(nx) + 0.5) * PITCH_LENGTH / nx
    ys = (np.arange(ny) + 0.5) * PITCH_WIDTH / ny
    gx, gy = np.meshgrid(xs, ys)
    return np.stack([gx.ravel(), gy.ravel()], axis=1)


def pitch_control(frame, team_ids: set[str], grid: tuple[int, int] = (21, 14)) -> tuple[np.ndarray, float]:
    """Probability that `team_ids` controls each cell, shape (rows=y, cols=x), and its mean share."""
    ids = list(frame.ids) if hasattr(frame, "ids") else [p.player_id for p in frame.players]
    pos = np.asarray(frame.pos) if hasattr(frame, "pos") else np.array([[p.x, p.y] for p in frame.players])
    mine = np.array([pid in team_ids for pid in ids])
    cells = _cells(grid)
    d = np.linalg.norm(pos[:, None, :] - cells[None, :, :], axis=2)
    tti = REACTION_S + d / MAX_SPEED
    t_mine = tti[mine].min(axis=0) if mine.any() else np.full(len(cells), 1e6)
    t_other = tti[~mine].min(axis=0) if (~mine).any() else np.full(len(cells), 1e6)
    surface = 1.0 / (1.0 + np.exp(-(t_other - t_mine) / SIGMA_S))
    return surface.reshape(grid[1], grid[0]), float(surface.mean())
