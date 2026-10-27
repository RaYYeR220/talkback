"""Writer: drafts the lines for a moment, each claim tied to the evidence it rests on."""

from __future__ import annotations

from typing import Literal

from agent_framework import Agent
from pydantic import BaseModel, Field

from talkback.gallery.agents.lab import LabResult
from talkback.gallery.jsonio import ParseError, parse_json
from talkback.gallery.spotter import Moment
from talkback.schemas.models import Claim, ClaimKind, Cue, Fact, Storyline

Audience = Literal["analyst", "casual", "presenter"]
TEMPLATES = ("stat_card", "story_card", "lower_third", "counterfactual_card", "table_swing", "player_tag")
MAX_AGE_MS = {"analyst": 120_000, "casual": 120_000, "presenter": 60_000}
# how long a line about this kind of moment stays worth saying (match ms)
MOMENT_MAX_AGE_MS = {"storyline": 600_000, "goal": 90_000, "red_card": 90_000, "big_chance": 60_000,
                     "big_save": 60_000, "pressing_surge": 180_000, "momentum_swing": 180_000}


def max_age(moment_kind: str, audience: str, pre_match: bool = False) -> int:
    base = MOMENT_MAX_AGE_MS.get(moment_kind, MAX_AGE_MS.get(audience, 120_000))
    if moment_kind == "storyline" and not pre_match:
        base = 180_000
    return min(base, MAX_AGE_MS["presenter"]) if audience == "presenter" and moment_kind != "storyline" else base

INSTRUCTIONS = (
    "You are the Writer in a football production gallery. Draft up to three short lines about the moment: "
    "one for the analyst feed, one for casual fans, and one 'presenter' line of at most 14 words that the "
    "presenter can say in a gap. Rules you must follow, they are checked by code:\n"
    "1. Every number in a line must be a claim whose refs point to a fact, experiment or storyline id from the "
    "evidence; the claim's value is the number exactly as written in the line (a fact of 0.31 written as 31% "
    "has value 31). Write numbers as digits (3, not three); a number in words is checked the same way. "
    "For comparative words (more, on top, dominant) cite the facts of both sides.\n"
    "2. The claim's subject is the player or club id the number or story belongs to (for a storyline claim, one "
    "of the ids listed as its subjects), never a fact, experiment or storyline id.\n"
    "3. Use causal words (because, forced, cost them, won it) only with a supported experiment; otherwise "
    "describe, do not explain.\n"
    "4. Declare each claim's strength: 0 neutral, 1 hedged (edging, early signs), 2 firm (on top, in charge), "
    "3 absolute (dominant, relentless, always). Strong words need lots of evidence; prefer 0-1 early in games.\n"
    "5. Never mention betting, odds or gambling.\n"
    "Answer only with JSON: {\"cues\": [{\"audience\": \"analyst|casual|presenter\", \"template\": \"stat_card\", "
    "\"text\": \"...\", \"data\": {}, \"claims\": [{\"span\": \"...\", \"kind\": \"numeric|comparative|causal|"
    "storyline|descriptive\", \"subject\": \"...\", \"refs\": [\"...\"], \"value\": 0.0, \"strength\": 0}]}]}"
)


class _Claim(BaseModel):
    span: str
    kind: ClaimKind
    subject: str | None = None
    refs: list[str] = Field(default_factory=list)
    value: float | None = None
    strength: int = Field(default=0, ge=0, le=3)


class _Draft(BaseModel):
    audience: Audience
    template: str = "stat_card"
    text: str = Field(min_length=3, max_length=400)
    data: dict[str, str | float | int | None] = Field(default_factory=dict)
    claims: list[_Claim] = Field(default_factory=list)


class WriterAnswer(BaseModel):
    cues: list[_Draft] = Field(max_length=3)


class WriterFailure(Exception):
    pass


# Decimals a commentator would say, by unit. The number check accepts this rounding of a fact's value.
_SPOKEN_DECIMALS = {"count": 0, "km": 1, "km/h": 1, "m": 1}


def say(fact: Fact) -> str:
    """The fact's value at broadcast precision: '0.33' xG, not '0.3331'."""
    text = f"{fact.value:.{_SPOKEN_DECIMALS.get(fact.unit, 2)}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def evidence_prompt(moment: Moment, facts: list[Fact], lab: LabResult | None, stories: list[Storyline],
                    names: dict[str, str]) -> str:
    lines = [f"Moment {moment.id}: {moment.kind} at {moment.t // 60_000}' subject={moment.subject} "
             f"({names.get(moment.subject or '', '')}) detail={moment.detail}", "", "Facts (id | metric | subject | value | n):"]
    for f in facts:
        lines.append(f"- {f.id} | {f.metric} | {f.subject} ({names.get(f.subject, '')}) | {say(f)} | n={f.sample_size}")
    lines.append("")
    lines.append("Experiments:")
    if lab and lab.experiments:
        for x in lab.experiments:
            lines.append(f"- {x.id} | {x.metric} | effect {x.effect} | ci95 {list(x.ci95)} | "
                         f"supported={x.ci95[0] > 0 or x.ci95[1] < 0} | {x.intervention.get('describe')}")
    else:
        lines.append("- none (no causal wording allowed)")
    lines.append("")
    lines.append("Storylines:")
    for s in stories:
        lines.append(f"- {s.id} | {s.kind} | subjects {s.subjects} | {s.summary} | facts {s.facts}")
    if not stories:
        lines.append("- none")
    return "\n".join(lines)


def make_writer(client) -> Agent:
    return Agent(client=client, instructions=INSTRUCTIONS, name="writer",
                 description="Drafts evidence-tied lines for analyst, casual and presenter feeds.")


def _normalise(claims: list[_Claim], stories: list[Storyline]) -> list[Claim]:
    """A claim naming a storyline id as its subject means the story's own subject."""
    by_id = {s.id: s for s in stories}
    out = []
    for c in claims:
        subject = c.subject
        if subject in by_id:
            story = by_id[subject]
            subject = story.subjects[0] if len(story.subjects) == 1 else None
        out.append(Claim(**{**c.model_dump(), "subject": subject}))
    return out


REVISE = (
    "Clearance rejected your line for these reasons:\n{reasons}\n\nRewrite it once so it passes: give every "
    "number a claim with the right ref, value and subject, remove anything you cannot back with the evidence, "
    "and soften wording that is too strong for the evidence. Same JSON format, one cue for the same audience."
)


async def revise_cue(agent: Agent, cue: Cue, reasons: list[str], moment: Moment, facts: list[Fact],
                     lab: LabResult | None, stories: list[Storyline], names: dict[str, str]) -> Cue | None:
    reasons_text = "\n".join(f"- {r}" for r in reasons[:6])
    prompt = (evidence_prompt(moment, facts, lab, stories, names) + "\n\nYour line (" + cue.audience + "): "
              + cue.text + "\n\n" + REVISE.format(reasons=reasons_text))
    try:
        answer = parse_json((await agent.run(prompt)).text, WriterAnswer)
    except ParseError:
        return None
    if not answer.cues:
        return None
    d = answer.cues[0]
    return cue.model_copy(update={"id": cue.id + "-r", "text": d.text.strip(), "claims": _normalise(d.claims, stories),
                                  "data": d.data, "verdicts": {}, "universal_reasons": []})


async def draft_cues(agent: Agent, moment: Moment, facts: list[Fact], lab: LabResult | None,
                     stories: list[Storyline], names: dict[str, str], state_hash: str, now_t: int) -> list[Cue]:
    result = await agent.run(evidence_prompt(moment, facts, lab, stories, names))
    try:
        answer = parse_json(result.text, WriterAnswer)
    except ParseError as exc:
        raise WriterFailure(str(exc)) from exc
    cues = []
    for n, d in enumerate(answer.cues):
        template = d.template if d.template in TEMPLATES else "stat_card"
        cues.append(Cue(
            id=f"Q-{moment.id}-{d.audience}-{n}", match_id=moment.match_id, moment_id=moment.id,
            audience=d.audience, text=d.text.strip(), lang="en",
            claims=_normalise(d.claims, stories), template=template, data=d.data,
            valid_state_hash=state_hash,
            max_age_ms=max_age(moment.kind, d.audience, pre_match=moment.detail.get("pre_match") == 1),
            created_t=now_t))
    return cues
