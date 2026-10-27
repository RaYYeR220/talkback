"""Season-so-far backfill using the fast match model."""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from talkback.sim.fast import simulate_fast
from talkback.world.league import League
from talkback.world.schedule import double_round_robin


class TableRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    club_id: str
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    gf: int = 0
    ga: int = 0
    gd: int = 0
    pts: int = 0
    form: str = ""
    unbeaten_run: int = 0


class SeasonState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    league: League
    matchday: int
    table: list[TableRow]
    results: list[dict]
    player_season: dict[str, dict[str, int]] = Field(default_factory=dict)
    keeper_clean_sheets: dict[str, int] = Field(default_factory=dict)
    fixtures_next: list[tuple[str, str]]
    schedule: list[list[tuple[str, str]]]

    def sorted_table(self) -> list[TableRow]:
        names = {c.id: c.name for c in self.league.clubs}
        return sorted(self.table, key=lambda r: (-r.pts, -r.gd, -r.gf, names[r.club_id]))

    def row(self, club_id: str) -> TableRow:
        return next(r for r in self.table if r.club_id == club_id)


def _record(row: TableRow, gf: int, ga: int) -> None:
    row.played += 1
    row.gf += gf
    row.ga += ga
    row.gd = row.gf - row.ga
    if gf > ga:
        row.won += 1
        row.pts += 3
        res = "W"
    elif gf == ga:
        row.drawn += 1
        row.pts += 1
        res = "D"
    else:
        row.lost += 1
        res = "L"
    row.form = (row.form + res)[-5:]
    row.unbeaten_run = 0 if res == "L" else row.unbeaten_run + 1


def backfill_season(league: League, matchdays: int = 11, seed: int = 11) -> SeasonState:
    rng = np.random.default_rng(seed)
    schedule = double_round_robin([c.id for c in league.clubs], seed)
    table = {c.id: TableRow(club_id=c.id) for c in league.clubs}
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"goals": 0, "apps": 0, "assists": 0, "yellows": 0, "reds": 0})
    clean: dict[str, int] = defaultdict(int)
    results: list[dict] = []
    for md in range(matchdays):
        for home_id, away_id in schedule[md]:
            home, away = league.club(home_id), league.club(away_id)
            r = simulate_fast(home, away, rng)
            _record(table[home_id], r.home_goals, r.away_goals)
            _record(table[away_id], r.away_goals, r.home_goals)
            for pid in r.appearances:
                stats[pid]["apps"] += 1
                league.player(pid).career.career_apps += 1
            for pid, _ in r.scorers:
                stats[pid]["goals"] += 1
                league.player(pid).career.career_goals += 1
            for pid, _ in r.assists:
                stats[pid]["assists"] += 1
            for pid, kind, _ in r.cards:
                stats[pid]["yellows" if kind == "yellow" else "reds"] += 1
            for k in r.clean_sheet_keepers:
                clean[k] += 1
            home.manager.games_in_charge += 1
            away.manager.games_in_charge += 1
            results.append({"matchday": md + 1, "home": home_id, "away": away_id,
                            "hg": r.home_goals, "ag": r.away_goals, "scorers": r.scorers})
    return SeasonState(
        league=league, matchday=matchdays, table=list(table.values()), results=results,
        player_season={k: dict(v) for k, v in stats.items()}, keeper_clean_sheets=dict(clean),
        fixtures_next=schedule[matchdays], schedule=schedule,
    )
