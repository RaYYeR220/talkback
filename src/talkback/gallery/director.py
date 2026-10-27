"""Director: the live table, its chances, and where the world feed should look.

Chances come from Monte Carlo of the minutes left in every live match plus the
rest of the season (fast match model). Before/after comparisons reuse the same
random numbers, so a swing is caused by the scoreline change, not by noise.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

import numpy as np

from talkback.gallery.spotter import Moment
from talkback.gallery.world import World
from talkback.sim.fast import MATCH_MINUTES, XG_ALPHA, XG_BETA, shot_rate

MEAN_XG = XG_ALPHA / (XG_ALPHA + XG_BETA)
SWING_MIN = 0.03


class LiveScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_id: str
    home: str
    away: str
    home_goals: int = 0
    away_goals: int = 0
    minute: int = 0
    home_red: int = 0
    away_red: int = 0
    finished: bool = False


class ClubChances(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    club_id: str
    position: int
    points: int
    title: float
    top4: float
    relegation: float


class Swing(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    club_id: str
    metric: str
    before: float
    after: float
    caused_by: str


class RundownItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    channel: str
    match_id: str
    from_t: int
    reason: str
    moment_ids: list[str]


class LiveTable:
    def __init__(self, world: World, n: int = 2000, seed: int = 17):
        self.world = world
        self.n = n
        self.seed = seed
        self.ids = [c.id for c in world.league.clubs]
        self.index = {c: i for i, c in enumerate(self.ids)}
        base = {r.club_id: r for r in world.table}
        self.base_pts = np.array([base[c].pts for c in self.ids], float)
        self.base_gd = np.array([base[c].gd for c in self.ids], float)
        schedule = world.data["season"].get("schedule", [])
        md = world.matchday  # the live round (1-based)
        self.remaining = [tuple(f) for rnd in schedule[md:] for f in rnd]

    def as_it_stands(self, scores: list[LiveScore]) -> list[tuple[str, int, int]]:
        pts = self.base_pts.copy()
        gd = self.base_gd.copy()
        for s in scores:
            h, a = self.index[s.home], self.index[s.away]
            gd[h] += s.home_goals - s.away_goals
            gd[a] += s.away_goals - s.home_goals
            if s.home_goals > s.away_goals:
                pts[h] += 3
            elif s.home_goals < s.away_goals:
                pts[a] += 3
            else:
                pts[h] += 1
                pts[a] += 1
        order = sorted(range(len(self.ids)), key=lambda i: (-pts[i], -gd[i], self.ids[i]))
        return [(self.ids[i], int(pts[i]), int(gd[i])) for i in order]

    def _goals(self, home: str, away: str, minutes: np.ndarray | int, reds: tuple[int, int],
               rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
        H, A = self.world.club(home), self.world.club(away)
        lam_h = shot_rate(H, A, True, reds[0]) * MEAN_XG * np.asarray(minutes, float)
        lam_a = shot_rate(A, H, False, reds[1]) * MEAN_XG * np.asarray(minutes, float)
        return rng.poisson(lam_h, self.n), rng.poisson(lam_a, self.n)

    def chances(self, scores: list[LiveScore]) -> list[ClubChances]:
        rng = np.random.default_rng(self.seed)
        n, k = self.n, len(self.ids)
        pts = np.tile(self.base_pts, (n, 1))
        gd = np.tile(self.base_gd, (n, 1))

        def apply(h, a, hg, ag):
            hi, ai = self.index[h], self.index[a]
            gd[:, hi] += hg - ag
            gd[:, ai] += ag - hg
            pts[:, hi] += np.where(hg > ag, 3, np.where(hg == ag, 1, 0))
            pts[:, ai] += np.where(ag > hg, 3, np.where(hg == ag, 1, 0))

        for s in sorted(scores, key=lambda s: s.fixture_id):
            left = 0 if s.finished else max(0, MATCH_MINUTES - s.minute)
            hg, ag = self._goals(s.home, s.away, left, (s.home_red, s.away_red), rng)
            apply(s.home, s.away, hg + s.home_goals, ag + s.away_goals)
        for h, a in self.remaining:
            hg, ag = self._goals(h, a, MATCH_MINUTES, (0, 0), rng)
            apply(h, a, hg, ag)
        score = pts * 1000 + gd + rng.random((n, k)) * 0.1
        rank = (-score).argsort(axis=1).argsort(axis=1) + 1
        table = {c: (p, pt) for p, (c, pt, _) in enumerate(self.as_it_stands(scores), start=1)}
        out = []
        for c, i in self.index.items():
            r = rank[:, i]
            out.append(ClubChances(club_id=c, position=table[c][0], points=table[c][1],
                                   title=float(np.mean(r == 1)), top4=float(np.mean(r <= 4)),
                                   relegation=float(np.mean(r >= k - 2))))
        return sorted(out, key=lambda x: x.position)


def swings(before: list[ClubChances], after: list[ClubChances], caused_by: str) -> list[Swing]:
    prev = {c.club_id: c for c in before}
    out = []
    for c in after:
        p = prev[c.club_id]
        for metric in ("title", "top4", "relegation"):
            b, a = getattr(p, metric), getattr(c, metric)
            if abs(a - b) >= SWING_MIN:
                out.append(Swing(club_id=c.club_id, metric=metric, before=round(b, 3), after=round(a, 3),
                                 caused_by=caused_by))
    return sorted(out, key=lambda s: -abs(s.after - s.before))


class Director:
    """Allocates the world feed's attention across the ten matches."""

    def __init__(self, half_life_ms: int = 90_000):
        self.half_life_ms = half_life_ms
        self.on_screen: str | None = None
        self.since_t = 0

    def attention(self, moments: list[Moment], swings_by_match: dict[str, float], now_t: int) -> dict[str, float]:
        score: dict[str, float] = {}
        for m in moments:
            decay = 0.5 ** (max(0, now_t - m.t) / self.half_life_ms)
            score[m.match_id] = score.get(m.match_id, 0.0) + m.salience * decay
        for mid, s in swings_by_match.items():
            score[mid] = score.get(mid, 0.0) + 2.0 * s
        return score

    def rundown(self, moments: list[Moment], swings_by_match: dict[str, float], now_t: int,
                names: dict[str, str]) -> RundownItem | None:
        score = self.attention(moments, swings_by_match, now_t)
        if not score:
            return None
        best = max(score, key=score.get)
        hold = self.on_screen is not None and now_t - self.since_t < 20_000
        if hold and score.get(self.on_screen, 0) >= 0.6 * score[best]:
            best = self.on_screen
        if best != self.on_screen:
            self.on_screen, self.since_t = best, now_t
        recent = sorted((m for m in moments if m.match_id == best), key=lambda m: -m.t)[:3]
        why = recent[0].kind.replace("_", " ") if recent else "table stakes"
        if swings_by_match.get(best, 0) >= SWING_MIN:
            why += f"; it moves the table ({swings_by_match[best]:.0%} swing)"
        return RundownItem(channel="world", match_id=best, from_t=self.since_t,
                           reason=f"{names.get(best, best)}: {why}", moment_ids=[m.id for m in recent])
