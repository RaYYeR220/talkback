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
