"""Drives broadcast graphics from the gallery stream through the OGraf Server API.

Listens to the same messages the console sees — cleared cues, scores and the
Director's rundown — and books OGraf actions per territory output. The Graphics
Op only ever talks to the OGraf server over its standard REST API.

Everything is booked in match time, from each message's sim_t. Between messages
the match clock runs on at the playout speed, which is where wall-clock time
comes in: an action booked for match time T plays when that clock reaches T.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from pydantic import ValidationError

from talkback.ograf.graphics_op import GraphicsOp, OGrafClient
from talkback.schemas.models import Cue, Fact, MatchState, state_hash

DELAY_MS = {"uk": 0, "es": 0, "br": 0, "kids": 0, "mena": 120_000, "world": 0}  # broadcast delay, match ms
TERRITORY_OUTPUTS = ("world", "uk", "es", "mena", "kids", "br")
# Messages run a few seconds out of order; a clock this far behind is a new run or replay loop.
REWIND_MS = 60_000
CUE_FIELDS = set(Cue.model_fields)
FACT_FIELDS = set(Fact.model_fields)


def facts(raw: object) -> list[Fact]:
    """The facts a cue message cites; malformed entries are skipped, not fatal."""
    out = []
    for f in raw if isinstance(raw, list) else []:
        try:
            out.append(Fact.model_validate({"match_id": None, "evidence": [], "computed_at": 0,
                                            **{k: v for k, v in f.items() if k in FACT_FIELDS}}))
        except (AttributeError, ValidationError):
            continue
    return out


class GraphicsDriver:
    def __init__(self, client: OGrafClient, speed: float = 10.0, clock: Callable[[], float] = time.monotonic):
        """speed: the replay's playout speed; a live run announces its own in its run message."""
        self.client = client
        self.clock = clock
        # The match clock: match ms _sim at wall-clock second _wall, running on at the playout speed.
        self._sim, self._wall = 0, clock()
        self.op = GraphicsOp(outputs={t: t for t in TERRITORY_OUTPUTS}, speed=speed)
        self.replay_speed = speed
        self.scores: dict[str, dict] = {}
        self.on_screen: str | None = None
        self.errors = 0

    @property
    def speed(self) -> float:
        """Match seconds per wall-clock second."""
        return self.op.speed

    @speed.setter
    def speed(self, value: float) -> None:
        self._sim, self._wall = self.now(), self.clock()
        self.op.speed = float(value)

    def now(self) -> int:
        """Match time now: the last sim_t heard, run on at the playout speed."""
        return self._sim + int((self.clock() - self._wall) * 1000 * self.speed)

    def delay(self, territory: str) -> int:
        return DELAY_MS.get(territory, 0)

    def _sync(self, sim_t: int, new_run: bool = False) -> None:
        """Follow the gallery's clock. When it goes back (a new run or replay loop), what is booked
        moves with it and keeps its wall-clock schedule."""
        if new_run or sim_t < self._sim - REWIND_MS:
            self.op.rebase(sim_t - self.now())
        elif sim_t <= self._sim:
            return
        self._sim, self._wall = sim_t, self.clock()

    def on_message(self, msg: dict) -> None:
        kind, d = msg["kind"], msg["data"]
        try:
            t = int(msg.get("sim_t", self.now()))
            if kind == "run" and d.get("status") == "started":
                self.speed = self.replay_speed if d.get("mode") == "replay" else float(d.get("speed") or self.speed)
                self._sync(t, new_run=True)
            elif kind == "cue":
                self._sync(t)
                cue = Cue.model_validate({k: v for k, v in d.items() if k in CUE_FIELDS})
                evidence = facts(d.get("evidence"))
                # The op airs each output's own verdict; world and the presenter strip follow uk's.
                for output in TERRITORY_OUTPUTS:
                    self.op.plan(cue, output, t, delay_ms=self.delay(output), evidence=evidence)
            elif kind == "score":
                self._sync(t)
                self.scores[d["match_id"]] = d
                if self.on_screen is None:
                    self.on_screen = d["match_id"]
                if d["match_id"] == self.on_screen:
                    self._scorebug(t)
            elif kind == "rundown":
                self._sync(t)
                if d["match_id"] != self.on_screen:
                    self.on_screen = d["match_id"]
                    self._scorebug(t)
        except Exception:  # noqa: BLE001 - graphics never take the gallery down
            self.errors += 1

    def _scorebug(self, now_t: int) -> None:
        d = self.scores.get(self.on_screen or "")
        if d is None:
            return
        state = MatchState(match_id=d["match_id"], t=0, period=d.get("period", 1), home_goals=d["score"][0],
                           away_goals=d["score"][1], home_red=d["reds"][0], away_red=d["reds"][1],
                           game_state_hash=state_hash(home_goals=d["score"][0], away_goals=d["score"][1],
                                                      home_red=d["reds"][0], away_red=d["reds"][1], subs_count=0,
                                                      period=d.get("period", 1)))
        elsewhere = [{"homeShort": s["home_short"], "awayShort": s["away_short"], "homeScore": s["score"][0],
                      "awayScore": s["score"][1]} for mid, s in sorted(self.scores.items()) if mid != d["match_id"]]
        for territory in TERRITORY_OUTPUTS:
            self.op.plan_score(state, territory, now_t, self.delay(territory), home=d["home_short"],
                               away=d["away_short"], minute=d.get("minute"), elsewhere=elsewhere[:9],
                               status="FT" if d.get("finished") else None)

    async def run(self, subscribe) -> None:
        async def feed():
            async for msg in subscribe():
                self.on_message(msg)

        task = asyncio.create_task(feed())
        try:
            while True:
                try:
                    await self.op.tick(self.now(), self.client)
                except Exception:  # noqa: BLE001
                    self.errors += 1
                await asyncio.sleep(0.1)
        finally:
            task.cancel()
