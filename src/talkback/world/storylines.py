"""Plant storylines into the season so the live matchday has stories to find.

Each storyline is made *true in the data* (career numbers, previous clubs,
table positions, line-ups) before the matchday is played. Which ones must be
surfaced is only decided after play, in `talkback.world.key`.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict

from talkback.schemas.models import Fact, Storyline
from talkback.sim.fast import select_xi
from talkback.world.league import Player
from talkback.world.season import SeasonState

KINDS = [
    "milestone_goals", "farewell", "debut", "former_club", "unbeaten_run", "manager_100",
    "relegation_six_pointer", "golden_boot", "clean_sheet_record", "injury_return", "siblings",
]

Lineups = dict[str, tuple[list[str], list[str]]]


class ForcedBeat(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    player_id: str
    kind: Literal["goal"]
    window_ms: tuple[int, int]
    prob: float


class PlantedStoryline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    storyline: Storyline
    must_surface: Literal["live", "recap"]
    forced_beat: ForcedBeat | None = None


def fixture_ids(season: SeasonState) -> list[tuple[str, str, str]]:
    md = season.matchday + 1
    return [(f"MD{md:02d}-F{i + 1:02d}", h, a) for i, (h, a) in enumerate(season.fixtures_next)]


def _swap_into_xi(xi: list[str], player: Player, lg_player) -> list[str]:
    if player.id in xi:
        return xi
    same = [pid for pid in xi if lg_player(pid).position == player.position]
    out = same[-1] if same else xi[-1]
    return [player.id if pid == out else pid for pid in xi]


def _make_six_pointer(season: SeasonState) -> tuple[str, str]:
    """Rearrange next matchday's pairings so 18th hosts 19th (each club still plays once)."""
    order = [r.club_id for r in season.sorted_table()]
    a, b = order[17], order[18]
    fx = list(season.fixtures_next)
    ia = next(i for i, f in enumerate(fx) if a in f)
    ib = next(i for i, f in enumerate(fx) if b in f)
    if ia != ib:
        oa = fx[ia][1] if fx[ia][0] == a else fx[ia][0]
        ob = fx[ib][1] if fx[ib][0] == b else fx[ib][0]
        fx[ia] = (a, b)
        fx[ib] = (oa, ob)
    else:
        fx[ia] = (a, b)
    season.fixtures_next = fx
    season.schedule[season.matchday] = fx
    return a, b


def plant_storylines(season: SeasonState, seed: int, per_matchday: int = 12
                     ) -> tuple[list[PlantedStoryline], list[Fact], Lineups]:
    rng = np.random.default_rng(seed)
    lg = season.league
    six_a, six_b = _make_six_pointer(season)
    fixtures = fixture_ids(season)
    lineups: Lineups = {}
    for fid, h, a in fixtures:
        hx, _ = select_xi(lg.club(h), rng)
        ax, _ = select_xi(lg.club(a), rng)
        lineups[fid] = ([p.id for p in hx], [p.id for p in ax])

    def fixture_of(club_id: str) -> tuple[str, str, str]:
        return next(f for f in fixtures if club_id in f[1:])

    def side_xi(fid: str, club_id: str) -> list[str]:
        h_xi, a_xi = lineups[fid]
        return h_xi if fixtures_by_id[fid][1] == club_id else a_xi

    fixtures_by_id = {f[0]: f for f in fixtures}
    six_fid = fixture_of(six_a)[0]
    free = [f for f in fixtures if f[0] != six_fid]
    order = list(rng.permutation(len(free)))
    slots = iter([free[i] for i in order] * 2)
    planted: list[PlantedStoryline] = []

    def add(kind: str, fid: str, subjects: list[str], summary: str, facts: dict, trigger: str,
            spec: dict, must: Literal["live", "recap"], beat: ForcedBeat | None = None) -> None:
        planted.append(PlantedStoryline(
            storyline=Storyline(id=f"S-{fid}-{kind}", kind=kind, subjects=subjects, fixture_id=fid,
                                summary=summary, facts=facts, trigger=trigger, trigger_spec=spec),
            must_surface=must, forced_beat=beat))

    # milestone: a forward on 99 career goals
    fid, h, a = next(slots)
    xi = side_xi(fid, h)
    striker = max((lg.player(p) for p in xi if lg.player(p).position == "FW"),
                  key=lambda p: p.attrs.finishing)
    striker.career.career_goals = 99
    add("milestone_goals", fid, [striker.id], f"{striker.name} is on 99 career goals.",
        {"career_goals": 99, "milestone": 100}, "on_event", {"type": "goal", "player": striker.id},
        "live", ForcedBeat(player_id=striker.id, kind="goal", window_ms=(55 * 60_000, 85 * 60_000), prob=0.85))

    # farewell: the oldest starter plays his last game
    fid, h, a = next(slots)
    vet = max((lg.player(p) for p in side_xi(fid, a)), key=lambda p: p.age)
    vet.age = max(vet.age, 35)
    vet.career.farewell = True
    add("farewell", fid, [vet.id], f"{vet.name} makes his final appearance before retiring.",
        {"age": vet.age, "career_apps": vet.career.career_apps + 1}, "pre_match", {}, "live")

    # debut: youngest outfielder not in the XI starts for the first time
    fid, h, a = next(slots)
    xi = side_xi(fid, h)
    kid = min((p for p in lg.club(h).squad if p.id not in xi and p.position != "GK"), key=lambda p: p.age)
    kid.age, kid.career.career_apps, kid.career.career_goals, kid.career.debut_pending = 18, 0, 0, True
    new_xi = _swap_into_xi(xi, kid, lg.player)
    lineups[fid] = (new_xi, lineups[fid][1])
    add("debut", fid, [kid.id], f"{kid.name}, 18, makes his senior debut.", {"age": 18}, "pre_match", {}, "live")

    # former club: a starter faces a club he used to play for
    fid, h, a = next(slots)
    player = max((lg.player(p) for p in side_xi(fid, a) if lg.player(p).position != "GK"),
                 key=lambda p: p.age)
    if h not in player.career.previous_clubs:
        player.career.previous_clubs = sorted(player.career.previous_clubs + [h])
    add("former_club", fid, [player.id], f"{player.name} returns to face his former club.",
        {"opponent": h}, "pre_match", {"upgrade_on": "goal", "player": player.id}, "live")

    # unbeaten run: the longest current run in the table
    best = max(season.table, key=lambda r: (r.unbeaten_run, -r.lost))
    fid = fixture_of(best.club_id)[0]
    add("unbeaten_run", fid, [best.club_id], f"{lg.club(best.club_id).name} are unbeaten in {best.unbeaten_run}.",
        {"unbeaten_run": best.unbeaten_run}, "on_event", {"type": "final", "club": best.club_id}, "recap")

    # manager's 100th game
    fid, h, a = next(slots)
    mgr = lg.club(h).manager
    mgr.games_in_charge = 99
    add("manager_100", fid, [mgr.id], f"{mgr.name} takes charge of his 100th game.",
        {"games_in_charge": 100}, "pre_match", {}, "live")

    # relegation six-pointer: 18th hosts 19th
    pts = {r.club_id: r.pts for r in season.table}
    add("relegation_six_pointer", six_fid, [six_a, six_b],
        f"{lg.club(six_a).name} (18th) host {lg.club(six_b).name} (19th).",
        {"gap": abs(pts[six_a] - pts[six_b])}, "pre_match", {}, "live")

    # golden boot: top two scorers one goal apart, both starting
    scorers = sorted(((pid, s["goals"]) for pid, s in season.player_season.items()), key=lambda x: -x[1])
    (p1, g1), (p2, g2) = scorers[0], scorers[1]
    season.player_season[p1]["goals"] = g2 + 1
    for pid in (p1, p2):
        f = fixture_of(pid.split("-")[0])
        xi = side_xi(f[0], pid.split("-")[0])
        new = _swap_into_xi(xi, lg.player(pid), lg.player)
        lineups[f[0]] = (new, lineups[f[0]][1]) if f[1] == pid.split("-")[0] else (lineups[f[0]][0], new)
    gb_fid = fixture_of(p1.split("-")[0])[0]
    add("golden_boot", gb_fid, [p1, p2], f"{lg.player(p1).name} leads the scoring chart by one from {lg.player(p2).name}.",
        {"leader_goals": g2 + 1, "chaser_goals": g2}, "on_event", {"type": "goal", "players": f"{p1},{p2}"}, "live")

    # clean-sheet record: the keeper is one away from the club record
    fid, h, a = next(slots)
    gk = side_xi(fid, h)[0]
    cs = max(season.keeper_clean_sheets.get(gk, 0), 4)
    season.keeper_clean_sheets[gk] = cs
    add("clean_sheet_record", fid, [gk], f"{lg.player(gk).name} needs one more clean sheet to equal the club record of {cs + 1}.",
        {"clean_sheets": cs, "record": cs + 1}, "on_event", {"type": "final_clean_sheet", "club": h, "keeper": gk}, "recap")

    # injury return
    fid, h, a = next(slots)
    back = lg.player(side_xi(fid, a)[5])
    back.career.returning_from_injury = True
    add("injury_return", fid, [back.id], f"{back.name} starts after eight weeks out injured.",
        {"weeks_out": 8}, "pre_match", {}, "live")

    # siblings on opposite sides
    fid, h, a = next(slots)
    hp = lg.player(side_xi(fid, h)[6])
    ap = lg.player(side_xi(fid, a)[6])
    surname = hp.name.split(" ", 1)[1]
    ap.name = f"{ap.name.split(' ', 1)[0]} {surname}"
    ap.short_name = surname
    hp.career.sibling_id, ap.career.sibling_id = ap.id, hp.id
    add("siblings", fid, [hp.id, ap.id], f"Brothers {hp.name} and {ap.name} line up on opposite sides.",
        {}, "pre_match", {}, "live")

    distractors = _trivia(season, rng)
    return planted, distractors, lineups


def _trivia(season: SeasonState, rng: np.random.Generator) -> list[Fact]:
    lg = season.league
    out: list[Fact] = []
    players = [p for c in lg.clubs for p in c.squad]
    picks = rng.choice(len(players), size=8, replace=False)
    metrics = ["trivia.shirt", "trivia.age", "trivia.career_apps", "trivia.shirt",
               "trivia.age", "trivia.career_apps", "trivia.shirt", "trivia.age"]
    for n, (i, metric) in enumerate(zip(picks, metrics)):
        p = players[int(i)]
        value = {"trivia.shirt": p.shirt, "trivia.age": p.age, "trivia.career_apps": p.career.career_apps}[metric]
        out.append(Fact(id=f"T-{n + 1:02d}", match_id=None, metric=metric, subject=p.id, value=float(value),
                        unit="count", window=(0, 0), sample_size=0, evidence=[], computed_at=0))
    return out
