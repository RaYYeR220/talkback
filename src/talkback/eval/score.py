"""Scoring of on-air output against the sealed key (same rules for every system)."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from talkback.clearance.lexicon import detect_strength
from talkback.eval.detect import mentions_subject, numbers, surfaces
from talkback.gallery.world import World
from talkback.models.xt import load_xt_grid
from talkback.schemas.models import Event, EventType
from talkback.stats.desk import StatsDesk
from talkback.world.key import AnswerKey

THIN_WINDOW_MS = 8 * 60_000
SPOILER_DELAY_MS = 2 * 60_000


class Line(BaseModel):
    system: str
    match_id: str
    sim_t: int
    text: str
    kind: str = "live"          # live | recap
    territory: str = "uk"


@dataclass
class Context:
    world: World
    key: AnswerKey
    events: list[Event]

    @classmethod
    def load(cls, run_dir: Path) -> "Context":
        run_dir = Path(run_dir)
        events = [Event.model_validate_json(l) for l in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        key = AnswerKey.model_validate_json((run_dir / "key.sealed.json").read_text(encoding="utf-8"))
        return cls(World.load(run_dir / "world.json"), key, events)

    def name_of(self, subject: str) -> list[str]:
        w = self.world
        if subject.endswith("-M"):
            return [w.club(subject[:-2]).manager.name]
        if "-P" in subject:
            return [w.player(subject).name]
        c = w.club(subject)
        return [c.name, c.short, c.city]


def _known_numbers(ctx: Context) -> dict[str, list[tuple[int, set[float]]]]:
    """Per match, the set of numbers an honest line could have cited, by time (every 5 minutes)."""
    w = ctx.world
    xt = load_xt_grid()
    out: dict[str, list[tuple[int, set[float]]]] = defaultdict(list)
    season: set[float] = set()
    for c in w.league.clubs:
        r = w.row(c.id)
        season |= {float(r.pts), float(r.gd), float(r.gf), float(r.ga), float(r.played), float(r.unbeaten_run),
                   float(w.position(c.id)), float(c.manager.games_in_charge), float(c.manager.games_in_charge + 1)}
        for p in c.squad:
            season |= {float(p.age), float(p.career.career_goals), float(p.career.career_apps),
                       float(p.career.career_goals + 1), float(p.career.career_apps + 1), float(p.shirt)}
    for pid, st in w.player_season.items():
        season |= {float(v) for v in st.values()} | {float(v) + 1 for v in st.values()}
    season |= {float(v) for v in w.clean_sheets.values()} | {float(v) + 1 for v in w.clean_sheets.values()}
    by_match: dict[str, list[Event]] = defaultdict(list)
    for e in ctx.events:
        by_match[e.match_id].append(e)
    for fid, h, a in w.fixtures:
        desk = StatsDesk(fid, w.club(h), w.club(a), xt)
        evs = by_match[fid]
        i = 0
        for t in range(0, 100 * 60_000 + 1, 5 * 60_000):
            while i < len(evs) and evs[i].t <= t:
                desk.ingest(evs[i])
                i += 1
            vals = set(season) | set(range(0, 121))
            for f in desk.facts(t):
                vals.add(round(f.value, 2))
                vals.add(round(f.value * 100, 1))
            out[fid].append((t, vals))
    return out


def _verifiable(value: float, unit: str, known: set[float]) -> bool:
    if value.is_integer() and value <= 120 and not unit:
        return True  # small integers are minute marks, scores and counts; never decisive
    for k in known:
        if abs(k - value) <= (0.5 if unit == "%" else 0.05):
            return True
    return False


def score(ctx: Context, lines: list[Line], end_t: int | None = None) -> dict:
    w = ctx.world
    by_system: dict[str, list[Line]] = defaultdict(list)
    for ln in lines:
        by_system[ln.system].append(ln)
    known = _known_numbers(ctx)
    goals = defaultdict(list)
    for e in ctx.events:
        if e.type == EventType.goal:
            goals[e.match_id].append(e.t)
    fixture_of_story = {}
    for it in ctx.key.items:
        clubs = {s.split("-")[0] for s in it.subjects}
        fixture_of_story[it.storyline_id] = {f for f, h, a in w.fixtures if h in clubs or a in clubs}
    trivia = ctx.world.trivia
    results = {}
    for system, ls in by_system.items():
        uk = [l for l in ls if l.territory == "uk"]
        must = [i for i in ctx.key.items if i.must]
        hit, late, missed = [], [], []
        for it in must:
            names = [n for s in it.subjects for n in ctx.name_of(s)]
            cands = [l for l in uk if l.match_id in fixture_of_story[it.storyline_id]
                     and surfaces(l.text, it.kind, names)]
            if it.deadline == "live":
                lo, hi = it.window_ms
                if any(l.kind == "live" and lo <= l.sim_t <= hi for l in cands):
                    hit.append(it.storyline_id)
                elif cands:
                    late.append(it.storyline_id)
                else:
                    missed.append(it.storyline_id)
            else:
                (hit if cands else missed).append(it.storyline_id)
        n_numbers = n_bad = 0
        for l in uk:
            series = known.get(l.match_id, [])
            vals = next((v for t, v in reversed(series) if t <= l.sim_t + 5 * 60_000), series[-1][1] if series else set())
            for value, unit in numbers(l.text):
                n_numbers += 1
                if not _verifiable(value, unit, vals):
                    n_bad += 1
        over = [l for l in uk if l.kind == "live" and l.sim_t <= THIN_WINDOW_MS and detect_strength(l.text, "en")[0] >= 2]
        intrusion = 0
        for t in trivia:
            names = ctx.name_of(t["subject"])
            intrusion += sum(1 for l in uk if mentions_subject(l.text, names) and str(int(t["value"])) in l.text)
        spoilers = 0
        mena = [l for l in ls if l.territory in ("mena", "all")]
        for l in mena:
            for fid, h, a in w.fixtures:
                if fid == l.match_id:
                    continue
                recent = any(l.sim_t - SPOILER_DELAY_MS <= g <= l.sim_t for g in goals[fid])
                if recent and (mentions_subject(l.text, ctx.name_of(h)) or mentions_subject(l.text, ctx.name_of(a))):
                    spoilers += 1
        results[system] = {
            "lines": len(uk), "story_recall": round(len(hit) / max(1, len(must)), 3),
            "stories_hit": len(hit), "stories_late": len(late), "stories_missed": len(missed), "must": len(must),
            "missed_ids": missed, "late_ids": late,
            "numbers": n_numbers, "unverifiable_numbers": n_bad,
            "unverifiable_rate": round(n_bad / max(1, n_numbers), 3),
            "overclaims_in_thin_windows": len(over), "trivia_intrusions": intrusion, "mena_spoilers": spoilers,
        }
    return results


def lines_from_broadcast(path: Path, system: str = "talkback", include_killed: bool = False) -> list[Line]:
    """Talkback's aired lines (or, for the negative control, every drafted line) from a broadcast log."""
    out = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        msg = json.loads(raw)
        if msg["kind"] != "cue":
            continue
        c = msg["data"]
        kind = "recap" if c.get("audience") == "recap" else "live"
        # effective air time at 1x: the moment's match time plus the pipeline's measured wall latency
        sim_t = int(c["moment_t"]) + int(c.get("latency_ms", 0)) if "moment_t" in c else msg["sim_t"]
        msg = {**msg, "sim_t": sim_t}
        for terr, v in c["verdicts"].items():
            if include_killed:
                # without Clearance the first draft would have aired as written, in English, everywhere
                text = (c.get("data") or {}).get("original_text") or c["text"]
                out.append(Line(system=system, match_id=c["match_id"], sim_t=msg["sim_t"], text=text, kind=kind,
                                territory=terr))
                continue
            if v["verdict"] == "ON_AIR":
                text = v["text"] if v.get("text") else c["text"]
                out.append(Line(system=system, match_id=c["match_id"], sim_t=msg["sim_t"], text=text, kind=kind,
                                territory=terr))
    return out
