"""The story board: what could be said about this match, and what has become due.

Stories come from the miners at kick-off. Events move them from latent to
live (pre-match stories go live at kick-off; a milestone goes live when the
goal is scored) and to resolved at full time. Surfacing is recorded so the
eval can measure Story Recall.
"""

from __future__ import annotations

from talkback.gallery.miners import StoryCandidate, mine_fixture
from talkback.gallery.world import World
from talkback.schemas.models import Event, EventType, Storyline

PRE_MATCH = {"debut", "farewell", "injury_return", "former_club", "relegation_six_pointer", "top_clash",
             "manager_milestone", "siblings", "milestone_apps"}
FINAL = {"unbeaten_run", "clean_sheet_record"}


def _story(c: StoryCandidate, status: str, **facts) -> Storyline:
    return Storyline(id=c.id, kind=c.kind, subjects=c.subjects, fixture_id=c.fixture_id, summary=c.summary,
                     facts={**c.evidence, **facts}, trigger="pre_match" if c.kind in PRE_MATCH else "on_event",
                     status=status)


class StoryBoard:
    def __init__(self, world: World, fixture_id: str):
        self.world = world
        self.fixture_id = fixture_id
        self.candidates = {c.id: c for c in mine_fixture(world, fixture_id)}
        self.stories: dict[str, Storyline] = {c.id: _story(c, "latent") for c in self.candidates.values()}
        self.goals_today: dict[str, int] = {}
        self.conceded: dict[str, int] = {}
        self.surfaced_by: dict[str, list[str]] = {}

    def _set(self, sid: str, status: str, **facts) -> Storyline:
        s = self.stories[sid]
        s = s.model_copy(update={"status": status, "facts": {**s.facts, **facts}})
        self.stories[sid] = s
        return s

    def kickoff(self) -> list[Storyline]:
        return [self._set(sid, "live") for sid, c in self.candidates.items() if c.kind in PRE_MATCH]

    def on_event(self, e: Event) -> list[Storyline]:
        changed: list[Storyline] = []
        if e.type == EventType.goal and e.player_id:
            self.goals_today[e.player_id] = self.goals_today.get(e.player_id, 0) + 1
            _, h, a = self.world.fixture(self.fixture_id)
            against = a if e.team_id == h else h
            self.conceded[against] = self.conceded.get(against, 0) + 1
            for sid, c in self.candidates.items():
                if e.player_id not in c.subjects:
                    continue
                if c.kind == "milestone_goals":
                    total = int(c.evidence["career_goals"]) + self.goals_today[e.player_id]
                    if total >= int(c.evidence["next"]):
                        changed.append(self._set(sid, "live", reached=total, goal_event=e.id))
                elif c.kind == "former_club":
                    changed.append(self._set(sid, "live", scored_against_former_club=True, goal_event=e.id))
                elif c.kind == "golden_boot":
                    changed.append(self._set(sid, "live", scorer=e.player_id, goal_event=e.id))
        if e.type == EventType.period_end and e.period == 2:
            for sid, c in self.candidates.items():
                if c.kind == "unbeaten_run":
                    club = c.subjects[0]
                    changed.append(self._set(sid, "resolved", lost=self._lost(club)))
                elif c.kind == "clean_sheet_record":
                    keeper_club = self.world.player(c.subjects[0]).club_id
                    if self.conceded.get(keeper_club, 0) == 0:
                        changed.append(self._set(sid, "resolved", kept=True))
        return changed

    def _lost(self, club: str) -> bool:
        _, h, a = self.world.fixture(self.fixture_id)
        other = a if club == h else h
        return self.conceded.get(club, 0) > self.conceded.get(other, 0)

    def surfaced(self, story_id: str, cue_id: str) -> None:
        self.surfaced_by.setdefault(story_id, []).append(cue_id)
        if story_id in self.stories and self.stories[story_id].status != "resolved":
            self._set(story_id, "surfaced")

    def live(self) -> list[Storyline]:
        return [s for s in self.stories.values() if s.status in ("live", "resolved")]
