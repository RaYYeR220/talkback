"""Expected threat grid (Singh's method), learned from simulated matches."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict

from talkback.models.xg import PITCH_LENGTH, PITCH_WIDTH
from talkback.schemas.models import Event, EventType, Outcome

GRID_PATH = Path(__file__).with_name("xt_grid.json")


class XTGrid(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cols: int = 16
    rows: int = 12
    values: list[list[float]]  # [row][col], attacking right

    def cell(self, x: float, y: float) -> tuple[int, int]:
        c = min(self.cols - 1, max(0, int(x / PITCH_LENGTH * self.cols)))
        r = min(self.rows - 1, max(0, int(y / PITCH_WIDTH * self.rows)))
        return r, c

    def value(self, x: float, y: float, attacking_right: bool) -> float:
        if not attacking_right:
            x, y = PITCH_LENGTH - x, PITCH_WIDTH - y
        r, c = self.cell(x, y)
        return self.values[r][c]


def prior_grid(cols: int = 16, rows: int = 12) -> XTGrid:
    vals = []
    for r in range(rows):
        y = (r + 0.5) * PITCH_WIDTH / rows
        row = []
        for c in range(cols):
            x = (c + 0.5) * PITCH_LENGTH / cols
            row.append(0.002 + 0.38 * math.exp(-((105 - x) / 22) ** 2) * math.exp(-((y - 34) / 14) ** 2))
        vals.append(row)
    return XTGrid(cols=cols, rows=rows, values=vals)


def load_xt_grid(path: Path = GRID_PATH) -> XTGrid:
    return XTGrid.model_validate_json(Path(path).read_text(encoding="utf-8"))


def save_xt_grid(grid: XTGrid, path: Path = GRID_PATH) -> None:
    Path(path).write_text(json.dumps(grid.model_dump(), indent=1), encoding="utf-8", newline="\n")


MOVES = (EventType.pass_, EventType.carry, EventType.dribble, EventType.cross)


def compute_xt_grid(events: list[Event], cols: int = 16, rows: int = 12, iters: int = 30) -> XTGrid:
    """Value iteration over events already normalised to attacking-right coordinates."""
    g = XTGrid(cols=cols, rows=rows, values=[[0.0] * cols for _ in range(rows)])
    n = rows * cols
    shots = np.zeros(n)
    shot_xg = np.zeros(n)
    moves = np.zeros(n)
    trans = np.zeros((n, n))
    for e in events:
        if e.x is None or e.y is None:
            continue
        r, c = g.cell(e.x, e.y)
        i = r * cols + c
        if e.type == EventType.shot:
            shots[i] += 1
            shot_xg[i] += float(e.qualifiers.get("xg", 0.0))
        elif e.type in MOVES:
            moves[i] += 1
            if e.outcome == Outcome.success and e.end_x is not None and e.end_y is not None:
                r2, c2 = g.cell(e.end_x, e.end_y)
                trans[i, r2 * cols + c2] += 1
    total = shots + moves
    p_shot = np.divide(shots, total, out=np.zeros(n), where=total > 0)
    p_move = np.divide(moves, total, out=np.zeros(n), where=total > 0)
    mean_xg = np.divide(shot_xg, shots, out=np.zeros(n), where=shots > 0)
    t = np.divide(trans, moves[:, None], out=np.zeros_like(trans), where=moves[:, None] > 0)
    xt = np.zeros(n)
    for _ in range(iters):
        xt = p_shot * mean_xg + p_move * (t @ xt)
    return XTGrid(cols=cols, rows=rows, values=xt.reshape(rows, cols).round(6).tolist())
