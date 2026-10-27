"""Azure AI Content Safety for every outgoing line (fails closed)."""

from __future__ import annotations

import os

from talkback.clearance.safety import ContentSafety, LocalDevSafety

SEVERITY_LIMIT = 2  # block at "low" and above for a family broadcast


class AzureContentSafety:
    def __init__(self, endpoint: str):
        from azure.ai.contentsafety.aio import ContentSafetyClient
        from azure.identity.aio import DefaultAzureCredential

        self._client = ContentSafetyClient(endpoint, DefaultAzureCredential())

    async def analyze(self, text: str) -> tuple[bool, str]:
        from azure.ai.contentsafety.models import AnalyzeTextOptions

        result = await self._client.analyze_text(AnalyzeTextOptions(text=text))
        worst = max((c.severity or 0 for c in result.categories_analysis), default=0)
        if worst >= SEVERITY_LIMIT:
            cats = ",".join(c.category for c in result.categories_analysis if (c.severity or 0) >= SEVERITY_LIMIT)
            return False, f"content-safety: {cats} severity {worst}"
        return True, "content-safety: ok"


def make_safety() -> ContentSafety:
    endpoint = os.environ.get("CONTENT_SAFETY_ENDPOINT")
    if endpoint:
        return AzureContentSafety(endpoint)
    return LocalDevSafety()
