"""Shared test helpers: cues, Server API schema checks and fake renderer pages."""

import asyncio
import json
import re
import threading
import time

from talkback.ograf.spec import api_validator, server_api
from talkback.schemas.models import Claim, ClaimKind, Cue, TerritoryVerdict, Verdict


def make_cue(template="stat_card", *, text="Okafor has 14 pressures in the final third.", audience="analyst",
             data=None, created_t=60_000, max_age_ms=45_000, cue_id=None, verdicts=None) -> Cue:
    """verdicts: territory -> Verdict, or (Verdict, localised text)."""
    out = {}
    for territory, v in (verdicts or {"uk": Verdict.ON_AIR}).items():
        verdict, line = v if isinstance(v, tuple) else (v, text)
        out[territory] = TerritoryVerdict(territory=territory, verdict=verdict, text=line,
                                          reasons=[] if verdict == Verdict.ON_AIR else ["held in test"])
    return Cue(
        id=cue_id or f"Q-{template}-{created_t}", match_id="F01", audience=audience, text=text,
        claims=[Claim(span="14", kind=ClaimKind.numeric, subject="C02-P09", refs=["F-1"], value=14)],
        template=template, data=data or {}, valid_state_hash="abc123def456", max_age_ms=max_age_ms,
        created_t=created_t, verdicts=out,
    )


def path_template(path: str, prefix: str = "/ograf/v1") -> str:
    """The server-api.yaml path that a concrete request path belongs to."""
    rel = path[len(prefix):] or "/"
    for template in server_api()["paths"]:
        if re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", template), rel):
            return template
    raise AssertionError(f"{path} is not a Server API path")


def assert_valid(instance, path: str, method: str, status: int | None = None) -> None:
    """Check a body against server-api.yaml: a response for `status`, the request body when None."""
    errors = [f"{list(e.absolute_path)}: {e.message}" for e in api_validator(path, method, status).iter_errors(instance)]
    assert errors == [], f"{method.upper()} {path} {status or 'request'}: {errors}"


def reply_for(msg: dict) -> dict:
    if msg["method"] == "playAction":
        return {"result": {"statusCode": 200, "currentStep": 0}}
    if msg["method"] == "updateAction":
        return {"result": None}
    return {"result": {"statusCode": 200}}


class FakePage:
    """A renderer page on a TestClient WebSocket that answers like well-behaved graphics."""

    def __init__(self, ws, *, fail=(), silent=False):
        self.ws, self.fail, self.silent = ws, set(fail), silent
        self.seen: list[dict] = []
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                msg = self.ws.receive_json()
            except BaseException:  # noqa: BLE001 - the session closes under us at teardown
                return
            self.seen.append(msg)
            if "id" not in msg or self.silent:
                continue
            if msg["method"] in self.fail:
                body = {"error": {"code": -32000, "message": f"{msg['method']} blew up"}}
            else:
                body = reply_for(msg)
            self.ws.send_json({"jsonrpc": "2.0", "id": msg["id"], **body})

    def methods(self) -> list[str]:
        return [m["method"] for m in self.seen]

    def wait_for(self, n: int, timeout: float = 3.0) -> list[dict]:
        end = time.monotonic() + timeout
        while len(self.seen) < n and time.monotonic() < end:
            time.sleep(0.01)
        return list(self.seen)


class InProcessPage:
    """A renderer page attached straight to the server's hub, on the caller's event loop."""

    def __init__(self, server, renderer_id: str):
        self.server, self.renderer_id = server, renderer_id
        self.seen: list[dict] = []
        self.page = None

    async def start(self) -> "InProcessPage":
        self.page = await self.server.attach(self.renderer_id, self._send)
        return self

    async def _send(self, text: str) -> None:
        msg = json.loads(text)
        self.seen.append(msg)
        if "id" in msg:
            reply = json.dumps({"jsonrpc": "2.0", "id": msg["id"], **reply_for(msg)})
            asyncio.get_running_loop().call_soon(self.page.receive, reply)

    def methods(self) -> list[str]:
        return [m["method"] for m in self.seen]
