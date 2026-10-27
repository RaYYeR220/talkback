"""Detectors applied identically to every system's on-air text.

A storyline counts as surfaced when a line names one of its subjects and uses
language of that kind of story. The same detector scores Talkback, Talkback
without Clearance and the single-model baseline, so no system is credited for
structure the others lack.
"""

from __future__ import annotations

import re
import unicodedata

KIND_WORDS: dict[str, tuple[str, ...]] = {
    "milestone_goals": ("100", "hundred", "milestone", "century"),
    "farewell": ("farewell", "final game", "final appearance", "last game", "last appearance", "retire", "goodbye"),
    "debut": ("debut", "first start", "first appearance", "first senior"),
    "former_club": ("former club", "old club", "former side", "old side", "returns to", "reunion", "used to play",
                    "left ", "against the club"),
    "unbeaten_run": ("unbeaten", "without defeat", "without losing", "run ends", "run continues", "streak"),
    "manager_100": ("100", "hundred", "milestone", "century"),
    "relegation_six_pointer": ("relegation", "bottom", "six-pointer", "six pointer", "survival", "drop zone", "18th", "19th"),
    "golden_boot": ("top scorer", "scoring chart", "golden boot", "scoring race", "leads the scoring", "goals this season"),
    "clean_sheet_record": ("clean sheet", "record"),
    "injury_return": ("return", "back from", "after injury", "injury", "weeks out", "comeback"),
    "siblings": ("brother", "brothers", "sibling", "family"),
}


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def name_tokens(full_name: str) -> list[str]:
    parts = [p for p in re.split(r"[\s\-]+", full_name) if len(p) >= 3]
    return [fold(full_name)] + [fold(p) for p in parts[1:]] if len(parts) > 1 else [fold(full_name)]


def mentions_subject(text: str, names: list[str]) -> bool:
    t = fold(text)
    for n in names:
        for tok in name_tokens(n):
            if re.search(rf"(?<![a-z]){re.escape(tok)}(?![a-z])", t):
                return True
    return False


def mentions_kind(text: str, kind: str) -> bool:
    t = fold(text)
    return any(w in t for w in KIND_WORDS.get(kind, ()))


def surfaces(text: str, kind: str, subject_names: list[str]) -> bool:
    return mentions_subject(text, subject_names) and mentions_kind(text, kind)


NUMBER = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(%|km/h|km)?")


def numbers(text: str) -> list[tuple[float, str]]:
    out = []
    for m in NUMBER.finditer(text):
        raw = m.group(1).replace(",", ".")
        try:
            out.append((float(raw), m.group(2) or ""))
        except ValueError:
            continue
    return out
