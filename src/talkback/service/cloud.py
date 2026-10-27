"""Starting a live matchday in Azure: kick off the generator job and fetch its run.

The service's managed identity holds the Container Apps Jobs Operator role on
the generator job; the run's world appears in the storage account a few seconds
after generation and the events follow on Event Hubs.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx

ARM = "https://management.azure.com"
API_VERSION = "2024-03-01"


def cloud_enabled() -> bool:
    return all(os.environ.get(k) for k in ("EVENTHUB_FQDN", "GENERATOR_JOB_NAME", "AZURE_SUBSCRIPTION_ID",
                                           "AZURE_RESOURCE_GROUP", "STORAGE_ACCOUNT_URL"))


async def _token() -> str:
    from azure.identity.aio import DefaultAzureCredential

    async with DefaultAzureCredential() as cred:
        return (await cred.get_token(f"{ARM}/.default")).token


async def start_generator(run_id: str, seed: int, speed: float) -> str:
    job = (f"{ARM}/subscriptions/{os.environ['AZURE_SUBSCRIPTION_ID']}/resourceGroups/"
           f"{os.environ['AZURE_RESOURCE_GROUP']}/providers/Microsoft.App/jobs/{os.environ['GENERATOR_JOB_NAME']}")
    headers = {"Authorization": f"Bearer {await _token()}"}
    async with httpx.AsyncClient(timeout=30) as http:
        spec = (await http.get(job, params={"api-version": API_VERSION}, headers=headers)).raise_for_status().json()
        container = spec["properties"]["template"]["containers"][0]
        env = [e for e in container.get("env", []) if e["name"] not in ("TALKBACK_RUN_ID", "TALKBACK_SEED",
                                                                         "TALKBACK_LIVE_SPEED")]
        env += [{"name": "TALKBACK_RUN_ID", "value": run_id}, {"name": "TALKBACK_SEED", "value": str(seed)},
                {"name": "TALKBACK_LIVE_SPEED", "value": str(speed)}]
        body = {"containers": [{"name": container["name"], "image": container["image"], "env": env,
                                "resources": container.get("resources")}]}
        r = await http.post(f"{job}/start", params={"api-version": API_VERSION}, headers=headers, json=body)
        r.raise_for_status()
        return r.json().get("name", "started")


async def wait_for_run(run_id: str, dest: Path, timeout_s: float = 240) -> Path:
    """Poll the storage account until the generator has published the run's world; download it."""
    from azure.identity.aio import DefaultAzureCredential
    from azure.storage.blob.aio import BlobServiceClient

    dest.mkdir(parents=True, exist_ok=True)
    async with DefaultAzureCredential() as cred:
        async with BlobServiceClient(os.environ["STORAGE_ACCOUNT_URL"], credential=cred) as svc:
            c = svc.get_container_client(os.environ.get("TALKBACK_RUNS_CONTAINER", "runs"))
            deadline = asyncio.get_running_loop().time() + timeout_s
            while True:
                blob = c.get_blob_client(f"{run_id}/world.json")
                if await blob.exists():
                    data = await (await blob.download_blob()).readall()
                    (dest / "world.json").write_bytes(data)
                    (dest / "events.jsonl").touch()
                    return dest
                if asyncio.get_running_loop().time() > deadline:
                    raise TimeoutError(f"run {run_id} did not appear in storage")
                await asyncio.sleep(3)
