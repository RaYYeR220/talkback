"""The per-moment workflow (Microsoft Agent Framework).

    intake ──► archivist ─┐
           └─► lab ───────┴─► writer ──► clearance ──(holds)──► producer (human) ──► output

Every spotted moment runs this graph once. Archivist and Lab work in
parallel; the Writer only sees what they returned; Clearance localises for
every territory and applies the gate; anything held waits for the producer
through a request/response pause. A failing Archivist or Lab degrades the
run (no storylines / no causal wording) instead of stopping it.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler, response_handler

from talkback.clearance.checks import CheckContext
from talkback.clearance.gate import Gate
from talkback.clearance.packs import PackContext
from talkback.gallery.agents.archivist import make_archivist, pick_storylines
from talkback.gallery.agents.desks import TerritoryDesk, localise_all
from talkback.gallery.agents.lab import LabBackend, LabResult, finalize, make_lab
from talkback.gallery.agents.writer import WriterFailure, draft_cues, make_writer
from talkback.gallery.spotter import Moment
from talkback.gallery.storyboard import StoryBoard
from talkback.gallery.world import World
from talkback.schemas.models import Cue, Fact, MatchState, Storyline, Verdict

LAB_MOMENTS = {"goal", "big_chance", "big_save"}
DEFAULT_EXPERIMENT = {"goal": "cancel_shot", "big_chance": "cancel_shot", "big_save": "cancel_shot"}


@dataclass
class MomentJob:
    moment: Moment
    facts: list[Fact]
    names: dict[str, str]
    state: MatchState
    now_t: int
    anchor_event_id: str | None = None


@dataclass
class Stories:
    job: MomentJob
    stories: list[Storyline]
    status: str
    ms: int


@dataclass
class LabOut:
    job: MomentJob
    result: LabResult
    status: str
    ms: int


@dataclass
class Drafts:
    job: MomentJob
    cues: list[Cue]
    stories: list[Storyline]
    lab: LabResult
    status: dict[str, str]
    timings: dict[str, int]


@dataclass
class HoldRequest:
    moment_id: str
    match_id: str
    holds: list[dict]


@dataclass
class CueBundle:
    moment: Moment
    cues: list[Cue]
    stories: list[Storyline]
    lab: LabResult
    status: dict[str, str]
    timings: dict[str, int] = field(default_factory=dict)


@dataclass
class MomentDeps:
    world: World
    boards: dict[str, StoryBoard]
    lab: LabBackend | None
    gate: Gate
    desks: list[TerritoryDesk]
    pack_ctx: Callable[[str], PackContext]
    state_now: Callable[[str], MatchState]
    client: Callable[[str], object]          # tier -> chat client
    archivist_override: Callable[[MomentJob], object] | None = None


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


class Intake(Executor):
    @handler
    async def take(self, job: MomentJob, ctx: WorkflowContext[MomentJob]) -> None:
        await ctx.send_message(job)


class ArchivistExec(Executor):
    def __init__(self, deps: MomentDeps, **kw):
        super().__init__(**kw)
        self.deps = deps

    @handler
    async def research(self, job: MomentJob, ctx: WorkflowContext[Stories]) -> None:
        t0 = time.perf_counter()
        board = self.deps.boards[job.moment.match_id]
        try:
            agent = make_archivist(self.deps.client("strong"), self.deps.world, board)
            stories = await pick_storylines(agent, job.moment, board, self.deps.world)
            await ctx.send_message(Stories(job, stories, "ok", _ms(t0)))
        except Exception as exc:  # noqa: BLE001 - degrade, never stop the moment
            await ctx.send_message(Stories(job, [], f"degraded: {type(exc).__name__}", _ms(t0)))


class LabExec(Executor):
    def __init__(self, deps: MomentDeps, **kw):
        super().__init__(**kw)
        self.deps = deps

    @handler
    async def experiment(self, job: MomentJob, ctx: WorkflowContext[LabOut]) -> None:
        t0 = time.perf_counter()
        empty = LabResult(experiments=[], conclusion="", supported=False, status="skipped")
        backend = self.deps.lab
        m = job.moment
        if backend is None or m.kind not in LAB_MOMENTS or not job.anchor_event_id:
            await ctx.send_message(LabOut(job, empty, "skipped", _ms(t0)))
            return
        try:
            agent = make_lab(self.deps.client("strong"), backend, m.id, m.match_id)
            prompt = (f"Moment {m.kind} at {m.t // 60_000}' in {m.match_id}. The shot event is {job.anchor_event_id}. "
                      f"Menu: cancel_shot (what if he had not shot), complete_intercepted_pass.")
            result = finalize((await agent.run(prompt)).text, backend)
            if not result.experiments:
                # the model ran nothing: run the default experiment so the writer still has evidence
                xs = await asyncio.to_thread(backend.run, m.id, m.match_id, job.anchor_event_id,
                                             DEFAULT_EXPERIMENT[m.kind])
                supported = any(x.metric == "threat" and (x.ci95[0] > 0 or x.ci95[1] < 0) for x in xs)
                result = LabResult(experiments=xs, conclusion="" if supported else "no clear effect",
                                   supported=supported, status="default")
            await ctx.send_message(LabOut(job, result, result.status, _ms(t0)))
        except Exception as exc:  # noqa: BLE001
            await ctx.send_message(LabOut(job, empty.model_copy(update={"status": "degraded"}),
                                          f"degraded: {type(exc).__name__}", _ms(t0)))


class WriterExec(Executor):
    def __init__(self, deps: MomentDeps, **kw):
        super().__init__(**kw)
        self.deps = deps

    @handler
    async def write(self, parts: list[Stories | LabOut], ctx: WorkflowContext[Drafts]) -> None:
        t0 = time.perf_counter()
        stories = next(p for p in parts if isinstance(p, Stories))
        lab = next(p for p in parts if isinstance(p, LabOut))
        job = stories.job
        status = {"archivist": stories.status, "lab": lab.status}
        timings = {"archivist": stories.ms, "lab": lab.ms}
        try:
            cues = await draft_cues(make_writer(self.deps.client("fast")), job.moment, job.facts, lab.result,
                                    stories.stories, job.names, job.state.game_state_hash, job.now_t)
            status["writer"] = "ok"
        except (WriterFailure, Exception) as exc:  # noqa: BLE001
            cues = []
            status["writer"] = f"failed: {type(exc).__name__}: {str(exc)[:160]}"
        timings["writer"] = _ms(t0)
        await ctx.send_message(Drafts(job, cues, stories.stories, lab.result, status, timings))


class ClearanceExec(Executor):
    def __init__(self, deps: MomentDeps, **kw):
        super().__init__(**kw)
        self.deps = deps
        self.pending: dict[str, Drafts] = {}

    @handler
    async def clear(self, d: Drafts, ctx: WorkflowContext[None, CueBundle]) -> None:
        t0 = time.perf_counter()
        match_id = d.job.moment.match_id
        ctx_checks = CheckContext(
            facts={f.id: f for f in d.job.facts}, experiments={x.id: x for x in d.lab.experiments},
            storylines={s.id: s for s in d.stories}, state=self.deps.state_now(match_id),
            now_t=self.deps.state_now(match_id).t, lang="en")
        for cue in d.cues:
            localized = await localise_all(cue, self.deps.desks)
            await self.deps.gate.evaluate(cue, ctx_checks, localized, self.deps.pack_ctx(match_id))
        d.timings["clearance"] = _ms(t0)
        holds = [{"cue_id": c.id, "text": c.text,
                  "territories": [t for t, v in c.verdicts.items() if v.verdict == Verdict.HOLD_FOR_PRODUCER],
                  "reasons": sorted({r for v in c.verdicts.values() for r in v.reasons})}
                 for c in d.cues if any(v.verdict == Verdict.HOLD_FOR_PRODUCER for v in c.verdicts.values())]
        if holds:
            self.pending[d.job.moment.id] = d
            await ctx.request_info(request_data=HoldRequest(d.job.moment.id, match_id, holds), response_type=dict)
            return
        await ctx.yield_output(_bundle(d))

    @response_handler
    async def decided(self, request: HoldRequest, decision: dict, ctx: WorkflowContext[None, CueBundle]) -> None:
        d = self.pending.pop(request.moment_id)
        for cue in d.cues:
            choice = decision.get(cue.id)
            for t, v in list(cue.verdicts.items()):
                if v.verdict != Verdict.HOLD_FOR_PRODUCER:
                    continue
                if choice == "approve":
                    cue.verdicts[t] = v.model_copy(update={"verdict": Verdict.ON_AIR,
                                                            "reasons": v.reasons + ["producer: approved"]})
                else:
                    why = "rejected" if choice == "reject" else "expired"
                    cue.verdicts[t] = v.model_copy(update={"verdict": Verdict.KILLED,
                                                            "reasons": v.reasons + [f"producer: {why}"]})
        d.status["producer"] = "decided"
        await ctx.yield_output(_bundle(d))


def _bundle(d: Drafts) -> CueBundle:
    return CueBundle(moment=d.job.moment, cues=d.cues, stories=d.stories, lab=d.lab, status=d.status,
                     timings=d.timings)


def build_moment_workflow(deps: MomentDeps):
    intake = Intake(id="intake")
    archivist = ArchivistExec(deps, id="archivist")
    lab = LabExec(deps, id="lab")
    writer = WriterExec(deps, id="writer")
    clearance = ClearanceExec(deps, id="clearance")
    return (WorkflowBuilder(start_executor=intake, name="moment", description="One moment, from evidence to air")
            .add_fan_out_edges(intake, [archivist, lab])
            .add_fan_in_edges([archivist, lab], writer)
            .add_edge(writer, clearance)
            .build())


@dataclass
class MomentRun:
    workflow: object
    bundle: CueBundle | None = None
    hold: HoldRequest | None = None
    request_id: str | None = None
    trace: list[tuple[str, str]] = field(default_factory=list)


async def _drain(run: MomentRun, stream) -> MomentRun:
    async for ev in stream:
        if ev.type == "output":
            run.bundle = ev.data
        elif ev.type == "request_info":
            run.hold = ev.data
            run.request_id = ev.request_id
        elif ev.type in ("executor_invoked", "executor_completed") and getattr(ev, "executor_id", None):
            run.trace.append((ev.type, ev.executor_id))
    return run


async def run_moment(deps: MomentDeps, job: MomentJob) -> MomentRun:
    wf = build_moment_workflow(deps)
    return await _drain(MomentRun(wf), wf.run(job, stream=True))


async def answer_hold(run: MomentRun, decision: dict[str, str]) -> MomentRun:
    """Resume a paused moment with the producer's decision per cue (approve / reject / expired)."""
    rid = run.request_id
    run.hold, run.request_id = None, None
    return await _drain(run, run.workflow.run(stream=True, responses={rid: decision}))
