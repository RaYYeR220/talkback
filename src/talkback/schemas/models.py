"""Shared data model for every stage of the pipeline.

Events and frames come out of the simulator, Facts out of the Stats Desk,
Storylines out of the world generator, Experiments out of the Lab, and Cues
carry a line from the Writer through Clearance to air.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

Scalar = float | int | str | bool


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EventType(StrEnum):
    kickoff = "kickoff"
    pass_ = "pass"
    carry = "carry"
    dribble = "dribble"
    cross = "cross"
    shot = "shot"
    goal = "goal"
    save = "save"
    block = "block"
    pressure = "pressure"
    tackle = "tackle"
    interception = "interception"
    clearance = "clearance"
    ball_recovery = "ball_recovery"
    foul = "foul"
    card = "card"
    substitution = "substitution"
    injury = "injury"
    throw_in = "throw_in"
    corner = "corner"
    free_kick = "free_kick"
    goal_kick = "goal_kick"
    penalty = "penalty"
    offside = "offside"
    period_start = "period_start"
    period_end = "period_end"


class Outcome(StrEnum):
    success = "success"
    fail = "fail"
    out = "out"
    on_target = "on_target"
    off_target = "off_target"
    blocked = "blocked"
    saved = "saved"
    goal = "goal"
    yellow = "yellow"
    red = "red"
    none = "none"


class Verdict(StrEnum):
    ON_AIR = "ON_AIR"
    HOLD_FOR_PRODUCER = "HOLD_FOR_PRODUCER"
    KILLED = "KILLED"


class ClaimKind(StrEnum):
    numeric = "numeric"
    comparative = "comparative"
    causal = "causal"
    storyline = "storyline"
    descriptive = "descriptive"


def event_id(match_id: str, seq: int) -> str:
    return f"{match_id}-{seq:06d}"


def state_hash(*, home_goals: int, away_goals: int, home_red: int, away_red: int,
               subs_count: int, period: int) -> str:
    raw = f"{home_goals}:{away_goals}:{home_red}:{away_red}:{subs_count}:{period}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


class Event(Frozen):
    id: str
    match_id: str
    seq: int
    t: int
    period: int
    type: EventType
    team_id: str | None = None
    player_id: str | None = None
    other_player_id: str | None = None
    x: float | None = None
    y: float | None = None
    end_x: float | None = None
    end_y: float | None = None
    outcome: Outcome = Outcome.none
    possession_id: int = 0
    qualifiers: dict[str, Scalar] = Field(default_factory=dict)


class PlayerPos(Frozen):
    player_id: str
    x: float
    y: float
    speed: float


class TrackingFrame(Frozen):
    match_id: str
    t: int
    ball: tuple[float, float, float]
    players: list[PlayerPos]


class MatchState(Frozen):
    match_id: str
    t: int
    period: int
    home_goals: int
    away_goals: int
    home_red: int = 0
    away_red: int = 0
    possession_team: str | None = None
    game_state_hash: str


class Fact(Frozen):
    id: str
    match_id: str | None
    metric: str
    subject: str
    value: float
    unit: str
    window: tuple[int, int]
    sample_size: int
    evidence: list[str]
    computed_at: int


class Storyline(Frozen):
    id: str
    kind: str
    subjects: list[str]
    fixture_id: str
    summary: str
    facts: dict[str, Scalar] = Field(default_factory=dict)
    trigger: str
    trigger_spec: dict[str, Scalar] = Field(default_factory=dict)
    status: str = "latent"


class Experiment(Frozen):
    id: str
    moment_id: str
    intervention: dict[str, Scalar | None]
    n: int
    metric: str
    baseline: float
    counterfactual: float
    effect: float
    ci95: tuple[float, float]
    seed: int


class Claim(Frozen):
    span: str
    kind: ClaimKind
    subject: str | None = None
    refs: list[str] = Field(default_factory=list)
    value: float | None = None
    strength: int = Field(default=0, ge=0, le=3)


class TerritoryVerdict(Frozen):
    territory: str
    verdict: Verdict
    reasons: list[str] = Field(default_factory=list)
    text: str


class Cue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    match_id: str
    moment_id: str | None = None
    audience: str
    text: str
    lang: str = "en"
    claims: list[Claim] = Field(default_factory=list)
    template: str
    data: dict[str, Scalar | None] = Field(default_factory=dict)
    valid_state_hash: str
    max_age_ms: int
    created_t: int
    universal_reasons: list[str] = Field(default_factory=list)
    verdicts: dict[str, TerritoryVerdict] = Field(default_factory=dict)


ALL_MODELS: list[type[BaseModel]] = [
    Event, PlayerPos, TrackingFrame, MatchState, Fact, Storyline, Experiment,
    Claim, TerritoryVerdict, Cue,
]
