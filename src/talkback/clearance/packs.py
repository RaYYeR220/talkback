"""Territory clearance packs: per-market editorial rules authored as YAML.

Packs are illustrative editorial templates, not legal advice. Loading is
strict: an unknown rule type or field, an unknown topic or language, a
duplicate key, a language with no terms or a delay without an embargo fails
at load, so a broken pack can never quietly un-block anything.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from talkback.clearance.checks import worst
from talkback.clearance.lexicon import (
    LEXICONS, base_lang, detect_strength, load_yaml, match_terms, normalize,
)
from talkback.clearance.numbers import normalize_digits
from talkback.clearance.sensitive import LANGS as TOPIC_LANGS
from talkback.clearance.sensitive import sensitive_topics
from talkback.schemas.models import Cue, TerritoryVerdict, Verdict

PACKS_DIR = Path(__file__).with_name("packs")
Topic = Literal["injury", "discipline", "referee", "personal"]

_SCORE = re.compile(r"\d+\s*[-–—:]\s*\d+")
# Phrases that point a bare score at another match.
_ELSEWHERE = {
    "en": ["elsewhere", "meanwhile", "at the other ground", "in the other game",
           "in the other match", "around the grounds", "across the league"],
    "es": ["en otros campos", "en otro campo", "en el otro partido", "en otro partido",
           "en otros partidos", "mientras tanto"],
    "ar": ["في مباراة أخرى", "في المباراة الأخرى", "في الملاعب الأخرى", "في ملعب آخر",
           "في الأثناء"],
    "pt": ["em outros jogos", "em outro jogo", "no outro jogo", "nos outros jogos",
           "em outros campos", "enquanto isso"],
}
SUPPORTED_LANGS = frozenset(LEXICONS) & TOPIC_LANGS & frozenset(_ELSEWHERE)


@dataclass(frozen=True)
class PackContext:
    """Matchday context for territory rules.

    `other_fixtures` maps the other fixtures' ids to (home club id, away club id);
    `fixture_clubs` maps every fixture id, the cue's own included, to its club ids;
    `club_names` maps a club id to every name or alias it may appear under in text;
    `recent_goal_times` maps a fixture id to its goal times on the match clock (ms).
    """

    other_fixtures: Mapping[str, tuple[str, str]]
    fixture_clubs: Mapping[str, list[str]]
    club_names: Mapping[str, list[str]]
    recent_goal_times: Mapping[str, list[int]]
    now_t: int


class _Rule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    rationale: str = ""

    @property
    def verdict(self) -> Verdict:
        return Verdict.KILLED


class BlockTerms(_Rule):
    type: Literal["block_terms"]
    terms: dict[str, list[str]]
    action: Literal["KILLED"] = "KILLED"

    def check(self, text: str, lang: str, topics: set[str], cue: Cue,
              ctx: PackContext) -> list[str]:
        return [f"{self.id}: blocked term '{t}'" for t in match_terms(text, self.terms[lang], lang)]


class HoldTopics(_Rule):
    type: Literal["hold_topics"]
    topics: list[Topic] = Field(min_length=1)
    action: Literal["HOLD_FOR_PRODUCER"] = "HOLD_FOR_PRODUCER"

    @property
    def verdict(self) -> Verdict:
        return Verdict.HOLD_FOR_PRODUCER

    def check(self, text: str, lang: str, topics: set[str], cue: Cue,
              ctx: PackContext) -> list[str]:
        return [f"{self.id}: {t}" for t in self.topics if t in topics]


class KillTopics(_Rule):
    type: Literal["kill_topics"]
    topics: list[Topic] = Field(min_length=1)

    def check(self, text: str, lang: str, topics: set[str], cue: Cue,
              ctx: PackContext) -> list[str]:
        return [f"{self.id}: {t}" for t in self.topics if t in topics]


class ResultsEmbargo(_Rule):
    """Kills mentions of another fixture (club names, or a score pointed 'elsewhere')
    while that fixture has a goal inside the territory's delay window."""

    type: Literal["results_embargo"]
    delay_minutes: int = Field(gt=0)

    def check(self, text: str, lang: str, topics: set[str], cue: Cue,
              ctx: PackContext) -> list[str]:
        cutoff = ctx.now_t - self.delay_minutes * 60_000
        own = set(ctx.fixture_clubs.get(cue.match_id, []))
        live = [fid for fid in ctx.other_fixtures if fid != cue.match_id
                and any(t > cutoff for t in ctx.recent_goal_times.get(fid, []))]
        reasons = []
        for fid in live:
            ids = (*ctx.other_fixtures[fid], *ctx.fixture_clubs.get(fid, []))
            names = [n for c in dict.fromkeys(ids) if c not in own for n in ctx.club_names[c]]
            hits = match_terms(text, names, lang)
            if hits:
                reasons.append(f"{self.id}: '{hits[0]}' has a result inside the "
                               f"{self.delay_minutes}-min delay")
        if (live and not reasons and _SCORE.search(normalize_digits(text))
                and match_terms(text, _ELSEWHERE[lang], lang)):
            reasons.append(f"{self.id}: another match's score inside the "
                           f"{self.delay_minutes}-min delay")
        return reasons


class MaxStrength(_Rule):
    type: Literal["max_strength"]
    level: int = Field(ge=0, le=3)

    def check(self, text: str, lang: str, topics: set[str], cue: Cue,
              ctx: PackContext) -> list[str]:
        level, terms = detect_strength(text, lang)
        if level <= self.level:
            return []
        return [f"{self.id}: '{terms[0]}' is level {level}, this feed allows {self.level}"]


class Impartiality(_Rule):
    type: Literal["impartiality"]
    terms: dict[str, list[str]]

    def check(self, text: str, lang: str, topics: set[str], cue: Cue,
              ctx: PackContext) -> list[str]:
        return [f"{self.id}: loaded term '{t}'" for t in match_terms(text, self.terms[lang], lang)]


PackRule = Annotated[
    BlockTerms | HoldTopics | KillTopics | ResultsEmbargo | MaxStrength | Impartiality,
    Field(discriminator="type"),
]


class ClearancePack(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    territory: str = Field(min_length=1)
    name: str
    langs: list[str] = Field(min_length=1)
    delay_minutes: int = Field(ge=0)
    minors_safe: bool
    rules: list[PackRule]
    disclaimer: str

    @model_validator(mode="after")
    def _check(self) -> ClearancePack:
        if "not legal advice" not in self.disclaimer.casefold():
            raise ValueError("the disclaimer must say the pack is not legal advice")
        unsupported = [lang for lang in self.langs if lang not in SUPPORTED_LANGS]
        if unsupported:
            raise ValueError(f"unsupported languages {unsupported}")
        ids = [r.id for r in self.rules]
        if len(set(ids)) != len(ids):
            raise ValueError("rule ids must be unique")
        for rule in self.rules:
            if isinstance(rule, BlockTerms | Impartiality):
                for lang in self.langs:
                    terms = rule.terms.get(lang)
                    if not terms or not all(normalize(t) for t in terms):
                        raise ValueError(f"rule {rule.id}: no usable terms for {lang!r}")
        embargo = max((r.delay_minutes for r in self.rules if isinstance(r, ResultsEmbargo)),
                      default=0)
        if embargo < self.delay_minutes:
            raise ValueError(f"a {self.delay_minutes}-min delay needs a results_embargo "
                             "at least that long")
        return self


def load_pack(path: Path) -> ClearancePack:
    try:
        return ClearancePack.model_validate(load_yaml(path))
    except (yaml.YAMLError, ValidationError) as exc:
        raise ValueError(f"invalid clearance pack {path.name}: {exc}") from exc


def load_packs(directory: Path) -> dict[str, ClearancePack]:
    packs: dict[str, ClearancePack] = {}
    for path in sorted(directory.glob("*.yaml")):
        pack = load_pack(path)
        if pack.territory in packs:
            raise ValueError(f"territory {pack.territory!r} is defined twice ({path.name})")
        packs[pack.territory] = pack
    if not packs:
        raise ValueError(f"no clearance packs in {directory}")
    return packs


def apply_pack(pack: ClearancePack, text: str, lang: str, cue: Cue,
               ctx: PackContext) -> TerritoryVerdict:
    key = base_lang(lang)
    if key not in pack.langs:
        raise ValueError(f"{pack.territory} does not air {lang!r}")
    topics = sensitive_topics(text, key)
    verdict, reasons = Verdict.ON_AIR, []
    for rule in pack.rules:
        hits = rule.check(text, key, topics, cue, ctx)
        if hits:
            verdict = worst(verdict, rule.verdict)
            reasons += hits
    return TerritoryVerdict(territory=pack.territory, verdict=verdict, reasons=reasons, text=text)
