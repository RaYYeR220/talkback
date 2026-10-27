import pytest

from talkback.clearance.lexicon import (
    CAUSAL_MARKERS, LEXICONS, THRESHOLDS, EvidenceThreshold, detect_strength, has_causal, normalize,
)


def test_levels_en():
    assert detect_strength("Ashford are edging it", "en")[0] == 1
    assert detect_strength("Ashford are dominant", "en") == (3, ["dominant"])
    assert detect_strength("Ashford win a corner on the left", "en") == (0, [])


def test_word_boundary():
    assert detect_strength("a neverending spell for Ashford", "en") == (0, [])
    assert detect_strength("Ashford NEVER give it away", "en") == (3, ["never"])


def test_strongest_term_first():
    level, terms = detect_strength("Ashford are edging it, and now they look dominant", "en")
    assert level == 3 and terms == ["dominant", "edging", "edging it"]


def test_es_ar():
    assert detect_strength("Dominio absoluto de Ashford", "es")[0] == 3
    # Diacritics, alef-hamza variants and tatweel are folded before matching.
    assert detect_strength("أشفورد مُسَيْطِرٌ", "ar")[0] == 3
    assert detect_strength("لن يخسروا أبداً", "ar")[0] == 3
    assert detect_strength("أشفورد مسيـــطر", "ar")[0] == 3
    # Attached proclitics (wa-, al-) still match.
    assert detect_strength("والمسيطر هو أشفورد", "ar")[0] == 3


def test_pt():
    assert detect_strength("Ashford ligeiramente melhor", "pt")[0] == 1
    assert detect_strength("Ashford é avassalador", "pt")[0] == 3


def test_causal():
    assert has_causal("They lost it because of the press", "en") == ["because"]
    assert has_causal("They lost the ball under pressure", "en") == []
    assert has_causal("Ganaron gracias a la presión", "es") == ["gracias a"]
    assert has_causal("خسروا بسبب الضغط", "ar") == ["بسبب"]


def test_lexicon_coverage():
    assert set(LEXICONS) == {"en", "es", "ar", "pt"}
    for lang, lex in LEXICONS.items():
        for level in (1, 2, 3):
            assert len(lex.levels[level]) >= 10, (lang, level)
        assert len(CAUSAL_MARKERS[lang]) >= 10, lang


def test_thresholds():
    assert THRESHOLDS[0] == EvidenceThreshold(min_sample=0, min_effect=0.0, min_window_s=0)
    assert THRESHOLDS[1] == EvidenceThreshold(min_sample=3, min_effect=0.0, min_window_s=120)
    assert THRESHOLDS[2] == EvidenceThreshold(min_sample=8, min_effect=0.10, min_window_s=300)
    assert THRESHOLDS[3] == EvidenceThreshold(min_sample=15, min_effect=0.25, min_window_s=600)


def test_normalize():
    assert normalize("  Ａshford  Está\tAQUÍ ") == "ashford esta aqui"
    assert normalize("إصابةٌ") == "اصابه"


def test_unknown_language_raises():
    with pytest.raises(ValueError):
        detect_strength("Ashford are dominant", "xx")
