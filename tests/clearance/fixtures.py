"""Shared builders for the Clearance tests (fictional clubs and players only)."""

from talkback.clearance.checks import CheckContext
from talkback.schemas.models import (
    Claim, ClaimKind, Cue, Experiment, Fact, MatchState, Storyline, state_hash,
)

NOW = 70 * 60_000
STATE_HASH = state_hash(home_goals=1, away_goals=0, home_red=0, away_red=0, subs_count=2, period=2)
STATE = MatchState(match_id="F01", t=NOW, period=2, home_goals=1, away_goals=0,
                   game_state_hash=STATE_HASH)


def fact(fid: str, subject: str, value: float, *, metric: str = "team.xg", unit: str = "xg",
         n: int = 20, window: tuple[int, int] = (0, 900_000), match_id: str = "F01") -> Fact:
    return Fact(id=fid, match_id=match_id, metric=metric, subject=subject, value=value, unit=unit,
                window=window, sample_size=n, evidence=[], computed_at=window[1])


FACTS = {
    "F_xg_home": fact("F_xg_home", "C01", 1.4),
    "F_xg_away": fact("F_xg_away", "C02", 1.0),
    "F_comp_P07": fact("F_comp_P07", "C01-P07", 0.91, metric="player.pass_completion",
                       unit="ratio", n=34),
    "F_tilt_home": fact("F_tilt_home", "C01", 0.31, metric="team.field_tilt", unit="ratio"),
    "F_goals_C05": fact("F_goals_C05", "C05", 2, metric="team.goals", unit="count", match_id="F02"),
    "F_goals_C06": fact("F_goals_C06", "C06", 1, metric="team.goals", unit="count", match_id="F02"),
}

STORYLINES = {
    "S_milestone": Storyline(id="S_milestone", kind="milestone_goals", subjects=["C01-P07"],
                             fixture_id="F01", summary="Mensah is on 99 career goals.",
                             facts={"career_goals": 99, "milestone": 100}, trigger="on_event"),
}


def experiment(ci95: tuple[float, float], eid: str = "E_press") -> Experiment:
    return Experiment(id=eid, moment_id="M1", intervention={"type": "tactic", "team_id": "C01"},
                      n=240, metric="goal_for", baseline=0.02, counterfactual=0.05, effect=0.03,
                      ci95=ci95, seed=0)


def claim(span: str, kind: str = "numeric", *, subject: str | None = None, refs=(),
          value: float | None = None, strength: int = 0) -> Claim:
    return Claim(span=span, kind=ClaimKind(kind), subject=subject, refs=list(refs), value=value,
                 strength=strength)


def cue(text: str, claims=(), *, lang: str = "en", valid_state_hash: str = STATE_HASH,
        created_t: int = NOW - 5_000, max_age_ms: int = 30_000) -> Cue:
    return Cue(id="Q1", match_id="F01", audience="presenter", text=text, lang=lang,
               claims=list(claims), template="line", valid_state_hash=valid_state_hash,
               max_age_ms=max_age_ms, created_t=created_t)


def ctx(*, facts=None, experiments=None, storylines=None, state: MatchState = STATE,
        now_t: int = NOW, lang: str = "en") -> CheckContext:
    return CheckContext(facts=FACTS if facts is None else facts,
                        experiments={} if experiments is None else experiments,
                        storylines=STORYLINES if storylines is None else storylines,
                        state=state, now_t=now_t, lang=lang)


XG_CLAIM = claim("1.4 xG", subject="C01", refs=["F_xg_home"], value=1.4)
