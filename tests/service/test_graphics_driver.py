from talkback.schemas.models import Verdict
from talkback.service.graphics import GraphicsDriver
from tests.ograf.support import make_cue, make_fact

NOW = 60_000


def cue_msg(cue, sim_t=NOW, evidence=()):
    """A cue as the gallery broadcasts it: the cue, its moment and the facts it cites."""
    data = {**cue.model_dump(mode="json"), "moment_kind": "pressing_surge", "evidence": list(evidence)}
    return {"kind": "cue", "sim_t": sim_t, "wall": 0.0, "data": data}


def loads(driver, renderer):
    return [a for a in driver.op.pending if a.action == "load" and a.renderer_id == renderer]


def test_presenter_and_world_air_uk_words_whatever_order_the_verdicts_come_in():
    lines = {"br": "Okafor tem 14 pressões.", "es": "Okafor suma 14 presiones.", "uk": "Okafor has 14 pressures."}
    on_air = {t: (Verdict.ON_AIR, line) for t, line in lines.items()}
    driver = GraphicsDriver(None, speed=1.0)
    driver.on_message(cue_msg(make_cue("lower_third", audience="presenter", cue_id="P1", verdicts=on_air)))
    driver.on_message(cue_msg(make_cue("lower_third", cue_id="Q-1", verdicts=on_air)))
    assert [a.data["text"] for a in loads(driver, "presenter")] == [lines["uk"]]
    assert [a.data["line"] for a in loads(driver, "world")] == [lines["uk"]]
    assert [a.data["line"] for a in loads(driver, "br")] == [lines["br"]]
    killed = {**on_air, "uk": Verdict.KILLED}
    driver.on_message(cue_msg(make_cue("lower_third", audience="presenter", cue_id="P2", verdicts=killed)))
    driver.on_message(cue_msg(make_cue("lower_third", cue_id="Q-2", verdicts=killed)))
    assert len(loads(driver, "presenter")) == len(loads(driver, "world")) == 1 and driver.errors == 0


def test_the_cited_facts_sent_with_a_cue_fill_the_stat_card():
    driver = GraphicsDriver(None, speed=1.0)
    fact = make_fact().model_dump(mode="json")
    driver.on_message(cue_msg(make_cue("stat_card"), evidence=[fact]))
    sparse = {k: fact[k] for k in ("id", "metric", "subject", "value", "unit", "window", "sample_size")}
    driver.on_message(cue_msg(make_cue("stat_card", cue_id="Q-2", verdicts={"es": Verdict.ON_AIR}),
                              evidence=[sparse, {"id": "broken"}]))
    assert driver.errors == 0
    [uk], [es] = loads(driver, "uk"), loads(driver, "es")
    assert uk.graphic_id == es.graphic_id == "talkback-stat-card"
    assert uk.data["value"] == es.data["value"] == "14" and uk.data["label"] == "Pressures"


class Clock:
    """A monotonic wall clock (seconds) the test moves by hand."""

    def __init__(self):
        self.t = 5_000.0

    def __call__(self):
        return self.t


def run_msg(**data):
    return {"kind": "run", "sim_t": 0, "wall": 0.0, "data": {"id": "r", "status": "started", **data}}


def due(driver, action="play"):
    return [a.renderer_id for a in driver.op.due(driver.now()) if a.action == action]


def test_a_driver_up_for_hours_still_airs_fresh_cues():
    clock = Clock()
    driver = GraphicsDriver(None, speed=10.0, clock=clock)
    clock.t += 3 * 3_600
    driver.on_message(cue_msg(make_cue("lower_third", created_t=NOW)))
    assert due(driver) == ["world", "uk"], driver.op.log


def test_a_new_replay_loop_airs_from_match_time_zero_again():
    clock = Clock()
    driver = GraphicsDriver(None, speed=10.0, clock=clock)
    loop = clock.t

    def publish(msg):  # the replay sends each message sim_t / speed after its loop started
        clock.t = loop + msg["sim_t"] / 10_000
        driver.on_message(msg)

    cue = make_cue("lower_third", created_t=NOW, cue_id="Q-1")
    publish(cue_msg(cue))
    assert due(driver) == ["world", "uk"]
    publish(cue_msg(make_cue("lower_third", created_t=1_199_800, cue_id="Q-9"), sim_t=1_199_800))
    assert due(driver) == ["world", "uk"]
    loop += 120 + 90  # two minutes of wall clock for the loop, then the finished replay holds for 90 s
    clock.t = loop
    assert due(driver, "stop") == ["world", "uk"]
    publish(cue_msg(cue))
    assert due(driver) == ["world", "uk"], driver.op.log


def test_delays_are_match_time_and_graphics_stay_up_for_their_wall_clock_length():
    clock = Clock()
    driver = GraphicsDriver(None, speed=10.0, clock=clock)
    on_air = {"uk": Verdict.ON_AIR, "mena": Verdict.ON_AIR}
    driver.on_message(cue_msg(make_cue("lower_third", created_t=NOW, max_age_ms=180_000, verdicts=on_air)))
    plays = {a.renderer_id: a for a in driver.op.pending if a.action == "play"}
    assert plays["uk"].at_ms == NOW and plays["mena"].at_ms == NOW + 120_000, "MENA runs 120 s of match time late"
    assert plays["uk"].until_ms - plays["uk"].at_ms == 6_000 * 10, "a 6 s lower third is up for 6 s of wall clock"
    clock.t += 11.9
    assert due(driver) == ["world", "uk"]
    clock.t += 0.2
    assert due(driver) == ["mena"]


def test_booked_graphics_keep_their_wall_clock_schedule_when_a_new_run_starts():
    clock = Clock()
    driver = GraphicsDriver(None, speed=10.0, clock=clock)
    cue = make_cue("lower_third", created_t=1_190_000, max_age_ms=180_000, verdicts={"mena": Verdict.ON_AIR})
    driver.on_message(cue_msg(cue, sim_t=1_190_000))  # MENA airs it 12 s of wall clock from now
    clock.t += 2
    driver.on_message(run_msg(mode="replay"))
    clock.t += 9.9
    assert due(driver) == []
    clock.t += 0.2
    assert due(driver) == ["mena"]


def test_each_run_announces_its_playout_speed():
    driver = GraphicsDriver(None, speed=10.0, clock=Clock())
    driver.on_message(run_msg(speed=4.0))
    assert driver.speed == driver.op.speed == 4.0
    driver.on_message(run_msg(speed=20.0, mode="replay"))
    assert driver.speed == 10.0, "a replay plays at the service's replay speed, not at the recorded run's"
