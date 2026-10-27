"""The claim ledger in Azure Cosmos DB: every line the gallery produced, aired or not.

Each document is one cue with its claims, cited evidence, Lab experiments and
the verdict for every territory, partitioned by run. Writes are best-effort
and never block the gallery.
"""

from __future__ import annotations

import asyncio
import os


class CosmosLedger:
    def __init__(self, endpoint: str, database: str = "talkback", container: str = "cues"):
        from azure.cosmos.aio import CosmosClient
        from azure.identity.aio import DefaultAzureCredential

        self._cred = DefaultAzureCredential()
        self._client = CosmosClient(endpoint, credential=self._cred)
        self._container = self._client.get_database_client(database).get_container_client(container)
        self.written = 0
        self.failed = 0

    async def write(self, run_id: str, cue: dict) -> None:
        doc = {**cue, "id": cue["id"].replace("/", "_").replace("#", "_"), "run_id": run_id}
        try:
            await self._container.upsert_item(doc)
            self.written += 1
        except Exception:  # noqa: BLE001 - the ledger must never take the gallery down
            self.failed += 1

    async def run(self, subscribe, run_id_of) -> None:
        async for msg in subscribe():
            if msg["kind"] == "cue":
                asyncio.create_task(self.write(run_id_of(), msg["data"]))

    async def close(self) -> None:
        await self._client.close()
        await self._cred.close()


def make_ledger() -> CosmosLedger | None:
    endpoint = os.environ.get("COSMOS_ENDPOINT")
    if not endpoint:
        return None
    return CosmosLedger(endpoint, os.environ.get("COSMOS_DATABASE", "talkback"))
