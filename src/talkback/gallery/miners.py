"""Story miners: generic scans of the season data for things worth saying.

They know nothing about which storylines were planted; they look for the
kinds of facts a researcher in a real gallery would look for.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from talkback.gallery.world import World


class StoryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: str
    fixture_id: str
    subjects: list[str]
    evidence: dict[str, str | int | float]
    summary: str


def _near_round(n: int) -> int | None:
    """The round number n is one short of, if any (49 -> 50, 99 -> 100, 199 -> 200)."""
    if n > 0 and (n + 1) % 50 == 0:
        return n + 1
    return None


def milestones(world: World, fixture_id: str) -> list[StoryCandidate]:
    out = []
    for pid in world.starters(fixture_id):
        p = world.player(pid)
        m = _near_round(p.career.career_goals)
        if m and p.position != "GK":
            out.append(StoryCandidate(
                id=f"M-{fixture_id}-{pid}-goals", kind="milestone_goals", fixture_id=fixture_id, subjects=[pid],
                evidence={"career_goals": p.career.career_goals, "next": m},
                summary=f"{p.name} is one goal from {m} career goals."))
        m2 = _near_round(p.career.career_apps)
        if m2:
            out.append(StoryCandidate(
                id=f"M-{fixture_id}-{pid}-apps", kind="milestone_apps", fixture_id=fixture_id, subjects=[pid],
                evidence={"career_apps": p.career.career_apps, "next": m2},
                summary=f"{p.name} makes career appearance number {m2}."))
    _, h, a = world.fixture(fixture_id)
    for cid in (h, a):
        mgr = world.club(cid).manager
        if (mgr.games_in_charge + 1) % 50 == 0:
            out.append(StoryCandidate(
                id=f"M-{fixture_id}-{mgr.id}", kind="manager_milestone", fixture_id=fixture_id, subjects=[mgr.id],
                evidence={"games_in_charge": mgr.games_in_charge + 1},
                summary=f"{mgr.name} takes charge of game {mgr.games_in_charge + 1}."))
    return out


def reunions(world: World, fixture_id: str) -> list[StoryCandidate]:
    _, h, a = world.fixture(fixture_id)
    hx, ax = world.lineups[fixture_id]
    out = []
    for xi, opp in ((hx, a), (ax, h)):
        for pid in xi:
            p = world.player(pid)
            if opp in p.career.previous_clubs:
                out.append(StoryCandidate(
                    id=f"R-{fixture_id}-{pid}", kind="former_club", fixture_id=fixture_id, subjects=[pid],
                    evidence={"opponent": opp}, summary=f"{p.name} faces his former club {world.club(opp).name}."))
    return out


def firsts_and_lasts(world: World, fixture_id: str) -> list[StoryCandidate]:
    out = []
    for pid in world.starters(fixture_id):
        p = world.player(pid)
        if p.career.debut_pending:
            out.append(StoryCandidate(id=f"F-{fixture_id}-{pid}-debut", kind="debut", fixture_id=fixture_id,
                                      subjects=[pid], evidence={"age": p.age}, summary=f"{p.name} makes his debut."))
        if p.career.farewell:
            out.append(StoryCandidate(id=f"F-{fixture_id}-{pid}-farewell", kind="farewell", fixture_id=fixture_id,
                                      subjects=[pid], evidence={"age": p.age, "career_apps": p.career.career_apps + 1},
                                      summary=f"{p.name} plays his final game."))
        if p.career.returning_from_injury:
            out.append(StoryCandidate(id=f"F-{fixture_id}-{pid}-return", kind="injury_return", fixture_id=fixture_id,
                                      subjects=[pid], evidence={}, summary=f"{p.name} returns from injury."))
    return out


def table_stakes(world: World, fixture_id: str) -> list[StoryCandidate]:
    _, h, a = world.fixture(fixture_id)
    ph, pa = world.position(h), world.position(a)
    n = len(world.table)
    out = []
    if ph >= n - 3 and pa >= n - 3:
        out.append(StoryCandidate(
            id=f"T-{fixture_id}-bottom", kind="relegation_six_pointer", fixture_id=fixture_id, subjects=[h, a],
            evidence={"home_position": ph, "away_position": pa},
            summary=f"{world.club(h).name} ({ph}) v {world.club(a).name} ({pa}) at the bottom."))
    if ph <= 3 and pa <= 3:
        out.append(StoryCandidate(
            id=f"T-{fixture_id}-top", kind="top_clash", fixture_id=fixture_id, subjects=[h, a],
            evidence={"home_position": ph, "away_position": pa},
            summary=f"{world.club(h).name} ({ph}) v {world.club(a).name} ({pa}) at the top."))
    return out


def races(world: World) -> list[StoryCandidate]:
    scorers = sorted(((pid, s.get("goals", 0)) for pid, s in world.player_season.items()), key=lambda x: -x[1])
    if len(scorers) < 2:
        return []
    (p1, g1), (p2, g2) = scorers[0], scorers[1]
    if g1 - g2 > 1:
        return []
    playing = {pid: fid for fid, _, _ in world.fixtures for pid in world.starters(fid)}
    if p1 not in playing or p2 not in playing:
        return []
    return [StoryCandidate(
        id=f"G-{p1}-{p2}", kind="golden_boot", fixture_id=playing[p1], subjects=[p1, p2],
        evidence={"leader_goals": g1, "chaser_goals": g2},
        summary=f"{world.player(p1).name} ({g1}) leads {world.player(p2).name} ({g2}) in the scoring chart.")]


def streaks(world: World, fixture_id: str) -> list[StoryCandidate]:
    _, h, a = world.fixture(fixture_id)
    out = []
    for cid in (h, a):
        r = world.row(cid)
        if r.unbeaten_run >= 5:
            out.append(StoryCandidate(
                id=f"S-{fixture_id}-{cid}-unbeaten", kind="unbeaten_run", fixture_id=fixture_id, subjects=[cid],
                evidence={"unbeaten_run": r.unbeaten_run},
                summary=f"{world.club(cid).name} are unbeaten in {r.unbeaten_run}."))
    hx, ax = world.lineups[fixture_id]
    for xi in (hx, ax):
        gk = xi[0]
        cs = world.clean_sheets.get(gk, 0)
        if cs >= 4:
            out.append(StoryCandidate(
                id=f"S-{fixture_id}-{gk}-cs", kind="clean_sheet_record", fixture_id=fixture_id, subjects=[gk],
                evidence={"clean_sheets": cs}, summary=f"{world.player(gk).name} has {cs} clean sheets this season."))
    return out


def relations(world: World, fixture_id: str) -> list[StoryCandidate]:
    hx, ax = world.lineups[fixture_id]
    out = []
    for pid in hx:
        sib = world.player(pid).career.sibling_id
        if sib and sib in ax:
            out.append(StoryCandidate(
                id=f"B-{fixture_id}-{pid}", kind="siblings", fixture_id=fixture_id, subjects=[pid, sib], evidence={},
                summary=f"Brothers {world.player(pid).name} and {world.player(sib).name} on opposite sides."))
    return out


def mine_fixture(world: World, fixture_id: str) -> list[StoryCandidate]:
    found: list[StoryCandidate] = []
    for fn in (milestones, reunions, firsts_and_lasts, table_stakes, streaks, relations):
        found.extend(fn(world, fixture_id))
    found.extend(c for c in races(world) if c.fixture_id == fixture_id)
    return found
