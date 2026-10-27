import pytest

from talkback.gallery.agents.writer import evidence_prompt, say
from talkback.gallery.spotter import Moment
from talkback.schemas.models import Fact


def _fact(metric: str, value: float, unit: str) -> Fact:
    return Fact(id=f"MD12-F01:{metric}:C01:0-600000", match_id="MD12-F01", metric=metric, subject="C01",
                value=value, unit=unit, window=(0, 600_000), sample_size=40, evidence=[], computed_at=600_000)


@pytest.mark.parametrize("metric,value,unit,spoken", [
    ("team.xg", 0.3331, "xG", "0.33"),
    ("team.ppda", 8.4375, "ratio", "8.44"),
    ("player.top_speed_kmh", 33.4712, "km/h", "33.5"),
    ("player.distance_km", 10.0, "km", "10"),
    ("team.shots", 3.0, "count", "3"),
])
def test_facts_are_offered_at_broadcast_precision(metric, value, unit, spoken):
    assert say(_fact(metric, value, unit)) == spoken


def test_prompt_shows_the_spoken_value():
    m = Moment(id="M-1", match_id="MD12-F01", t=600_000, kind="stat", subject="C01", salience=1.0,
               rationale="", event_ids=[])
    text = evidence_prompt(m, [_fact("team.xg", 0.3331, "xG")], None, [], {})
    assert "0.3331" not in text and "| 0.33 |" in text


def _client(answer: dict):
    import json

    from talkback.gallery.llm import ScriptedClient

    return ScriptedClient(lambda messages: json.dumps(answer))


def test_model_written_graphic_data_never_reaches_a_cue():
    import asyncio

    from talkback.gallery.agents.writer import draft_cues, make_writer

    hostile = {"cues": [{"audience": "analyst", "template": "stat_card", "text": "Ashford have 1 shot.",
                         "data": {"value": "73%", "label": "bookies' favourites", "title": "Robbed!"},
                         "claims": []}]}
    m = Moment(id="M-1", match_id="MD12-F01", t=600_000, kind="stat", subject="C01", salience=1.0,
               rationale="", event_ids=[])
    cues = asyncio.run(draft_cues(make_writer(_client(hostile)), m, [], None, [], {}, "h", 600_000))
    assert cues and all(c.data == {} for c in cues)


def test_a_full_recap_fits():
    import asyncio

    from talkback.gallery.agents.recap import make_recap_writer, write_recap

    text = ("Calder Vale beat Ashcombe Rovers 2-1. " * 12).strip()
    assert 400 < len(text) < 900
    cue = asyncio.run(write_recap(make_recap_writer(_client({"cues": [{"audience": "casual", "text": text,
                                                                  "data": {"title": "x"}, "claims": []}]})),
                                  "MD12-F01", "Calder Vale v Ashcombe Rovers", "2-1", [], [], [], {}, "h", 5_700_000))
    assert cue.text == text and cue.data == {}
