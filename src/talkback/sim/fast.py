"""Fast minute-level match model.

Used where the 10 Hz engine would be too slow: backfilling the season,
win probability, and Monte Carlo of the live table.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, ConfigDict

from talkback.world.league import Club, Player

BASE_SHOT_RATE = 0.115
HOME_BOOST = 0.32
RED_PENALTY = 0.35
XG_ALPHA, XG_BETA = 1.2, 9.0
MATCH_MINUTES = 94
POSITION_WEIGHT = {"FW": 1.0, "MF": 0.45, "DF": 0.12, "GK": 0.0}


class FastResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    home_goals: int
    away_goals: int
    scorers: list[tuple[str, int]]
    assists: list[tuple[str, int]]
    cards: list[tuple[str, str, int]]
    appearances: list[str]
    clean_sheet_keepers: list[str]


def formation_counts(formation: str) -> tuple[int, int, int]:
    parts = [int(x) for x in formation.split("-")]
    return parts[0], sum(parts[1:-1]), parts[-1]


def _overall(p: Player) -> float:
    a = p.attrs
    if p.position == "GK":
        return a.keeping
    return (a.pace + a.passing + a.finishing + a.tackling + a.pressing + a.stamina + a.composure) / 7


def select_xi(club: Club, rng: np.random.Generator) -> tuple[list[Player], list[Player]]:
    """Pick a starting XI for the club's formation plus a seven-man bench."""
    df, mf, fw = formation_counts(club.formation)
    noisy = {p.id: _overall(p) + rng.normal(0, 3) for p in club.squad}
    starters: list[Player] = []
    for pos, n in (("GK", 1), ("DF", df), ("MF", mf), ("FW", fw)):
        pool = sorted((p for p in club.squad if p.position == pos), key=lambda p: -noisy[p.id])
        starters.extend(pool[:n])
    chosen = {p.id for p in starters}
    bench = sorted((p for p in club.squad if p.id not in chosen), key=lambda p: -noisy[p.id])[:7]
    return starters, bench


def shot_rate(team: Club, opp: Club, home: bool, reds_self: int) -> float:
    m = np.exp(0.035 * (team.strength - opp.strength))
    m *= 1 + (HOME_BOOST if home else 0)
    m *= (1 - RED_PENALTY) ** reds_self
    m *= 0.95 + 0.1 * team.style.directness
    return float(BASE_SHOT_RATE * m)


def _weighted_pick(players: list[Player], rng: np.random.Generator, attr: str) -> Player:
    w = np.array([max(getattr(p.attrs, attr), 1) * POSITION_WEIGHT[p.position] for p in players], float)
    if w.sum() <= 0:
        w = np.ones(len(players))
    return players[int(rng.choice(len(players), p=w / w.sum()))]


def simulate_fast(home: Club, away: Club, rng: np.random.Generator, start_minute: int = 0,
                  score: tuple[int, int] = (0, 0), reds: tuple[int, int] = (0, 0)) -> FastResult:
    h_xi, h_bench = select_xi(home, rng)
    a_xi, a_bench = select_xi(away, rng)
    on_pitch = {"h": list(h_xi), "a": list(a_xi)}
    apps = [p.id for p in h_xi + a_xi]
    goals = {"h": score[0], "a": score[1]}
    red = {"h": reds[0], "a": reds[1]}
    scorers: list[tuple[str, int]] = []
    assists: list[tuple[str, int]] = []
    cards: list[tuple[str, str, int]] = []
    subs_done = {"h": 0, "a": 0}
    for minute in range(start_minute, MATCH_MINUTES):
        for side, team, opp, bench in (("h", home, away, h_bench), ("a", away, home, a_bench)):
            if minute >= 60 and subs_done[side] < 3 and rng.random() < 0.06:
                out_i = int(rng.integers(1, len(on_pitch[side])))
                sub = bench[subs_done[side]]
                on_pitch[side][out_i] = sub
                apps.append(sub.id)
                subs_done[side] += 1
            if rng.random() < shot_rate(team, opp, side == "h", red[side]):
                xg = rng.beta(XG_ALPHA, XG_BETA)
                if rng.random() < xg:
                    goals[side] += 1
                    scorer = _weighted_pick(on_pitch[side], rng, "finishing")
                    scorers.append((scorer.id, minute))
                    mates = [p for p in on_pitch[side] if p.id != scorer.id and p.position != "GK"]
                    if mates and rng.random() < 0.75:
                        assists.append((_weighted_pick(mates, rng, "passing").id, minute))
            if rng.random() < 0.036:
                p = on_pitch[side][int(rng.integers(1, len(on_pitch[side])))]
                kind = "red" if rng.random() < 0.025 else "yellow"
                cards.append((p.id, kind, minute))
                if kind == "red":
                    red[side] += 1
    keepers = []
    if goals["a"] == 0:
        keepers.append(on_pitch["h"][0].id)
    if goals["h"] == 0:
        keepers.append(on_pitch["a"][0].id)
    return FastResult(home_goals=goals["h"], away_goals=goals["a"], scorers=scorers, assists=assists,
                      cards=cards, appearances=list(dict.fromkeys(apps)), clean_sheet_keepers=keepers)


def remaining_goals(team: Club, opp: Club, home: bool, reds_self: int, minutes: int, n: int,
                    rng: np.random.Generator) -> np.ndarray:
    """Vectorised goal counts over `n` simulations for the remaining minutes."""
    if minutes <= 0:
        return np.zeros(n, dtype=int)
    p = shot_rate(team, opp, home, reds_self)
    shots = rng.random((n, minutes)) < p
    xg = rng.beta(XG_ALPHA, XG_BETA, size=(n, minutes))
    scored = shots & (rng.random((n, minutes)) < xg)
    return scored.sum(axis=1)


def win_probability(home: Club, away: Club, minute: int, score: tuple[int, int],
                    reds: tuple[int, int], n: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    left = max(0, MATCH_MINUTES - minute)
    hg = score[0] + remaining_goals(home, away, True, reds[0], left, n, rng)
    ag = score[1] + remaining_goals(away, home, False, reds[1], left, n, rng)
    hw = float(np.mean(hg > ag))
    dr = float(np.mean(hg == ag))
    return hw, dr, 1.0 - hw - dr
