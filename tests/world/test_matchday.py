import json

import numpy as np
import pytest

from talkback.world.key import AnswerKey
from talkback.world.matchday import prepare_matchday, run_matchday_offline


@pytest.mark.slow
def test_matchday_offline(tmp_path):
    md = prepare_matchday(seed=2026)
    assert len(md.fixtures) == 10
    out = run_matchday_offline(md, tmp_path / "md")
    lines = (out / "events.jsonl").read_text(encoding="utf-8").splitlines()
    evs = [json.loads(x) for x in lines]
    keys = [(e["t"], e["match_id"], e["seq"]) for e in evs]
    assert keys == sorted(keys)
    assert {e["match_id"] for e in evs} == {f for f, _, _ in md.fixtures}
    world = (out / "world.json").read_text(encoding="utf-8")
    assert '"must"' not in world and "forced_beat" not in world and '"storylines"' not in world
    assert (out / "planted.sealed.json").exists()
    key = AnswerKey.model_validate_json((out / "key.sealed.json").read_text(encoding="utf-8"))
    assert (out / "key.sha256").read_text().strip() == key.sha256()
    players = {p.id for c in md.league.clubs for p in c.squad} | {c.id for c in md.league.clubs} | \
              {c.manager.id for c in md.league.clubs}
    for item in key.items:
        if item.must:
            assert all(s in players for s in item.subjects)
    fr = np.load(out / f"frames_{md.fixtures[0][0]}.npz")
    assert fr["pos"].shape[1:] == (22, 2) and np.all(np.diff(fr["t"]) == 100)
