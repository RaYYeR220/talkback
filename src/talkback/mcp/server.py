"""MCP server: "ask the gallery" — read-only tools over the live Talkback service.

Usable from GitHub Copilot Agent Mode or any MCP client. Every answer comes
from what the gallery has actually computed or aired; nothing is generated here.

    python -m talkback.mcp.server            (streamable HTTP on :8100/mcp)
"""

from __future__ import annotations

import os
from typing import Annotated

import httpx
from mcp.server.mcpserver import MCPServer
from pydantic import Field

API = os.environ.get("TALKBACK_API", "http://127.0.0.1:8000")

server = MCPServer(
    name="talkback",
    title="Talkback gallery",
    description="Read-only access to a live matchday gallery: scores, story boards, aired lines, "
                "refused lines with reasons, the live table and the evidence behind any line.",
    instructions="Use these tools to answer questions about the matchday the Talkback gallery is covering. "
                 "Quote lines exactly as aired; when asked why something was said, use explain_line.",
)


async def _state() -> list[dict]:
    async with httpx.AsyncClient(base_url=API, timeout=10) as c:
        r = await c.get("/api/state")
        r.raise_for_status()
        return r.json()["last"]


def _of(msgs: list[dict], kind: str) -> list[dict]:
    return [m for m in msgs if m["kind"] == kind]


@server.tool(description="All matches of the matchday with score, minute and status.")
async def list_matches() -> list[dict]:
    return [m["data"] for m in _of(await _state(), "score")]


@server.tool(description="Lines that went to air, newest first, optionally for one match and one territory.")
async def aired_lines(match_id: Annotated[str | None, Field(description="e.g. MD12-F03")] = None,
                      territory: Annotated[str, Field(description="uk, es, mena, kids or br")] = "uk",
                      limit: Annotated[int, Field(ge=1, le=50)] = 10) -> list[dict]:
    rows = [m for m in _of(await _state(), "aired")
            if m["data"]["territory"] == territory and (match_id is None or m["data"]["match_id"] == match_id)]
    rows.sort(key=lambda m: -m["sim_t"])
    return [{"minute": m["sim_t"] // 60_000, **m["data"]} for m in rows[:limit]]


@server.tool(description="Lines Clearance refused or held, with the reasons, per territory.")
async def refused_lines(match_id: Annotated[str | None, Field(description="e.g. MD12-F03")] = None,
                        limit: Annotated[int, Field(ge=1, le=50)] = 10) -> list[dict]:
    out = []
    for m in sorted(_of(await _state(), "cue"), key=lambda m: -m["sim_t"]):
        c = m["data"]
        if match_id and c["match_id"] != match_id:
            continue
        bad = {t: v for t, v in c["verdicts"].items() if v["verdict"] != "ON_AIR"}
        if bad:
            out.append({"cue_id": c["id"], "text": c["text"],
                        "refused": {t: {"verdict": v["verdict"], "reasons": v["reasons"]} for t, v in bad.items()}})
        if len(out) >= limit:
            break
    return out


@server.tool(description="The story board of one match: storylines found in the season data and their status.")
async def story_board(match_id: Annotated[str, Field(description="e.g. MD12-F03")]) -> list[dict]:
    for m in _of(await _state(), "board"):
        if m["data"]["match_id"] == match_id:
            return [{k: s[k] for k in ("id", "kind", "status", "summary")} for s in m["data"]["stories"]]
    return []


@server.tool(description="The live table as it stands with title, top-four and relegation chances, and recent swings.")
async def live_table() -> dict:
    rows = _of(await _state(), "table")
    return rows[-1]["data"] if rows else {"rows": [], "swings": []}


@server.tool(description="Why a line was said: its claims, the facts and events they cite, and every territory verdict.")
async def explain_line(cue_id: Annotated[str, Field(description="a cue id from aired_lines or refused_lines")]) -> dict:
    async with httpx.AsyncClient(base_url=API, timeout=10) as c:
        r = await c.get(f"/api/ledger/{cue_id}")
        if r.status_code == 404:
            return {"error": "unknown line"}
        r.raise_for_status()
        return r.json()


def main() -> None:
    import uvicorn

    uvicorn.run(server.streamable_http_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8100")))


if __name__ == "__main__":
    main()
