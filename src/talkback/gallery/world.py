"""The agent-visible world: league, season so far, fixtures and line-ups (no storylines)."""

from __future__ import annotations

import json
from pathlib import Path

from talkback.world.league import Club, League, Player
from talkback.world.season import TableRow


class World:
    def __init__(self, data: dict):
        self.data = data
        self.league = League.model_validate(data["league"])
        season = data["season"]
        self.matchday = int(season["matchday"]) + 1
        self.table = [TableRow.model_validate(r) for r in season["table"]]
        self.results: list[dict] = season["results"]
        self.player_season: dict[str, dict[str, int]] = season.get("player_season", {})
        self.clean_sheets: dict[str, int] = season.get("keeper_clean_sheets", {})
        self.fixtures: list[tuple[str, str, str]] = [tuple(f) for f in data["fixtures"]]
        self.lineups: dict[str, tuple[list[str], list[str]]] = {k: (v[0], v[1]) for k, v in data["lineups"].items()}
        self.trivia = data.get("trivia", [])
        self._clubs = {c.id: c for c in self.league.clubs}
        self._players = {p.id: p for c in self.league.clubs for p in c.squad}

    @classmethod
    def load(cls, path: Path) -> "World":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def club(self, club_id: str) -> Club:
        return self._clubs[club_id]

    def player(self, player_id: str) -> Player:
        return self._players[player_id]

    def fixture(self, fixture_id: str) -> tuple[str, str, str]:
        return next(f for f in self.fixtures if f[0] == fixture_id)

    def fixture_of_club(self, club_id: str) -> str:
        return next(f[0] for f in self.fixtures if club_id in f[1:])

    def starters(self, fixture_id: str) -> list[str]:
        h, a = self.lineups[fixture_id]
        return list(h) + list(a)

    def sorted_table(self) -> list[TableRow]:
        names = {c.id: c.name for c in self.league.clubs}
        return sorted(self.table, key=lambda r: (-r.pts, -r.gd, -r.gf, names[r.club_id]))

    def position(self, club_id: str) -> int:
        return [r.club_id for r in self.sorted_table()].index(club_id) + 1

    def row(self, club_id: str) -> TableRow:
        return next(r for r in self.table if r.club_id == club_id)

    def fixture_context(self, fixture_id: str) -> dict:
        fid, h, a = self.fixture(fixture_id)

        def side(cid: str) -> dict:
            r = self.row(cid)
            return {"club": self.club(cid).name, "id": cid, "position": self.position(cid), "points": r.pts,
                    "form": r.form, "manager": self.club(cid).manager.name}

        return {"fixture": fid, "home": side(h), "away": side(a), "matchday": self.matchday}
