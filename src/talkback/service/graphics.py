"""Drives broadcast graphics from the gallery stream through the OGraf Server API.

Listens to the same messages the console sees — cleared cues, scores and the
Director's rundown — and books OGraf actions per territory output. The Graphics
Op only ever talks to the OGraf server over its standard REST API.
"""

from __future__ import annotations

import asyncio
import time

from talkback.ograf.graphics_op import GraphicsOp, OGrafClient
from talkback.schemas.models import Cue, MatchState, Verdict, state_hash

DELAY_MS = {"uk": 0, "es": 0, "br": 0, "kids": 0, "mena": 120_000, "world": 0}
TERRITORY_OUTPUTS = ("world", "uk", "es", "mena", "kids", "br")
CUE_FIELDS = set(Cue.model_fields)


class GraphicsDriver:
    def __init__(self, client: OGrafClient, speed: float = 10.0):
        self.client = client
        self.speed = speed
        outputs = {t: t for t in TERRITORY_OUTPUTS}
        self.op = GraphicsOp(outputs=outputs)
        self.scores: dict[str, dict] = {}
        self.on_screen: str | None = None
        self.t0 = time.monotonic()
        self.errors = 0

    def now(self) -> int:
        return int((time.monotonic() - self.t0) * 1000)

    def delay(self, territory: str) -> int:
        return int(DELAY_MS.get(territory, 0) / max(self.speed, 1.0))

    def on_message(self, msg: dict) -> None:
        kind, d = msg["kind"], msg["data"]
        try:
            if kind == "cue":
                cue = Cue.model_validate({k: v for k, v in d.items() if k in CUE_FIELDS})
                for territory, v in cue.verdicts.items():
                    if v.verdict == Verdict.ON_AIR:
                        self.op.plan(cue, territory, self.now(), delay_ms=self.delay(territory))
                        if territory == "uk":
                            self.op.plan(cue, "world", self.now(), delay_ms=0) if "world" in self.op.outputs else None
            elif kind == "score":
                self.scores[d["match_id"]] = d
                if self.on_screen is None:
                    self.on_screen = d["match_id"]
                if d["match_id"] == self.on_screen:
                    self._scorebug()
            elif kind == "rundown":
                if d["match_id"] != self.on_screen:
                    self.on_screen = d["match_id"]
                    self._scorebug()
        except Exception:  # noqa: BLE001 - graphics never take the gallery down
            self.errors += 1

    def _scorebug(self) -> None:
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
            self.op.plan_score(state, territory, self.now(), self.delay(territory), home=d["home_short"],
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
