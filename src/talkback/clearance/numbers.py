"""Pull every number out of a line, however the locale writes it.

Handles Western, Arabic-Indic and Persian digits; decimal points and commas
(per language) and thousands grouping; `%` / `٪` / percent words with or
without a space; ordinals; minute marks ("63'", "45+2'", "minute 63"). Units
such as km/h do not change the value. Anything ambiguous is still extracted,
so an unchecked number cannot slip through on formatting alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from talkback.clearance.lexicon import base_lang

COMMA_DECIMAL = frozenset({"es", "pt", "fr", "de", "it", "nl", "tr"})

_INVISIBLE = [0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x061C, 0xFEFF,
              *range(0x202A, 0x202F), *range(0x2066, 0x206A)]
_TRANSLATE = str.maketrans({
    **{0x0660 + i: str(i) for i in range(10)},
    **{0x06F0 + i: str(i) for i in range(10)},
    0x066B: ".", 0x066C: "", 0x066A: "%", 0x2212: "-",
    **{c: None for c in _INVISIBLE},
})

_NUM = re.compile(r"(?P<base>\d+)\s*\+\s*(?P<add>\d+)\s*['’′]|\d+(?:[.,]\d+)*")
_PCT_AFTER = re.compile(
    r"\s*(?:%|per\s?cent\b|por\s+ciento\b|por\s+cento\b|في\s+المئة|في\s+المائة|بالمئة|بالمائة)",
    re.IGNORECASE)
_PCT_BEFORE = re.compile(r"%\s*$")
_MINUTE_AFTER = re.compile(
    r"\s?['’′](?![\w'’′])|(?:st|nd|rd|th|º|°)?\s*(?:minute|minuto|min)\b", re.IGNORECASE)
_MINUTE_BEFORE = re.compile(r"(?<!\w)(?:minute|minuto|min\.?|الدقيقة|دقيقة)\s*$", re.IGNORECASE)
_ORDINAL_AFTER = re.compile(r"(?:st|nd|rd|th)(?!\w)|\.?[ºª°]", re.IGNORECASE)


@dataclass(frozen=True)
class NumberToken:
    value: float
    raw: str
    decimals: int = 0
    percent: bool = False
    minute: bool = False
    ordinal: bool = False

    @property
    def tolerance(self) -> float:
        if self.percent:
            return 0.5
        if self.decimals:
            return 0.05
        return 0.0

    def label(self) -> str:
        return f"{self.value:g}{'%' if self.percent else ''}"


def normalize_digits(text: str) -> str:
    return text.translate(_TRANSLATE)


def _parse(raw: str, lang: str) -> list[tuple[float, int]]:
    """Value(s) and decimal places of a digit run such as '1.234,5'. Unparseable runs split."""
    seps = [i for i, c in enumerate(raw) if c in ".,"]
    if not seps:
        return [(float(raw), 0)]
    parts = re.split(r"[.,]", raw)
    group = "." if base_lang(lang) in COMMA_DECIMAL else ","
    last = raw[seps[-1]]
    grouped = len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:])
    kinds = {raw[i] for i in seps}
    if len(kinds) == 1:
        if len(seps) == 1 and not (last == group and len(parts[1]) == 3):
            return [(float(f"{parts[0]}.{parts[1]}"), len(parts[1]))]
        if grouped:
            return [(float("".join(parts)), 0)]
    else:
        head = raw[:seps[-1]]
        int_parts = re.split(r"[.,]", head)
        if (last not in head and len(int_parts[0]) <= 3
                and all(len(p) == 3 for p in int_parts[1:])):
            return [(float(f"{''.join(int_parts)}.{parts[-1]}"), len(parts[-1]))]
    return [(float(p), 0) for p in parts]


def _negative(s: str, start: int) -> bool:
    return start >= 1 and s[start - 1] == "-" and (start == 1 or not s[start - 2].isalnum())


def extract_tokens(text: str, lang: str) -> list[NumberToken]:
    s = normalize_digits(text)
    out: list[NumberToken] = []
    for m in _NUM.finditer(s):
        if m.group("base"):
            value = float(m.group("base")) + float(m.group("add"))
            out.append(NumberToken(value=value, raw=m.group(0), minute=True))
            continue
        before, after = s[max(0, m.start() - 16):m.start()], s[m.end():]
        sign = -1.0 if _negative(s, m.start()) else 1.0
        values = _parse(m.group(0), lang)
        if len(values) > 1:
            out += [NumberToken(value=v, raw=m.group(0)) for v, _ in values]
            continue
        value, decimals = values[0]
        out.append(NumberToken(
            value=sign * value, raw=m.group(0), decimals=decimals,
            percent=bool(_PCT_AFTER.match(after) or _PCT_BEFORE.search(before)),
            minute=bool(_MINUTE_AFTER.match(after) or _MINUTE_BEFORE.search(before)),
            ordinal=bool(_ORDINAL_AFTER.match(after)),
        ))
    return out


def extract_numbers(text: str, lang: str) -> list[float]:
    return [t.value for t in extract_tokens(text, lang)]
