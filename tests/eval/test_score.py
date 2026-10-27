import pytest

from talkback.eval.detect import surfaces
from talkback.eval.score import Context, Line, score
from talkback.world.matchday import prepare_matchday, run_matchday_offline


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    out = run_matchday_offline(prepare_matchday(2026), tmp_path_factory.mktemp("ev") / "run", snapshots=False)
    return Context.load(out)


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
