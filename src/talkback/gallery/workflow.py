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
from talkback.gallery.agents.archivist import make_archivist, moment_prompt, pick_storylines, stories_from_answer
from talkback.gallery.agents.desks import TerritoryDesk, localise_all, localise_many
from talkback.gallery.agents.lab import LabBackend, LabResult, finalize, make_lab
from talkback.gallery.agents.writer import WriterFailure, draft_cues, make_writer, revise_cue
from talkback.gallery.spotter import Moment
from talkback.gallery.storyboard import StoryBoard
from talkback.gallery.world import World
from talkback.hosted.runs import with_run
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
    wall0: float = field(default_factory=time.monotonic)

    def age_now_t(self) -> int:
        """Match time as a 1x broadcast would see it: the moment's time plus real elapsed pipeline time."""
        return self.now_t + int((time.monotonic() - self.wall0) * 1000)


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
    evidence: list[Fact] = field(default_factory=list)
    job: MomentJob | None = None


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
    remote: object | None = None             # RemoteAgents: Archivist and Lab over A2A
    run_name: str | None = None              # the run the remote agents load (storage prefix)


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
        remote = self.deps.remote
        note = ""
        if remote is not None and remote.enabled("archivist"):
            try:
                text = await remote.ask("archivist", with_run(self.deps.run_name,
                                                              moment_prompt(job.moment, board, self.deps.world)))
                await ctx.send_message(Stories(job, stories_from_answer(text, board), remote.via("archivist"),
                                               _ms(t0)))
                return
            except Exception as exc:  # noqa: BLE001 - fall back to the in-process archivist
                note = f"degraded: {remote.via('archivist')} {type(exc).__name__}, ran in-process"
        try:
            agent = make_archivist(self.deps.client("strong"), self.deps.world, board)
            stories = await pick_storylines(agent, job.moment, board, self.deps.world)
            await ctx.send_message(Stories(job, stories, note or "ok", _ms(t0)))
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
        prompt = (f"Moment {m.kind} at {m.t // 60_000}' in {m.match_id} (moment id {m.id}). The shot event is "
                  f"{job.anchor_event_id}. Menu: cancel_shot (what if he had not shot), complete_intercepted_pass.")
        remote = self.deps.remote
        note = ""
        if remote is not None and remote.enabled("lab"):
            try:
                sealed = LabResult.model_validate_json(await remote.ask("lab", with_run(self.deps.run_name, prompt)))
                ok = any(x.metric == "threat" and (x.ci95[0] > 0 or x.ci95[1] < 0) for x in sealed.experiments)
                sealed = sealed.model_copy(update={"supported": ok, "status": remote.via("lab")})
                if sealed.experiments:
                    await ctx.send_message(LabOut(job, sealed, remote.via("lab"), _ms(t0)))
                    return
                note = f"degraded: {remote.via('lab')} ran no experiment, ran in-process"
            except Exception as exc:  # noqa: BLE001 - fall through to the in-process Lab
                note = f"degraded: {remote.via('lab')} {type(exc).__name__}, ran in-process"
        try:
            agent = make_lab(self.deps.client("strong"), backend, m.id, m.match_id)
            result = finalize((await agent.run(prompt)).text, backend)
            if not result.experiments:
                # the model ran nothing: run the default experiment so the writer still has evidence
                xs = await asyncio.to_thread(backend.run, m.id, m.match_id, job.anchor_event_id,
                                             DEFAULT_EXPERIMENT[m.kind])
                supported = any(x.metric == "threat" and (x.ci95[0] > 0 or x.ci95[1] < 0) for x in xs)
                result = LabResult(experiments=xs, conclusion="" if supported else "no clear effect",
                                   supported=supported, status="default")
            await ctx.send_message(LabOut(job, result, note or result.status, _ms(t0)))
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

        def checks() -> CheckContext:
            # built right before each evaluation, so localising and revising count towards a line's age
            return CheckContext(
                facts={f.id: f for f in d.job.facts}, experiments={x.id: x for x in d.lab.experiments},
                storylines={s.id: s for s in d.stories}, state=self.deps.state_now(match_id),
                now_t=d.job.age_now_t(), lang="en")

        try:
            batch = await localise_many(d.cues, self.deps.desks)
        except Exception:  # noqa: BLE001 - without translations each desk falls back to the source or refuses
            batch = [{} for _ in d.cues]
        for n, cue in enumerate(d.cues):
            await self.deps.gate.evaluate(cue, checks(), batch[n], self.deps.pack_ctx(match_id))
            if _fixable(cue):
                # one revision: the writer sees exactly why Clearance refused and may try once more
                try:
                    second = await revise_cue(make_writer(self.deps.client("fast")), cue, cue.universal_reasons,
                                              d.job.moment, d.job.facts, d.lab, d.stories, d.job.names)
                except Exception:  # noqa: BLE001 - the first refusal stands
                    second = None
                if second is not None:
                    try:
                        localized = await localise_all(second, self.deps.desks)
                    except Exception:  # noqa: BLE001
                        localized = {}
                    await self.deps.gate.evaluate(second, checks(), localized, self.deps.pack_ctx(match_id))
                    second.data = {**second.data, "revision_of": cue.id,
                                   "first_refusal": "; ".join(cue.universal_reasons)[:300], "original_text": cue.text}
                    d.cues[n] = second
                    d.status["revisions"] = str(int(d.status.get("revisions", "0")) + 1)
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


FIXABLE = ("number", "attribution", "strength", "causal", "storyline")


def _fixable(cue: Cue) -> bool:
    killed_everywhere = bool(cue.verdicts) and all(v.verdict == Verdict.KILLED for v in cue.verdicts.values())
    return bool(killed_everywhere and cue.universal_reasons
                and all(r.split(":")[0] in FIXABLE for r in cue.universal_reasons))


def _bundle(d: Drafts) -> CueBundle:
    cited = {r for c in d.cues for cl in c.claims for r in cl.refs}
    evidence = [f for f in d.job.facts if f.id in cited]
    return CueBundle(moment=d.job.moment, cues=d.cues, stories=d.stories, lab=d.lab, status=d.status,
                     timings=d.timings, evidence=evidence, job=d.job)


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
