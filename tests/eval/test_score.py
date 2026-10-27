import json

import pytest

from talkback.eval.detect import surfaces
from talkback.eval.score import Context, Line, lines_from_broadcast, score


@pytest.fixture(scope="module")
def ctx(run_dir):
    return Context.load(run_dir)


def _item(ctx, kind):
    return next(i for i in ctx.key.items if i.kind == kind and i.must)


def test_detector_needs_subject_and_kind_words():
    assert surfaces("Mensah makes his debut tonight.", "debut", ["Kofi Mensah"])
    assert not surfaces("Mensah starts tonight.", "debut", ["Kofi Mensah"])
    assert not surfaces("A debut for the youngster.", "debut", ["Kofi Mensah"])


@pytest.mark.slow
def test_story_recall_counts_in_window_lines_only(ctx):
    farewell = _item(ctx, "farewell")
    fid = next(f for f, h, a in ctx.world.fixtures if farewell.subjects[0].split("-")[0] in (h, a))
    name = ctx.name_of(farewell.subjects[0])[0]
    on_time = Line(system="a", match_id=fid, sim_t=5 * 60_000, text=f"{name} plays his final game today.")
    too_late = Line(system="b", match_id=fid, sim_t=70 * 60_000, text=f"{name} plays his final game today.")
    res = score(ctx, [on_time, too_late])
    assert farewell.storyline_id not in res["a"]["missed_ids"] and farewell.storyline_id not in res["a"]["late_ids"]
    assert farewell.storyline_id in res["b"]["late_ids"]
    assert res["a"]["story_recall"] > res["b"]["story_recall"]


@pytest.mark.slow
def test_overclaims_and_spoilers_are_counted(ctx):
    fid, h, a = ctx.world.fixtures[0]
    goals = [e for e in ctx.events if e.type.value == "goal" and e.match_id != fid]
    g = goals[0]
    other = next((x, y) for f, x, y in ctx.world.fixtures if f == g.match_id)
    club = ctx.world.club(other[0]).name
    lines = [Line(system="s", match_id=fid, sim_t=3 * 60_000, text=f"{ctx.world.club(h).name} are dominant."),
             Line(system="s", match_id=fid, sim_t=g.t + 30_000, text=f"Meanwhile {club} have scored.",
                  territory="mena")]
    res = score(ctx, lines)["s"]
    assert res["overclaims_in_thin_windows"] == 1
    assert res["mena_spoilers"] == 1


@pytest.mark.slow
def test_a_system_without_lines_still_counts_every_must_story(ctx):
    must = sum(1 for i in ctx.key.items if i.must)
    res = score(ctx, [])
    assert {"talkback", "talkback_without_clearance", "baseline"} <= set(res)
    for row in res.values():
        assert row["lines"] == 0 and row["story_recall"] == 0
        assert row["must"] == must and row["stories_missed"] == must


@pytest.mark.slow
def test_mena_spoilers_are_read_in_the_english_source_too(ctx, tmp_path):
    fid = ctx.world.fixtures[0][0]
    g = next(e for e in ctx.events if e.type.value == "goal" and e.match_id != fid)
    club = ctx.world.club(next(x for f, x, y in ctx.world.fixtures if f == g.match_id)).name
    english = f"Meanwhile {club} have scored."
    cue = {"kind": "cue", "sim_t": g.t, "data": {
        "match_id": fid, "text": english, "audience": "fan", "moment_t": g.t + 30_000, "latency_ms": 0,
        "verdicts": {"uk": {"verdict": "ON_AIR", "text": english},
                     "mena": {"verdict": "ON_AIR", "text": "في الأثناء سجل المنافس."}}}}
    path = tmp_path / "broadcast.jsonl"
    path.write_text(json.dumps(cue) + "\n", encoding="utf-8")
    lines = lines_from_broadcast(path, "talkback")
    assert score(ctx, lines)["talkback"]["mena_spoilers"] == 1


def test_number_words_count_as_numbers_for_every_system():
    from talkback.eval.detect import numbers

    assert [v for v, _ in numbers("three goals and 4 shots")] == [3.0, 4.0]
