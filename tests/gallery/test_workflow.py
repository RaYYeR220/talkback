import asyncio
import json
import re

import pytest

from talkback.clearance.gate import Gate
from talkback.clearance.packs import PACKS_DIR, PackContext, load_packs
from talkback.clearance.safety import LocalDevSafety
from talkback.gallery.agents.desks import TerritoryDesk
from talkback.gallery.agents.lab import LabBackend
from talkback.gallery.evidence import evidence_facts
from talkback.gallery.llm import ScriptedClient, message_text
from talkback.gallery.snapshots import SnapshotStore
from talkback.gallery.spotter import Moment
from talkback.gallery.storyboard import StoryBoard
from talkback.gallery.workflow import MomentDeps, MomentJob, answer_hold, run_moment
from talkback.gallery.world import World
from talkback.models.xt import load_xt_grid
from talkback.schemas.models import EventType, Verdict
from talkback.sim.engine import MatchEngine
from talkback.stats.desk import StatsDesk
from talkback.world.matchday import prepare_matchday


def script(msgs):
    text = message_text(msgs)
    if "Story board:" in text:
        return '{"storylines": []}'
    if "Menu: cancel_shot" in text:
        return '{"experiments": [], "conclusion": "no clear effect", "supported": false}'
    if "Facts (id | metric" in text:
        line = next(l for l in text.splitlines() if "| team.shots |" in l and ":0-" in l)
        fid, _, subject, value = [p.strip() for p in line.lstrip("- ").split("|")[:4]]
        subject = subject.split(" ")[0]
        n = int(float(value))
        return json.dumps({"cues": [
            {"audience": "analyst", "template": "stat_card", "text": f"{n} shots so far for the home side.",
             "claims": [{"span": f"{n} shots", "kind": "numeric", "subject": subject, "refs": [fid], "value": n,
                         "strength": 0}]},
            {"audience": "casual", "template": "lower_third", "text": "A player is down injured near the box.",
             "claims": [{"span": "down injured", "kind": "descriptive", "strength": 0}]},
        ]})
    m = re.search(r"(\d+ shots so far for the home side\.|A player is down injured near the box\.)", text)
    return json.dumps({"text": m.group(1) if m else "?"})


@pytest.fixture(scope="module")
def env(tmp_path_factory, monkeypatch_module):
    monkeypatch_module.setenv("TALKBACK_ENV", "dev")
    md = prepare_matchday(2026)
    world = World(json.loads(json.dumps(md.public_world())))
    fid, h, a = md.fixtures[0]
    home, away = md.league.club(h), md.league.club(a)
    eng = MatchEngine(fid, home, away, md.seeds[fid], start_xi=tuple(md.lineups[fid]))
    desk = StatsDesk(fid, home, away, load_xt_grid())
    store = SnapshotStore(tmp_path_factory.mktemp("snaps"))
    store.save(fid, eng.snapshot())
    events = list(eng._events)
    while eng.t < 15 * 60_000:
        fr, evs = eng.step()
        events.extend(evs)
        for e in evs:
            desk.ingest(e)
        desk.ingest_frame(fr)
        if eng.t % 30_000 == 0:
            store.save(fid, eng.snapshot())
    state = eng.state()
    board = StoryBoard(world, fid)
    board.kickoff()
    others = {f: (x, y) for f, x, y in md.fixtures if f != fid}
    pack_ctx = PackContext(other_fixtures=others, fixture_clubs={f: [x, y] for f, x, y in md.fixtures},
                           club_names={c.id: [c.name] for c in md.league.clubs}, recent_goal_times={}, now_t=state.t)
    by_id = {e.id: e for e in events}
    shot = next((e for e in events if e.type == EventType.shot), None)
    client = ScriptedClient(script)
    deps = MomentDeps(world=world, boards={fid: board}, lab=LabBackend(store, world, by_id.get, n=12, horizon_s=5),
                      gate=Gate(load_packs(PACKS_DIR), LocalDevSafety()),
                      desks=[TerritoryDesk(t, client) for t in ("uk", "es", "mena", "kids", "br")],
                      pack_ctx=lambda m: pack_ctx, state_now=lambda m: state, client=lambda tier: client)
    moment = Moment(id=f"M-{fid}-goal-1", match_id=fid, t=state.t, kind="goal", subject=None, salience=0.9,
                    rationale="test", event_ids=[shot.id] if shot else [])
    job = MomentJob(moment=moment, facts=evidence_facts(desk, moment, state.t),
                    names={c.id: c.name for c in md.league.clubs}, state=state, now_t=state.t,
                    anchor_event_id=shot.id if shot else None)
    return deps, job


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def test_moment_runs_end_to_end_with_a_hold(env):
    deps, job = env
    run = asyncio.run(run_moment(deps, job))
    assert run.bundle is None and run.hold is not None
    held = run.hold.holds[0]
    assert "injured" in held["text"] and "uk" in held["territories"]
    run = asyncio.run(answer_hold(run, {held["cue_id"]: "approve"}))
    b = run.bundle
    stat = next(c for c in b.cues if c.audience == "analyst")
    injury = next(c for c in b.cues if c.audience == "casual")
    assert stat.verdicts["uk"].verdict == Verdict.ON_AIR, stat.verdicts["uk"].reasons
    assert injury.verdicts["uk"].verdict == Verdict.ON_AIR and "producer: approved" in injury.verdicts["uk"].reasons
    assert injury.verdicts["kids"].verdict == Verdict.KILLED
    assert b.status["lab"] in ("default", "ok", "degraded: ValueError")
    executors = {e for _, e in run.trace}
    assert {"intake", "archivist", "lab", "writer", "clearance"} <= executors


def test_rejected_hold_is_killed(env):
    deps, job = env
    run = asyncio.run(run_moment(deps, job))
    held = run.hold.holds[0]
    run = asyncio.run(answer_hold(run, {held["cue_id"]: "expired"}))
    injury = next(c for c in run.bundle.cues if c.audience == "casual")
    assert injury.verdicts["uk"].verdict == Verdict.KILLED and "producer: expired" in injury.verdicts["uk"].reasons


def test_lab_failure_degrades_but_moment_still_airs(env):
    deps, job = env
    broken = MomentDeps(**{**deps.__dict__, "lab": LabBackend(deps.lab.store, deps.world, lambda _id: None)})
    run = asyncio.run(run_moment(broken, job))
    run = asyncio.run(answer_hold(run, {run.hold.holds[0]["cue_id"]: "reject"}))
    assert run.bundle.status["lab"].startswith("degraded")
    stat = next(c for c in run.bundle.cues if c.audience == "analyst")
    assert stat.verdicts["uk"].verdict == Verdict.ON_AIR


class _OfflineRemote:
    """Records what the workflow would send over A2A, then fails like an unreachable agent."""

    def __init__(self):
        self.prompts: list[tuple[str, str]] = []

    def enabled(self, name: str) -> bool:
        return True

    def via(self, name: str) -> str:
        return "a2a"

    async def ask(self, name: str, prompt: str) -> str:
        self.prompts.append((name, prompt))
        raise ConnectionError("agent unreachable")


def test_remote_agents_are_told_the_run_and_failures_are_marked(env):
    deps, job = env
    remote = _OfflineRemote()
    run = asyncio.run(run_moment(MomentDeps(**{**deps.__dict__, "remote": remote, "run_name": "md-2026"}), job))
    run = asyncio.run(answer_hold(run, {h["cue_id"]: "reject" for h in run.hold.holds}))
    assert {n for n, _ in remote.prompts} == {"archivist", "lab"}
    assert all(p.startswith("Run: md-2026\n") for _, p in remote.prompts)
    assert run.bundle.status["archivist"].startswith("degraded: a2a")
    assert run.bundle.status["lab"].startswith("degraded: a2a")


def test_a_failing_territory_desk_does_not_lose_the_moment(env, monkeypatch):
    import talkback.gallery.workflow as wf

    deps, job = env

    async def desk_down(*args, **kwargs):
        raise ConnectionError("desk down")

    monkeypatch.setattr(wf, "localise_many", desk_down)
    monkeypatch.setattr(wf, "localise_all", desk_down)
    run = asyncio.run(run_moment(deps, job))
    if run.hold is not None:
        run = asyncio.run(answer_hold(run, {h["cue_id"]: "reject" for h in run.hold.holds}))
    assert run.bundle is not None and run.bundle.cues
    assert all(c.verdicts["es"].verdict is Verdict.KILLED for c in run.bundle.cues)


def test_one_desk_failing_leaves_the_others_translated():
    from talkback.gallery.agents.desks import localise_many
    from talkback.schemas.models import Cue

    class Desk:
        def __init__(self, territory, fail):
            self.territory, self.lang, self.agent, self.fail = territory, territory, object(), fail

        async def localise(self, cue):
            if self.fail:
                raise ConnectionError("desk down")
            return f"[{self.territory}] {cue.text}", self.lang

    c = Cue(id="Q", match_id="F", audience="analyst", text="A goal.", template="stat_card", valid_state_hash="h",
            max_age_ms=1, created_t=0)
    out = asyncio.run(localise_many([c], [Desk("es", False), Desk("mena", True)]))
    assert out == [{"es": ("[es] A goal.", "es")}]
