"""Calling the Archivist and the Lab over A2A v1.0.

In Azure both run as Foundry hosted agents: the agent card is resolved from
the hosted endpoint, every request carries an Entra token for the Foundry
audience and the `A2A-Version: 1.0` header. Locally (or in Plan B) they are
plain A2A servers with the card at the well-known path.
"""

from __future__ import annotations

import os

import httpx
from agent_framework.a2a import A2AAgent

FOUNDRY_SCOPE = "https://ai.azure.com/.default"


class _EntraAuth(httpx.Auth):
    def __init__(self):
        from azure.identity.aio import DefaultAzureCredential

        self.cred = DefaultAzureCredential()

    async def async_auth_flow(self, request):
        token = await self.cred.get_token(FOUNDRY_SCOPE)
        request.headers["Authorization"] = f"Bearer {token.token}"
        yield request


def _needs_entra(url: str) -> bool:
    return ".ai.azure.com" in url or ".services.ai.azure.com" in url or os.environ.get("A2A_ENTRA") == "1"


async def connect(url: str, card_path: str | None = None, timeout: float = 90.0) -> A2AAgent:
    """An A2A client for the agent at `url`, with its card already resolved."""
    from a2a.client import A2ACardResolver

    http = httpx.AsyncClient(headers={"A2A-Version": "1.0"}, timeout=timeout,
                             auth=_EntraAuth() if _needs_entra(url) else None)
    path = card_path or os.environ.get("A2A_AGENT_CARD_PATH") or "/.well-known/agent-card.json"
    card = await A2ACardResolver(http, url, agent_card_path=path).get_agent_card()
    return A2AAgent(agent_card=card, url=url, http_client=http, timeout=timeout)


class HostedAgent:
    """A Foundry hosted agent called on its Responses endpoint.

    Foundry's A2A gateway serves prompt agents only, so a hosted agent is called the way Foundry serves it. Each
    answer names the agent session (sandbox) that produced it; idle sessions are lent to the next call, so a moment
    usually lands on a warm sandbox with the run already loaded.
    """

    KEEP_IDLE = 4

    def __init__(self, url: str, http: httpx.AsyncClient | None = None, timeout: float = 120.0):
        self.url = url
        self._http = http or httpx.AsyncClient(timeout=timeout, auth=_EntraAuth() if _needs_entra(url) else None)
        self.idle: list[str] = []

    async def ask(self, prompt: str) -> str:
        session = self.idle.pop() if self.idle else None
        body = {"input": prompt, **({"agent_session_id": session} if session else {})}
        response = await self._http.post(self.url, json=body)
        response.raise_for_status()
        answer = response.json()
        if answer.get("status", "completed") != "completed":
            raise RuntimeError(f"hosted agent answered with status {answer.get('status')!r}")
        if answer.get("agent_session_id") and len(self.idle) < self.KEEP_IDLE:
            self.idle.append(answer["agent_session_id"])
        return "".join(part.get("text", "") for item in answer.get("output", []) if item.get("type") == "message"
                       for part in item.get("content", []) if part.get("type") == "output_text")


class RemoteAgents:
    """The Archivist and the Lab out of process: Foundry hosted agents over their Responses endpoint, or any
    A2A v1.0 agent. A failed connection is retried on the next call."""

    def __init__(self, archivist_url: str | None, lab_url: str | None):
        self.urls = {"archivist": archivist_url, "lab": lab_url}
        self._agents: dict[str, A2AAgent | HostedAgent] = {}

    @classmethod
    def from_env(cls) -> "RemoteAgents":
        return cls(os.environ.get("ARCHIVIST_RESPONSES_URL") or os.environ.get("ARCHIVIST_A2A_URL"),
                   os.environ.get("LAB_RESPONSES_URL") or os.environ.get("LAB_A2A_URL"))

    def enabled(self, name: str) -> bool:
        return bool(self.urls.get(name))

    def via(self, name: str) -> str:
        """How the agent is reached: "hosted" (a Foundry hosted agent) or "a2a"."""
        return "hosted" if "/protocols/openai/responses" in (self.urls.get(name) or "") else "a2a"

    async def ask(self, name: str, prompt: str) -> str:
        if name not in self._agents:
            url = self.urls[name]
            self._agents[name] = HostedAgent(url) if self.via(name) == "hosted" else await connect(url)
        agent = self._agents[name]
        if isinstance(agent, HostedAgent):
            return await agent.ask(prompt)
        try:
            result = await agent.run(prompt)
        except Exception:
            self._agents.pop(name, None)
            raise
        return result.text
