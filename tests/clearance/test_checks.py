import asyncio

import pytest

from talkback.clearance.checks import (
    check_causal, check_numbers, check_stale, check_storyline, check_strength, universal_checks,
)
from talkback.clearance.numbers import extract_numbers
from talkback.clearance.safety import LocalDevSafety
from talkback.clearance.sensitive import sensitive_topics
from talkback.schemas.models import MatchState, Verdict
from tests.clearance.fixtures import (
    FACTS, NOW, STATE_HASH, XG_CLAIM, claim, ctx, cue, experiment, fact,
)


def test_numbers_ok():
    assert check_numbers(cue("Ashford have 1.4 xG", [XG_CLAIM]), ctx()) == []


def test_number_without_claim_killed():
    reasons = check_numbers(cue("Ashford have 1.4 xG from 9 shots", [XG_CLAIM]), ctx())
    assert reasons == ["number: 9 has no matching claim"]


def test_claim_value_must_match_ref():
    wrong = claim("1.6 xG", subject="C01", refs=["F_xg_home"], value=1.6)
    reasons = check_numbers(cue("Ashford have 1.6 xG", [wrong]), ctx())
    assert len(reasons) == 1 and reasons[0].startswith("value:")


def test_unknown_ref_killed():
    ghost = claim("1.4 xG", subject="C01", refs=["F_missing"], value=1.4)
    reasons = check_numbers(cue("Ashford have 1.4 xG", [ghost]), ctx())
    assert len(reasons) == 1 and reasons[0].startswith("ref:")


def test_misattribution_killed():
    c = claim("completes 91%", subject="C01-P09", refs=["F_comp_P07"], value=91)
    reasons = check_numbers(cue("Mensah completes 91%", [c]), ctx())
    assert len(reasons) == 1 and reasons[0].startswith("attribution")


def test_percent_fraction():
    c = claim("31% of the territory", subject="C01", refs=["F_tilt_home"], value=31)
    assert check_numbers(cue("Ashford have 31% of the territory", [c]), ctx()) == []


def test_arabic_digits():
    assert extract_numbers("٣١٪", "ar") == [31.0]


@pytest.mark.parametrize(("text", "lang", "expected"), [
    ("0,8 xG", "es", [0.8]),
    ("31 %", "en", [31.0]),
    ("31 %", "es", [31.0]),
    ("%31", "ar", [31.0]),
    ("1.200 pases", "es", [1200.0]),
    ("1,200 passes", "en", [1200.0]),
    ("1,25 xG", "en", [1.25]),
    ("1.234,5 metros", "pt", [1234.5]),
    ("٠٫٨", "ar", [0.8]),
    ("١٬٢٠٠", "ar", [1200.0]),
    ("۳۱٪", "ar", [31.0]),
    ("٣١‏٪", "ar", [31.0]),
    ("34,2 km/h", "pt", [34.2]),
    ("his 100th goal", "en", [100.0]),
    ("63'", "en", [63.0]),
    ("45+2'", "en", [47.0]),
    ("2-1", "en", [2.0, 1.0]),
    ("an effect of -0.3", "en", [-0.3]),
])
def test_extract_localized(text, lang, expected):
    assert extract_numbers(text, lang) == pytest.approx(expected)


@pytest.mark.parametrize(("text", "lang"), [
    ("Mensah completa el 91 % de sus pases", "es"),
    ("Mensah completa 91 por ciento de sus pases", "es"),
    ("مينساه يكمل ٩١٪ من تمريراته", "ar"),
    ("Mensah acerta 91% dos passes", "pt"),
])
def test_localized_percent_checked(text, lang):
    c = claim("91%", subject="C01-P07", refs=["F_comp_P07"], value=91)
    assert check_numbers(cue(text, [c], lang=lang), ctx(lang=lang)) == []
    wrong = text.replace("91", "93").replace("٩١", "٩٣")
    assert check_numbers(cue(wrong, [c], lang=lang), ctx(lang=lang)) != []


def test_minute_marks():
    # 70:00 on the clock in the second half: the shown minute is 66'-70' (first-half stoppage varies).
    assert check_numbers(cue("Still 1-0 at 68'", [
        claim("1", subject="C01", refs=["F_one"], value=1),
        claim("0", subject="C02", refs=["F_zero"], value=0),
    ]), ctx(facts={"F_one": fact("F_one", "C01", 1, metric="team.goals", unit="count"),
                   "F_zero": fact("F_zero", "C02", 0, metric="team.goals", unit="count")})) == []
    assert check_numbers(cue("Pressing since the 12th minute"), ctx()) == [
        "number: 12 has no matching claim"]
    first_half = MatchState(match_id="F01", t=30 * 60_000 + 20_000, period=1, home_goals=0,
                            away_goals=0, game_state_hash=STATE_HASH)
    assert check_numbers(cue("Ashford press high, 31'"), ctx(state=first_half)) == []


def test_storyline_count_allowed():
    story = claim("his 100th career goal", "storyline", subject="C01-P07", refs=["S_milestone"])
    text = "Mensah is chasing his 100th career goal"
    assert check_numbers(cue(text, [story]), ctx()) == []
    assert check_storyline(cue(text, [story]), ctx()) == []
    bare = claim("his 100th career goal", "storyline", subject="C01-P07")
    assert check_numbers(cue(text, [bare]), ctx()) == ["number: 100 has no matching claim"]
    assert check_storyline(cue(text, [bare]), ctx())[0].startswith("storyline:")


def test_storyline_misattribution():
    story = claim("his 100th career goal", "storyline", subject="C01-P09", refs=["S_milestone"])
    reasons = check_storyline(cue("Okafor is chasing his 100th career goal", [story]), ctx())
    assert len(reasons) == 1 and reasons[0].startswith("attribution")


def _dominant(n: int, window_s: int, away: float):
    facts = {
        "F_a": fact("F_a", "C01", 1.4, n=n, window=(0, window_s * 1000)),
        "F_b": fact("F_b", "C02", away, n=n, window=(0, window_s * 1000)),
    }
    c = claim("Ashford are dominant", "comparative", subject="C01", refs=["F_a", "F_b"], strength=3)
    return cue("Ashford are dominant", [c]), ctx(facts=facts)


def test_strength_thin_evidence():
    reasons = check_strength(*_dominant(n=4, window_s=900, away=1.0))
    assert len(reasons) == 1
    assert reasons[0].startswith("strength: 'dominant' needs n>=15") and "got n=4" in reasons[0]
    assert check_strength(*_dominant(n=20, window_s=900, away=1.0)) == []   # effect 0.4
    assert check_strength(*_dominant(n=20, window_s=300, away=1.0)) != []   # window too short
    assert check_strength(*_dominant(n=20, window_s=900, away=1.3)) != []   # effect 0.08


def test_strength_above_declared():
    c = claim("Ashford are dominant", "comparative", subject="C01", refs=["F_xg_home"], strength=1)
    reasons = check_strength(cue("Ashford are dominant", [c]), ctx())
    assert reasons and reasons[0].startswith("strength: 'dominant' is level 3")


def test_strength_outside_any_claim():
    reasons = check_strength(cue("Ashford have 1.4 xG and are utterly dominant", [XG_CLAIM]), ctx())
    assert reasons and "no claim declares" in reasons[0]


def test_causal_requires_supported_experiment():
    c = claim("because of the press", "causal", subject="C01", refs=["E_press"])
    text = "They scored because of the press"
    weak = check_causal(cue(text, [c]), ctx(experiments={"E_press": experiment((-0.01, 0.05))}))
    assert "causal: unsupported 'because'" in weak
    assert check_causal(cue(text, [c]), ctx(experiments={"E_press": experiment((0.02, 0.08))})) == []
    assert check_causal(cue(text), ctx()) == ["causal: unsupported 'because'"]


def test_stale():
    assert check_stale(cue("Ashford lead", valid_state_hash="000000000000"), ctx()) == [
        "stale: state changed"]
    assert check_stale(cue("Ashford lead", created_t=NOW - 60_000), ctx()) == ["stale: too old"]
    assert check_stale(cue("Ashford lead"), ctx()) == []


def test_sensitive_hold():
    assert universal_checks(cue("He went off injured"), ctx()) == (
        Verdict.HOLD_FOR_PRODUCER, ["sensitive: injury"])


def test_sensitive_topics_languages():
    assert sensitive_topics("Mensah se retira lesionado", "es") == {"injury"}
    assert sensitive_topics("البطاقة الحمراء لمينساه", "ar") == {"discipline"}
    assert sensitive_topics("O árbitro anulou o gol após revisão do VAR", "pt") == {"referee"}
    assert sensitive_topics("Mensah misses out for personal reasons", "en") == {"personal"}
    assert sensitive_topics("Ashford win a corner", "en") == set()


def test_universal_verdicts():
    assert universal_checks(cue("Ashford have 1.4 xG", [XG_CLAIM]), ctx()) == (Verdict.ON_AIR, [])
    verdict, reasons = universal_checks(cue("Ashford have 1.4 xG from 9 shots", [XG_CLAIM]), ctx())
    assert verdict is Verdict.KILLED and reasons == ["number: 9 has no matching claim"]


class _Boom(dict):
    def __getitem__(self, key):
        raise RuntimeError("store down")

    def __contains__(self, key):
        raise RuntimeError("store down")

    def get(self, key, default=None):
        raise RuntimeError("store down")


def test_fail_closed():
    verdict, reasons = universal_checks(cue("Ashford have 1.4 xG", [XG_CLAIM]), ctx(facts=_Boom()))
    assert verdict is Verdict.KILLED
    assert reasons == ["error: RuntimeError"]


def test_dev_safety_guard(monkeypatch):
    monkeypatch.delenv("TALKBACK_ENV", raising=False)
    with pytest.raises(RuntimeError):
        LocalDevSafety()
    monkeypatch.setenv("TALKBACK_ENV", "prod")
    with pytest.raises(RuntimeError):
        LocalDevSafety()
    monkeypatch.setenv("TALKBACK_ENV", "dev")
    assert asyncio.run(LocalDevSafety().analyze("Ashford lead")) == (
        True, "content-safety: skipped (dev)")


@pytest.mark.parametrize("text,lang,values", [
    ("three goals in his last four, one short of his hundredth", "en", [3, 4, 100]),
    ("twenty-one passes and a thousand fans", "en", [21, 1000]),
    ("tres goles en sus últimos cuatro partidos", "es", [3, 4]),
    ("dois gols em três jogos, o centésimo", "pt", [2, 3, 100]),
    ("one of the best in the first half", "en", []),
])
def test_number_words_are_numbers(text, lang, values):
    assert extract_numbers(text, lang) == values


def test_spelled_out_number_without_a_claim_is_killed():
    verdict, reasons = universal_checks(cue("Okafor has three goals this season"), ctx())
    assert verdict is Verdict.KILLED and any(r.startswith("number: 3") for r in reasons)


def test_number_words_do_not_misread_common_phrases():
    assert extract_numbers("91 por ciento de sus pases", "es") == [91]
    assert extract_numbers("a fifty-fifty ball", "en") == []


def _numbers_only(reasons):
    return [r for r in reasons if r.startswith("number:")]


def test_a_rounded_large_value_matches_its_claim():
    speed = fact("F_speed", "C01-P07", 122.7, metric="event.shot_speed_kmh", unit="km/h")
    c = cue("Mensah hit it at 123 km/h", [claim("123 km/h", subject="C01-P07", refs=["F_speed"], value=122.7)])
    _, reasons = universal_checks(c, ctx(facts={**FACTS, "F_speed": speed}))
    assert _numbers_only(reasons) == []
    small = cue("Ashford have 1 xG", [claim("1 xG", subject="C01", refs=["F_xg_away"], value=1.4)])
    assert _numbers_only(universal_checks(small, ctx())[1])  # rounding 1.4 to 1 is not allowed


def test_football_compounds_are_not_number_words():
    assert extract_numbers("a relegation six-pointer", "en") == []
    assert extract_numbers("a one-two on the edge", "en") == []


@pytest.mark.parametrize("text,moment_t,ok", [
    ("At 2 minutes, Mensah faced his old club", 90_000, True),    # a line about a moment at 2'
    ("Mensah saved it in the 1st minute", 30_000, True),
    ("Mensah saved it in the 1st minute", NOW - 5_000, False),    # nothing at 70' backs a 1st-minute save
    ("Mensah will score in the 85th minute", NOW - 5_000, False),
])
def test_minute_marks_point_at_the_lines_moment_or_later_not_ahead(text, moment_t, ok):
    assert (_numbers_only(universal_checks(cue(text, created_t=moment_t, max_age_ms=10_000_000), ctx())[1])
            == []) is ok
