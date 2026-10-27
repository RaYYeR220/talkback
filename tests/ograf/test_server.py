import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from talkback.ograf import layout
from talkback.ograf.graphics_op import OGrafClient
from talkback.ograf.layout import OUTPUTS, control_token
from talkback.ograf.server import END_STEP, MAX_MISSES, OFFLINE, OGrafServer, create_app, target_step
from talkback.ograf.spec import component_validator
from tests.ograf.support import FakePage, assert_valid

LOAD = "/renderers/{rendererId}/target/graphicInstance/load"
UPDATE = "/renderers/{rendererId}/target/graphicInstance/updateAction"
PLAY = "/renderers/{rendererId}/target/graphicInstance/playAction"
STOP = "/renderers/{rendererId}/target/graphicInstance/stopAction"
CLEAR = "/renderers/{rendererId}/target/graphicInstance/clear"
CUSTOM = "/renderers/{rendererId}/target/graphicInstance/customActions/{customActionId}"
CARD = {"layer": 40}


@pytest.fixture
def server():
    return OGrafServer(timeout_s=2.0)


def auth(server):
    return {"Authorization": f"Bearer {server.token}"}


@pytest.fixture
def client(server):
    with TestClient(create_app(server), headers=auth(server)) as c:
        yield c


def call(client, method, template, body=None, status=200, **path):
    """Send a spec-shaped request and check the response against server-api.yaml."""
    url = "/ograf/v1" + template.format(**{"rendererId": "uk", **path})
    if body is not None:
        assert_valid(body, template, method)
    r = client.request(method.upper(), url, json=body)
    assert r.status_code == status, r.text
    if status == 400:
        _problem(r.json(), 400)
    else:
        assert_valid(r.json(), template, method, status)
    return r.json()


def _problem(body, status):
    assert [e.message for e in component_validator("ErrorResponse").iter_errors(body)] == []
    assert body["status"] == status and body["title"]


def load_body(graphic="talkback-stat-card", target=CARD, **data):
    return {"renderTarget": target, "graphicId": graphic, "params": {"data": {"label": "Pressures", "value": "14", **data}}}


def targeted(iid, target=CARD, **params):
    return {"renderTarget": target, "graphicInstanceId": iid, "params": params}


def test_target_step_follows_the_spec_table():
    rows = [(None, 1, None, None, 0), (None, 1, 0, None, 0), (None, 1, None, 1, 0), (None, 2, 1, 2, 1),
            (0, 2, 1, None, 1), (0, 3, None, 2, 2), (2, 3, 1, None, 1), (2, 3, None, -2, 0), (0, 1, None, 1, None)]
    for current, count, goto, delta, expected in rows:
        assert target_step(current, count, goto, delta) == expected
    assert target_step(None, 0) is None
    assert target_step(7, -1, delta=1) == 8


def test_info_and_listings_follow_the_schema(client):
    info = call(client, "get", "/")
    assert info["name"]
    assert client.get("/ograf/v1").json() == info
    graphics = call(client, "get", "/graphics")["graphics"]
    assert {g["id"] for g in graphics} >= {"talkback-scorebug", "talkback-ifb", "talkback-stat-card"}
    one = call(client, "get", "/graphics/{graphicId}", graphicId="talkback-scorebug")
    assert one["graphic"]["id"] == one["manifest"]["id"] == "talkback-scorebug"
    renderers = call(client, "get", "/renderers")["renderers"]
    assert [r["id"] for r in renderers] == list(OUTPUTS)
    for rid in OUTPUTS:
        info = call(client, "get", "/renderers/{rendererId}", rendererId=rid)["renderer"]
        assert info["status"] == {"status": "WARNING", "message": OFFLINE}
        assert [t["renderTarget"]["layer"] for t in info["renderTargets"]] == [10, 20, 30, 40, 50]
        assert info["renderCharacteristics"]["resolution"] == {"width": 1920, "height": 1080}


def test_unknown_things_are_404_problems(client):
    call(client, "get", "/graphics/{graphicId}", status=404, graphicId="nope")
    call(client, "get", "/renderers/{rendererId}", status=404, rendererId="nope")
    r = client.get("/ograf/v1/renderers/uk/target", params={"renderTarget": json.dumps({"layer": 99})})
    assert r.status_code == 404
    _problem(r.json(), 404)
    call(client, "post", LOAD, load_body(graphic="nope"), status=404)
    call(client, "post", LOAD, load_body(target={"layer": 11}), status=404)
    call(client, "post", PLAY, targeted("gi-missing"), status=404)


def test_bad_requests_are_400_problems(client):
    r = client.post("/ograf/v1/renderers/uk/target/graphicInstance/load", content=b"{not json",
                    headers={"content-type": "application/json"})
    assert r.status_code == 400
    _problem(r.json(), 400)
    r = client.post("/ograf/v1/renderers/uk/target/graphicInstance/load", json={"renderTarget": CARD, "graphicId": "x"})
    assert r.status_code == 400 and "params" in r.json()["detail"]
    r = client.get("/ograf/v1/renderers/uk/target", params={"renderTarget": "layer=40"})
    assert r.status_code == 400
    r = client.get("/ograf/v1/renderers/uk/target")
    assert r.status_code == 400
    _problem(r.json(), 400)


def test_full_lifecycle_through_a_renderer_page(client):
    with client.websocket_connect("/ograf/ws/uk") as ws:
        page = FakePage(ws)
        assert page.wait_for(1)[0]["method"] == "hello"
        status = call(client, "get", "/renderers/{rendererId}")["renderer"]["status"]
        assert status == {"status": "OK", "message": "1 page(s) connected"}

        body = load_body()
        body["params"]["v_trace"] = "abc"
        res = call(client, "post", LOAD, body)
        iid = res["graphicInstanceId"]
        assert res["statusCode"] == 200
        msg = page.seen[-1]
        assert msg["method"] == "load" and msg["params"]["graphicInstanceId"] == iid
        assert msg["params"]["graphic"] == {"id": "talkback-stat-card",
                                           "main": "/ograf/graphics/talkback-stat-card/graphic.mjs"}
        params = msg["params"]["params"]
        assert params["renderType"] == "realtime" and params["renderCharacteristics"]["frameRate"] == 50
        assert params["data"]["value"] == "14" and params["v_trace"] == "abc"
        assert client.get("/ograf/graphics/talkback-stat-card/graphic.mjs").headers["content-type"].startswith("text/javascript")

        res = call(client, "post", PLAY, targeted(iid))
        assert res == {"statusCode": 200, "currentStep": 0, "graphicInstanceId": iid}
        res = call(client, "post", UPDATE, targeted(iid, data={"value": "15"}, skipAnimation=True))
        assert res["statusCode"] == 200
        assert page.seen[-1]["params"] == {"graphicInstanceId": iid, "params": {"data": {"value": "15"}, "skipAnimation": True}}
        custom = call(client, "post", CUSTOM, targeted(iid, payload={"side": "home"}), customActionId="flash")
        assert custom["statusCode"] == 200 and page.seen[-1]["params"]["params"]["id"] == "flash"

        info = client.get("/ograf/v1/renderers/uk/target", params={"renderTarget": json.dumps(CARD)})
        assert_valid(info.json(), "/renderers/{rendererId}/target", "get", 200)
        assert [g["graphicInstanceId"] for g in info.json()["graphicInstances"]] == [iid]

        call(client, "post", STOP, targeted(iid))
        res = call(client, "put", CLEAR, {"filters": [{"graphicInstanceId": iid}]})
        assert res == {"graphicInstances": [{"renderTarget": CARD, "graphicInstanceId": iid}]}
        assert page.seen[-1]["method"] == "clear" and page.seen[-1]["params"] == {"graphicInstanceIds": [iid]}
        assert page.methods()[1:] == ["load", "playAction", "updateAction", "customAction", "stopAction", "clear"]
        assert client.get("/ograf/v1/renderers/uk/target", params={"renderTarget": json.dumps(CARD)}).json()["graphicInstances"] == []


def test_play_to_the_end_reports_the_end_step(client, server):
    iid = call(client, "post", LOAD, load_body())["graphicInstanceId"]
    assert call(client, "post", PLAY, targeted(iid))["currentStep"] == 0
    assert call(client, "post", PLAY, targeted(iid))["currentStep"] == END_STEP
    assert server.renderers["uk"].instances[iid].step is None


def test_graphic_errors_are_550(client):
    with client.websocket_connect("/ograf/ws/uk") as ws:
        page = FakePage(ws, fail={"playAction", "load"})
        page.wait_for(1)
        body = call(client, "post", LOAD, load_body(), status=550)
        assert "load() threw" in body["detail"]
        assert call(client, "get", "/renderers/{rendererId}")["renderer"]["renderTargets"][3]["graphicInstances"] == []
        page.fail = {"playAction"}
        iid = call(client, "post", LOAD, load_body())["graphicInstanceId"]
        assert "blew up" in call(client, "post", PLAY, targeted(iid), status=550)["detail"]


def test_silent_page_times_out_as_500_until_it_is_dropped(server):
    server.timeout_s = 0.2
    with TestClient(create_app(server), headers=auth(server)) as client, client.websocket_connect("/ograf/ws/uk") as ws:
        FakePage(ws, silent=True)
        for _ in range(MAX_MISSES):
            body = call(client, "post", LOAD, load_body(), status=500)
            assert body["title"] == "Renderer Timeout"
        assert call(client, "post", LOAD, load_body())["statusMessage"] == OFFLINE


def test_a_silent_page_does_not_stall_the_pages_that_answer(server):
    server.timeout_s = 0.5
    with (TestClient(create_app(server), headers=auth(server)) as client,
          client.websocket_connect("/ograf/ws/uk") as good_ws, client.websocket_connect("/ograf/ws/uk") as bad_ws):
        good, bad = FakePage(good_ws), FakePage(bad_ws, silent=True)
        good.wait_for(1), bad.wait_for(1)
        for _ in range(MAX_MISSES):
            started = time.monotonic()
            assert call(client, "post", LOAD, load_body())["statusCode"] == 200
            assert time.monotonic() - started < 0.4, "the first answer is enough"
        end = time.monotonic() + 3
        while len(server.renderers["uk"].pages) > 1 and time.monotonic() < end:
            time.sleep(0.02)
        assert server.renderers["uk"].pages and len(server.renderers["uk"].pages) == 1, "the silent page is dropped"
        assert call(client, "post", LOAD, load_body())["statusCode"] == 200


def test_offline_renderer_keeps_state_and_replays_it_to_a_late_page(client):
    iid = call(client, "post", LOAD, load_body(graphic="talkback-scorebug", target={"layer": 10}, homeScore=0))["graphicInstanceId"]
    res = call(client, "post", PLAY, targeted(iid, target={"layer": 10}))
    assert res["statusMessage"] == OFFLINE and res["currentStep"] == 0
    call(client, "post", UPDATE, targeted(iid, target={"layer": 10}, data={"homeScore": 1}))
    other = call(client, "post", LOAD, load_body())["graphicInstanceId"]

    with client.websocket_connect("/ograf/ws/uk") as ws:
        seen = FakePage(ws).wait_for(4)
    assert [m["method"] for m in seen] == ["hello", "load", "playAction", "load"]
    assert all("id" not in m for m in seen), "replay is sent as notifications"
    bug, play, card = seen[1]["params"], seen[2]["params"], seen[3]["params"]
    assert bug["graphicInstanceId"] == iid and bug["params"]["data"]["homeScore"] == 1
    assert bug["params"]["data"]["label"] == "Pressures", "load data is kept and updates merged into it"
    assert play == {"graphicInstanceId": iid, "params": {"goto": 0, "skipAnimation": True}}
    assert card["graphicInstanceId"] == other


def test_a_renderer_holds_a_bounded_number_of_instances(server, client):
    server.max_instances = 3
    with client.websocket_connect("/ograf/ws/uk") as ws:
        page = FakePage(ws)
        page.wait_for(1)
        ids = [call(client, "post", LOAD, load_body())["graphicInstanceId"] for _ in range(5)]
        assert list(server.renderers["uk"].instances) == ids[2:]
        cleared = [i for m in page.wait_for(8) if m["method"] == "clear" for i in m["params"]["graphicInstanceIds"]]
        assert cleared == ids[:2], "the oldest go first, from the page as well"


def test_two_pages_on_one_renderer_both_get_commands(client):
    with client.websocket_connect("/ograf/ws/world") as a, client.websocket_connect("/ograf/ws/world") as b:
        pa, pb = FakePage(a), FakePage(b)
        pa.wait_for(1), pb.wait_for(1)
        call(client, "post", LOAD, load_body(), rendererId="world")
        assert pa.wait_for(2)[-1]["method"] == pb.wait_for(2)[-1]["method"] == "load"
        assert call(client, "get", "/renderers/{rendererId}", rendererId="world")["renderer"]["status"]["status"] == "OK"


def test_clear_filters(client):
    a = call(client, "post", LOAD, load_body())["graphicInstanceId"]
    b = call(client, "post", LOAD, load_body(graphic="talkback-lower-third", target={"layer": 30}))["graphicInstanceId"]
    c = call(client, "post", LOAD, load_body(graphic="talkback-story-card", target={"layer": 30}))["graphicInstanceId"]
    res = call(client, "put", CLEAR, {"filters": [{"renderTarget": {"layer": 30}, "graphicId": "talkback-story-card"}]})
    assert [g["graphicInstanceId"] for g in res["graphicInstances"]] == [c]
    res = call(client, "put", CLEAR, {"filters": [{"renderTarget": {"layer": 40}}, {"graphicInstanceId": b}]})
    assert sorted(g["graphicInstanceId"] for g in res["graphicInstances"]) == sorted([a, b])
    call(client, "post", LOAD, load_body())
    assert len(call(client, "put", CLEAR, {"filters": []})["graphicInstances"]) == 1


def test_renderer_custom_action(client):
    with client.websocket_connect("/ograf/ws/kids") as ws:
        page = FakePage(ws)
        page.wait_for(1)
        res = call(client, "post", "/renderers/{rendererId}/customActions/{customActionId}", {"payload": {}},
                   rendererId="kids", customActionId="identify")
        assert res["result"]["pages"] == 1
        assert page.seen[-1]["method"] == "rendererAction"
    call(client, "post", "/renderers/{rendererId}/customActions/{customActionId}", {"payload": {}}, status=404,
         rendererId="kids", customActionId="self-destruct")


def test_unknown_renderer_socket_is_refused(client):
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ograf/ws/nope") as ws:
        ws.receive_json()


def test_static_files_and_cors(client):
    page = client.get("/ograf/renderer/")
    assert page.status_code == 200 and "renderer.mjs" in page.text
    assert client.get("/ograf/renderer/renderer.mjs").headers["content-type"].startswith("text/javascript")
    r = client.get("/ograf/v1/graphics", headers={"Origin": "http://controller.example"})
    assert r.headers["access-control-allow-origin"] == "*"


MUTATIONS = [("post", LOAD), ("post", UPDATE), ("post", PLAY), ("post", STOP), ("put", CLEAR), ("post", CUSTOM),
             ("post", "/renderers/{rendererId}/customActions/{customActionId}")]


@pytest.mark.parametrize(("method", "template"), MUTATIONS)
def test_changing_graphics_needs_the_control_token(server, method, template):
    url = "/ograf/v1" + template.format(rendererId="kids", customActionId="identify")
    with TestClient(create_app(server)) as anon:
        r = anon.request(method.upper(), url, json={})
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
        _problem(r.json(), 401)
        r = anon.request(method.upper(), url, json={}, headers={"Authorization": "Bearer not-the-token"})
        assert r.status_code == 403
        _problem(r.json(), 403)
        r = anon.request(method.upper(), url, json={}, headers=auth(server))
        assert r.status_code == 400, "past the token check, only the empty body is wrong"


def test_with_the_token_graphics_go_on_air(server):
    with TestClient(create_app(server)) as anon:
        url = "/ograf/v1" + LOAD.format(rendererId="presenter")
        assert anon.post(url, json=load_body()).status_code == 401
        assert server.renderers["presenter"].instances == {}
        assert anon.post(url, json=load_body(), headers=auth(server)).status_code == 200
        assert len(server.renderers["presenter"].instances) == 1


def test_reading_and_rendering_stay_public(server):
    with TestClient(create_app(server)) as anon:
        assert anon.get("/ograf/v1").status_code == anon.get("/ograf/v1/graphics").status_code == 200
        assert anon.get("/ograf/v1/renderers/presenter").status_code == 200
        r = anon.get("/ograf/v1/renderers/kids/target", params={"renderTarget": json.dumps(CARD)})
        assert r.status_code == 200
        assert anon.get("/ograf/renderer/").status_code == 200
        with anon.websocket_connect("/ograf/ws/kids") as ws:
            assert ws.receive_json()["method"] == "hello"


def test_the_control_token_comes_from_the_environment_or_is_made_once_per_process(monkeypatch):
    monkeypatch.setattr(layout, "_TOKEN", None)
    monkeypatch.setenv("TALKBACK_OGRAF_TOKEN", "from-the-env")
    assert control_token() == OGrafServer().token == OGrafClient(None).token == "from-the-env"
    monkeypatch.setattr(layout, "_TOKEN", None)
    monkeypatch.delenv("TALKBACK_OGRAF_TOKEN")
    made = control_token()
    assert len(made) >= 32 and control_token() == made == OGrafServer().token == OGrafClient(None).token
