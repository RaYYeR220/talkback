"""The Talkback service: gallery stream, producer seat, run control and the claim ledger.

When nobody has started a live matchday, the service replays the latest
recorded real run on a loop (labelled REPLAY), so the gallery is always
watchable without credentials. A live run pre-empts the replay; only one
runs at a time and the number per day is capped.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from talkback.gallery.bus import Broadcaster, FileSource
from talkback.ograf.graphics_op import OGrafClient
from talkback.ograf.server import OGrafServer
from talkback.service.graphics import GraphicsDriver

RUN_DIR = Path(os.environ.get("TALKBACK_RUN_DIR", "runs/md-2026"))
REPLAY_FILE = os.environ.get("TALKBACK_REPLAY", "broadcast-replay.jsonl")
# Each live run costs model tokens; the public console can start at most this many a day.
LIVE_PER_DAY = int(os.environ.get("TALKBACK_LIVE_PER_DAY", "3"))
LIVE_SPEED = float(os.environ.get("TALKBACK_LIVE_SPEED", "10"))
# A live feed that goes quiet this long has ended (the generator died or never sent `end`) ...
LIVE_IDLE_S = float(os.environ.get("TALKBACK_LIVE_IDLE_S", "180"))
# ... and no live run, however it is fed, holds the console for longer than this.
LIVE_MAX_S = float(os.environ.get("TALKBACK_LIVE_MAX_S", str(75 * 60)))
REPLAY_SPEED = float(os.environ.get("TALKBACK_REPLAY_SPEED", "10"))
# How long the finished replay stays on screen before it starts again.
REPLAY_HOLD_S = float(os.environ.get("TALKBACK_REPLAY_HOLD_S", "90"))


class StartRequest(BaseModel):
    # At 2x a matchday's feed takes about 49 minutes, inside the generator job's one-hour limit; above 20x the
    # token rate outruns the budget.
    speed: float | None = Field(default=None, ge=2, le=20)


def cors_origins() -> list[str]:
    return [o.strip() for o in os.environ.get("TALKBACK_CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]


async def drain(queue: asyncio.Queue, idle_s: float):
    """Items from a live feed until `end`, or until nothing has arrived for `idle_s`."""
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), idle_s)
        except TimeoutError:
            return
        yield item
        if item.get("kind") == "end":
            return


class Decision(BaseModel):
    decisions: dict[str, str]


class Gallery:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.bc = Broadcaster()
        self.source = FileSource(run_dir)
        self.mode = "idle"
        self.run_id: str | None = None
        self.sim_t = 0
        self.runner = None
        self.task: asyncio.Task | None = None
        self.live_started: list[float] = []
        self.pool: ProcessPoolExecutor | None = None
        self.ledger: dict[str, dict] = {}
        self.graphics: GraphicsDriver | None = None

    def recorded_events(self) -> dict:
        if not hasattr(self, "_events"):
            self._events = {e.id: e for e in self.source.events()}
        return self._events

    def _remember(self, msg: dict) -> None:
        if msg["kind"] == "cue":
            self.ledger[msg["data"]["id"]] = msg["data"]

    # ---------------------------------------------------------------- replay
    def replay_path(self) -> Path | None:
        p = self.run_dir / REPLAY_FILE
        return p if p.exists() else None

    async def replay_loop(self) -> None:
        path = self.replay_path()
        if path is None:
            return
        msgs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        while True:
            self.mode, self.run_id = "replay", f"replay:{path.stem}"
            self.ledger.clear()
            self.bc.reset()
            if self.graphics is not None:
                self.graphics.speed = REPLAY_SPEED
            loop = asyncio.get_running_loop()
            wall0 = loop.time()
            for msg in msgs:
                due = msg["sim_t"] / 1000 / REPLAY_SPEED
                delay = due - (loop.time() - wall0)
                if delay > 0:
                    await asyncio.sleep(delay)
                self.sim_t = msg["sim_t"]
                data = dict(msg["data"])
                if msg["kind"] == "run":
                    data.update({"mode": "replay", "recorded": msg.get("wall")})
                self._remember({**msg, "data": data})
                self.bc.publish(msg["kind"], msg["sim_t"], data, record=False)
            await asyncio.sleep(REPLAY_HOLD_S)

    # ------------------------------------------------------------------ live
    async def start_live(self, speed: float) -> str:
        from talkback.clearance.gate import Gate
        from talkback.clearance.packs import PACKS_DIR, load_packs
        from talkback.gallery.llm import make_client
        from talkback.gallery.runner import MatchdayRunner
        from talkback.service.safety import make_safety

        from talkback.service.cloud import cloud_enabled

        if self.mode == "live":
            raise HTTPException(409, "a live matchday is already running")
        day_ago = time.time() - 86_400
        self.live_started = [t for t in self.live_started if t > day_ago]
        if len(self.live_started) >= LIVE_PER_DAY:
            raise HTTPException(429, "daily live-run cap reached; the replay keeps playing")
        run_id = f"live-{int(time.time())}"
        self.pool = self.pool or ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 1))
        runner = None
        if not cloud_enabled():
            # build everything that can fail before touching the replay, so a failed start changes nothing
            try:
                clients = {"fast": make_client("fast"), "strong": make_client("strong")}
                runner = MatchdayRunner(self.run_dir, Gate(load_packs(PACKS_DIR), make_safety()),
                                        clients.__getitem__, self.bc, speed=speed, lab_pool=self.pool,
                                        run_id=run_id)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(503, f"live matchday unavailable ({type(exc).__name__}); "
                                         "the replay keeps playing") from exc
        if self.task:
            self.task.cancel()
        self.live_started.append(time.time())
        self.run_id = run_id
        self.mode = "live"
        self.ledger.clear()
        self.bc.reset()
        record = self.run_dir / f"broadcast-{self.run_id}.jsonl"
        self.bc._fh = open(record, "a", encoding="utf-8", newline="\n")
        if self.graphics is not None:
            self.graphics.speed = speed
        self.live_speed = speed
        self.runner = runner
        self.task = asyncio.create_task(self._live())
        return self.run_id

    async def start_cloud(self, speed: float) -> str:
        """Live run in Azure: generator job → Event Hubs → this service (no local run directory needed)."""
        from talkback.clearance.gate import Gate
        from talkback.clearance.packs import PACKS_DIR, load_packs
        from talkback.gallery.bus import EventHubsSource
        from talkback.gallery.llm import make_client
        from talkback.gallery.runner import MatchdayRunner
        from talkback.service.cloud import start_generator, wait_for_run
        from talkback.service.safety import make_safety

        seed = int(time.time()) % 100_000
        run_id = f"md-{seed}-{int(time.time())}"
        buffer: asyncio.Queue = asyncio.Queue(maxsize=50_000)

        async def pump() -> None:
            async for item in EventHubsSource(run_id).items():
                await buffer.put(item)

        pump_task = asyncio.create_task(pump())
        try:
            await asyncio.sleep(2)  # let the consumer attach before the first event is published
            await start_generator(run_id, seed, speed)
            self.bc.publish("run", 0, {"id": run_id, "status": "generating", "mode": "live"}, record=False)
            dest = await wait_for_run(run_id, Path(os.environ.get("TMPDIR", "/tmp")) / "talkback-live" / run_id)
            clients = {"fast": make_client("fast"), "strong": make_client("strong")}
            self.runner = MatchdayRunner(dest, Gate(load_packs(PACKS_DIR), make_safety()), clients.__getitem__,
                                         self.bc, speed=speed, lab_pool=self.pool, run_id=run_id)
            await self.runner.run_feed(drain(buffer, LIVE_IDLE_S))
        finally:
            pump_task.cancel()
        return run_id

    async def _live(self) -> None:
        from talkback.service.cloud import cloud_enabled

        try:
            run = (self.start_cloud(getattr(self, "live_speed", LIVE_SPEED)) if cloud_enabled()
                   else self.runner.run())
            await asyncio.wait_for(run, LIVE_MAX_S)
        except Exception as exc:  # noqa: BLE001 - whatever happened, the console goes back to the replay
            self.bc.publish("run", self.sim_t, {"id": self.run_id, "status": "failed", "error": type(exc).__name__},
                            record=False)
        finally:
            self.bc.close()
            self.mode = "idle"
            self.runner = None
            self.task = asyncio.create_task(self.replay_loop())


gallery = Gallery(RUN_DIR)


ograf = OGrafServer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    import httpx

    from talkback.service import telemetry

    telemetry.configure()

    gallery.task = asyncio.create_task(gallery.replay_loop())
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://talkback.local")
    driver = GraphicsDriver(OGrafClient(http), speed=REPLAY_SPEED)
    gallery.graphics = driver
    graphics_task = asyncio.create_task(driver.run(gallery.bc.subscribe))

    async def follow() -> None:
        # the ledger and the clock are kept whether or not anyone is watching the stream
        async for msg in gallery.bc.subscribe():
            gallery._remember(msg)
            if gallery.runner is not None:
                gallery.sim_t = gallery.runner.sim_t

    follow_task = asyncio.create_task(follow())
    from talkback.service.ledger import make_ledger

    ledger = make_ledger()
    ledger_task = None
    if ledger is not None:
        ledger_task = asyncio.create_task(ledger.run(gallery.bc.subscribe, lambda: gallery.run_id or "unknown"))
    yield
    graphics_task.cancel()
    follow_task.cancel()
    if ledger_task:
        ledger_task.cancel()
        await ledger.close()
    await http.aclose()
    if gallery.task:
        gallery.task.cancel()
    if gallery.pool:
        gallery.pool.shutdown(cancel_futures=True)


app = FastAPI(title="Talkback", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=cors_origins(), allow_methods=["GET", "POST", "PUT", "DELETE"],
                   allow_headers=["*"])
ograf.mount(app, prefix="/ograf/v1", base="/ograf")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "mode": gallery.mode, "run": gallery.run_id}


@app.get("/api/state")
def state() -> dict:
    return {"mode": gallery.mode, "run": gallery.run_id, "sim_t": gallery.sim_t,
            "last": list(gallery.bc.last.values())}


@app.get("/api/stream")
async def stream() -> StreamingResponse:
    async def gen():
        yield f"event: hello\ndata: {json.dumps({'mode': gallery.mode, 'run': gallery.run_id})}\n\n"
        async for msg in gallery.bc.subscribe():
            yield f"event: {msg['kind']}\ndata: {json.dumps(msg, default=str)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/frames/{match_id}")
def frame(match_id: str, t: int | None = None) -> dict:
    live = getattr(gallery.runner, "live_frames", None)
    if live and match_id in live:  # a cloud run has no tracking on disk here; its latest frame is the one
        item = live[match_id]
        return {k: item[k] for k in ("match_id", "t", "ball", "ids", "pos")}
    at = gallery.sim_t if t is None else t
    f = gallery.source.frame_at(match_id, at)
    if f is None:
        raise HTTPException(404, "no tracking for this match yet")
    return f


@app.post("/api/live")
async def start_live(req: StartRequest) -> dict:
    run_id = await gallery.start_live(req.speed or LIVE_SPEED)
    return {"run": run_id, "mode": "live"}


@app.get("/api/holds")
def holds() -> dict:
    if gallery.runner is None:
        return {"holds": []}
    return {"holds": [run.hold.__dict__ for run, _ in gallery.runner.holds.values() if run.hold]}


@app.post("/api/holds/{moment_id}")
async def decide(moment_id: str, d: Decision) -> dict:
    if gallery.runner is None:
        raise HTTPException(409, "the producer seat is only open during a live matchday")
    bad = {v for v in d.decisions.values() if v not in ("approve", "reject")}
    if bad:
        raise HTTPException(422, f"decisions must be approve or reject, got {sorted(bad)}")
    if not await gallery.runner.decide(moment_id, d.decisions):
        raise HTTPException(404, "no such hold (it may have expired)")
    return {"ok": True}


@app.get("/api/ledger/{cue_id}")
def ledger(cue_id: str) -> dict:
    cue = gallery.ledger.get(cue_id)
    if cue is None:
        raise HTTPException(404, "unknown cue")
    index = gallery.runner.events_by_id if gallery.runner is not None else gallery.recorded_events()
    events = {}
    for f in cue.get("evidence", []):
        for eid in f.get("evidence", [])[-12:]:
            e = index.get(eid)
            if e is not None:
                events[eid] = e.model_dump(mode="json")
    return {"cue": cue, "events": events}
