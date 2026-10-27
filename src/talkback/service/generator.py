"""The matchday generator: the gallery's live data feed.

Generates a matchday, publishes the run directory (world, frames, engine
snapshots, sealed key) to the storage account for the hosted agents, then plays
the ten matches out in compressed real time onto Event Hubs — one partition
per match — as match events plus tracking at 2 Hz.

    python -m talkback.service.generator --seed 2026 --run-id md-2026 --speed 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

import numpy as np

FRAME_EVERY_MS = 500


def upload_run(run_dir: Path, run_id: str) -> int:
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    svc = BlobServiceClient(os.environ["STORAGE_ACCOUNT_URL"], credential=DefaultAzureCredential())
    c = svc.get_container_client(os.environ.get("TALKBACK_RUNS_CONTAINER", "runs"))
    n = 0
    for path in run_dir.rglob("*"):
        if path.is_file() and not path.name.startswith("broadcast"):
            with open(path, "rb") as fh:
                c.upload_blob(f"{run_id}/{path.relative_to(run_dir).as_posix()}", fh, overwrite=True)
            n += 1
    return n


def feed_items(run_dir: Path) -> list[tuple[int, str, dict]]:
    """(t, match_id, payload) for every event and every 2 Hz tracking frame, in match-time order."""
    items: list[tuple[int, str, dict]] = []
    with open(run_dir / "events.jsonl", encoding="utf-8") as fh:
        for line in fh:
            e = json.loads(line)
            items.append((e["t"], e["match_id"], {"kind": "event", "event": e}))
    for path in sorted(run_dir.glob("frames_*.npz")):
        mid = path.stem.removeprefix("frames_")
        with np.load(path, allow_pickle=False) as z:
            t, pos, speed, slot, players, ball = z["t"], z["pos"], z["speed"], z["slot"], z["players"], z["ball"]
            for i in range(0, len(t), FRAME_EVERY_MS // 100):
                keep = slot[i] >= 0
                items.append((int(t[i]), mid, {"kind": "frame", "match_id": mid, "t": int(t[i]),
                                               "ids": [str(players[s]) for s in slot[i][keep]],
                                               "pos": pos[i][keep].round(2).tolist(),
                                               "speed": speed[i][keep].astype(float).round(2).tolist(),
                                               "ball": ball[i].astype(float).round(2).tolist()}))
    items.sort(key=lambda x: (x[0], x[1]))
    return items


async def publish(run_dir: Path, run_id: str, speed: float) -> int:
    from azure.eventhub import EventData
    from azure.eventhub.aio import EventHubProducerClient
    from azure.identity.aio import DefaultAzureCredential

    cred = DefaultAzureCredential()
    producer = EventHubProducerClient(os.environ["EVENTHUB_FQDN"], os.environ.get("EVENTHUB_NAME", "matchday"), cred)
    items = feed_items(run_dir)
    sent = 0
    start = time.monotonic()
    async with producer:
        i = 0
        while i < len(items):
            now_ms = (time.monotonic() - start) * speed * 1000
            batch: dict[str, list] = {}
            while i < len(items) and items[i][0] <= now_ms:
                _, mid, payload = items[i]
                payload["run_id"] = run_id
                batch.setdefault(mid, []).append(payload)
                i += 1
            for mid, payloads in batch.items():
                eb = await producer.create_batch(partition_key=mid)
                for p in payloads:
                    try:
                        eb.add(EventData(json.dumps(p, separators=(",", ":"))))
                    except ValueError:
                        await producer.send_batch(eb)
                        eb = await producer.create_batch(partition_key=mid)
                        eb.add(EventData(json.dumps(p, separators=(",", ":"))))
                await producer.send_batch(eb)
                sent += len(payloads)
            await asyncio.sleep(0.05)
        end = await producer.create_batch()
        end.add(EventData(json.dumps({"kind": "end", "run_id": run_id})))
        await producer.send_batch(end)
    await cred.close()
    return sent


def main(argv: list[str] | None = None) -> None:
    from talkback.world.matchday import prepare_matchday, run_matchday_offline

    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", type=Path, default=None,
                    help="only upload an existing run directory (e.g. the replay run before the agents deploy)")
    ap.add_argument("--seed", type=int, default=int(os.environ.get("TALKBACK_SEED", "2026")))
    ap.add_argument("--run-id", default=os.environ.get("TALKBACK_RUN_ID"))
    ap.add_argument("--speed", type=float, default=float(os.environ.get("TALKBACK_LIVE_SPEED", "10")))
    ap.add_argument("--out", type=Path, default=Path(os.environ.get("TMPDIR", "/tmp")) / "talkback-gen")
    a = ap.parse_args(argv)
    if a.upload is not None:
        run_id = a.run_id or a.upload.name
        print(f"uploaded {upload_run(a.upload, run_id)} files of {run_id}", flush=True)
        return
    run_id = a.run_id or f"md-{a.seed}-{int(time.time())}"
    out = run_matchday_offline(prepare_matchday(a.seed), a.out / run_id)
    print(f"generated {run_id}; uploaded {upload_run(out, run_id)} files", flush=True)
    print(f"published {asyncio.run(publish(out, run_id, a.speed))} feed items", flush=True)


if __name__ == "__main__":
    main()
