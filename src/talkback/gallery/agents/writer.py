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
MAX_AGE_MS = {"analyst": 45_000, "casual": 45_000, "presenter": 20_000}

INSTRUCTIONS = (
    "You are the Writer in a football production gallery. Draft up to three short lines about the moment: "
    "one for the analyst feed, one for casual fans, and one 'presenter' line of at most 14 words that the "
    "presenter can say in a gap. Rules you must follow, they are checked by code:\n"
    "1. Every number in a line must be a claim whose refs point to a fact, experiment or storyline id from the "
    "evidence, with exactly that value (a fraction like 0.31 may be written as 31%).\n"
    "2. The claim's subject is the player or club id the number belongs to.\n"
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


def evidence_prompt(moment: Moment, facts: list[Fact], lab: LabResult | None, stories: list[Storyline],
                    names: dict[str, str]) -> str:
    lines = [f"Moment {moment.id}: {moment.kind} at {moment.t // 60_000}' subject={moment.subject} "
             f"({names.get(moment.subject or '', '')}) detail={moment.detail}", "", "Facts (id | metric | subject | value | n):"]
    for f in facts:
        lines.append(f"- {f.id} | {f.metric} | {f.subject} ({names.get(f.subject, '')}) | {f.value} | n={f.sample_size}")
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
        lines.append(f"- {s.id} | {s.kind} | {s.summary} | facts {s.facts}")
    if not stories:
        lines.append("- none")
    return "\n".join(lines)


def make_writer(client) -> Agent:
    return Agent(client=client, instructions=INSTRUCTIONS, name="writer",
                 description="Drafts evidence-tied lines for analyst, casual and presenter feeds.")


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
            claims=[Claim(**c.model_dump()) for c in d.claims], template=template, data=d.data,
            valid_state_hash=state_hash, max_age_ms=MAX_AGE_MS[d.audience], created_t=now_t))
    return cues
