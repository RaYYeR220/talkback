"""Universal Clearance checks, run on every cue before any territory sees it.

Each check returns reasons; an empty list means it passed. `universal_checks`
fails closed: any reason kills the cue, and so does any exception.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from talkback.clearance.lexicon import THRESHOLDS, detect_strength, has_causal
from talkback.clearance.numbers import NumberToken, extract_tokens, normalize_digits
from talkback.clearance.sensitive import sensitive_topics
from talkback.schemas.models import (
    Claim, ClaimKind, Cue, Experiment, Fact, MatchState, Storyline, Verdict,
)

SEVERITY = {Verdict.ON_AIR: 0, Verdict.HOLD_FOR_PRODUCER: 1, Verdict.KILLED: 2}
FRACTION_UNITS = frozenset({"ratio", "fraction", "share", "probability", "prob", "rate"})
LOWER_IS_BETTER = frozenset({"team.ppda"})
_NUMERIC = (ClaimKind.numeric, ClaimKind.comparative)
_EPS = 1e-9


@dataclass(frozen=True)
class CheckContext:
    facts: Mapping[str, Fact]
    experiments: Mapping[str, Experiment]
    storylines: Mapping[str, Storyline]
    state: MatchState
    now_t: int
    lang: str


def worst(a: Verdict, b: Verdict) -> Verdict:
    return a if SEVERITY[a] >= SEVERITY[b] else b


def is_supported(ci: tuple[float, float]) -> bool:
    return ci[0] > 0 or ci[1] < 0


def _dedupe(reasons: list[str]) -> list[str]:
    return list(dict.fromkeys(reasons))


def _close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol + _EPS


# --- numbers and attribution -------------------------------------------------

def _shown_minutes(state: MatchState) -> tuple[int, int]:
    """Range of the minute on the broadcast clock. The 2nd half starts after 1-5 min of
    first-half stoppage, which MatchState does not carry."""
    elapsed = state.t // 60_000
    if state.period <= 1:
        return elapsed + 1, elapsed + 1
    return elapsed - 4, elapsed


_SCORELINE = re.compile(r"(?<![\d.])(\d{1,2})\s*[-\u2013\u2014:]\s*(\d{1,2})(?![\d.])")


def _live_score_numbers(text: str, state: MatchState) -> Counter:
    """Each number of a scoreline in the text that is this match's live score, once."""
    left: Counter = Counter()
    for m in _SCORELINE.finditer(normalize_digits(text)):
        pair = {(int(m.group(1)), int(m.group(2))), (int(m.group(2)), int(m.group(1)))}
        if (state.home_goals, state.away_goals) in pair:
            left[float(m.group(1))] += 1
            left[float(m.group(2))] += 1
    return left


def _rounded(tok: NumberToken, value: float) -> bool:
    """A whole number written for a large value it rounds to ("123 km/h" for 122.7). Small values must be
    written as they are: rounding 1.4 xG to 1 changes what the line says."""
    return not tok.decimals and not tok.percent and abs(value) >= 10 and round(value) == tok.value


def _minute_ok(tok: NumberToken, state: MatchState, created_t: int) -> bool:
    """A minute mark is the minute of the line's own moment or later, never ahead of the clock. An earlier
    minute ("pressing since the 12th minute" at 70') is a claim nothing here backs."""
    lo, hi = _shown_minutes(state)
    own = created_t // 60_000 + 1  # a moment is spotted up to a few minutes after it happened
    return tok.minute and min(own, lo) - 5 <= tok.value <= hi + 2


def _story_values(story: Storyline) -> list[float]:
    return [float(v) for v in story.facts.values()
            if isinstance(v, int | float) and not isinstance(v, bool)]


def _storyline_count(tok: NumberToken, cue: Cue, ctx: CheckContext) -> bool:
    return any(_close(tok.value, v, tok.tolerance)
               for c in cue.claims for r in c.refs if r in ctx.storylines
               for v in _story_values(ctx.storylines[r]))


def _known(ref: str, ctx: CheckContext) -> bool:
    return ref in ctx.facts or ref in ctx.experiments or ref in ctx.storylines


def _ref_matches(value: float, ref: str, tok: NumberToken | None, ctx: CheckContext) -> bool:
    tol = tok.tolerance if tok else (0.05 if value != int(value) else 0.0)
    percent = tok is not None and tok.percent
    if ref in ctx.facts:
        f = ctx.facts[ref]
        candidates, as_percent = [f.value], percent or f.unit in FRACTION_UNITS
    elif ref in ctx.experiments:
        e = ctx.experiments[ref]
        candidates, as_percent = [e.baseline, e.counterfactual, e.effect, *e.ci95], percent
    else:
        candidates, as_percent = _story_values(ctx.storylines[ref]), False
    if any(_close(value, c, tol) for c in candidates):
        return True
    return as_percent and any(_close(value, c * 100, 0.5) for c in candidates)


def _subject_of(ref: str, ctx: CheckContext) -> str:
    if ref in ctx.facts:
        return ctx.facts[ref].subject
    if ref in ctx.storylines:
        return ", ".join(ctx.storylines[ref].subjects)
    return "an experiment"


def _subject_ok(claim: Claim, ref: str, ctx: CheckContext) -> bool:
    if ref in ctx.facts:
        return claim.subject == ctx.facts[ref].subject
    if ref in ctx.storylines:
        subjects = ctx.storylines[ref].subjects
        return claim.subject is None or not subjects or claim.subject in subjects
    return True


def _verify(claim: Claim, tok: NumberToken | None, ctx: CheckContext) -> list[str]:
    label = f"'{claim.span}'"
    if not claim.refs:
        return [f"ref: claim {label} cites nothing"]
    unknown = [r for r in claim.refs if not _known(r, ctx)]
    if unknown:
        return [f"ref: claim {label} cites unknown {', '.join(unknown)}"]
    if claim.value is None:
        if claim.kind is ClaimKind.numeric:
            return [f"value: numeric claim {label} has no value"]
        matching = claim.refs
    else:
        matching = [r for r in claim.refs if _ref_matches(claim.value, r, tok, ctx)]
        if not matching:
            return [f"value: claim {label} = {claim.value:g} matches none of {', '.join(claim.refs)}"]
    if any(_subject_ok(claim, r, ctx) for r in matching):
        return []
    ref = matching[0]
    return [f"attribution: claim {label} is about {claim.subject} but {ref} is about "
            f"{_subject_of(ref, ctx)}"]


def check_numbers(cue: Cue, ctx: CheckContext) -> list[str]:
    """Every number in the text has a claim; every numeric claim matches its ref and subject.

    Claim values are as written in the text (31 for "31%"); refs may hold the fraction.
    """
    claims = [c for c in cue.claims if c.kind in _NUMERIC]
    score_left = _live_score_numbers(cue.text, ctx.state)
    shown: dict[int, NumberToken] = {}
    reasons: list[str] = []
    for tok in extract_tokens(cue.text, ctx.lang):
        hits = [i for i, c in enumerate(claims) if c.value is not None
                and (_close(tok.value, c.value, tok.tolerance) or _rounded(tok, c.value)
                     or (tok.percent and _close(tok.value, c.value * 100, tok.tolerance)))]  # 31% for 0.31
        for i in hits:
            shown.setdefault(i, tok)
        if hits or _minute_ok(tok, ctx.state, cue.created_t) or _storyline_count(tok, cue, ctx):
            continue
        if score_left[tok.value] > 0:  # the live score of this match, which the state itself backs
            score_left[tok.value] -= 1
            continue
        reasons.append(f"number: {tok.label()} has no matching claim")
    for i, claim in enumerate(claims):
        reasons += _verify(claim, shown.get(i), ctx)
    return _dedupe(reasons)


# --- wording strength --------------------------------------------------------

def _relative(f: Fact, rival: Fact) -> float:
    diff = f.value - rival.value
    if f.metric in LOWER_IS_BETTER:
        diff = -diff
    if rival.value == 0:
        return float("inf") if diff > 0 else 0.0
    return diff / abs(rival.value)


def _evidence(claim: Claim, ctx: CheckContext) -> Iterator[tuple[int, float, float]]:
    """(sample size, window seconds, effect) for each cited Fact about the claim's subject.
    The effect is the best relative edge over a cited same-metric Fact about someone else."""
    facts = [ctx.facts[r] for r in claim.refs if r in ctx.facts]
    for f in facts:
        if f.subject != claim.subject:
            continue
        rivals = [g for g in facts if g.metric == f.metric and g.subject != f.subject]
        effect = max((_relative(f, g) for g in rivals), default=0.0)
        yield f.sample_size, (f.window[1] - f.window[0]) / 1000, effect


def _evidence_reason(term: str, level: int, claims: list[Claim], ctx: CheckContext) -> str | None:
    th = THRESHOLDS[level]
    best = (0, 0.0, 0.0)
    for claim in claims:
        for n, window_s, effect in _evidence(claim, ctx):
            if n >= th.min_sample and window_s >= th.min_window_s and effect >= th.min_effect - _EPS:
                return None
            best = max(best, (n, window_s, effect))
    n, window_s, effect = best
    return (f"strength: '{term}' needs n>={th.min_sample}, window>={th.min_window_s}s, "
            f"effect>={th.min_effect:g}; got n={n}, window={window_s:g}s, effect={effect:.2f}")


def check_strength(cue: Cue, ctx: CheckContext) -> list[str]:
    """Wording strength must be declared by a claim and backed by its cited Facts.

    Claim spans are read in `cue.lang`; the full text in `ctx.lang`, so a localised
    text is held to the same evidence as the source.
    """
    reasons: list[str] = []
    for claim in cue.claims:
        level, terms = detect_strength(claim.span, cue.lang)
        if level > claim.strength:
            reasons.append(f"strength: '{terms[0]}' is level {level} but the claim declares "
                           f"{claim.strength}")
        elif level and (r := _evidence_reason(terms[0], level, [claim], ctx)):
            reasons.append(r)
    level, terms = detect_strength(cue.text, ctx.lang)
    if level:
        backing = [c for c in cue.claims if c.strength >= level]
        if not backing:
            reasons.append(f"strength: '{terms[0]}' is level {level} but no claim declares it")
        elif r := _evidence_reason(terms[0], level, backing, ctx):
            reasons.append(r)
    return _dedupe(reasons)


# --- causal, storyline, staleness --------------------------------------------

def _supported_causal(claim: Claim, ctx: CheckContext) -> bool:
    return any(r in ctx.experiments and is_supported(ctx.experiments[r].ci95) for r in claim.refs)


def check_causal(cue: Cue, ctx: CheckContext) -> list[str]:
    causal = [c for c in cue.claims if c.kind is ClaimKind.causal]
    reasons: list[str] = []
    if not any(_supported_causal(c, ctx) for c in causal):
        reasons += [f"causal: unsupported '{m}'" for m in has_causal(cue.text, ctx.lang)]
    reasons += [f"causal: claim '{c.span}' cites no supported experiment"
                for c in causal if not _supported_causal(c, ctx)]
    return reasons


def check_storyline(cue: Cue, ctx: CheckContext) -> list[str]:
    reasons: list[str] = []
    for claim in cue.claims:
        if claim.kind is not ClaimKind.storyline:
            continue
        refs = [r for r in claim.refs if r in ctx.storylines]
        if not refs:
            reasons.append(f"storyline: claim '{claim.span}' cites no known storyline")
        elif not any(_subject_ok(claim, r, ctx) for r in refs):
            reasons.append(f"attribution: claim '{claim.span}' is about {claim.subject} but "
                           f"{refs[0]} is about {_subject_of(refs[0], ctx)}")
    return reasons


def check_stale(cue: Cue, ctx: CheckContext) -> list[str]:
    reasons = []
    if cue.valid_state_hash != ctx.state.game_state_hash:
        reasons.append("stale: state changed")
    if ctx.now_t - cue.created_t > cue.max_age_ms:
        reasons.append("stale: too old")
    return reasons


def universal_checks(cue: Cue, ctx: CheckContext) -> tuple[Verdict, list[str]]:
    try:
        reasons = [*check_numbers(cue, ctx), *check_strength(cue, ctx), *check_causal(cue, ctx),
                   *check_storyline(cue, ctx), *check_stale(cue, ctx)]
        if reasons:
            return Verdict.KILLED, reasons
        topics = sensitive_topics(cue.text, ctx.lang)
        if topics:
            return Verdict.HOLD_FOR_PRODUCER, [f"sensitive: {t}" for t in sorted(topics)]
        return Verdict.ON_AIR, []
    except Exception as exc:
        return Verdict.KILLED, [f"error: {type(exc).__name__}"]
