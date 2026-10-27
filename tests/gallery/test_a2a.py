import asyncio
import json
import socket
import threading
import time

import pytest
import uvicorn
from agent_framework import Agent

from talkback.gallery.llm import ScriptedClient
from talkback.gallery.remote import RemoteAgents


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(agent: Agent, name: str, port: int) -> uvicorn.Server:
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
    from a2a.server.tasks import InMemoryTaskStore
    from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
    from agent_framework.a2a import A2AExecutor
    from starlette.applications import Starlette

    url = f"http://127.0.0.1:{port}"
    card = AgentCard(name=name, description=name, version="1.0",
                     supported_interfaces=[AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version="1.0")],
                     capabilities=AgentCapabilities(streaming=False), default_input_modes=["text/plain"],
                     default_output_modes=["text/plain"],
                     skills=[AgentSkill(id="pick", name="pick", description="pick", tags=["test"])])
    handler = DefaultRequestHandler(agent_executor=A2AExecutor(agent), task_store=InMemoryTaskStore(), agent_card=card)
    app = Starlette(routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(handler, "/")])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return server


@pytest.fixture(scope="module")
def archivist_server():
    port = _free_port()
    agent = Agent(client=ScriptedClient(lambda m: json.dumps({"storylines": [{"storyline_id": "S-1", "why_now": "a2a"}]})),
                  instructions="archivist", name="archivist")
    server = _serve(agent, "archivist", port)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


def test_remote_archivist_answers_over_a2a(archivist_server):
    remote = RemoteAgents(archivist_url=archivist_server, lab_url=None)
    text = asyncio.run(remote.ask("archivist", "Story board:\n- S-1 [live] something"))
    assert json.loads(text)["storylines"][0]["why_now"] == "a2a"
    assert remote.enabled("archivist") and not remote.enabled("lab")


def test_dead_endpoint_raises_so_the_workflow_can_fall_back():
    remote = RemoteAgents(archivist_url=f"http://127.0.0.1:{_free_port()}", lab_url=None)
    with pytest.raises(Exception):
        asyncio.run(remote.ask("archivist", "hello"))


def test_hosted_agent_reuses_warm_sessions_over_responses():
    import httpx

    from talkback.gallery.remote import HostedAgent

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if "fail" in body["input"]:
            return httpx.Response(500, json={"error": {"message": "boom"}})
        sid = body.get("agent_session_id") or f"s{len(seen)}"
        return httpx.Response(200, json={"status": "completed", "agent_session_id": sid, "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": '{"storylines": []}'}]}]})

    agent = HostedAgent("https://x.services.ai.azure.com/agents/a/endpoint/protocols/openai/responses",
                        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def go():
        first = await agent.ask("Run: md-2026\nhello")
        second = await agent.ask("Run: md-2026\nagain")
        with pytest.raises(httpx.HTTPStatusError):
            await agent.ask("fail")
        return first, second

    first, second = asyncio.run(go())
    assert first == second == '{"storylines": []}'
    assert "agent_session_id" not in seen[0] and seen[1]["agent_session_id"] == "s1"
    assert seen[2]["agent_session_id"] == "s1"  # the warm session was lent out ...
    assert agent.idle == []  # ... and not returned after a failed call


def test_remote_agents_pick_the_protocol_from_the_url():
    r = RemoteAgents("https://x/agents/a/endpoint/protocols/openai/responses?api-version=v1", "http://127.0.0.1:9/a2a")
    assert r.via("archivist") == "hosted" and r.via("lab") == "a2a"
