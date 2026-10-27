import asyncio

import pytest

from talkback.clearance.gate import Gate
from talkback.clearance.packs import PACKS_DIR, PackContext, apply_pack, load_pack, load_packs
from talkback.clearance.safety import LocalDevSafety
from talkback.schemas.models import Verdict
from tests.clearance.fixtures import NOW, XG_CLAIM, claim, ctx, cue

ON, HOLD, KILL = Verdict.ON_AIR, Verdict.HOLD_FOR_PRODUCER, Verdict.KILLED

NAMES = {
    "C01": ["Ashford"],
    "C02": ["Brindle Athletic", "Brindle"],
    "C05": ["Calder Vale", "كالدر فيل"],
    "C06": ["Ashcombe Rovers", "Ashcombe", "أشكومب روفرز"],
}


def pack_ctx(goal_ago_ms: int | None = 60_000) -> PackContext:
    goals = {} if goal_ago_ms is None else {"F02": [NOW - goal_ago_ms]}
    return PackContext(other_fixtures={"F02": ("C05", "C06")},
                       fixture_clubs={"F01": ["C01", "C02"], "F02": ["C05", "C06"]},
                       club_names=NAMES, recent_goal_times=goals, now_t=NOW)


@pytest.fixture
def packs():
    return load_packs(PACKS_DIR)


@pytest.fixture
def safety(monkeypatch):
    monkeypatch.setenv("TALKBACK_ENV", "dev")
    return LocalDevSafety()


def run(gate: Gate, c, localized, pctx=None):
    out = asyncio.run(gate.evaluate(c, ctx(), localized, pctx or pack_ctx(None)))
    return {t: v.verdict for t, v in out.verdicts.items()}, out


VALID = """\
territory: test
name: Test desk
langs: [en]
delay_minutes: 0
minors_safe: false
disclaimer: "Illustrative editorial template — not legal advice."
rules:
  - id: gambling
    type: block_terms
    terms:
      en: [bet]
  - id: sensitive
    type: hold_topics
    topics: [injury]
"""


def _write(tmp_path, text):
    path = tmp_path / "pack.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_valid_pack_loads(tmp_path):
    pack = load_pack(_write(tmp_path, VALID))
    assert pack.territory == "test" and [r.type for r in pack.rules] == ["block_terms", "hold_topics"]


def test_unknown_rule_type_fails(tmp_path):
    with pytest.raises(ValueError):
        load_pack(_write(tmp_path, VALID.replace("type: block_terms", "type: banana")))


@pytest.mark.parametrize(("old", "new"), [
    ("rules:", "rules: ["),                                          # broken YAML
    ("minors_safe: false", "minors_safe: false\ncolour: red"),       # unknown field
    ("delay_minutes: 0", "delay_minutes: 0\ndelay_minutes: 5"),      # duplicate key
    ("    terms:", "    pattern: bet\n    terms:"),                 # unknown rule field
    ("langs: [en]", "langs: [en, es]"),                              # a language with no terms
    ("topics: [injury]", "topics: [weather]"),                       # unknown topic
    ("langs: [en]", "langs: [xx]"),                                  # unsupported language
    ("en: [bet]", "en: ['  ']"),                                     # empty term
    ("not legal advice", "legal advice"),                           # disclaimer
    ("delay_minutes: 0", "delay_minutes: 2"),                        # delayed without embargo
    (VALID, "- just\n- a list\n"),                                   # not a mapping
])
def test_malformed_pack_fails(tmp_path, old, new):
    assert old in VALID
    with pytest.raises(ValueError):
        load_pack(_write(tmp_path, VALID.replace(old, new)))


def test_duplicate_territory_fails(tmp_path):
    (tmp_path / "a.yaml").write_text(VALID, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(VALID, encoding="utf-8")
    with pytest.raises(ValueError):
        load_packs(tmp_path)


def test_shipped_packs(packs):
    assert set(packs) == {"uk", "es", "mena", "kids", "br"}
    for pack in packs.values():
        assert pack.disclaimer == "Illustrative editorial template — not legal advice."
    assert packs["mena"].langs == ["ar"] and packs["mena"].delay_minutes == 2
    assert any(r.type == "results_embargo" for r in packs["mena"].rules)
    assert packs["kids"].minors_safe and not packs["uk"].minors_safe


def test_gambling_blocked_es(packs, safety):
    gate = Gate({t: packs[t] for t in ("uk", "es")}, safety)
    verdicts, out = run(gate, cue("Ashford have 1.4 xG", [XG_CLAIM]), {
        "uk": ("Ashford have 1.4 xG", "en"),
        "es": ("Las cuotas ya señalan a Ashford, que suma 1,4 de xG", "es"),
    })
    assert verdicts == {"uk": ON, "es": KILL}
    assert out.verdicts["es"].reasons == ["gambling: blocked term 'cuotas'"]


def test_gambling_and_impartiality_uk(packs):
    c = cue("x")
    assert apply_pack(packs["uk"], "The bookies make Ashford favourites", "en", c,
                      pack_ctx(None)).verdict is KILL
    tv = apply_pack(packs["uk"], "Ashford were robbed", "en", c, pack_ctx(None))
    assert tv.verdict is KILL and tv.reasons == ["impartiality: loaded term 'robbed'"]
    assert apply_pack(packs["br"], "Ashford é favorito nas apostas", "pt", c,
                      pack_ctx(None)).verdict is KILL


SCORE_CLAIMS = [claim("2", subject="C05", refs=["F_goals_C05"], value=2),
                claim("1", subject="C06", refs=["F_goals_C06"], value=1)]


def test_results_embargo_mena(packs, safety):
    gate = Gate({t: packs[t] for t in ("uk", "mena")}, safety)
    c = cue("Calder Vale lead 2-1 at Ashcombe Rovers", SCORE_CLAIMS)
    localized = {"uk": (c.text, "en"), "mena": ("كالدر فيل يتقدم 2-1 على أشكومب روفرز", "ar")}
    verdicts, out = run(gate, c, localized, pack_ctx(goal_ago_ms=60_000))
    assert verdicts == {"uk": ON, "mena": KILL}
    assert out.verdicts["mena"].reasons[0].startswith("embargo:")
    # The goal is outside the 2-minute delay, or there was none: nothing to spoil.
    assert run(gate, c, localized, pack_ctx(goal_ago_ms=150_000))[0] == {"uk": ON, "mena": ON}
    assert run(gate, c, localized, pack_ctx(goal_ago_ms=None))[0] == {"uk": ON, "mena": ON}


def test_embargo_catches_score_elsewhere(packs):
    c = cue("x")
    tv = apply_pack(packs["mena"], "وفي مباراة أخرى النتيجة ٢-١", "ar", c, pack_ctx(60_000))
    assert tv.verdict is KILL and tv.reasons[0].startswith("embargo:")
    own = apply_pack(packs["mena"], "أشفورد يتقدم ١-٠", "ar", c, pack_ctx(60_000))
    assert own.verdict is ON


def test_kids_injury_killed(packs, safety):
    gate = Gate({t: packs[t] for t in ("uk", "kids")}, safety)
    text = "Mensah went off injured"
    verdicts, out = run(gate, cue(text), {"uk": (text, "en"), "kids": (text, "en")})
    assert verdicts == {"uk": HOLD, "kids": KILL}
    assert "minors-topics: injury" in out.verdicts["kids"].reasons


def test_matrix(packs, safety):
    """One cue: on air in the UK and Spain, killed on the delayed MENA feed and the kids feed."""
    dominant = claim("Ashford are dominant", "comparative", subject="C01",
                     refs=["F_xg_home", "F_xg_away"], strength=3)
    c = cue("Ashford are dominant while Calder Vale lead 2-1", [dominant, *SCORE_CLAIMS])
    localized = {
        "uk": (c.text, "en"),
        "kids": (c.text, "en"),
        "es": ("Ashford dominan mientras Calder Vale gana 2-1", "es"),
        "mena": ("أشفورد مسيطرون بينما كالدر فيل يتقدم 2-1", "ar"),
        "br": ("Ashford dominando enquanto o Calder Vale vence por 2-1", "pt"),
    }
    verdicts, out = run(Gate(packs, safety), c, localized, pack_ctx(goal_ago_ms=60_000))
    assert verdicts["uk"] is ON
    assert verdicts["es"] is ON
    assert verdicts["mena"] is KILL
    assert verdicts["kids"] in (HOLD, KILL)
    assert verdicts["br"] is ON
    assert any(r.startswith("embargo:") for r in out.verdicts["mena"].reasons)
    assert out.verdicts["kids"].reasons[0].startswith("minors-strength:")
    assert out.verdicts["mena"].text == localized["mena"][0]
    assert out.universal_reasons == []


def test_localized_number_mismatch(packs, safety):
    c = cue("Ashford have 1.4 xG", [XG_CLAIM])
    verdicts, out = run(Gate(packs, safety), c, {
        "uk": (c.text, "en"),
        "kids": (c.text, "en"),
        "es": ("Ashford suman 1,5 de xG", "es"),
        "mena": ("أشفورد لديه ١٫٤ من الأهداف المتوقعة", "ar"),
        "br": ("Ashford têm 1,4 de xG", "pt"),
    })
    assert verdicts == {"uk": ON, "kids": ON, "es": KILL, "mena": ON, "br": ON}
    assert out.verdicts["es"].reasons == ["number: 1.5 has no matching claim"]


def test_localized_strength_and_causal_rechecked(packs, safety):
    c = cue("Ashford have 1.4 xG", [XG_CLAIM])
    verdicts, out = run(Gate({t: packs[t] for t in ("uk", "es", "br")}, safety), c, {
        "uk": (c.text, "en"),
        "es": ("Ashford, imparables, suman 1,4 de xG", "es"),
        "br": ("Ashford tem 1,4 de xG porque pressiona alto", "pt"),
    })
    assert verdicts == {"uk": ON, "es": KILL, "br": KILL}
    assert out.verdicts["es"].reasons[0].startswith("strength:")
    assert out.verdicts["br"].reasons == ["causal: unsupported 'porque'"]


def test_universal_kill_reaches_every_territory(packs, safety):
    c = cue("Ashford have 1.4 xG from 9 shots", [XG_CLAIM])
    verdicts, out = run(Gate(packs, safety), c, {"uk": (c.text, "en")})
    assert set(verdicts.values()) == {KILL} and set(verdicts) == set(packs)
    assert out.universal_reasons == ["number: 9 has no matching claim"]
    assert all(v.reasons == out.universal_reasons for v in out.verdicts.values())


def test_missing_localisation_and_unknown_territory(packs, safety):
    c = cue("Ashford have 1.4 xG", [XG_CLAIM])
    verdicts, out = run(Gate(packs, safety), c, {"uk": (c.text, "en"), "moon": (c.text, "en")})
    assert verdicts == {"uk": ON, "kids": ON, "es": KILL, "mena": KILL, "br": KILL, "moon": KILL}
    assert out.verdicts["es"].reasons[0].startswith("localisation:")
    assert out.verdicts["moon"].reasons[0].startswith("pack:")


class _Raises:
    async def analyze(self, text):
        raise RuntimeError("safety service down")


class _Slow:
    async def analyze(self, text):
        await asyncio.sleep(1)
        return True, "ok"


class _Rejects:
    async def analyze(self, text):
        return False, "content-safety: violence"


@pytest.mark.parametrize(("safety_impl", "reason"), [
    (_Raises(), "error: RuntimeError"),
    (_Slow(), "error: TimeoutError"),
    (_Rejects(), "content-safety: violence"),
])
def test_gate_fails_closed_on_safety(packs, safety_impl, reason):
    gate = Gate({"uk": packs["uk"]}, safety_impl, safety_timeout_s=0.05)
    verdicts, out = run(gate, cue("Ashford have 1.4 xG", [XG_CLAIM]), {"uk": ("Ashford have 1.4 xG", "en")})
    assert verdicts == {"uk": KILL} and out.verdicts["uk"].reasons == [reason]


def test_gate_fails_closed_on_bad_context(packs, safety):
    gate = Gate({"mena": packs["mena"]}, safety)
    broken = PackContext(other_fixtures={"F02": ("C05", "C06")}, fixture_clubs={}, club_names={},
                         recent_goal_times={"F02": [NOW - 1_000]}, now_t=NOW)
    c = cue("Ashford have 1.4 xG", [XG_CLAIM])
    verdicts, out = run(gate, c, {"mena": ("أشفورد لديه ١٫٤ من الأهداف المتوقعة", "ar")}, broken)
    assert verdicts == {"mena": KILL} and out.verdicts["mena"].reasons == ["error: KeyError"]


def test_embargo_reads_the_source_when_the_translation_transliterates(packs, safety):
    gate = Gate({t: packs[t] for t in ("uk", "mena")}, safety)
    c = cue("Calder Vale lead 2-1 at Ashcombe Rovers", SCORE_CLAIMS)
    # a spelling the alias list does not know
    localized = {"uk": (c.text, "en"), "mena": ("كولدر ڤيل يتقدم 2-1", "ar")}
    verdicts, out = run(gate, c, localized, pack_ctx(goal_ago_ms=60_000))
    assert verdicts == {"uk": ON, "mena": KILL}
    assert out.verdicts["mena"].reasons[0].startswith("embargo:")


def test_sensitive_topic_added_by_the_translation_is_held(packs, safety):
    gate = Gate({t: packs[t] for t in ("uk", "br")}, safety)
    c = cue("Mensah is back on his feet")
    verdicts, out = run(gate, c, {"uk": (c.text, "en"), "br": ("Mensah sente dores e volta", "pt")})
    assert verdicts == {"uk": ON, "br": HOLD}
    assert "sensitive: injury" in out.verdicts["br"].reasons


def test_minors_safe_feed_never_waits_for_a_producer(packs, safety):
    gate = Gate({t: packs[t] for t in ("uk", "kids")}, safety)
    text = "The referee waved play on"
    verdicts, out = run(gate, cue(text), {"uk": (text, "en"), "kids": (text, "en")})
    assert verdicts == {"uk": HOLD, "kids": KILL}
    assert any(r.startswith("minors-safe:") for r in out.verdicts["kids"].reasons)
