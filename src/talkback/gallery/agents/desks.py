"""Territory desks: each market gets the line in its language and under its own rules.

A desk localises the cue (Spanish, Arabic, Portuguese, or a simpler English
for the kids feed) and hands the text back to Clearance, which re-checks the
numbers, strength and causal wording of the localised text before applying
the territory pack.
"""

from __future__ import annotations

import asyncio

from agent_framework import Agent
from pydantic import BaseModel, Field

from talkback.gallery.jsonio import ParseError, parse_json
from talkback.schemas.models import Cue

LANG = {"uk": "en", "kids": "en", "es": "es", "br": "pt", "mena": "ar"}
LANGUAGE_NAME = {"es": "Spanish (Spain)", "pt": "Portuguese (Brazil)", "ar": "Modern Standard Arabic"}

TRANSLATE = (
    "You localise one line of live football graphics for a broadcast market. Translate it into {language}. "
    "Keep every number, minute, name and club exactly as given (use the same digits). Do not add facts, "
    "adjectives, reasons or opinions, and never mention betting. Answer only with JSON: {{\"text\": \"...\"}}"
)
KIDS = (
    "You rewrite one line of live football graphics for a children's feed. Use short, simple English. Keep "
    "every number, name and club exactly as given. Leave out injuries, cards and refereeing details, and do "
    "not use strong words like dominant or relentless. Answer only with JSON: {\"text\": \"...\"}"
)


class _Text(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class TerritoryDesk:
    def __init__(self, territory: str, client=None):
        self.territory = territory
        self.lang = LANG[territory]
        self.agent: Agent | None = None
        if territory == "kids":
            self.agent = Agent(client=client, instructions=KIDS, name="desk-kids")
        elif self.lang != "en":
            self.agent = Agent(client=client, instructions=TRANSLATE.format(language=LANGUAGE_NAME[self.lang]),
                               name=f"desk-{territory}")

    async def localise(self, cue: Cue) -> tuple[str, str] | None:
        """The localised (text, lang), or None when the desk could not produce one."""
        if self.agent is None:
            return cue.text, self.lang
        result = await self.agent.run(cue.text)
        try:
            return parse_json(result.text, _Text).text, self.lang
        except ParseError:
            return None


async def localise_all(cue: Cue, desks: list[TerritoryDesk]) -> dict[str, tuple[str, str]]:
    """Territories whose desk failed are left out; the gate then kills them for missing localisation."""
    async def one(d: TerritoryDesk) -> tuple[str, tuple[str, str] | None]:
        try:
            return d.territory, await d.localise(cue)
        except Exception:  # noqa: BLE001
            return d.territory, None

    results = await asyncio.gather(*(one(d) for d in desks))
    return {t: v for t, v in results if v is not None}


BATCH = (
    "\n\nYou may get several numbered lines. Localise each one separately and answer only with JSON: "
    "{\"texts\": [\"<line 1>\", \"<line 2>\", ...]} in the same order."
)


class _Texts(BaseModel):
    texts: list[str]


async def localise_many(cues: list[Cue], desks: list[TerritoryDesk]) -> list[dict[str, tuple[str, str]]]:
    """One model call per territory for all of a moment's lines; failures leave that territory out."""
    if not cues:
        return []
    out: list[dict[str, tuple[str, str]]] = [{} for _ in cues]

    async def one(d: TerritoryDesk) -> None:
        if d.agent is None:
            for i, c in enumerate(cues):
                out[i][d.territory] = (c.text, d.lang)
            return
        if len(cues) == 1:
            got = await d.localise(cues[0])
            if got is not None:
                out[0][d.territory] = got
            return
        prompt = "\n".join(f"{i + 1}. {c.text}" for i, c in enumerate(cues)) + BATCH
        try:
            texts = parse_json((await d.agent.run(prompt)).text, _Texts).texts
        except Exception:  # noqa: BLE001
            return
        if len(texts) != len(cues):
            return
        for i, t in enumerate(texts):
            if t.strip():
                out[i][d.territory] = (t.strip(), d.lang)

    await asyncio.gather(*(one(d) for d in desks))
    return out
