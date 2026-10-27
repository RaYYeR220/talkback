"""Where a hosted agent finds the matchday it is working on.

Locally that is TALKBACK_RUN_DIR. In Azure the generator publishes the run to
the storage account (container `runs`, prefix = run id); the agent pulls what it
needs on first use with its own managed identity.
"""

from __future__ import annotations

import os
from pathlib import Path

from talkback.gallery.snapshots import SnapshotStore


def run_dir(run_id: str | None = None) -> Path:
    """The run's directory: TALKBACK_RUN_DIR or a sibling of it, else downloaded from the storage account."""
    from talkback.hosted.runs import RUN_ID

    if run_id is not None and not RUN_ID.fullmatch(run_id):
        raise ValueError(f"not a run id: {run_id!r}")
    local = Path(os.environ.get("TALKBACK_RUN_DIR", "runs/md-2026"))
    if run_id is not None and run_id != local.name:
        local = local.parent / run_id
    if (local / "world.json").exists():
        return local
    account = os.environ.get("STORAGE_ACCOUNT_URL")
    prefix = run_id or os.environ.get("TALKBACK_RUN_ID", "md-2026")
    if not account:
        raise RuntimeError("no run directory and no STORAGE_ACCOUNT_URL to fetch one from")
    target = Path(os.environ.get("TMPDIR", "/tmp")) / "talkback-run" / prefix
    _download(account, prefix, target, ("world.json", "events.jsonl"))
    return target


def _container():
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    svc = BlobServiceClient(os.environ["STORAGE_ACCOUNT_URL"], credential=DefaultAzureCredential())
    return svc.get_container_client(os.environ.get("TALKBACK_RUNS_CONTAINER", "runs"))


def _download(account: str, prefix: str, target: Path, names: tuple[str, ...]) -> None:
    target.mkdir(parents=True, exist_ok=True)
    c = _container()
    for name in names:
        path = target / name
        if not path.exists():
            with open(path, "wb") as fh:
                fh.write(c.download_blob(f"{prefix}/{name}").readall())


class BlobSnapshotStore(SnapshotStore):
    """Snapshot store that fills its local cache from the storage account per match."""

    def __init__(self, root: Path, prefix: str):
        super().__init__(root)
        self.prefix = prefix
        self._synced: set[str] = set()

    def times(self, match_id: str) -> list[int]:
        if match_id not in self._synced and not super().times(match_id):
            d = self._dir(match_id)
            d.mkdir(parents=True, exist_ok=True)
            c = _container()
            for blob in c.list_blobs(name_starts_with=f"{self.prefix}/snapshots/{match_id}/"):
                with open(d / Path(blob.name).name, "wb") as fh:
                    fh.write(c.download_blob(blob.name).readall())
            self._synced.add(match_id)
        return super().times(match_id)


def snapshot_store(root: Path, run_id: str | None = None) -> SnapshotStore:
    # With a storage account the Blob store is used even when some matches are cached: it reads the
    # local copy first and fetches only the matches that are missing.
    if not os.environ.get("STORAGE_ACCOUNT_URL"):
        return SnapshotStore(root / "snapshots")
    return BlobSnapshotStore(root / "snapshots", run_id or os.environ.get("TALKBACK_RUN_ID", "md-2026"))
