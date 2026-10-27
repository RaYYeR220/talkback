import pytest
from pydantic import ValidationError

from talkback.schemas.export import export_schemas
from talkback.schemas.models import Event, EventType, Fact, Outcome, event_id, state_hash


def test_event_id_format():
    e = Event(
        id=event_id("F01", 7), match_id="F01", seq=7, t=1200, period=1,
        type=EventType.pass_, team_id="C01", player_id="C01-P07",
        x=50.0, y=30.0, end_x=60.0, end_y=32.0, outcome=Outcome.success, possession_id=3,
    )
    assert e.id == "F01-000007"


def test_extra_fields_rejected():
    valid = dict(id="x", match_id="F01", metric="team.xg", subject="C01", value=1.2, unit="xg",
                 window=(0, 1000), sample_size=3, evidence=["F01-000001"], computed_at=1000)
    Fact(**valid)
    with pytest.raises(ValidationError):
        Fact(**valid, junk=1)


def test_state_hash_changes_on_goal():
    a = state_hash(home_goals=0, away_goals=0, home_red=0, away_red=0, subs_count=0, period=1)
    b = state_hash(home_goals=1, away_goals=0, home_red=0, away_red=0, subs_count=0, period=1)
    assert a != b
    assert len(a) == 12 and all(c in "0123456789abcdef" for c in a)


def test_export_writes_all(tmp_path):
    paths = export_schemas(tmp_path)
    assert len(paths) >= 14
    assert '"verdicts"' in (tmp_path / "Cue.schema.json").read_text(encoding="utf-8")
