from talkback.eval.report import aggregate


def _row(hit: int, must: int) -> dict:
    return {"lines": 5, "stories_hit": hit, "stories_late": 0, "stories_missed": must - hit, "must": must,
            "numbers": 2, "unverifiable_numbers": 0, "overclaims_in_thin_windows": 0, "trivia_intrusions": 0,
            "mena_spoilers": 0}


def test_a_matchday_a_system_is_missing_from_counts_against_it():
    results = [{"talkback": _row(4, 10), "baseline": _row(2, 10)}, {"baseline": _row(1, 8)}]
    systems = aggregate(results)["systems"]
    talkback = systems["talkback"]
    assert talkback["matchdays"] == 2 and talkback["must"] == 18 and talkback["stories_missed"] == 14
    assert talkback["story_recall"] == round(4 / 18, 3)
    assert systems["talkback_without_clearance"]["must"] == 18
    assert systems["baseline"]["story_recall"] == round(3 / 18, 3)
