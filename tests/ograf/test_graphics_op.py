import json

import pytest
from jsonschema import Draft202012Validator

from talkback.ograf.graphics_op import GAP_MS, PREROLL_MS, TEMPLATES, GraphicAction, GraphicsOp, _clock, is_rtl
from talkback.ograf.layout import OUTPUTS, Layer
from talkback.ograf.spec import GRAPHICS_DIR
from talkback.schemas.models import MatchState, Verdict
from tests.ograf.support import make_cue

NOW = 60_000
ARABIC = "أوكافور على بُعد هدف واحد."


@pytest.fixture
def op():
    return GraphicsOp()


def state(t=63 * 60_000, period=2, home=0, away=0):
    return MatchState(match_id="F01", t=t, period=period, home_goals=home, away_goals=away, game_state_hash="h")


def by(actions, kind):
    return [a for a in actions if a.action == kind]


def schema(gid):
    return json.loads((GRAPHICS_DIR / gid / "graphic.ograf.json").read_text("utf-8"))["schema"]


def test_in_time_is_now_plus_delay_and_out_time_is_the_template_duration(op):
    actions = op.plan(make_cue("stat_card", created_t=NOW), "uk", now_t=NOW, delay_ms=2_000)
    assert [a.action for a in actions] == ["load", "play", "stop"]
    load, play, stop = actions
    assert {a.renderer_id for a in actions} == {"uk"} and {a.layer for a in actions} == {Layer.CARD}
    assert {a.graphic_id for a in actions} == {"talkback-stat-card"}
    assert load.at_ms == NOW + 2_000 - PREROLL_MS
    assert (play.at_ms, play.until_ms) == (NOW + 2_000, NOW + 10_000)
    assert stop.at_ms == NOW + 10_000
    assert len({a.key for a in actions}) == 1
    assert op.pending == actions


@pytest.mark.parametrize(("template", "graphic", "duration"), [
    ("lower_third", "talkback-lower-third", 6_000), ("stat_card", "talkback-stat-card", 8_000),
    ("story_card", "talkback-story-card", 9_000), ("counterfactual_card", "talkback-counterfactual-card", 10_000),
    ("table_swing", "talkback-table-swing", 8_000), ("player_tag", "talkback-player-tag", 5_000),
])
def test_template_mapping(op, template, graphic, duration):
    play = by(op.plan(make_cue(template), "uk", NOW), "play")[0]
    assert play.graphic_id == graphic and play.until_ms - play.at_ms == duration


def test_preroll_never_lands_in_the_past(op):
    load = op.plan(make_cue(), "uk", NOW, delay_ms=0)[0]
    assert load.at_ms == NOW


def test_only_territories_where_the_cue_is_on_air(op):
    cue = make_cue(verdicts={"uk": Verdict.ON_AIR, "es": Verdict.HOLD_FOR_PRODUCER, "mena": Verdict.KILLED})
    assert op.plan(cue, "es", NOW) == [] and op.plan(cue, "mena", NOW) == [] and op.plan(cue, "kids", NOW) == []
    assert len(op.plan(cue, "uk", NOW)) == 3
    assert sum("not ON_AIR" in line for line in op.log) == 3


def test_planning_the_same_cue_twice_is_a_no_op(op):
    cue = make_cue()
    assert op.plan(cue, "uk", NOW) and op.plan(cue, "uk", NOW + 100) == []


def test_stale_cue_is_dropped(op):
    cue = make_cue(created_t=0, max_age_ms=20_000)
    assert op.plan(cue, "uk", now_t=25_000) == []
    assert "stale" in op.log[-1]


def test_higher_priority_pre_empts_the_layer(op):
    stat = op.plan(make_cue("stat_card", cue_id="S"), "uk", NOW)
    cf = op.plan(make_cue("counterfactual_card", cue_id="C", created_t=NOW + 2_000), "uk", NOW + 2_000)
    assert cf[0].action == "stop" and cf[0].key == stat[0].key and cf[0].at_ms == NOW + 2_000
    stat_stops = [a for a in op.pending if a.key == stat[0].key and a.action == "stop"]
    assert stat_stops == [cf[0]], "the stat card's own out-cue is replaced by the pre-emption"
    play = by(cf, "play")[0]
    assert play.at_ms == NOW + 2_000
    ordered = [a for a in op.pending if a.at_ms == NOW + 2_000]
    assert [a.action for a in ordered] == ["stop", "load", "play"]


def test_lower_priority_waits_for_the_layer(op):
    op.plan(make_cue("counterfactual_card", cue_id="C"), "uk", NOW)
    stat = op.plan(make_cue("stat_card", cue_id="S", created_t=NOW + 1_000), "uk", NOW + 1_000)
    assert by(stat, "play")[0].at_ms == NOW + 10_000 + GAP_MS
    assert not any(a.action == "stop" and a.cue_id == "C" and a.at_ms < NOW + 10_000 for a in op.pending)


def test_equal_priority_waits_too(op):
    op.plan(make_cue("stat_card", cue_id="A"), "uk", NOW)
    b = op.plan(make_cue("stat_card", cue_id="B"), "uk", NOW + 500)
    assert by(b, "play")[0].at_ms == NOW + 8_000 + GAP_MS


def test_a_waiting_cue_is_dropped_once_it_would_air_stale(op):
    op.plan(make_cue("counterfactual_card", cue_id="C"), "uk", NOW)
    late = make_cue("stat_card", cue_id="S", created_t=NOW, max_age_ms=5_000)
    assert op.plan(late, "uk", NOW + 1_000) == []
    assert "busy" in op.log[-1]


def test_layers_are_independent_and_so_are_outputs(op):
    cue = make_cue("story_card", verdicts={"uk": Verdict.ON_AIR, "es": Verdict.ON_AIR})
    story = op.plan(cue, "uk", NOW)
    stat = op.plan(make_cue("stat_card", cue_id="S"), "uk", NOW)
    es = op.plan(cue, "es", NOW)
    assert by(story, "play")[0].layer == Layer.LOWER and by(stat, "play")[0].layer == Layer.CARD
    assert by(stat, "play")[0].at_ms == NOW and by(es, "play")[0].renderer_id == "es"
    assert not any(a.action == "stop" and a.at_ms == NOW for a in op.pending)


def test_pre_empting_an_unaired_booking_cancels_it(op):
    op.plan(make_cue("stat_card", cue_id="S"), "uk", NOW, delay_ms=9_000)
    op.plan(make_cue("counterfactual_card", cue_id="C"), "uk", NOW)
    assert [a for a in op.pending if a.cue_id == "S"] == [], "never loaded, so nothing to stop"


def test_presenter_cues_go_to_the_ifb_strip_until_they_expire(op):
    cue = make_cue("stat_card", audience="presenter", created_t=NOW, max_age_ms=20_000, cue_id="P1")
    actions = op.plan(cue, "uk", NOW)
    play = by(actions, "play")[0]
    assert (play.renderer_id, play.graphic_id, play.layer) == ("presenter", "talkback-ifb", Layer.IFB)
    assert play.until_ms == NOW + 20_000
    data = actions[0].data
    assert data["text"] == cue.text and data["label"] == "STAT" and data["countdownMs"] == 20_000
    assert data["cueId"] == "P1"


def test_spoken_ifb_is_retired_now(op):
    op.plan(make_cue(audience="presenter", cue_id="P1", max_age_ms=20_000), "uk", NOW)
    stop = op.retire("P1", NOW + 3_000)
    assert [(a.action, a.at_ms) for a in stop] == [("stop", NOW + 3_000)]
    assert [a.at_ms for a in op.pending if a.action == "stop"] == [NOW + 3_000]


def test_a_newer_ifb_replaces_the_current_one(op):
    op.plan(make_cue(audience="presenter", cue_id="P1"), "uk", NOW)
    newer = op.plan(make_cue(audience="presenter", cue_id="P2"), "uk", NOW + 4_000)
    assert newer[0].action == "stop" and newer[0].cue_id == "P1" and by(newer, "play")[0].at_ms == NOW + 4_000


def test_unknown_template_falls_back_to_a_lower_third(op):
    play = by(op.plan(make_cue("mystery_card"), "uk", NOW), "play")[0]
    assert play.graphic_id == "talkback-lower-third"


def test_scorebug_loads_once_then_sends_only_what_changed(op):
    first = op.plan_score(state(), "uk", NOW, home="CAL", away="ASH", home_color="#7A1F2B")
    assert [a.action for a in first] == ["load", "play"]
    assert first[0].data["homeColor"] == "#7a1f2b" and first[0].data["minute"] == 64
    assert op.plan_score(state(), "uk", NOW + 100, home="CAL", away="ASH", home_color="#7A1F2B") == []
    goal = op.plan_score(state(home=1), "uk", NOW + 200, home="CAL", away="ASH", home_color="#7A1F2B")
    assert [(a.action, a.data) for a in goal] == [("update", {"homeScore": 1})]


def test_scorebug_on_a_delayed_territory_waits_out_the_delay(op):
    goal = op.plan_score(state(home=1), "mena", NOW, delay_ms=120_000, home="CAL", away="ASH", as_it_stands=True,
                         elsewhere=[{"homeShort": "IRO", "awayShort": "KES", "homeScore": 1, "awayScore": 0, "junk": 1}])
    assert goal[0].at_ms == NOW + 120_000 and goal[0].renderer_id == "mena"
    assert goal[0].data["elsewhere"] == [{"homeShort": "IRO", "awayShort": "KES", "homeScore": 1, "awayScore": 0}]
    assert goal[0].data["lang"] == "ar" and goal[0].data["asItStands"] is True


def test_clear_score(op):
    op.plan_score(state(), "uk", NOW, home="CAL", away="ASH")
    assert [a.action for a in op.clear_score("uk", NOW + 1)] == ["stop"]
    assert op.clear_score("uk", NOW + 2) == []


def test_match_clock():
    assert _clock(state(t=0, period=1)) == (1, 0)
    assert _clock(state(t=46 * 60_000 + 5, period=1)) == (45, 2)
    assert _clock(state(t=63 * 60_000, period=2)) == (64, 0)
    assert _clock(state(t=93 * 60_000, period=2)) == (90, 4)


WRITER_DATA = {
    "stat_card": {"metric": "Pressures in the final third", "value": 14, "player": "Tomas Okafor",
                  "league_avg": 9.0, "ratio": 0.7, "compare_ratio": 0.45, "n": 14, "window_from": 32, "window_to": 41,
                  "caption": "UNCLEARED"},
    "story_card": {"kind": "milestone_goals", "title": "One away from 100", "context": "CAL v ASH · 63′"},
    "counterfactual_card": {"metric": "Win probability", "baseline": 41.2, "counterfactual": 63.0, "effect": -22,
                            "ci_low": -34, "ci_high": -9, "n": 400},
    "table_swing": {"team": "Westmarsh Town", "metric": "Relegation chance", "before": 31, "after": 54,
                    "tone": "bad", "cause": "IRO 1–0 KES · 71′", "club_color": "#0F6B4F"},
    "lower_third": {"subject": "Tomas Okafor", "club": "Calder Vale"},
    "player_tag": {"player": "Okafor", "shirt": 9, "speed": 31.4, "x": 1.7},
}


@pytest.mark.parametrize("template", sorted(WRITER_DATA))
def test_shaped_data_validates_against_the_graphic_schema(op, template):
    cue = make_cue(template, data=WRITER_DATA[template])
    data = op.plan(cue, "uk", NOW)[0].data
    gid = TEMPLATES[template].graphic_id
    assert list(Draft202012Validator(schema(gid)).iter_errors(data)) == []
    assert set(data) <= set(schema(gid)["properties"])
    assert data["dir"] == "ltr" and data["lang"] == "en"


def test_shaping_maps_writer_keys(op):
    plan = lambda t: op.plan(make_cue(t, data=WRITER_DATA[t], cue_id=t), "uk", NOW)[0].data
    stat = plan("stat_card")
    assert (stat["label"], stat["value"], stat["subject"], stat["compareValue"]) == (
        "Pressures in the final third", "14", "Tomas Okafor", "9")
    assert stat["evidence"] == "n=14 · 32′–41′"
    assert stat["caption"] == "Okafor has 14 pressures in the final third.", "the cleared line, never cue.data text"
    op2 = GraphicsOp()
    story = op2.plan(make_cue("story_card", data=WRITER_DATA["story_card"]), "uk", NOW)[0].data
    assert story["kind"] == "MILESTONE" and story["line"].startswith("Okafor")
    cf = GraphicsOp().plan(make_cue("counterfactual_card", data=WRITER_DATA["counterfactual_card"]), "uk", NOW)[0].data
    assert (cf["asPlayed"], cf["ifNot"], cf["effect"]) == (41.2, 63.0, "−22 pts")
    assert cf["interval"] == "95% interval −34 to −9" and cf["evidence"] == "n=400"
    swing = GraphicsOp().plan(make_cue("table_swing", data=WRITER_DATA["table_swing"]), "uk", NOW)[0].data
    assert swing["club"] == "Westmarsh Town" and swing["causedBy"].startswith("IRO") and swing["clubColor"] == "#0f6b4f"
    tag = GraphicsOp().plan(make_cue("player_tag", data=WRITER_DATA["player_tag"]), "uk", NOW)[0].data
    assert tag["number"] == "9" and tag["x"] == 1 and tag["name"] == "Okafor"


def test_localised_rtl_text_flips_the_graphic(op):
    cue = make_cue("story_card", data={"kind": "farewell"}, verdicts={"mena": (Verdict.ON_AIR, ARABIC)})
    data = op.plan(cue, "mena", NOW, delay_ms=120_000)[0].data
    assert data["line"] == ARABIC and data["dir"] == "rtl" and data["lang"] == "ar" and data["kind"] == "FAREWELL"
    assert is_rtl(ARABIC) and not is_rtl("14 pressures") and not is_rtl("")


def test_br_has_its_own_portuguese_output(op):
    line = "Okafor tem 14 pressões no último terço."
    cue = make_cue("lower_third", verdicts={"br": (Verdict.ON_AIR, line)})
    load = op.plan(cue, "br", NOW)[0]
    assert "br" in OUTPUTS and load.renderer_id == "br"
    assert load.data["line"] == line and load.data["lang"] == "pt" and load.data["dir"] == "ltr"


def test_due_hands_out_actions_in_time_order(op):
    op.plan(make_cue("stat_card"), "uk", NOW, delay_ms=1_000)
    assert op.due(NOW) == []
    first = op.due(NOW + 1_000)
    assert [a.action for a in first] == ["load", "play"]
    assert [a.action for a in op.due(NOW + 60_000)] == ["stop"] and op.pending == []


def test_graphic_action_is_strict():
    with pytest.raises(ValueError):
        GraphicAction(renderer_id="uk", graphic_id="g", layer=40, action="explode", at_ms=0, key="k")
    with pytest.raises(ValueError):
        GraphicAction(renderer_id="uk", graphic_id="g", layer=40, action="play", at_ms=0, key="k", extra=1)
