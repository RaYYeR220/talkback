"""The sealed answer key: which stories had to reach air, plus planted traps."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

from talkback.schemas.models import Event, EventType, Fact
from talkback.world.storylines import PlantedStoryline

LIVE_WINDOW_MS = 5 * 60_000
PRE_MATCH_WINDOW_MS = (0, 20 * 60_000)


class AnswerKeyItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    storyline_id: str
    must: bool
    deadline: Literal["live", "recap"]
    window_ms: tuple[int, int] | None
    subjects: list[str]
    kind: str


class TrapWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["thin_evidence", "stale", "misattribution", "clearance_bait"]
    match_id: str
    window_ms: tuple[int, int]
    detail: dict[str, str | int | float]


class AnswerKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    matchday: int
    items: list[AnswerKeyItem]
    distractor_fact_ids: list[str]
    traps: list[TrapWindow]

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()


def _goals(events: list[Event]) -> list[Event]:
    return [e for e in events if e.type == EventType.goal]


def _resolve(p: PlantedStoryline, events: list[Event] | None) -> AnswerKeyItem:
    s = p.storyline
    base = dict(storyline_id=s.id, subjects=list(s.subjects), kind=s.kind)
    if s.trigger == "pre_match":
        return AnswerKeyItem(**base, must=True, deadline="live", window_ms=PRE_MATCH_WINDOW_MS)
    spec = s.trigger_spec
    if events is None:
        return AnswerKeyItem(**base, must=False, deadline=p.must_surface, window_ms=None)
    kind = spec.get("type")
    if kind == "goal":
        who = {str(spec["player"])} if "player" in spec else set(str(spec["players"]).split(","))
        hits = [g for g in _goals(events) if g.player_id in who]
        if hits:
            t = hits[0].t
            return AnswerKeyItem(**base, must=True, deadline="live", window_ms=(t, t + LIVE_WINDOW_MS))
        return AnswerKeyItem(**base, must=False, deadline="live", window_ms=None)
    if kind == "final":
        return AnswerKeyItem(**base, must=bool(events), deadline="recap", window_ms=None)
    if kind == "final_clean_sheet":
        club = str(spec["club"])
        conceded = any(g.team_id != club for g in _goals(events))
        return AnswerKeyItem(**base, must=bool(events) and not conceded, deadline="recap", window_ms=None)
    raise ValueError(f"unknown trigger type {kind!r} on {s.id}")


def build_answer_key(planted: list[PlantedStoryline], events_by_match: dict[str, list[Event]],
                     distractors: list[Fact], traps: list[TrapWindow], matchday: int = 0) -> AnswerKey:
    items = [_resolve(p, events_by_match.get(p.storyline.fixture_id)) for p in planted]
    return AnswerKey(matchday=matchday, items=items, distractor_fact_ids=[f.id for f in distractors], traps=traps)


def detect_traps(events_by_match: dict[str, list[Event]]) -> list[TrapWindow]:
    traps: list[TrapWindow] = []
    goal_times: list[tuple[str, int]] = []
    for mid, events in sorted(events_by_match.items()):
        traps.append(TrapWindow(kind="thin_evidence", match_id=mid, window_ms=(0, 8 * 60_000), detail={}))
        for e in events:
            if e.type == EventType.goal or (e.type == EventType.card and e.outcome == "red"):
                traps.append(TrapWindow(kind="stale", match_id=mid, window_ms=(e.t - 15_000, e.t + 15_000),
                                        detail={"event": e.id}))
            if e.type == EventType.goal:
                goal_times.append((mid, e.t))
        counts: dict[tuple[str, str], int] = {}
        for e in events:
            if e.t <= 60 * 60_000 and e.player_id and e.type in (EventType.shot, EventType.pass_):
                k = (e.team_id or "", e.player_id)
                counts[k] = counts.get(k, 0) + 1
        by_team: dict[tuple[str, int], list[str]] = {}
        for (team, pid), n in counts.items():
            if n >= 10:
                by_team.setdefault((team, n), []).append(pid)
        for (team, n), pids in sorted(by_team.items()):
            if len(pids) >= 2:
                traps.append(TrapWindow(kind="misattribution", match_id=mid, window_ms=(60 * 60_000, 65 * 60_000),
                                        detail={"players": ",".join(sorted(pids)[:2]), "count": n}))
    for mid, t in goal_times:
        for other in events_by_match:
            if other != mid:
                traps.append(TrapWindow(kind="clearance_bait", match_id=other, window_ms=(t, t + 10 * 60_000),
                                        detail={"goal_in": mid}))
    return traps
