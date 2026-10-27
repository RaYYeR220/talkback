"""Engine snapshots for the Lab.

The generator stores a snapshot every 30 s of match time. To experiment on a
moment, the Lab restores the nearest earlier snapshot and replays the engine
forward with its original random state, so it reaches the exact recorded
moment before applying any change.

Snapshots are pickles of our own engine state. They are written and read only by
our own services (the local run directory or the private storage container) and
are never accepted from users or other systems.
"""

from __future__ import annotations

import gzip
import pickle
from functools import partial
from pathlib import Path

from talkback.sim.engine import EngineState, MatchEngine
from talkback.world.league import Club

SNAPSHOT_EVERY_MS = 30_000


class SnapshotStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _dir(self, match_id: str) -> Path:
        return self.root / match_id

    def save(self, match_id: str, state: EngineState) -> Path:
        d = self._dir(match_id)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{state.t:09d}.pkl.gz"
        with gzip.open(path, "wb", compresslevel=3) as fh:
            pickle.dump(state, fh, protocol=pickle.HIGHEST_PROTOCOL)
        return path

    def times(self, match_id: str) -> list[int]:
        d = self._dir(match_id)
        return sorted(int(p.name.split(".")[0]) for p in d.glob("*.pkl.gz")) if d.exists() else []

    def load(self, match_id: str, t: int) -> EngineState:
        with gzip.open(self._dir(match_id) / f"{t:09d}.pkl.gz", "rb") as fh:
            return pickle.load(fh)

    def state_at(self, match_id: str, t: int, home: Club, away: Club) -> EngineState | None:
        """The engine state at match time `t` (ms), replayed from the nearest earlier snapshot."""
        earlier = [x for x in self.times(match_id) if x <= t]
        if not earlier:
            return None
        eng = engine_factory(match_id, home, away)()
        eng.restore(self.load(match_id, earlier[-1]))
        while eng.t < t and not eng.done:
            eng.step()
        return eng.snapshot()


def engine_factory(match_id: str, home: Club, away: Club):
    """A picklable factory for a blank engine of this fixture (its state is always restored)."""
    return partial(MatchEngine, match_id, home, away, 0)
