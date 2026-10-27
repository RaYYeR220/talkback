"""Recap: the full-time story of a match, held to the same evidence rules as live lines."""

from __future__ import annotations

from agent_framework import Agent

from talkback.gallery.agents.writer import WriterAnswer, WriterFailure, _normalise
from talkback.gallery.jsonio import ParseError, parse_json
from talkback.schemas.models import Cue, Fact, Storyline

INSTRUCTIONS = (
    "You are the Recap writer in a football production gallery. At full time, write the match recap as ONE line of "
    "three to five sentences for the casual audience. Lead with the result, then the stories that a fan of either "
    "club would be upset to miss (milestones reached, farewells, debuts, reunions, races, records kept or ended, "
    "relegation or title stakes), then one telling statistic. The same rules as live lines apply and are checked "
    "by code: every number is a claim citing a fact or storyline id with that exact value and its player or club "
    "id as subject; no causal words without a supported experiment; strength levels declared honestly; no betting. "
    "Answer only with JSON: {\"cues\": [{\"audience\": \"casual\", \"template\": \"story_card\", \"text\": \"...\", "
    "\"data\": {}, \"claims\": [...]}]}"
)


def make_recap_writer(client) -> Agent:
    return Agent(client=client, instructions=INSTRUCTIONS, name="recap",
                 description="Writes the full-time recap from evidence and the story board.")


def recap_prompt(match_name: str, score: str, facts: list[Fact], stories: list[Storyline], aired: list[str],
                 names: dict[str, str]) -> str:
    lines = [f"Full time: {match_name} {score}.", "", "Facts (id | metric | subject | value | n):"]
    for f in facts:
        lines.append(f"- {f.id} | {f.metric} | {f.subject} ({names.get(f.subject, '')}) | {f.value} | n={f.sample_size}")
    lines += ["", "Storylines (id | kind | subjects | status | summary | facts):"]
    for s in stories:
        lines.append(f"- {s.id} | {s.kind} | {s.subjects} | {s.status} | {s.summary} | {s.facts}")
    if not stories:
        lines.append("- none")
    lines += ["", "Already said on air during the match:"] + [f"- {t}" for t in aired[-12:]]
    return "\n".join(lines)


async def write_recap(agent: Agent, match_id: str, match_name: str, score: str, facts: list[Fact],
                      stories: list[Storyline], aired: list[str], names: dict[str, str], state_hash: str,
                      now_t: int) -> Cue:
    result = await agent.run(recap_prompt(match_name, score, facts, stories, aired, names))
    try:
        answer = parse_json(result.text, WriterAnswer)
    except ParseError as exc:
        raise WriterFailure(str(exc)) from exc
    if not answer.cues:
        raise WriterFailure("empty recap")
    d = answer.cues[0]
    return Cue(id=f"Q-{match_id}-recap", match_id=match_id, moment_id=None, audience="recap", text=d.text.strip(),
               lang="en", claims=_normalise(d.claims, stories), template="story_card", data=d.data,
               valid_state_hash=state_hash, max_age_ms=600_000, created_t=now_t)
