"""Prepare a live matchday (league, season, storylines, line-ups) and run it offline."""

from __future__ import annotations

import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict

from talkback.schemas.models import Event, Fact
from talkback.sim.engine import simulate_match
from talkback.world.key import build_answer_key, detect_traps
from talkback.world.league import League, generate_league
from talkback.world.season import SeasonState, backfill_season
from talkback.world.storylines import Lineups, PlantedStoryline, fixture_ids, plant_storylines


class Matchday(BaseModel):
    model_config = ConfigDict(extra="forbid")

    league: League
    season: SeasonState
    planted: list[PlantedStoryline]
    distractors: list[Fact]
    fixtures: list[tuple[str, str, str]]
    seeds: dict[str, int]
    lineups: Lineups

    def public_world(self) -> dict:
        """Everything the agents may see: raw league and season data only.

        Planted storylines, forced beats and must-surface flags stay in the sealed files;
        the gallery has to find the stories in the data itself.
        """
        return {
            "league": self.league.model_dump(mode="json"),
            "season": self.season.model_dump(mode="json", exclude={"league"}),
            "trivia": [f.model_dump(mode="json") for f in self.distractors],
            "fixtures": self.fixtures,
            "lineups": self.lineups,
        }


def prepare_matchday(seed: int = 2026, matchdays_played: int = 11) -> Matchday:
    league = generate_league(seed)
    season = backfill_season(league, matchdays=matchdays_played, seed=seed + 1)
    planted, distractors, lineups = plant_storylines(season, seed=seed + 2)
    fixtures = fixture_ids(season)
    seeds = {fid: seed * 1000 + n for n, (fid, _, _) in enumerate(fixtures)}
    return Matchday(league=season.league, season=season, planted=planted, distractors=distractors,
                    fixtures=fixtures, seeds=seeds, lineups=lineups)


def _play(args) -> tuple[str, list[dict], dict[str, np.ndarray]]:
    md_json, fid = args
    md = Matchday.model_validate_json(md_json)
    _, h, a = next(f for f in md.fixtures if f[0] == fid)
    beats = [p.forced_beat for p in md.planted if p.forced_beat and p.storyline.fixture_id == fid]
    events, frames = simulate_match(fid, md.league.club(h), md.league.club(a), seed=md.seeds[fid],
                                    beats=beats, start_xi=tuple(md.lineups[fid]))
    players = sorted({pid for fr in frames for pid in fr.ids})
    index = {pid: n for n, pid in enumerate(players)}
    n = len(frames)
    pos = np.full((n, 22, 2), np.nan, np.float16)
    slot = np.full((n, 22), -1, np.int16)
    for i, fr in enumerate(frames):
        k = len(fr.ids)
        pos[i, :k] = fr.pos
        slot[i, :k] = [index[p] for p in fr.ids]
    arrays = {"t": np.array([fr.t for fr in frames], np.int32), "ball": np.array([fr.ball for fr in frames], np.float16),
              "pos": pos, "slot": slot, "players": np.array(players)}
    return fid, [e.model_dump(mode="json") for e in events], arrays


def run_matchday_offline(md: Matchday, out_dir: Path, workers: int | None = None) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md_json = md.model_dump_json()
    workers = workers or min(len(md.fixtures), max(1, (os.cpu_count() or 2) - 1))
    with ProcessPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(_play, [(md_json, fid) for fid, _, _ in md.fixtures]))
    all_events: list[dict] = []
    by_match: dict[str, list[Event]] = {}
    for fid, events, arrays in results:
        all_events.extend(events)
        by_match[fid] = [Event.model_validate(e) for e in events]
        np.savez_compressed(out / f"frames_{fid}.npz", **arrays)
    all_events.sort(key=lambda e: (e["t"], e["match_id"], e["seq"]))
    with open(out / "events.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for e in all_events:
            fh.write(json.dumps(e, separators=(",", ":")) + "\n")
    (out / "world.json").write_text(json.dumps(md.public_world(), indent=1), encoding="utf-8", newline="\n")
    key = build_answer_key(md.planted, by_match, md.distractors, detect_traps(by_match),
                           matchday=md.season.matchday + 1)
    (out / "key.sealed.json").write_text(key.canonical_json(), encoding="utf-8", newline="\n")
    (out / "key.sha256").write_text(key.sha256() + "\n", encoding="utf-8", newline="\n")
    (out / "planted.sealed.json").write_text(
        json.dumps([p.model_dump(mode="json") for p in md.planted], indent=1), encoding="utf-8", newline="\n")
    return out
