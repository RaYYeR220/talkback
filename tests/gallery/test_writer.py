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
