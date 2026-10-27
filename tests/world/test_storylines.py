from talkback.schemas.models import Event, EventType, Outcome, event_id
from talkback.world.key import AnswerKey, build_answer_key
from talkback.world.league import generate_league
from talkback.world.season import backfill_season
from talkback.world.storylines import KINDS, plant_storylines


def _season():
    return backfill_season(generate_league(7), matchdays=11, seed=11)


def test_all_kinds_planted():
    st = _season()
    planted, distractors, _ = plant_storylines(st, seed=5)
    assert {p.storyline.kind for p in planted} == set(KINDS)
    assert len(KINDS) == 11
    assert len(distractors) == 8 and all(f.metric.startswith("trivia.") for f in distractors)


def test_storylines_true_in_data():
    st = _season()
    planted, _, _ = plant_storylines(st, seed=5)
    by_kind = {p.storyline.kind: p.storyline for p in planted}
    lg = st.league
    m = by_kind["milestone_goals"]
    assert lg.player(m.subjects[0]).career.career_goals == 99
    fc = by_kind["former_club"]
    player = lg.player(fc.subjects[0])
    assert fc.facts["opponent"] in player.career.previous_clubs
    six = by_kind["relegation_six_pointer"]
    order = [r.club_id for r in st.sorted_table()]
    assert {order[17], order[18]} == set(six.subjects)


def _goal(match_id, seq, t, player, team):
    return Event(id=event_id(match_id, seq), match_id=match_id, seq=seq, t=t, period=2,
                 type=EventType.goal, team_id=team, player_id=player, x=95.0, y=34.0,
                 outcome=Outcome.goal, possession_id=1)


def test_key_resolution():
    st = _season()
    planted, distractors, _ = plant_storylines(st, seed=5)
    m = next(p for p in planted if p.storyline.kind == "milestone_goals")
    fid = m.storyline.fixture_id
    pid = m.storyline.subjects[0]
    with_goal = {fid: [_goal(fid, 1, 4_000_000, pid, pid.split("-")[0])]}
    key = build_answer_key(planted, with_goal, distractors, traps=[])
    item = next(i for i in key.items if i.storyline_id == m.storyline.id)
    assert item.must and item.window_ms == (4_000_000, 4_300_000)
    key2 = build_answer_key(planted, {fid: []}, distractors, traps=[])
    item2 = next(i for i in key2.items if i.storyline_id == m.storyline.id)
    assert not item2.must


def test_key_hash_stable():
    st = _season()
    planted, distractors, _ = plant_storylines(st, seed=5)
    k1 = build_answer_key(planted, {}, distractors, traps=[])
    k2 = build_answer_key(planted, {}, distractors, traps=[])
    assert k1.sha256() == k2.sha256()
    flipped = AnswerKey(**{**k1.model_dump(), "items": [
        {**k1.items[0].model_dump(), "must": not k1.items[0].must}, *[i.model_dump() for i in k1.items[1:]]]})
    assert flipped.sha256() != k1.sha256()
