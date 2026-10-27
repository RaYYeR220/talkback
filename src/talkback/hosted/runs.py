"""One hosted agent serves every matchday run.

The gallery starts each remote prompt with a `Run: <run id>` line. RunScope
reads it for the duration of one agent run, and the tools look up that run's
world (and, for the Lab, its simulator backend) in a small cache. A missing
or malformed line means the default run.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from collections import OrderedDict
from contextvars import ContextVar
from typing import Callable, Generic, TypeVar

from agent_framework import AgentMiddleware

RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_RUN_LINE = re.compile(r"^Run: (\S+)$", re.M)
_current: ContextVar[str | None] = ContextVar("talkback_run", default=None)

T = TypeVar("T")
log = logging.getLogger(__name__)


def default_run() -> str:
    return os.environ.get("TALKBACK_RUN_ID", "md-2026")


def with_run(run_id: str | None, prompt: str) -> str:
    return f"Run: {run_id}\n{prompt}" if run_id else prompt


def run_of(messages) -> str:
    for message in reversed(list(messages)):
        m = _RUN_LINE.search(message.text or "")
        if m:
            return m.group(1) if RUN_ID.fullmatch(m.group(1)) else default_run()
    return default_run()


def current() -> str:
    return _current.get() or default_run()


class RunScope(AgentMiddleware):
    """Makes the prompt's run visible to the tools; `warm` loads it off the event loop first."""

    def __init__(self, warm: Callable[[str], object] | None = None):
        self.warm = warm

    async def process(self, context, call_next) -> None:
        run = run_of(context.messages)
        if self.warm is not None:
            await asyncio.to_thread(self.warm, run)
        token = _current.set(run)
        try:
            await call_next()
        finally:
            _current.reset(token)


class RunCache(Generic[T]):
    """The last few runs' loaded state, oldest evicted first."""

    def __init__(self, load: Callable[[str], T], size: int = 4):
        self.load = load
        self.size = size
        self._items: OrderedDict[str, T] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, run_id: str) -> T:
        with self._lock:
            if run_id in self._items:
                self._items.move_to_end(run_id)
                return self._items[run_id]
        value = self.load(run_id)
        with self._lock:
            self._items[run_id] = value
            self._items.move_to_end(run_id)
            while len(self._items) > self.size:
                self._items.popitem(last=False)
        return value


def prewarm(cache: RunCache, run_id: str) -> bool:
    """Load a run at start-up if possible. On the first deploy the agent's identity has no storage access
    yet, so a failure is logged and the run is loaded on the first request instead."""
    try:
        cache.get(run_id)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("could not preload run %s (%s: %s); loading it on first use", run_id, type(exc).__name__, exc)
        return False
