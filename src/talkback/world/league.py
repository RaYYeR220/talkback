"""Fictional league generator: clubs, styles, squads and careers."""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from talkback.world import names

Position = Literal["GK", "DF", "MF", "FW"]
Role = Literal["GK", "CB", "FB", "DM", "CM", "AM", "W", "ST"]
Formation = Literal["4-3-3", "4-2-3-1", "4-4-2", "3-5-2"]

FORMATIONS: list[Formation] = ["4-3-3", "4-2-3-1", "4-4-2", "3-5-2"]

# role -> (position, count in a 25-man squad)
SQUAD_TEMPLATE: list[tuple[Role, Position, int]] = [
    ("GK", "GK", 3), ("CB", "DF", 4), ("FB", "DF", 4), ("DM", "MF", 2), ("CM", "MF", 4),
    ("AM", "MF", 2), ("W", "FW", 3), ("ST", "FW", 3),
]

# attribute emphasis per role: pace, passing, finishing, tackling, pressing, stamina, composure, keeping
ROLE_PROFILE: dict[str, tuple[int, ...]] = {
    "GK": (-25, -10, -45, -40, -30, -10, 5, 15),
    "CB": (-5, -5, -30, 12, 5, 0, 0, -60),
    "FB": (8, 0, -20, 5, 8, 10, -5, -60),
    "DM": (-5, 6, -15, 10, 10, 8, 4, -60),
    "CM": (0, 10, -5, 0, 5, 10, 5, -60),
    "AM": (4, 12, 6, -15, 0, 0, 8, -60),
    "W": (12, 4, 4, -20, 2, 5, 0, -60),
    "ST": (6, -2, 14, -25, 2, 0, 6, -60),
}


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StyleVector(Model):
    press: float = Field(ge=0, le=1)
    line: float = Field(ge=0, le=1)
    directness: float = Field(ge=0, le=1)
    width: float = Field(ge=0, le=1)
    tempo: float = Field(ge=0, le=1)


class Attributes(Model):
    pace: int
    passing: int
    finishing: int
    tackling: int
    pressing: int
    stamina: int
    composure: int
    keeping: int


class Career(Model):
    previous_clubs: list[str] = Field(default_factory=list)
    career_goals: int = 0
    career_apps: int = 0
    debut_pending: bool = False
    farewell: bool = False
    returning_from_injury: bool = False
    sibling_id: str | None = None


class Player(Model):
    id: str
    name: str
    short_name: str
    club_id: str
    position: Position
    role: Role
    shirt: int
    age: int
    attrs: Attributes
    career: Career


class Manager(Model):
    id: str
    name: str
    games_in_charge: int


class Club(Model):
    id: str
    name: str
    short: str
    city: str
    primary: str
    secondary: str
    strength: float
    style: StyleVector
    formation: Formation
    manager: Manager
    squad: list[Player]


class League(Model):
    name: str
    season: str
    clubs: list[Club]

    def club(self, club_id: str) -> Club:
        for c in self.clubs:
            if c.id == club_id:
                return c
        raise KeyError(club_id)

    def player(self, player_id: str) -> Player:
        club = self.club(player_id.split("-")[0])
        for p in club.squad:
            if p.id == player_id:
                return p
        raise KeyError(player_id)


def _attrs(rng: np.random.Generator, strength: float, role: str) -> Attributes:
    prof = ROLE_PROFILE[role]
    vals = [int(np.clip(round(strength + d + rng.normal(0, 6)), 1, 99)) for d in prof]
    return Attributes(pace=vals[0], passing=vals[1], finishing=vals[2], tackling=vals[3],
                      pressing=vals[4], stamina=vals[5], composure=vals[6], keeping=vals[7])


def _career(rng: np.random.Generator, age: int, role: str, club_ids: list[str], own: str) -> Career:
    seasons = max(0, age - 18)
    apps = int(seasons * rng.uniform(14, 34))
    goal_rate = {"GK": 0.0, "CB": 0.04, "FB": 0.03, "DM": 0.05, "CM": 0.09, "AM": 0.18,
                 "W": 0.22, "ST": 0.38}[role]
    goals = int(rng.binomial(apps, goal_rate)) if apps else 0
    others = [c for c in club_ids if c != own]
    n_prev = int(rng.integers(0, 4)) if seasons > 2 else 0
    prev = sorted(rng.choice(others, size=n_prev, replace=False).tolist()) if n_prev else []
    return Career(previous_clubs=prev, career_goals=goals, career_apps=apps)


def generate_league(seed: int = 7) -> League:
    rng = np.random.default_rng(seed)
    club_ids = [f"C{i:02d}" for i in range(1, 21)]
    strengths = np.linspace(62, 88, 20) + rng.normal(0, 1.5, 20)
    rng.shuffle(strengths)
    formations = [f for f in FORMATIONS for _ in range(5)]
    rng.shuffle(formations)
    first = list(names.FIRST_NAMES)
    last = list(names.LAST_NAMES)
    used_names: set[str] = set()

    clubs: list[Club] = []
    for i, (cname, short, city, primary, secondary) in enumerate(names.CLUBS):
        cid = club_ids[i]
        strength = float(np.clip(strengths[i], 62, 88))
        style = StyleVector(
            press=float(rng.beta(2, 2)), line=float(rng.beta(2, 2)),
            directness=float(rng.beta(2, 2.5)), width=float(rng.beta(2.5, 2)),
            tempo=float(rng.beta(2.5, 2)),
        )
        squad: list[Player] = []
        shirts = iter([1, 13, 31, 2, 3, 4, 5, 6, 12, 15, 22, 16, 8, 14, 18, 20, 10, 23, 7, 11, 17, 9, 19, 21, 29])
        n = 0
        for role, pos, count in SQUAD_TEMPLATE:
            for _ in range(count):
                n += 1
                while True:
                    full = f"{first[int(rng.integers(len(first)))]} {last[int(rng.integers(len(last)))]}"
                    if full not in used_names:
                        used_names.add(full)
                        break
                age = int(rng.integers(18, 35))
                squad.append(Player(
                    id=f"{cid}-P{n:02d}", name=full, short_name=full.split(" ", 1)[1], club_id=cid,
                    position=pos, role=role, shirt=next(shirts), age=age,
                    attrs=_attrs(rng, strength, role), career=_career(rng, age, role, club_ids, cid),
                ))
        mgr_name = f"{names.MANAGER_FIRST[i]} {last[int(rng.integers(len(last)))]}"
        clubs.append(Club(
            id=cid, name=cname, short=short, city=city, primary=primary, secondary=secondary,
            strength=round(strength, 2), style=style, formation=formations[i],
            manager=Manager(id=f"{cid}-M", name=mgr_name, games_in_charge=int(rng.integers(20, 160))),
            squad=squad,
        ))
    for c in clubs:
        for banned in names.BANNED_CLUB_NAMES:
            assert banned.lower() not in c.name.lower() and banned.lower() not in c.city.lower()
    return League(name=names.LEAGUE_NAME, season=names.SEASON, clubs=clubs)
