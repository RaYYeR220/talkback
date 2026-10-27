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


@pytest.mark.slow
def test_tracking_facts_are_numbers_the_gallery_could_cite(ctx, run_dir):
    from talkback.gallery.bus import FileSource
    from talkback.gallery.runner import _Frame
    from talkback.models.xt import load_xt_grid
    from talkback.stats.desk import StatsDesk

    fid, h, a = ctx.world.fixtures[0]
    desk = StatsDesk(fid, ctx.world.club(h), ctx.world.club(a), load_xt_grid())
    f = FileSource(run_dir).tracking(fid)
    for i in range(len(f["t"])):
        if f["t"][i] > 20 * 60_000:
            break
        keep = f["slot"][i] >= 0
        desk.ingest_frame(_Frame(int(f["t"][i]), tuple(str(f["players"][s]) for s in f["slot"][i][keep]),
                                 f["pos"][i][keep].astype(float), f["speed"][i][keep].astype(float)))
    # a value no small integer or season figure stands in for
    speed = next(x for x in desk.facts(20 * 60_000) if x.metric == "player.top_speed_kmh"
                 and 0.2 < round(x.value, 1) % 1 < 0.8)
    name = ctx.name_of(speed.subject)[0]
    line = Line(system="s", match_id=fid, sim_t=20 * 60_000, text=f"{name}: top speed {speed.value:.1f} km/h")
    assert score(ctx, [line])["s"]["unverifiable_numbers"] == 0


def test_a_club_is_not_named_by_a_shared_word():
    from talkback.eval.detect import mentions_subject

    rival = ["Kestrel Bay Wanderers", "KBW", "Kestrel Bay"]
    assert not mentions_subject("Halverton Wanderers lead early", rival, surnames=False)
    assert mentions_subject("Kestrel Bay have scored", rival, surnames=False)
    assert mentions_subject("Mensah scores again", ["Kofi Mensah"])  # a player's surname still counts


@pytest.mark.slow
def test_mena_line_about_its_own_match_is_not_a_spoiler(ctx):
    by_word = {}
    for fid, h, a in ctx.world.fixtures:
        for c in (h, a):
            by_word.setdefault(ctx.world.club(c).name.split()[-1], []).append((fid, c))
    pairs = [v for v in by_word.values() if len({f for f, _ in v}) > 1]
    if not pairs:
        pytest.skip("no two fixtures share a club-name word in this league")
    (fa, ca), (fb, _) = pairs[0][0], next(x for x in pairs[0] if x[0] != pairs[0][0][0])
    goal = next(e.t for e in ctx.events if e.match_id == fb and e.type.value == "goal")
    own = ctx.world.club(ca).name
    line = Line(system="s", match_id=fa, sim_t=goal + 30_000, text=f"{own} keep the ball.", territory="mena")
    assert score(ctx, [line])["s"]["mena_spoilers"] == 0


@pytest.mark.slow
def test_an_earlier_shots_speed_is_a_number_the_gallery_could_cite(ctx, run_dir):
    from talkback.models.xt import load_xt_grid
    from talkback.stats.desk import StatsDesk

    fid, h, a = ctx.world.fixtures[0]
    shots = [e for e in ctx.events if e.match_id == fid and e.type.value == "shot" and e.player_id]
    first, later = next((s, t) for s, t in zip(shots, shots[1:]) if t.t // 300_000 == s.t // 300_000)
    desk = StatsDesk(fid, ctx.world.club(h), ctx.world.club(a), load_xt_grid())
    for e in ctx.events:
        if e.match_id == fid and e.t <= first.t:
            desk.ingest(e)
    speed = desk.fact("event.shot_speed_kmh", first.player_id)
    name = ctx.name_of(first.player_id)[0]
    line = Line(system="s", match_id=fid, sim_t=later.t + 1_000, text=f"{name} hit it at {speed.value:.1f} km/h")
    assert score(ctx, [line])["s"]["unverifiable_numbers"] == 0
