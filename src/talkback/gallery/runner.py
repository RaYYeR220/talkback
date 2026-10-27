"""The live matchday runner: ten matches, one gallery, compressed time.

Per match it keeps the Stats Desk, story board, triggers and match state.
Spotted moments run the agent workflow (bounded concurrency, so a slow model
queues moments instead of stalling the feed); deterministic tags (speed,
pass difficulty) are templated but still cleared. Holds wait for the
producer and expire as not aired. Every verdict is re-checked against the
match state at air time.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import numpy as np
from dataclasses import dataclass, field
from pathlib import Path

from talkback.clearance.checks import CheckContext
from talkback.clearance.gate import Gate
from talkback.clearance.packs import PackContext
from talkback.gallery.agents.desks import TerritoryDesk
from talkback.gallery.agents.lab import LabBackend
from talkback.gallery.bus import Broadcaster, FileSource
from talkback.gallery.director import Director, LiveScore, LiveTable, swings
from talkback.gallery.evidence import evidence_facts
from talkback.gallery.remote import RemoteAgents
from talkback.gallery.snapshots import SnapshotStore
from talkback.gallery.spotter import Candidate, Moment, Spotter, Triggers
from talkback.gallery.storyboard import StoryBoard
from talkback.gallery.workflow import MomentDeps, MomentJob, MomentRun, answer_hold, run_moment
from talkback.gallery.world import World
from talkback.models.xt import load_xt_grid
from talkback.schemas.models import Claim, ClaimKind, Cue, Event, EventType, MatchState, Outcome, Verdict, state_hash
from talkback.stats.desk import StatsDesk

AGENT_KINDS = {"goal", "red_card", "big_chance", "big_save", "storyline", "pressing_surge", "momentum_swing"}
TEMPLATE_KINDS = {"speed_alert"}
AGENT_MIN_SALIENCE = 0.5
SCAN_EVERY_MS = 5_000
TABLE_EVERY_MS = 30_000
HOLD_TIMEOUT_S = 25.0
# A moment that has not cleared in this long is abandoned; its lines would be stale anyway.
MOMENT_TIMEOUT_S = float(os.environ.get("TALKBACK_MOMENT_TIMEOUT_S", "180"))
TERRITORIES = ("uk", "es", "mena", "kids", "br")
DELAY_MS = {"uk": 0, "es": 0, "br": 0, "kids": 0, "mena": 120_000}


@dataclass
class MatchDesk:
    fixture_id: str
    home: str
    away: str
    desk: StatsDesk
    board: StoryBoard
    triggers: Triggers
    score: list[int] = field(default_factory=lambda: [0, 0])
    reds: list[int] = field(default_factory=lambda: [0, 0])
    subs: int = 0
    period: int = 1
    minute: int = 0
    t: int = 0
    new_events: list[Event] = field(default_factory=list)
    last_scan: int = 0
    goal_times: list[int] = field(default_factory=list)
    frame_i: int = 0
    finished: bool = False
    aired_texts: list[str] = field(default_factory=list)
    scorers: list[str] = field(default_factory=list)

    def state(self) -> MatchState:
        return MatchState(match_id=self.fixture_id, t=self.t, period=self.period, home_goals=self.score[0],
                          away_goals=self.score[1], home_red=self.reds[0], away_red=self.reds[1],
                          game_state_hash=state_hash(home_goals=self.score[0], away_goals=self.score[1],
                                                     home_red=self.reds[0], away_red=self.reds[1],
                                                     subs_count=self.subs, period=self.period))


class _Frame:
    __slots__ = ("t", "ids", "pos", "speed")

    def __init__(self, t, ids, pos, speed):
        self.t, self.ids, self.pos, self.speed = t, ids, pos, speed


class MatchdayRunner:
    def __init__(self, run_dir: Path, gate: Gate, client_for, broadcaster: Broadcaster, speed: float = 10.0,
                 lab_pool=None, lab_n: int = 160, max_concurrent: int = 6, run_id: str = "live"):
        self.run_dir = Path(run_dir)
        self.world = World.load(self.run_dir / "world.json")
        self.source = FileSource(self.run_dir)
        self.gate = gate
        self.client_for = client_for
        self.bc = broadcaster
        self.speed = speed
        self.run_id = run_id
        self.names = {c.id: c.name for c in self.world.league.clubs}
        self.names.update({p.id: p.name for c in self.world.league.clubs for p in c.squad})
        self.short = {c.id: c.short for c in self.world.league.clubs}
        xt = load_xt_grid()
        self.matches: dict[str, MatchDesk] = {}
        for fid, h, a in self.world.fixtures:
            desk = StatsDesk(fid, self.world.club(h), self.world.club(a), xt)
            self.matches[fid] = MatchDesk(fid, h, a, desk, StoryBoard(self.world, fid), Triggers(desk))
        self.events_by_id: dict[str, Event] = {}
        from talkback.hosted.runstore import snapshot_store

        self.lab = LabBackend(snapshot_store(self.run_dir, self.run_dir.name), self.world, self.events_by_id.get,
                              pool=lab_pool, n=lab_n, horizon_s=15)
        self.desks = [TerritoryDesk(t, client_for("fast")) for t in TERRITORIES]
        self.spotter = Spotter(_spotter_agent(client_for("fast")))
        self.table = LiveTable(self.world, n=1500)
        self.director = Director()
        self.moments: list[Moment] = []
        self.holds: dict[str, tuple[MomentRun, float]] = {}
        self.sem = asyncio.Semaphore(max_concurrent)
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.max_concurrent = max_concurrent
        self.workers: list[asyncio.Task] = []
        self._seq = 0
        self.tasks: set[asyncio.Task] = set()
        self.sim_t = 0
        self.last_table = -TABLE_EVERY_MS
        self.chances = None
        self.stats = {"moments": 0, "workflows": 0, "cues": 0, "aired": 0, "held": 0, "killed": 0, "stale": 0,
                      "timeouts": 0}
        self.deps = MomentDeps(world=self.world, boards={f: m.board for f, m in self.matches.items()},
                               lab=self.lab, gate=gate, desks=self.desks, pack_ctx=self.pack_ctx,
                               state_now=lambda f: self.matches[f].state(), client=client_for,
                               remote=RemoteAgents.from_env(), run_name=self.run_dir.name)

    # ------------------------------------------------------------- contexts
    def pack_ctx(self, match_id: str) -> PackContext:
        return PackContext(
            other_fixtures={f: (m.home, m.away) for f, m in self.matches.items() if f != match_id},
            fixture_clubs={f: [m.home, m.away] for f, m in self.matches.items()},
            club_names={c.id: [c.name, c.short, c.city] for c in self.world.league.clubs},
            recent_goal_times={f: list(m.goal_times) for f, m in self.matches.items()},
            now_t=self.sim_t)

    def live_scores(self) -> list[LiveScore]:
        return [LiveScore(fixture_id=f, home=m.home, away=m.away, home_goals=m.score[0], away_goals=m.score[1],
                          minute=m.minute, home_red=m.reds[0], away_red=m.reds[1], finished=m.finished)
                for f, m in self.matches.items()]

    # -------------------------------------------------------------- events
    def _dispatch(self, e: Event) -> None:
        m = self.matches[e.match_id]
        self.events_by_id[e.id] = e
        m.desk.ingest(e)
        m.t = e.t
        m.minute = int(e.qualifiers.get("minute", m.minute))
        k = 0 if e.team_id == m.home else 1
        if e.type == EventType.goal:
            m.score[k] += 1
            m.goal_times.append(e.t)
            if e.player_id:
                m.scorers.append(e.player_id)
        elif e.type == EventType.card and e.outcome == Outcome.red:
            m.reds[k] += 1
        elif e.type == EventType.substitution:
            m.subs += 1
        elif e.type == EventType.period_start:
            m.period = e.period
            if e.period == 1:
                for n, s in enumerate(m.board.kickoff()):
                    self._story_moment(m, s.id, s.kind, e.t + 60_000 + 20_000 * n, pre_match=True)
        elif e.type == EventType.period_end and e.period == 2:
            m.finished = True
            self._spawn(self._recap(m))
        for s in m.board.on_event(e):
            self._story_moment(m, s.id, s.kind, e.t, trigger=e.id)
        m.new_events.append(e)
        if e.type in (EventType.goal, EventType.card, EventType.shot, EventType.substitution, EventType.period_end):
            self.bc.publish("ticker", e.t, {"match_id": e.match_id, "type": e.type.value, "team": e.team_id,
                                             "player": self.names.get(e.player_id or "", ""), "minute": m.minute,
                                             "outcome": e.outcome.value, "xg": e.qualifiers.get("xg")})
        if e.type in (EventType.goal, EventType.card, EventType.period_start, EventType.period_end):
            self._publish_score(m)

    def _story_moment(self, m: MatchDesk, story_id: str, kind: str, t: int, pre_match: bool = False,
                      trigger: str | None = None) -> None:
        # a story can come due again (every goal in a scoring race): each trigger is its own moment
        suffix = f"@{trigger}" if trigger else ""
        c = Candidate(id=f"C-{m.fixture_id}-story-{story_id}{suffix}", match_id=m.fixture_id, t=t, kind="storyline",
                      subject=story_id, event_ids=[], detail={"story_kind": kind})
        moment = Moment(id=c.id.replace("C-", "M-", 1), match_id=m.fixture_id, t=t, kind="storyline",
                        subject=story_id, salience=0.6 if pre_match else 0.8, rationale=f"story board: {kind}",
                        event_ids=[], detail={"story_kind": kind, "pre_match": int(pre_match)}, ranked_by="rules")
        self._enqueue(moment)

    def _publish_score(self, m: MatchDesk) -> None:
        self.bc.publish("score", m.t, {"match_id": m.fixture_id, "home": m.home, "away": m.away,
                                        "home_short": self.short[m.home], "away_short": self.short[m.away],
                                        "score": list(m.score), "minute": m.minute, "period": m.period,
                                        "reds": list(m.reds), "finished": m.finished})

    def _frames_to(self, target_t: int) -> None:
        for m in self.matches.values():
            f = self.source.tracking(m.fixture_id)
            if f is None:
                continue
            ts = f["t"]
            while m.frame_i < len(ts) and ts[m.frame_i] <= target_t:
                i = m.frame_i
                slots = f["slot"][i]
                keep = slots >= 0
                ids = tuple(str(f["players"][s]) for s in slots[keep])
                m.desk.ingest_frame(_Frame(int(ts[i]), ids, f["pos"][i][keep].astype(float),
                                           f["speed"][i][keep].astype(float)))
                m.frame_i += 1

    # ------------------------------------------------------------- moments
    def _scan(self) -> None:
        for m in self.matches.values():
            if m.t - m.last_scan < SCAN_EVERY_MS:
                continue
            m.last_scan = m.t
            cands = m.triggers.scan(m.new_events, m.t)
            m.new_events = []
            if cands:
                self._spawn(self._spot(m, cands))

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _spot(self, m: MatchDesk, cands: list[Candidate]) -> None:
        ranked = await self.spotter.rank(cands, context=f"{self.names[m.home]} v {self.names[m.away]}, {m.minute}'")
        for moment in ranked:
            self.stats["moments"] += 1
            self.bc.publish("moment", moment.t, moment.model_dump(mode="json"))
            if moment.kind in TEMPLATE_KINDS:
                self._spawn(self._template(m, moment))
            elif moment.kind in AGENT_KINDS and moment.salience >= AGENT_MIN_SALIENCE:
                self._enqueue(moment)

    def _enqueue(self, moment: Moment) -> None:
        """Moments wait in salience order: a goal never queues behind pre-match stories."""
        self.moments.append(moment)
        self._seq += 1
        m = self.matches[moment.match_id]
        # snapshot the evidence and state at the moment itself, not when a worker gets to it
        job = MomentJob(moment=moment, facts=evidence_facts(m.desk, moment, m.t), names=self.names,
                        state=m.state(), now_t=max(m.t, moment.t), anchor_event_id=self._anchor(moment))
        self.queue.put_nowait((-moment.salience, moment.t, self._seq, job))
        if not self.workers:
            self.workers = [asyncio.create_task(self._worker()) for _ in range(self.max_concurrent)]

    async def _worker(self) -> None:
        while True:
            *_, job = await self.queue.get()
            try:
                await self._workflow(job)
            finally:
                self.queue.task_done()

    def _stop(self) -> None:
        """Workers and side tasks never outlive the run, however it ends."""
        for task in (*self.workers, *self.tasks):
            task.cancel()

    def _busy(self) -> bool:
        return self.queue._unfinished_tasks > 0  # noqa: SLF001

    def _anchor(self, moment: Moment) -> str | None:
        for eid in moment.event_ids:
            e = self.events_by_id.get(eid)
            if e is None:
                continue
            if e.type == EventType.shot:
                return e.id
            if e.type == EventType.goal:
                shots = [x for x in self.events_by_id.values()
                         if x.match_id == e.match_id and x.type == EventType.shot and x.t <= e.t]
                return max(shots, key=lambda x: x.t).id if shots else None
        return None

    async def _workflow(self, job: MomentJob) -> None:
        moment = job.moment
        m = self.matches[moment.match_id]
        self.stats["workflows"] += 1
        self.bc.publish("agent", m.t, {"moment_id": moment.id, "match_id": moment.match_id,
                                        "stage": "started", "kind": moment.kind})
        t0 = time.perf_counter()
        try:
            run = await asyncio.wait_for(run_moment(self.deps, job), MOMENT_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 - one bad moment never stops the gallery
            if isinstance(exc, TimeoutError):
                self.stats["timeouts"] += 1
            self.bc.publish("agent", m.t, {"moment_id": moment.id, "stage": "error", "error": type(exc).__name__})
            return
        self.bc.publish("agent", m.t, {"moment_id": moment.id, "match_id": moment.match_id, "stage": "done",
                                        "ms": int((time.perf_counter() - t0) * 1000),
                                        "trace": [e for _, e in run.trace if _ == "executor_completed"]})
        await self._after_run(run)

    async def _after_run(self, run: MomentRun) -> None:
        if run.hold is not None:
            self.stats["held"] += len(run.hold.holds)
            self.holds[run.hold.moment_id] = (run, time.monotonic() + HOLD_TIMEOUT_S)
            self.bc.publish("hold", self.sim_t, {"id": run.hold.moment_id, "match_id": run.hold.match_id,
                                                  "holds": run.hold.holds, "expires_in_s": HOLD_TIMEOUT_S})
            return
        if run.bundle is not None:
            self._air(run.bundle)

    async def decide(self, moment_id: str, decision: dict[str, str]) -> bool:
        entry = self.holds.pop(moment_id, None)
        if entry is None:
            return False
        run = await answer_hold(entry[0], decision)
        self.bc.publish("hold_resolved", self.sim_t, {"id": moment_id, "decision": decision})
        if run.bundle is not None:
            self._air(run.bundle)
        return True

    async def _expire_holds(self) -> None:
        now = time.monotonic()
        for mid, (run, deadline) in list(self.holds.items()):
            if now >= deadline:
                await self.decide(mid, {h["cue_id"]: "expired" for h in run.hold.holds})

    def _air(self, bundle) -> None:
        m = self.matches[bundle.moment.match_id]
        current = m.state().game_state_hash
        job = bundle.job
        # as a 1x broadcast sees it: queue, pipeline and producer time all count
        air_t = job.age_now_t() if job is not None else None
        latency = (int((time.monotonic() - job.wall0) * 1000) if job is not None
                   else int(sum(bundle.timings.values())) if bundle.timings else 0)
        for cue in bundle.cues:
            self.stats["cues"] += 1
            for t, v in list(cue.verdicts.items()):
                if v.verdict != Verdict.ON_AIR:
                    continue
                why = ("stale: state changed before air" if cue.valid_state_hash != current
                       else "stale: too old at air" if air_t is not None and air_t > cue.created_t + cue.max_age_ms
                       else None)
                if why:
                    cue.verdicts[t] = v.model_copy(update={"verdict": Verdict.KILLED, "reasons": v.reasons + [why]})
                    self.stats["stale"] += 1
            for t, v in cue.verdicts.items():
                if v.verdict == Verdict.ON_AIR:
                    self.stats["aired"] += 1
                    if t == "uk":
                        m.aired_texts.append(cue.text)
                    self.bc.publish("aired", m.t, {"id": f"{cue.id}:{t}", "cue_id": cue.id, "match_id": cue.match_id,
                                                    "territory": t, "text": v.text, "template": cue.template,
                                                    "data": cue.data, "audience": cue.audience,
                                                    "delay_ms": DELAY_MS.get(t, 0)})
                elif v.verdict == Verdict.KILLED:
                    self.stats["killed"] += 1
            for claim in cue.claims:
                for ref in claim.refs:
                    if ref in m.board.stories and any(v.verdict == Verdict.ON_AIR for v in cue.verdicts.values()):
                        m.board.surfaced(ref, cue.id)
            self.bc.publish("cue", m.t, {**cue.model_dump(mode="json"), "moment_kind": bundle.moment.kind,
                                          "moment_t": bundle.moment.t, "latency_ms": latency,
                                          "status": bundle.status, "timings": bundle.timings,
                                          "stories": [s.id for s in bundle.stories],
                                          "experiments": [x.model_dump(mode="json") for x in bundle.lab.experiments],
                                          "lab_conclusion": bundle.lab.conclusion,
                                          "evidence": [f.model_dump(mode="json") for f in bundle.evidence
                                                       if any(f.id in cl.refs for cl in cue.claims)]})
        self.bc.publish("board", m.t, {"match_id": m.fixture_id,
                                        "stories": [s.model_dump(mode="json") for s in m.board.stories.values()]})

    async def _template(self, m: MatchDesk, moment: Moment) -> None:
        pid = moment.subject or ""
        f = m.desk.fact("player.top_speed_kmh", pid)
        if f is None:
            return
        v = round(f.value, 1)
        name = self.names.get(pid, pid)
        cue = Cue(id=f"Q-{moment.id}-tag", match_id=m.fixture_id, moment_id=moment.id, audience="casual",
                  text=f"{name}: top speed {v} km/h", template="player_tag",
                  data={"name": name, "speed_kmh": v},
                  claims=[Claim(span=f"{v} km/h", kind=ClaimKind.numeric, subject=pid, refs=[f.id], value=v)],
                  valid_state_hash=m.state().game_state_hash, max_age_ms=30_000, created_t=m.t)
        loc = {"uk": (cue.text, "en"), "kids": (cue.text, "en"),
               "es": (f"{name}: velocidad máxima {str(v).replace('.', ',')} km/h", "es"),
               "br": (f"{name}: velocidade máxima {str(v).replace('.', ',')} km/h", "pt"),
               "mena": (f"{name}: السرعة القصوى {v} كم/س", "ar")}
        ctx = CheckContext(facts={f.id: f}, experiments={}, storylines={}, state=m.state(), now_t=m.t, lang="en")
        await self.gate.evaluate(cue, ctx, loc, self.pack_ctx(m.fixture_id))
        from talkback.gallery.agents.lab import LabResult
        from talkback.gallery.workflow import CueBundle
        self._air(CueBundle(moment=moment, cues=[cue], stories=[],
                            lab=LabResult(experiments=[], conclusion="", supported=False, status="skipped"),
                            status={"template": "ok"}))

    async def _recap(self, m: MatchDesk) -> None:
        from talkback.gallery.agents.lab import LabResult
        from talkback.gallery.agents.recap import make_recap_writer, write_recap
        from talkback.gallery.agents.desks import localise_all
        from talkback.gallery.agents.writer import WriterFailure, make_writer, revise_cue
        from talkback.gallery.workflow import CueBundle, _fixable

        async with self.sem:
            await asyncio.sleep(0)
            moment = Moment(id=f"M-{m.fixture_id}-recap", match_id=m.fixture_id, t=m.t, kind="recap", subject=None,
                            salience=1.0, rationale="full time", event_ids=[], ranked_by="rules")
            facts = evidence_facts(m.desk, moment, m.t)
            for pid in dict.fromkeys(m.scorers):
                for metric in ("player.goals", "player.xg", "player.shots"):
                    f = m.desk.fact(metric, pid)
                    if f is not None:
                        facts.append(f)
            stories = list(m.board.stories.values())
            name = f"{self.names[m.home]} v {self.names[m.away]}"
            state = m.state()
            try:
                cue = await write_recap(make_recap_writer(self.client_for("strong")), m.fixture_id, name,
                                        f"{m.score[0]}-{m.score[1]}", facts, stories, m.aired_texts, self.names,
                                        state.game_state_hash, m.t)
            except (WriterFailure, Exception) as exc:  # noqa: BLE001
                self.bc.publish("agent", m.t, {"moment_id": moment.id, "stage": "error", "error": type(exc).__name__})
                return
            ctx = CheckContext(facts={f.id: f for f in facts}, experiments={}, storylines={s.id: s for s in stories},
                               state=state, now_t=m.t, lang="en")
            await self.gate.evaluate(cue, ctx, await localise_all(cue, self.desks), self.pack_ctx(m.fixture_id))
            if _fixable(cue):
                second = await revise_cue(make_writer(self.client_for("fast")), cue, cue.universal_reasons, moment,
                                          facts, None, stories, self.names)
                if second is not None:
                    await self.gate.evaluate(second, ctx, await localise_all(second, self.desks),
                                             self.pack_ctx(m.fixture_id))
                    second.data = {**second.data, "revision_of": cue.id,
                                   "first_refusal": "; ".join(cue.universal_reasons)[:300], "original_text": cue.text}
                    cue = second
            cited = {r for cl in cue.claims for r in cl.refs}
            self._air(CueBundle(moment=moment, cues=[cue], stories=[s for s in stories if s.id in cited],
                                lab=LabResult(experiments=[], conclusion="", supported=False, status="skipped"),
                                status={"recap": "ok"}, evidence=[f for f in facts if f.id in cited]))

    # ---------------------------------------------------------------- table
    def _table(self) -> None:
        if self.sim_t - self.last_table < TABLE_EVERY_MS:
            return
        self.last_table = self.sim_t
        scores = self.live_scores()
        now = self.table.chances(scores)
        sw = swings(self.chances, now, caused_by="matchday") if self.chances else []
        self.chances = now
        self.bc.publish("table", self.sim_t, {"rows": [c.model_dump() for c in now],
                                              "swings": [s.model_dump() for s in sw[:6]]})
        by_match: dict[str, float] = {}
        for s in sw:
            fid = self.world.fixture_of_club(s.club_id)
            by_match[fid] = max(by_match.get(fid, 0.0), abs(s.after - s.before))
        names = {f: f"{self.names[m.home]} v {self.names[m.away]}" for f, m in self.matches.items()}
        item = self.director.rundown(self.moments[-60:], by_match, self.sim_t, names)
        if item:
            self.bc.publish("rundown", self.sim_t, item.model_dump())

    # ----------------------------------------------------------------- loop
    async def run_feed(self, items) -> dict:
        """Run from a live feed (Event Hubs): events and 2 Hz tracking arrive with their own pacing."""
        self.live_frames: dict[str, dict] = {}
        self.bc.publish("run", 0, {"id": self.run_id, "status": "started", "speed": self.speed, "source": "eventhubs",
                                    "fixtures": [{"match_id": f, "home": h, "away": a, "home_name": self.names[h],
                                                  "away_name": self.names[a]} for f, h, a in self.world.fixtures]})
        try:
            loop = asyncio.get_running_loop()
            last_house = 0.0
            async for item in items:
                kind = item.get("kind")
                if kind == "end":
                    break
                if kind == "event":
                    e = Event.model_validate(item["event"])
                    self._dispatch(e)
                    self.sim_t = max(self.sim_t, e.t)
                elif kind == "frame":
                    m = self.matches.get(item["match_id"])
                    if m is not None:
                        m.desk.ingest_frame(_Frame(item["t"], tuple(item["ids"]), np.asarray(item["pos"], float),
                                                   np.asarray(item["speed"], float)))
                        self.live_frames[item["match_id"]] = item
                if loop.time() - last_house > 0.2:
                    last_house = loop.time()
                    self._scan()
                    self._table()
                    await self._expire_holds()
                    self.bc.publish("clock", self.sim_t, {"stats": dict(self.stats), "holds": list(self.holds)},
                                    record=False)
            while self.tasks or self.holds or not self.queue.empty() or self._busy():
                await self._expire_holds()
                await asyncio.sleep(0.2)
        finally:
            self._stop()
        self.bc.publish("run", self.sim_t, {"id": self.run_id, "status": "finished", "stats": self.stats})
        return dict(self.stats)

    async def run(self, until_ms: int | None = None) -> dict:
        self.bc.publish("run", 0, {"id": self.run_id, "status": "started", "speed": self.speed,
                                    "fixtures": [{"match_id": f, "home": h, "away": a, "home_name": self.names[h],
                                                  "away_name": self.names[a]} for f, h, a in self.world.fixtures]})
        try:
            loop = asyncio.get_running_loop()
            wall0 = loop.time()
            events = self.source.events()
            nxt = next(events, None)
            last_pub = -1
            while nxt is not None or self.tasks or self.holds or not self.queue.empty() or self._busy():
                target = int((loop.time() - wall0) * self.speed * 1000)
                if until_ms is not None:
                    target = min(target, until_ms)
                while nxt is not None and nxt.t <= target:
                    self._dispatch(nxt)
                    nxt = next(events, None)
                self.sim_t = max(self.sim_t, target if nxt is not None else self.sim_t)
                self._frames_to(self.sim_t)
                self._scan()
                self._table()
                await self._expire_holds()
                if self.sim_t // 1000 != last_pub:
                    last_pub = self.sim_t // 1000
                    self.bc.publish("clock", self.sim_t, {"stats": dict(self.stats), "holds": list(self.holds)},
                                    record=False)
                if (until_ms is not None and target >= until_ms and not self.tasks and self.queue.empty()
                        and not self._busy()):
                    break
                await asyncio.sleep(0.05)
        finally:
            self._stop()
        self.bc.publish("run", self.sim_t, {"id": self.run_id, "status": "finished", "stats": self.stats})
        return dict(self.stats)


def _spotter_agent(client):
    from agent_framework import Agent

    from talkback.gallery.spotter import RANK_INSTRUCTIONS

    return Agent(client=client, instructions=RANK_INSTRUCTIONS, name="spotter")


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
