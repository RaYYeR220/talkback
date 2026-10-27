"""The single-model baseline: one prompt per match segment, no specialists, no gate.

It gets the same raw season data for both line-ups, the same event stream
(summarised per 15-minute segment) and the same model as Talkback's writer,
and is asked for broadcast lines and a full-time recap.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path

from agent_framework import Agent
from pydantic import BaseModel, Field

from talkback.eval.score import Context, Line
from talkback.gallery.jsonio import ParseError, parse_json
from talkback.schemas.models import Event, EventType, Outcome

SEGMENT_MS = 15 * 60_000

INSTRUCTIONS = (
    "You are the AI commentary producer for a live football broadcast. You get the pre-match data sheet and the "
    "events of the latest period. Write up to three short on-air lines for this period that a viewer would want "
    "to see, including any storylines from the data sheet that matter now. Be accurate. Answer only with JSON: "
    "{\"lines\": [\"...\"]}. At full time you are asked for a recap instead: {\"lines\": [\"<three to five "
    "sentence recap>\"]}."
)


class _Lines(BaseModel):
    lines: list[str] = Field(default_factory=list, max_length=5)


def data_sheet(ctx: Context, fixture_id: str) -> str:
    w = ctx.world
    fid, h, a = w.fixture(fixture_id)
    rows = []
    for cid in (h, a):
        c = w.club(cid)
        r = w.row(cid)
        rows.append(f"{c.name}: position {w.position(cid)}, {r.pts} pts, form {r.form}, unbeaten run {r.unbeaten_run}, "
                    f"manager {c.manager.name} ({c.manager.games_in_charge} games before today)")
    hx, ax = w.lineups[fixture_id]
    for cid, xi in ((h, hx), (a, ax)):
        rows.append(f"{w.club(cid).name} starting XI:")
        for pid in xi:
            p = w.player(pid)
            season = w.player_season.get(pid, {})
            prev = ", ".join(w.club(x).name for x in p.career.previous_clubs) or "none"
            flags = [k for k, v in (("debut pending", p.career.debut_pending), ("final appearance", p.career.farewell),
                                    ("returning from injury", p.career.returning_from_injury)) if v]
            sib = f", brother of {w.player(p.career.sibling_id).name}" if p.career.sibling_id else ""
            cs = w.clean_sheets.get(pid)
            rows.append(f"- {p.name} ({p.position}, age {p.age}): career goals {p.career.career_goals}, career apps "
                        f"{p.career.career_apps}, season goals {season.get('goals', 0)}, previous clubs {prev}"
                        + (f", clean sheets this season {cs}" if cs else "") + (f", {'; '.join(flags)}" if flags else "")
                        + sib)
    top = sorted(((pid, s.get("goals", 0)) for pid, s in w.player_season.items()), key=lambda x: -x[1])[:3]
    rows.append("League top scorers: " + ", ".join(f"{w.player(pid).name} {g}" for pid, g in top))
    return "\n".join(rows)


def digest(events: list[Event], names: dict[str, str]) -> str:
    out = []
    shots = defaultdict(int)
    passes = defaultdict(int)
    for e in events:
        if e.type == EventType.shot:
            shots[e.team_id] += 1
        if e.type == EventType.pass_:
            passes[e.team_id] += 1
        if e.type in (EventType.goal, EventType.card, EventType.substitution) or \
                (e.type == EventType.shot and float(e.qualifiers.get("xg", 0)) >= 0.15):
            what = e.type.value if e.type != EventType.card else f"{e.outcome.value} card"
            extra = f" (xG {float(e.qualifiers['xg']):.2f})" if e.type == EventType.shot else ""
            out.append(f"{e.qualifiers.get('minute')}' {what}: {names.get(e.player_id or '', '')} "
                       f"[{names.get(e.team_id or '', '')}]{extra}")
    out.append("Shots: " + ", ".join(f"{names.get(t, t)} {n}" for t, n in shots.items()))
    out.append("Passes: " + ", ".join(f"{names.get(t, t)} {n}" for t, n in passes.items()))
    return "\n".join(out)


async def run_baseline(ctx: Context, client, concurrency: int = 6) -> list[Line]:
    names = {c.id: c.name for c in ctx.world.league.clubs}
    names.update({p.id: p.name for c in ctx.world.league.clubs for p in c.squad})
    by_match: dict[str, list[Event]] = defaultdict(list)
    for e in ctx.events:
        by_match[e.match_id].append(e)
    sem = asyncio.Semaphore(concurrency)
    lines: list[Line] = []

    async def segment(fid: str, start: int, end: int, recap: bool) -> None:
        evs = [e for e in by_match[fid] if start <= e.t < end]
        if not evs and not recap:
            return
        score = [0, 0]
        h = ctx.world.fixture(fid)[1]
        for e in by_match[fid]:
            if e.type == EventType.goal and e.t < end:
                score[0 if e.team_id == h else 1] += 1
        ask = "Full time. Write the recap." if recap else f"Events from {start // 60_000}' to {end // 60_000}':"
        prompt = (f"Data sheet:\n{data_sheet(ctx, fid)}\n\nScore: {score[0]}-{score[1]}\n\n{ask}\n"
                  + digest(by_match[fid] if recap else evs, names))
        async with sem:
            result = await Agent(client=client, instructions=INSTRUCTIONS, name="baseline").run(prompt)
        try:
            got = parse_json(result.text, _Lines).lines
        except ParseError:
            got = []
        for text in got:
            lines.append(Line(system="baseline", match_id=fid, sim_t=end if not recap else end + 1,
                              text=text, kind="recap" if recap else "live", territory="uk"))
            lines.append(Line(system="baseline", match_id=fid, sim_t=end, text=text,
                              kind="recap" if recap else "live", territory="mena"))

    tasks = []
    for fid, _, _ in ctx.world.fixtures:
        last = max(e.t for e in by_match[fid])
        for start in range(0, last + 1, SEGMENT_MS):
            tasks.append(segment(fid, start, min(start + SEGMENT_MS, last + 1), False))
        tasks.append(segment(fid, 0, last + 1, True))
    await asyncio.gather(*tasks)
    return sorted(lines, key=lambda l: (l.match_id, l.sim_t))


def save_lines(lines: list[Line], path: Path) -> None:
    Path(path).write_text("\n".join(l.model_dump_json() for l in lines), encoding="utf-8", newline="\n")


def load_lines(path: Path) -> list[Line]:
    return [Line.model_validate_json(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
