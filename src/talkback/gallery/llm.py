"""Chat clients for the gallery's agents.

TALKBACK_LLM selects the provider:
  foundry  — Microsoft Foundry models (production and the eval of record)
  venice   — an OpenAI-compatible endpoint used while developing locally
  scripted — a deterministic client for tests and offline replays
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any, Literal

from agent_framework import BaseChatClient, ChatResponse, ChatResponseUpdate, Message

Tier = Literal["fast", "strong"]


class ScriptedClient(BaseChatClient):
    """Answers with `script(messages)`; never touches the network."""

    OTEL_PROVIDER_NAME = "scripted"

    def __init__(self, script: Callable[[Sequence[Message]], str], **kwargs: Any):
        super().__init__(**kwargs)
        self._script = script
        self.calls = 0

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        self.calls += 1
        text = self._script(messages)
        if stream:
            async def _stream():
                yield ChatResponseUpdate(role="assistant", contents=[{"type": "text", "text": text}])
            return _stream()
        return ChatResponse(messages=[Message(role="assistant", contents=[text])], response_id=f"scripted-{self.calls}")


def message_text(messages: Sequence[Message]) -> str:
    return "\n".join(m.text or "" for m in messages)


def provider() -> str:
    return os.environ.get("TALKBACK_LLM", "scripted")


def make_client(tier: Tier = "fast", script: Callable[[Sequence[Message]], str] | None = None) -> BaseChatClient:
    which = provider()
    if which == "foundry":
        from azure.identity import DefaultAzureCredential
        from agent_framework.foundry import FoundryChatClient

        model = os.environ["FOUNDRY_MODEL_STRONG" if tier == "strong" else "FOUNDRY_MODEL_FAST"]
        return FoundryChatClient(project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], model=model,
                                 credential=DefaultAzureCredential())
    if which == "venice":
        from openai import AsyncOpenAI
        from agent_framework.openai import OpenAIChatCompletionClient

        model = os.environ.get("VENICE_MODEL_STRONG" if tier == "strong" else "VENICE_MODEL_FAST", "llama-3.3-70b")
        client = AsyncOpenAI(base_url=os.environ.get("VENICE_BASE_URL", "https://api.venice.ai/api/v1"),
                             api_key=os.environ["VENICE_API_KEY"])
        return OpenAIChatCompletionClient(model=model, async_client=client)
    if which == "scripted":
        if script is None:
            raise RuntimeError("scripted provider needs a script")
        return ScriptedClient(script)
    raise RuntimeError(f"unknown TALKBACK_LLM={which!r}")
