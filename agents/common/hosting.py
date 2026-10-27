"""Serve one Talkback agent as a Foundry hosted agent or as a plain A2A v1.0 server.

TALKBACK_SERVE_MODE=responses (default)
    Foundry hosted agent: ResponsesHostServer on :8088. Foundry adds the A2A
    endpoint and card on top (agentEndpoint / agentCard in azure.yaml).
TALKBACK_SERVE_MODE=a2a
    Plan B, the agent as its own Container App: a2a-sdk JSON-RPC server on
    :$PORT with the card at /.well-known/agent-card.json.

The agent comes from ``talkback.hosted.<name>:build_agent()`` when the package
provides it. Until then a fallback agent with the spec's instructions and no
tools is served, so the endpoint, card and A2A wiring can be proven early.
"""

from __future__ import annotations

import importlib
import logging
import os
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("talkback.hosting")


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    description: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentSpec:
    name: str
    description: str
    skills: tuple[Skill, ...]
    fallback_instructions: str


def _model() -> str:
    model = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME") or os.environ.get("FOUNDRY_MODEL_STRONG")
    if not model:
        raise RuntimeError("AZURE_AI_MODEL_DEPLOYMENT_NAME is not set")
    # talkback.gallery.llm reads FOUNDRY_MODEL_*; hosted agents can't declare
    # FOUNDRY_* variables (reserved by the platform), so map them here.
    os.environ.setdefault("FOUNDRY_MODEL_STRONG", model)
    os.environ.setdefault("FOUNDRY_MODEL_FAST", os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME_FAST", model))
    os.environ.setdefault("TALKBACK_LLM", "foundry")
    return model


def build_agent(spec: AgentSpec) -> Any:
    model = _model()
    factory_module = f"talkback.hosted.{spec.name}"
    try:
        module = importlib.import_module(factory_module)
    except ModuleNotFoundError as exc:
        if exc.name not in ("talkback.hosted", factory_module):
            raise
        module = None
    if module is not None:
        log.info("serving %s from %s.build_agent()", spec.name, factory_module)
        return module.build_agent()

    log.warning("%s not found; serving the instruction-only fallback for %s", factory_module, spec.name)
    from agent_framework import Agent
    from agent_framework.foundry import FoundryChatClient
    from azure.identity import DefaultAzureCredential

    client = FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=model,
        credential=DefaultAzureCredential(),
    )
    return Agent(
        client=client,
        name=spec.name,
        description=spec.description,
        instructions=spec.fallback_instructions,
        # The hosting layer keeps conversation history.
        default_options={"store": False},
    )


def _serve_responses(agent: Any) -> None:
    from agent_framework_foundry_hosting import ResponsesHostServer

    ResponsesHostServer(agent).run()


def _serve_a2a(spec: AgentSpec, agent: Any) -> None:
    import uvicorn
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
    from a2a.server.tasks import InMemoryTaskStore
    from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
    from agent_framework.a2a import A2AExecutor
    from starlette.applications import Starlette

    port = int(os.environ.get("PORT", "8088"))
    url = os.environ.get("A2A_PUBLIC_URL", f"http://localhost:{port}")
    card = AgentCard(
        name=spec.name,
        description=spec.description,
        version="1.0",
        supported_interfaces=[AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(id=s.id, name=s.name, description=s.description, tags=list(s.tags))
            for s in spec.skills
        ],
    )
    handler = DefaultRequestHandler(
        agent_executor=A2AExecutor(agent),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    app = Starlette(routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(handler, "/")])
    uvicorn.run(app, host="0.0.0.0", port=port)


def run(spec: AgentSpec) -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
    agent = build_agent(spec)
    mode = os.environ.get("TALKBACK_SERVE_MODE", "responses").lower()
    if mode == "a2a":
        _serve_a2a(spec, agent)
    elif mode == "responses":
        _serve_responses(agent)
    else:
        raise RuntimeError(f"unknown TALKBACK_SERVE_MODE={mode!r}")
