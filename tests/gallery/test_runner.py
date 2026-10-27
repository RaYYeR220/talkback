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


@pytest.mark.slow
def test_runner_from_a_live_feed(run_dir, monkeypatch):
    """The Event Hubs path: the same feed items the generator publishes drive the gallery."""
    from talkback.service.generator import feed_items

    monkeypatch.setenv("TALKBACK_ENV", "dev")
    items = [p for t, _, p in feed_items(Path(run_dir)) if t <= 6 * 60_000] + [{"kind": "end"}]

    async def feed():
        for it in items:
            yield it

    client = ScriptedClient(script)
    bc = Broadcaster()
    runner = MatchdayRunner(run_dir, Gate(load_packs(PACKS_DIR), LocalDevSafety()), lambda tier: client, bc, lab_n=8)
    stats = asyncio.run(runner.run_feed(feed()))
    assert stats["workflows"] >= 5 and stats["cues"] > 0
    assert runner.live_frames and all(len(f["ids"]) >= 20 for f in runner.live_frames.values())


def _quiet_runner(run_dir, monkeypatch):
    monkeypatch.setenv("TALKBACK_ENV", "dev")
    bc = Broadcaster()
    published: list[tuple[str, dict]] = []
    monkeypatch.setattr(bc, "publish", lambda kind, t, data, record=True: published.append((kind, data)))
    runner = MatchdayRunner(run_dir, Gate(load_packs(PACKS_DIR), LocalDevSafety()),
                            lambda tier: ScriptedClient(script), bc, lab_n=8)
    return runner, published


def test_a_hung_moment_is_abandoned(run_dir, monkeypatch):
    from types import SimpleNamespace

    import talkback.gallery.runner as runner_mod

    runner, published = _quiet_runner(run_dir, monkeypatch)

    async def hang(deps, job):
        await asyncio.sleep(3600)

    monkeypatch.setattr(runner_mod, "MOMENT_TIMEOUT_S", 0.2)
    monkeypatch.setattr(runner_mod, "run_moment", hang)
    job = SimpleNamespace(moment=SimpleNamespace(id="M-x", match_id=runner.world.fixtures[0][0], kind="goal"))
    asyncio.run(asyncio.wait_for(runner._workflow(job), 5))
    assert runner.stats["timeouts"] == 1
    assert ("agent", {"moment_id": "M-x", "stage": "error", "error": "TimeoutError"}) in published


def test_workers_stop_when_the_feed_fails(run_dir, monkeypatch):
    runner, _ = _quiet_runner(run_dir, monkeypatch)

    async def go():
        runner.workers = [asyncio.create_task(asyncio.sleep(3600))]

        async def feed():
            yield {"kind": "frame", "match_id": "nope"}
            raise ConnectionError("event hub gone")

        with pytest.raises(ConnectionError):
            await runner.run_feed(feed())
        await asyncio.sleep(0)
        return [w.cancelled() for w in runner.workers]  # checked inside the loop, before asyncio.run cleans up

    assert asyncio.run(go()) == [True]


def test_retriggered_story_gets_a_new_moment(run_dir, monkeypatch):
    runner, _ = _quiet_runner(run_dir, monkeypatch)
    m = runner.matches[runner.world.fixtures[0][0]]

    async def go():
        runner._story_moment(m, "S-1", "golden_boot", 600_000, trigger="E-1")
        runner._story_moment(m, "S-1", "golden_boot", 1_800_000, trigger="E-2")
        ids = [job.moment.id for *_, job in runner.queue._queue]  # noqa: SLF001
        runner._stop()
        return ids

    ids = asyncio.run(go())
    assert len(ids) == len(set(ids)) == 2


def _bundle_aged(runner, age_s: float):
    import time as _time

    from talkback.gallery.agents.lab import LabResult
    from talkback.gallery.spotter import Moment
    from talkback.gallery.workflow import CueBundle, MomentJob
    from talkback.schemas.models import Cue, TerritoryVerdict, Verdict

    fid = runner.world.fixtures[0][0]
    state = runner.matches[fid].state()
    moment = Moment(id="M-a", match_id=fid, t=0, kind="goal", subject=None, salience=0.9, rationale="",
                    event_ids=[])
    cue = Cue(id="Q-a", match_id=fid, audience="analyst", text="A goal.", template="stat_card",
              valid_state_hash=state.game_state_hash, max_age_ms=90_000, created_t=0,
              verdicts={"uk": TerritoryVerdict(territory="uk", verdict=Verdict.ON_AIR, text="A goal.")})
    job = MomentJob(moment=moment, facts=[], names={}, state=state, now_t=0, wall0=_time.monotonic() - age_s)
    return CueBundle(moment=moment, cues=[cue], stories=[], status={}, job=job,
                     lab=LabResult(experiments=[], conclusion="", supported=False)), cue


def test_line_too_old_at_air_is_killed(run_dir, monkeypatch):
    from talkback.schemas.models import Verdict

    runner, published = _quiet_runner(run_dir, monkeypatch)
    bundle, cue = _bundle_aged(runner, 100)
    runner._air(bundle)
    assert cue.verdicts["uk"].verdict is Verdict.KILLED
    assert "stale: too old at air" in cue.verdicts["uk"].reasons
    assert not [d for k, d in published if k == "aired"]


def test_latency_is_measured_from_spotting_to_air(run_dir, monkeypatch):
    runner, published = _quiet_runner(run_dir, monkeypatch)
    bundle, _ = _bundle_aged(runner, 10)
    runner._air(bundle)
    (cue_msg,) = [d for k, d in published if k == "cue"]
    assert 10_000 <= cue_msg["latency_ms"] < 15_000
    assert [d for k, d in published if k == "aired"]


def test_mena_embargo_is_checked_again_at_air(run_dir, monkeypatch):
    from talkback.schemas.models import TerritoryVerdict, Verdict

    runner, published = _quiet_runner(run_dir, monkeypatch)
    (fid, _, _), (other, oh, _) = runner.world.fixtures[0], runner.world.fixtures[1]
    rival = runner.world.club(oh).name

    def aired_in_mena(goal_t):
        bundle, cue = _bundle_aged(runner, 10)  # airs at 10 s of match time, as a 1x broadcast sees it
        cue.text = f"Meanwhile {rival} are on top."
        cue.verdicts = {"mena": TerritoryVerdict(territory="mena", verdict=Verdict.ON_AIR, text="في هذه الأثناء")}
        runner.matches[other].goal_times = [goal_t]
        runner._air(bundle)
        return cue.verdicts["mena"]

    v = aired_in_mena(5_000)  # the rival scored 5 s before the line aired: inside the two-minute delay
    assert v.verdict is Verdict.KILLED and any(r.startswith("embargo") for r in v.reasons)
    assert aired_in_mena(9_000_000).verdict is Verdict.ON_AIR  # a goal after air time had not happened yet
