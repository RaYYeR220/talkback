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
