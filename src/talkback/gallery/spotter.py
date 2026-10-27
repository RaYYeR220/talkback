"""Spotter: deterministic triggers propose moments, a fast model ranks them.

Triggers never produce on-air text, so when the ranking call fails the
Spotter falls back to rule salience and says so (`ranked_by="rules"`).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from talkback.gallery.jsonio import ParseError, parse_json
from talkback.schemas.models import Event, EventType, Outcome
from talkback.stats.desk import StatsDesk

RULE_SALIENCE = {
    "goal": 0.95, "red_card": 0.85, "big_chance": 0.7, "big_save": 0.6, "storyline": 0.75,
    "pressing_surge": 0.55, "momentum_swing": 0.5, "speed_alert": 0.35, "hard_pass": 0.3,
}
SURGE_DROP = 0.4
SURGE_WINDOW_MS = 10 * 60_000
SPEED_ALERT_KMH = 33.0


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    match_id: str
    t: int
    kind: str
    subject: str | None
    event_ids: list[str]
    detail: dict[str, str | float | int] = Field(default_factory=dict)


class Moment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    match_id: str
    t: int
    kind: str
    subject: str | None
    salience: float
    rationale: str
    event_ids: list[str]
    detail: dict[str, str | float | int] = Field(default_factory=dict)
    ranked_by: str = "model"


class _Rank(BaseModel):
    candidate_id: str
    salience: float = Field(ge=0, le=1)
    rationale: str


class _Ranking(BaseModel):
    ranking: list[_Rank]


class Triggers:
    """Scans new events (and the desk's rolling metrics) for candidate moments."""

    def __init__(self, desk: StatsDesk):
        self.desk = desk
        self._seen: set[str] = set()
        self._last_momentum: dict[str, float] = {}
        self._last_surge_t: dict[str, int] = {}
        self._speed_flagged: set[str] = set()

    def _cand(self, kind: str, e: Event | None, t: int, subject: str | None, event_ids: list[str],
              **detail) -> Candidate | None:
        cid = f"C-{self.desk.match_id}-{kind}-{e.seq if e else t}"
        if cid in self._seen:
            return None
        self._seen.add(cid)
        return Candidate(id=cid, match_id=self.desk.match_id, t=t, kind=kind, subject=subject,
                         event_ids=event_ids, detail=detail)

    def scan(self, new_events: list[Event], now_t: int) -> list[Candidate]:
        out: list[Candidate | None] = []
        for e in new_events:
            if e.type == EventType.goal:
                out.append(self._cand("goal", e, e.t, e.player_id, [e.id], team=e.team_id or ""))
            elif e.type == EventType.card and e.outcome == Outcome.red:
                out.append(self._cand("red_card", e, e.t, e.player_id, [e.id], team=e.team_id or ""))
            elif e.type == EventType.shot and float(e.qualifiers.get("xg", 0)) >= 0.15 and e.outcome != Outcome.goal:
                out.append(self._cand("big_chance", e, e.t, e.player_id, [e.id], xg=float(e.qualifiers["xg"])))
            elif e.type == EventType.save:
                out.append(self._cand("big_save", e, e.t, e.player_id, [e.id]))
            elif (e.type == EventType.pass_ and e.outcome == Outcome.success
                  and 1 - float(e.qualifiers.get("xpass", 1)) >= 0.75):
                out.append(self._cand("hard_pass", e, e.t, e.player_id, [e.id],
                                      difficulty=round(1 - float(e.qualifiers["xpass"]), 3)))
        out.extend(self._rolling(now_t))
        return [c for c in out if c is not None]

    def _rolling(self, now_t: int) -> list[Candidate | None]:
        out: list[Candidate | None] = []
        if now_t >= 2 * SURGE_WINDOW_MS:
            for team in self.desk.team_ids:
                now = self.desk.window_fact("team.ppda", team, now_t - SURGE_WINDOW_MS, now_t)
                before = self.desk.window_fact("team.ppda", team, now_t - 2 * SURGE_WINDOW_MS, now_t - SURGE_WINDOW_MS)
                recent = now_t - self._last_surge_t.get(team, -10**9) < SURGE_WINDOW_MS
                if (now.sample_size >= 3 and before.sample_size >= 3 and before.value > 0
                        and now.value <= (1 - SURGE_DROP) * before.value and not recent):
                    self._last_surge_t[team] = now_t
                    out.append(self._cand("pressing_surge", None, now_t, team, now.evidence[-10:],
                                          ppda_before=round(before.value, 2), ppda_now=round(now.value, 2)))
        for team in self.desk.team_ids:
            m = self.desk.fact("team.momentum", team)
            if m is None:
                continue
            prev = self._last_momentum.get(team)
            self._last_momentum[team] = m.value
            if prev is not None and (prev > 0) != (m.value > 0) and abs(m.value - prev) >= 0.15:
                out.append(self._cand("momentum_swing", None, now_t, team, m.evidence[-10:],
                                      before=round(prev, 3), now=round(m.value, 3)))
        for pid in self.desk.players():
            if pid in self._speed_flagged:
                continue
            f = self.desk.fact("player.top_speed_kmh", pid)
            if f and f.value >= SPEED_ALERT_KMH:
                self._speed_flagged.add(pid)
                out.append(self._cand("speed_alert", None, now_t, pid, [], top_speed_kmh=round(f.value, 1)))
        return out


def rule_moments(cands: list[Candidate]) -> list[Moment]:
    return [Moment(id=c.id.replace("C-", "M-", 1), match_id=c.match_id, t=c.t, kind=c.kind, subject=c.subject,
                   salience=RULE_SALIENCE.get(c.kind, 0.3), rationale="rules", event_ids=c.event_ids,
                   detail=c.detail, ranked_by="rules") for c in cands]


RANK_INSTRUCTIONS = (
    "You are the Spotter in a football production gallery. You get candidate moments from one match. "
    "Score each candidate's salience for a live broadcast between 0 and 1 and give a one-line reason. "
    "Goals and red cards are always at least 0.8. Answer only with JSON: "
    '{"ranking": [{"candidate_id": "...", "salience": 0.0, "rationale": "..."}]}'
)


class Spotter:
    def __init__(self, agent):
        self.agent = agent

    async def rank(self, cands: list[Candidate], context: str = "") -> list[Moment]:
        if not cands:
            return []
        prompt = context + "\nCandidates:\n" + "\n".join(
            f"- {c.id}: {c.kind} subject={c.subject} detail={c.detail}" for c in cands)
        try:
            result = await self.agent.run(prompt)
            ranking = {r.candidate_id: r for r in parse_json(result.text, _Ranking).ranking}
        except (ParseError, Exception):  # noqa: BLE001 - ranking failure degrades to rules, never to air
            return rule_moments(cands)
        out = []
        for c, m in zip(cands, rule_moments(cands)):
            r = ranking.get(c.id)
            if r is None:
                out.append(m)
                continue
            sal = max(r.salience, 0.8) if c.kind in ("goal", "red_card") else r.salience
            out.append(m.model_copy(update={"salience": sal, "rationale": r.rationale, "ranked_by": "model"}))
        return out
