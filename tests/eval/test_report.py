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


def test_the_web_scorecard_carries_measured_values_only():
    from talkback.eval.report import to_web

    summary = aggregate([{"talkback": _row(8, 10), "baseline": _row(3, 10), "talkback_without_clearance": _row(8, 10),
                          "_meta": {"key_sha256": "abc"}}])
    web = to_web(summary, latencies_ms=[1_000, 2_000, 3_000, 40_000], generated_at="2026-10-27T15:00:00Z")
    assert web["provisional"] is False and web["setup"]["sealed_key_sha256"] == ["abc"]
    assert [s["id"] for s in web["systems"]] == ["talkback", "baseline", "negative_control"]
    recall = next(m for m in web["metrics"] if m["id"] == "story_recall")
    assert recall["headline"] and recall["values"] == {"talkback": 0.8, "baseline": 0.3, "negative_control": 0.8}
    assert {m["id"] for m in web["metrics"]} <= {"story_recall", "unverifiable_numbers", "over_claims", "spoilers",
                                                 "distractor_intrusion"}
    assert web["latency"]["p50_ms"] == 2_000 and "clearance" not in web
