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


class RemoteAgents:
    """Lazily connected A2A clients; a failed connection is retried on the next call."""

    def __init__(self, archivist_url: str | None, lab_url: str | None):
        self.urls = {"archivist": archivist_url, "lab": lab_url}
        self._agents: dict[str, A2AAgent] = {}

    @classmethod
    def from_env(cls) -> "RemoteAgents":
        return cls(os.environ.get("ARCHIVIST_A2A_URL"), os.environ.get("LAB_A2A_URL"))

    def enabled(self, name: str) -> bool:
        return bool(self.urls.get(name))

    async def ask(self, name: str, prompt: str) -> str:
        if name not in self._agents:
            self._agents[name] = await connect(self.urls[name])
        try:
            result = await self._agents[name].run(prompt)
        except Exception:
            self._agents.pop(name, None)
            raise
        return result.text
