import asyncio
import json
import re
from pathlib import Path

import pytest

from talkback.clearance.gate import Gate
from talkback.clearance.packs import PACKS_DIR, load_packs
from talkback.clearance.safety import LocalDevSafety
from talkback.gallery.bus import Broadcaster
from talkback.gallery.llm import ScriptedClient, message_text
from talkback.gallery.runner import MatchdayRunner
from talkback.world.matchday import prepare_matchday, run_matchday_offline


def script(msgs):
    text = message_text(msgs)
    if "Candidates:" in text:
        ids = re.findall(r"- (C-\S+):", text)
        return json.dumps({"ranking": [{"candidate_id": i, "salience": 0.6, "rationale": "scripted"} for i in ids]})
    if "Story board:" in text:
        live = re.findall(r"- (\S+) \[live\]", text)
        return json.dumps({"storylines": [{"storyline_id": s, "why_now": "now"} for s in live[:1]]})
    if "Menu: cancel_shot" in text:
        return '{"experiments": [], "conclusion": "no clear effect", "supported": false}'
    if "Facts (id | metric" in text:
        line = next(l for l in text.splitlines() if "| team.shots |" in l and ":0-" in l)
        fid, _, subject, value = [p.strip() for p in line.lstrip("- ").split("|")[:4]]
        n = int(float(value))
        story = re.search(r"Storylines:\n- (\S+) \|", text)
        claims = [{"span": f"{n} shots", "kind": "numeric", "subject": subject.split(" ")[0], "refs": [fid],
                   "value": n, "strength": 0}]
        if story:
            claims.append({"span": "story", "kind": "storyline", "refs": [story.group(1)], "strength": 0})
        return json.dumps({"cues": [{"audience": "analyst", "template": "stat_card",
                                     "text": f"{n} shots so far.", "claims": claims}]})
    m = re.search(r"(\d+ shots so far\.)", text)
    return json.dumps({"text": m.group(1) if m else text.strip()[:80]})


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("md")
    return run_matchday_offline(prepare_matchday(2026), out / "run")


@pytest.mark.slow
def test_runner_first_fifteen_minutes(run_dir, monkeypatch):
    monkeypatch.setenv("TALKBACK_ENV", "dev")
    client = ScriptedClient(script)
    record = Path(run_dir) / "broadcast.jsonl"
    bc = Broadcaster(record)
    runner = MatchdayRunner(run_dir, Gate(load_packs(PACKS_DIR), LocalDevSafety()), lambda tier: client, bc,
                            speed=300, lab_n=8)
    stats = asyncio.run(runner.run(until_ms=15 * 60_000))
    bc.close()
    msgs = [json.loads(l) for l in record.read_text(encoding="utf-8").splitlines()]
    kinds = {m["kind"] for m in msgs}
    assert {"run", "score", "moment", "cue", "aired", "board", "table"} <= kinds, kinds
    assert stats["workflows"] >= 10 and stats["aired"] > 0
    story_moments = [m for m in msgs if m["kind"] == "moment" and m["data"]["kind"] == "storyline"]
    cues = [m["data"] for m in msgs if m["kind"] == "cue"]
    assert all(set(c["verdicts"]) == {"uk", "es", "mena", "kids", "br"} for c in cues)
    boards = [m["data"] for m in msgs if m["kind"] == "board"]
    surfaced = {s["id"] for b in boards for s in b["stories"] if s["status"] == "surfaced"}
    assert surfaced, "at least one storyline reached air"
