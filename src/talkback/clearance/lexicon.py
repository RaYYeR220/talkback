"""Strength and causal lexicons: how strong a line sounds, per language.

Terms live in `lexicon/<lang>.yaml`. Matching is word-boundary and
case-insensitive on normalised text: accents and Arabic diacritics are
stripped, alef / yeh / teh-marbuta variants are folded and tatweel removed.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

LEXICON_DIR = Path(__file__).with_name("lexicon")


class EvidenceThreshold(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    min_sample: int
    min_effect: float
    min_window_s: int


# min_effect is the relative difference vs the opponent or the baseline, as a fraction.
THRESHOLDS: dict[int, EvidenceThreshold] = {
    0: EvidenceThreshold(min_sample=0, min_effect=0.0, min_window_s=0),
    1: EvidenceThreshold(min_sample=3, min_effect=0.0, min_window_s=120),
    2: EvidenceThreshold(min_sample=8, min_effect=0.10, min_window_s=300),
    3: EvidenceThreshold(min_sample=15, min_effect=0.25, min_window_s=600),
}

_ARABIC_FOLD = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ـ": None,
    **{chr(c): None for c in range(0x064B, 0x0660)}, "ٰ": None,
})
# Arabic proclitics that attach to the next word: wa-/fa-, bi-/li-/ka-, al-.
_AR_PROCLITICS = "(?:[وف]?[بلك]?(?:ال)?)"


def base_lang(lang: str) -> str:
    return lang.split("-")[0].casefold()


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.translate(_ARABIC_FOLD))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(text.casefold().split())


@lru_cache(maxsize=8192)
def _pattern(term: str, lang: str) -> re.Pattern[str]:
    words = normalize(term).split()
    if not words:
        raise ValueError(f"empty term {term!r}")
    prefix = _AR_PROCLITICS if base_lang(lang) == "ar" else ""
    body = r"\s+".join(re.escape(w) for w in words)
    return re.compile(rf"(?<!\w){prefix}{body}(?!\w)")


def find_terms(text: str, terms: Iterable[str], lang: str) -> list[tuple[int, str]]:
    """(position, term) for every term found in `text`, in reading order."""
    norm = normalize(text)
    hits = []
    for term in terms:
        m = _pattern(term, lang).search(norm)
        if m:
            hits.append((m.start(), term))
    return sorted(hits)


def match_terms(text: str, terms: Iterable[str], lang: str) -> list[str]:
    return [term for _, term in find_terms(text, terms, lang)]


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of keeping the last one."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            if isinstance(key, (list, dict)):
                continue
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate key {key!r}", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep)


def load_yaml(path: Path) -> object:
    with open(path, encoding="utf-8") as fh:
        return yaml.load(fh, Loader=_StrictLoader)


class Lexicon(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lang: str
    levels: dict[Literal[1, 2, 3], list[str]]
    causal: list[str]

    @model_validator(mode="after")
    def _check(self) -> Lexicon:
        if set(self.levels) != {1, 2, 3}:
            raise ValueError("levels must be exactly 1, 2 and 3")
        seen: dict[str, int] = {}
        for level, terms in self.levels.items():
            for term in terms:
                key = normalize(term)
                if not key:
                    raise ValueError(f"empty term at level {level}")
                if key in seen:
                    raise ValueError(f"'{term}' is listed at levels {seen[key]} and {level}")
                seen[key] = level
        if not all(normalize(m) for m in self.causal):
            raise ValueError("empty causal marker")
        return self


def load_lexicon(path: Path) -> Lexicon:
    try:
        lex = Lexicon.model_validate(load_yaml(path))
    except (yaml.YAMLError, ValidationError) as exc:
        raise ValueError(f"invalid lexicon {path.name}: {exc}") from exc
    if lex.lang != path.stem:
        raise ValueError(f"{path.name} declares lang {lex.lang!r}")
    return lex


LEXICONS: dict[str, Lexicon] = {
    lex.lang: lex for lex in map(load_lexicon, sorted(LEXICON_DIR.glob("*.yaml")))
}
CAUSAL_MARKERS: dict[str, list[str]] = {lang: list(lex.causal) for lang, lex in LEXICONS.items()}


def lexicon(lang: str) -> Lexicon:
    try:
        return LEXICONS[base_lang(lang)]
    except KeyError:
        raise ValueError(f"no lexicon for language {lang!r}") from None


def detect_strength(text: str, lang: str) -> tuple[int, list[str]]:
    """Max strength level in `text` and the matched terms, strongest first, then in reading order."""
    level_of = {term: level for level, terms in lexicon(lang).levels.items() for term in terms}
    hits = sorted((-level_of[term], pos, term) for pos, term in find_terms(text, level_of, lang))
    return (-hits[0][0] if hits else 0), [term for _, _, term in hits]


def has_causal(text: str, lang: str) -> list[str]:
    return match_terms(text, lexicon(lang).causal, lang)
