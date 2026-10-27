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
