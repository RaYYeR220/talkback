import asyncio
import json

import httpx

from talkback.ograf.graphics_op import GraphicsOp, OGrafClient
from talkback.ograf.server import OGrafServer, create_app
from talkback.schemas.models import MatchState, Verdict
from tests.ograf.support import InProcessPage, assert_valid, make_cue, make_fact, path_template

NOW = 60_000


def checked_client(app, checked: list[str]) -> httpx.AsyncClient:
    """An ASGI client that checks every request and response body against server-api.yaml."""

    async def on_request(request: httpx.Request) -> None:
        if request.content:
            assert_valid(json.loads(request.content), path_template(request.url.path), request.method.lower())

    async def on_response(response: httpx.Response) -> None:
        await response.aread()
        req = response.request
        assert_valid(response.json(), path_template(req.url.path), req.method.lower(), response.status_code)
        checked.append(f"{req.method} {path_template(req.url.path)} {response.status_code}")

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ograf",
                             event_hooks={"request": [on_request], "response": [on_response]})


def test_graphics_op_drives_a_renderer_through_the_server_api():
    async def scenario():
        server = OGrafServer(timeout_s=2.0)
        page = await InProcessPage(server, "uk").start()
        checked: list[str] = []
        async with checked_client(create_app(server), checked) as http:
            client = OGrafClient(http)
            assert (await client.info())["name"]
            op = GraphicsOp()
            state = MatchState(match_id="F01", t=63 * 60_000, period=2, home_goals=0, away_goals=0, game_state_hash="h")
            op.plan_score(state, "uk", NOW, delay_ms=1_000, home="CAL", away="ASH")
            op.plan(make_cue("stat_card", created_t=NOW), "uk", NOW, delay_ms=1_000, evidence=[make_fact()])

            first = await op.tick(NOW + 500, client)
            assert [(a.action.graphic_id, a.action.action) for a in first] == [("talkback-stat-card", "load")]
            second = await op.tick(NOW + 1_000, client)
            assert [(a.action.graphic_id, a.action.action) for a in second] == [
                ("talkback-scorebug", "load"), ("talkback-scorebug", "play"), ("talkback-stat-card", "play")]
            assert all(a.ok for a in first + second), [a.detail for a in first + second]
            assert second[2].detail["currentStep"] == 0

            card = await client.target("uk", {"layer": 40})
            assert [g["graphic"]["id"] for g in card["graphicInstances"]] == ["talkback-stat-card"]
            goal = state.model_copy(update={"home_goals": 1})
            op.plan_score(goal, "uk", NOW + 4_000, delay_ms=1_000, home="CAL", away="ASH")
            assert [a.ok for a in await op.tick(NOW + 5_000, client)] == [True]

            done = await op.tick(NOW + 9_000, client)
            assert [(a.action.action, a.ok) for a in done] == [("stop", True)]
            assert (await client.target("uk", {"layer": 40}))["graphicInstances"] == []
            bug = await client.target("uk", {"layer": 10})
            assert [g["graphic"]["id"] for g in bug["graphicInstances"]] == ["talkback-scorebug"]

        sent = [m for m in page.methods() if m != "hello"]
        assert sent == ["load", "load", "playAction", "playAction", "updateAction", "stopAction", "clear"]
        update = next(m for m in page.seen if m["method"] == "updateAction")
        assert update["params"]["params"]["data"] == {"homeScore": 1}
        assert "PUT /renderers/{rendererId}/target/graphicInstance/clear 200" in checked
        assert len(checked) >= 10

    asyncio.run(scenario())


def test_preemption_round_trip_and_offline_outputs():
    async def scenario():
        server = OGrafServer()
        page = await InProcessPage(server, "uk").start()
        async with checked_client(create_app(server), []) as http:
            client = OGrafClient(http)
            op = GraphicsOp()
            both = {"uk": Verdict.ON_AIR, "kids": Verdict.ON_AIR}
            op.plan(make_cue("lower_third", cue_id="S", verdicts=both), "uk", NOW)
            op.plan(make_cue("lower_third", cue_id="S", verdicts=both), "kids", NOW)
            await op.tick(NOW, client)
            op.plan(make_cue("story_card", cue_id="T", created_t=NOW + 2_000), "uk", NOW + 2_000)
            applied = await op.tick(NOW + 2_000, client)
            assert [(a.action.cue_id, a.action.action) for a in applied] == [("S", "stop"), ("T", "load"), ("T", "play")]
            assert all(a.ok for a in applied)
            lower = await client.target("uk", {"layer": 30})
            assert [g["graphic"]["id"] for g in lower["graphicInstances"]] == ["talkback-story-card"]
            kids = await client.target("kids", {"layer": 30})
            assert [g["graphic"]["id"] for g in kids["graphicInstances"]] == ["talkback-lower-third"], \
                "an output with no page connected still tracks what is on air"
            assert (await client.renderer("kids"))["renderer"]["status"]["status"] == "WARNING"
        assert page.methods().count("load") == 2

    asyncio.run(scenario())


def test_failed_calls_are_reported_not_raised():
    async def scenario():
        async with checked_client(create_app(OGrafServer()), []) as http:
            op = GraphicsOp(outputs={"uk": "nowhere"})
            op.plan(make_cue(), "uk", NOW)
            applied = await op.tick(NOW + 60_000, OGrafClient(http))
            assert [(a.action.action, a.ok) for a in applied] == [("load", False), ("play", True), ("stop", True)]
            assert "404" in applied[0].detail["error"]
            assert applied[1].detail == {"skipped": "graphic instance not loaded"}

    asyncio.run(scenario())
