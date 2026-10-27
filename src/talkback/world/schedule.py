"""Double round-robin fixture list (circle method)."""

from __future__ import annotations

import numpy as np


def double_round_robin(club_ids: list[str], seed: int) -> list[list[tuple[str, str]]]:
    rng = np.random.default_rng(seed)
    teams = list(club_ids)
    rng.shuffle(teams)
    n = len(teams)
    first_half: list[list[tuple[str, str]]] = []
    rot = teams[1:]
    for r in range(n - 1):
        order = [teams[0]] + rot
        md = []
        for i in range(n // 2):
            a, b = order[i], order[n - 1 - i]
            md.append((a, b) if (r + i) % 2 == 0 else (b, a))
        first_half.append(md)
        rot = rot[-1:] + rot[:-1]
    second_half = [[(b, a) for a, b in md] for md in first_half]
    return first_half + second_half
