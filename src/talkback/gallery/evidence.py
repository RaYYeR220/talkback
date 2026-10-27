"""Which Facts a moment's writer gets to see (and Clearance checks against)."""

from __future__ import annotations

from talkback.gallery.spotter import Moment
from talkback.schemas.models import Fact
from talkback.stats.desk import StatsDesk

TEAM = ("team.xg", "team.shots", "team.shots_on_target", "team.possession", "team.field_tilt", "team.ppda",
        "team.momentum", "team.win_probability", "team.pass_completion")
PLAYER = ("player.goals", "player.xg", "player.shots", "player.passes", "player.pass_completion",
          "player.distance_km", "player.top_speed_kmh", "player.xt_added", "player.tackles_won")
WINDOW_MS = 10 * 60_000


def evidence_facts(desk: StatsDesk, moment: Moment, now_t: int) -> list[Fact]:
    facts: list[Fact] = []
    for team in desk.team_ids:
        for metric in TEAM:
            f = desk.fact(metric, team)
            if f is not None:
                facts.append(f)
        start = max(0, now_t - WINDOW_MS)
        for metric in ("team.ppda", "team.field_tilt", "team.possession"):
            facts.append(desk.window_fact(metric, team, start, now_t))
    subject = moment.subject
    if subject and subject not in desk.team_ids:
        for metric in PLAYER:
            f = desk.fact(metric, subject)
            if f is not None:
                facts.append(f)
        for metric in ("event.shot_speed_kmh", "event.pass_difficulty", "event.pass_distance_m"):
            f = desk.fact(metric, subject)
            if f is not None and f.sample_size:
                facts.append(f)
    seen: set[str] = set()
    out = []
    for f in facts:
        key = f"{f.metric}:{f.subject}:{f.window}"
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out
