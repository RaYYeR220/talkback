"""Event sources and the broadcaster.

An EventSource yields the matchday's events (and tracking frames) in match-time
order. FileSource replays a generated run directory; the Event Hubs source
reads the same JSON events from the live bus. The Broadcaster fans every
gallery message out to subscribers (the SSE stream) and records it.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Protocol

import numpy as np

from talkback.schemas.models import Event


class EventSource(Protocol):
    def events(self) -> Iterator[Event]: ...

    def frame_at(self, match_id: str, t: int) -> dict | None: ...


class FileSource:
    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self._frames: dict[str, dict[str, np.ndarray]] = {}

    def events(self) -> Iterator[Event]:
        with open(self.run_dir / "events.jsonl", encoding="utf-8") as fh:
            for line in fh:
                yield Event.model_validate_json(line)

    def _load(self, match_id: str) -> dict[str, np.ndarray] | None:
        if match_id not in self._frames:
            p = self.run_dir / f"frames_{match_id}.npz"
            if not p.exists():
                return None
            with np.load(p, allow_pickle=False) as z:
                self._frames[match_id] = {k: z[k] for k in z.files}
        return self._frames[match_id]

    def frame_at(self, match_id: str, t: int) -> dict | None:
        f = self._load(match_id)
        if f is None:
            return None
        i = int(np.searchsorted(f["t"], t, side="right") - 1)
        if i < 0:
            return None
        slots = f["slot"][i]
        keep = slots >= 0
        players = f["players"]
        pos = f["pos"][i][keep].astype(float)
        return {"match_id": match_id, "t": int(f["t"][i]), "ball": f["ball"][i].astype(float).round(2).tolist(),
                "ids": [str(players[s]) for s in slots[keep]], "pos": pos.round(2).tolist()}

    def tracking(self, match_id: str):
        """(t, pos, speed, ids) per tick, for the Stats Desk."""
        f = self._load(match_id)
        if f is None:
            return None
        return f


class Broadcaster:
    # What a new subscriber is sent to catch up: the latest message per key, at most this many of each kind.
    KEEP_PER_KIND = 300

    def __init__(self, record_path: Path | None = None):
        self._subs: set[asyncio.Queue] = set()
        self._fh = open(record_path, "a", encoding="utf-8", newline="\n") if record_path else None
        self.last: dict[str, dict] = {}
        self._keys: dict[str, deque[str]] = {}

    def publish(self, kind: str, sim_t: int, data: dict, record: bool = True) -> None:
        msg = {"kind": kind, "sim_t": sim_t, "wall": round(time.time(), 3), "data": data}
        key = f"{kind}:{data.get('id') or data.get('match_id') or kind}"
        if key not in self.last:
            keys = self._keys.setdefault(kind, deque())
            keys.append(key)
            while len(keys) > self.KEEP_PER_KIND:
                self.last.pop(keys.popleft(), None)
        self.last[key] = msg
        for q in list(self._subs):
            if q.qsize() < 5000:
                q.put_nowait(msg)
        if record and self._fh:
            self._fh.write(json.dumps(msg, separators=(",", ":"), default=str) + "\n")
            self._fh.flush()

    def reset(self) -> None:
        """Forget the catch-up state (a new run starts)."""
        self.last.clear()
        self._keys.clear()

    async def subscribe(self) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.add(q)
        try:
            for msg in list(self.last.values()):
                q.put_nowait(msg)
            while True:
                yield await q.get()
        finally:
            self._subs.discard(q)

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


class EventHubsSource:
    """The live feed: match events and tracking frames for one run from Event Hubs (all partitions)."""

    def __init__(self, run_id: str):
        import os

        self.run_id = run_id
        self.fqdn = os.environ["EVENTHUB_FQDN"]
        self.hub = os.environ.get("EVENTHUB_NAME", "matchday")
        self.group = os.environ.get("EVENTHUB_CONSUMER_GROUP", "$Default")

    async def items(self) -> AsyncIterator[dict]:
        from azure.eventhub.aio import EventHubConsumerClient
        from azure.identity.aio import DefaultAzureCredential

        cred = DefaultAzureCredential()
        client = EventHubConsumerClient(self.fqdn, self.group, self.hub, credential=cred)
        queue: asyncio.Queue = asyncio.Queue()

        async def on_event(partition_context, event):
            if event is None:
                return
            body = json.loads(event.body_as_str())
            if body.get("run_id") == self.run_id:
                await queue.put(body)

        task = asyncio.create_task(client.receive(on_event=on_event, starting_position="@latest"))
        try:
            while True:
                item = await queue.get()
                yield item
                if item.get("kind") == "end":
                    break
        finally:
            task.cancel()
            await client.close()
            await cred.close()
