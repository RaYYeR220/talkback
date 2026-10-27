import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    (run / "events.jsonl").write_text("", encoding="utf-8")
    msgs = [{"kind": "run", "sim_t": 0, "wall": 1.0, "data": {"id": "r1", "status": "started"}},
            {"kind": "cue", "sim_t": 10, "wall": 1.1, "data": {"id": "Q-1", "text": "5 shots so far.", "evidence": []}}]
    (run / "broadcast-replay.jsonl").write_text("\n".join(json.dumps(m) for m in msgs), encoding="utf-8")
    import talkback.service.app as svc
    monkeypatch.setattr(svc, "gallery", svc.Gallery(run))
    with TestClient(svc.app) as c:
        yield c, svc


def test_health_and_state(client):
    c, _ = client
    assert c.get("/api/health").json()["ok"] is True
    assert "last" in c.get("/api/state").json()


def test_producer_seat_closed_outside_live(client):
    c, _ = client
    assert c.post("/api/holds/M-1", json={"decisions": {"Q-1": "approve"}}).status_code == 409
    assert c.get("/api/holds").json() == {"holds": []}


def test_replay_fills_the_ledger(client):
    c, svc = client
    import time
    for _ in range(40):
        if "Q-1" in svc.gallery.ledger:
            break
        time.sleep(0.05)
    r = c.get("/api/ledger/Q-1")
    assert r.status_code == 200 and r.json()["cue"]["text"] == "5 shots so far."
    assert c.get("/api/ledger/nope").status_code == 404


def test_frames_404_without_tracking(client):
    c, _ = client
    assert c.get("/api/frames/MD12-F01").status_code == 404


@pytest.mark.parametrize("speed", [0, 0.001, 500])
def test_live_speed_is_bounded(client, speed):
    c, svc = client
    assert c.post("/api/live", json={"speed": speed}).status_code == 422
    assert svc.gallery.mode != "live"


def test_generator_can_upload_an_existing_run_without_publishing(tmp_path, monkeypatch):
    from talkback.service import generator

    uploaded, published = [], []
    monkeypatch.setattr(generator, "upload_run", lambda d, r: uploaded.append((d, r)) or 3)
    monkeypatch.setattr(generator, "publish", lambda *a: published.append(a))
    generator.main(["--upload", str(tmp_path), "--run-id", "md-2026"])
    assert uploaded == [(tmp_path, "md-2026")] and published == []


def test_failed_live_start_leaves_the_replay_running(client, monkeypatch):
    c, svc = client
    monkeypatch.delenv("TALKBACK_LLM", raising=False)  # the scripted provider refuses to start without a script
    r = c.post("/api/live", json={"speed": 10})
    assert r.status_code == 503
    assert svc.gallery.mode != "live" and svc.gallery.live_started == []
    assert c.get("/api/health").json()["mode"] != "live"


def test_live_frames_win_over_the_recorded_run(client):
    from types import SimpleNamespace

    c, svc = client
    item = {"match_id": "MD12-F01", "t": 5_000, "ball": [1, 2, 0], "ids": ["P1"], "pos": [[1, 2]], "speed": [0]}
    svc.gallery.runner = SimpleNamespace(live_frames={"MD12-F01": item}, sim_t=5_000)
    try:
        assert c.get("/api/frames/MD12-F01?t=4000").json()["t"] == 5_000
    finally:
        svc.gallery.runner = None


def test_live_feed_ends_when_it_goes_quiet():
    import asyncio

    from talkback.service.app import drain

    async def go():
        q: asyncio.Queue = asyncio.Queue()
        q.put_nowait({"kind": "event"})
        return [item async for item in drain(q, idle_s=0.1)]

    assert asyncio.run(go()) == [{"kind": "event"}]


def test_cors_origins_come_from_the_environment(monkeypatch):
    from talkback.service.app import cors_origins

    monkeypatch.setenv("TALKBACK_CORS_ORIGINS", "https://web.example, https://other.example")
    assert cors_origins() == ["https://web.example", "https://other.example"]
    monkeypatch.delenv("TALKBACK_CORS_ORIGINS")
    assert cors_origins() == ["*"]


def test_broadcaster_catch_up_is_bounded_and_keeps_the_run_first():
    from talkback.gallery.bus import Broadcaster

    bc = Broadcaster()
    bc.publish("run", 0, {"id": "r1", "status": "started"})
    for i in range(1000):
        bc.publish("cue", i, {"id": f"Q-{i}"})
    msgs = list(bc.last.values())
    assert msgs[0]["kind"] == "run"
    cues = [m for m in msgs if m["kind"] == "cue"]
    assert len(cues) == Broadcaster.KEEP_PER_KIND and cues[-1]["data"]["id"] == "Q-999"
