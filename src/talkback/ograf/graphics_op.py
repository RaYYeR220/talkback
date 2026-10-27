"""Graphics Op: turns ON_AIR cues into timed OGraf actions and plays them through the Server API.

The controller talks to the server only through the standard OGraf Server API, so it can drive
any compliant server. Times are match-clock milliseconds; a territory's in-time is now plus its
broadcast delay budget. What a viewer sees (how long a graphic stays up, the preroll, the gap
between graphics) is wall-clock time, stretched into match time by the playout speed. Each layer
holds one graphic at a time: a higher-priority cue pre-empts, anything else waits for the layer
(or is dropped once it would air stale).
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

from talkback.ograf.layout import OUTPUTS, PRESENTER, Layer, render_target
from talkback.ograf.spec import GRAPHICS_DIR
from talkback.schemas.models import ClaimKind, Cue, Fact, MatchState, Verdict

ActionKind = Literal["load", "update", "play", "stop"]
PREROLL_MS = 500
GAP_MS = 300
SCOREBUG = "talkback-scorebug"
_ORDER = {"stop": 0, "load": 1, "update": 2, "play": 3}


class GraphicAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    renderer_id: str
    graphic_id: str
    layer: int
    action: ActionKind
    data: dict[str, Any] = Field(default_factory=dict)
    at_ms: int
    until_ms: int | None = None
    key: str
    cue_id: str | None = None


class Template(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    graphic_id: str
    layer: Layer
    priority: int
    duration_ms: int | None
    replace_equal: bool = False


TEMPLATES: dict[str, Template] = {
    "story_card": Template(graphic_id="talkback-story-card", layer=Layer.LOWER, priority=30, duration_ms=9_000),
    "table_swing": Template(graphic_id="talkback-table-swing", layer=Layer.CARD, priority=25, duration_ms=8_000),
    "counterfactual_card": Template(graphic_id="talkback-counterfactual-card", layer=Layer.CARD, priority=20,
                                    duration_ms=10_000),
    "lower_third": Template(graphic_id="talkback-lower-third", layer=Layer.LOWER, priority=15, duration_ms=6_000),
    "stat_card": Template(graphic_id="talkback-stat-card", layer=Layer.CARD, priority=10, duration_ms=8_000),
    "player_tag": Template(graphic_id="talkback-player-tag", layer=Layer.TAG, priority=5, duration_ms=5_000),
    # On the presenter strip until spoken (retire) or until the cue expires; the Prompter owns the queue.
    "ifb": Template(graphic_id="talkback-ifb", layer=Layer.IFB, priority=50, duration_ms=None, replace_equal=True),
}
FALLBACK_TEMPLATE = "lower_third"
# Their own figures (as played / if not, before / after) have no source Clearance checked, so they
# are drawn as a stat card from the cited fact.
AS_STAT_CARD = ("counterfactual_card", "table_swing")

IFB_LABELS = {"story_card": "STORY", "stat_card": "STAT", "counterfactual_card": "WHAT IF", "table_swing": "TABLE",
              "lower_third": "NAME", "player_tag": "PLAYER"}
LANGUAGES = {"world": "en", "uk": "en", "kids": "en", "es": "es", "mena": "ar", "br": "pt"}
# Outputs with no clearance of their own air uk's verdict and uk's line: the international English
# feed, and the presenter strip (presenter cues are planned only from the uk verdict).
FOLLOWS = {"world": "uk", PRESENTER: "uk"}

# Graphics carry only what Clearance passed or code computed: the cleared, localised line in the
# free-text field, figures from the facts the line cites, and labels made here. cue.data is free
# Writer output that no check ever sees, so it is never read.
TEXT_FIELD = {
    "talkback-lower-third": "line", "talkback-stat-card": "caption", "talkback-story-card": "line",
    "talkback-counterfactual-card": "caption", "talkback-table-swing": "caption", "talkback-ifb": "text",
    "talkback-player-tag": "name",
}
# Decimals a commentator would say, by unit (the Writer is offered facts at the same precision).
SPOKEN_DECIMALS = {"count": 0, "km": 1, "km/h": 1, "m": 1}
UNITLESS = ("count", "ratio", "probability")
METRIC_LABELS = {"xg": "Expected goals", "ppda": "PPDA", "xt_added": "Threat added", "distance_km": "Distance covered",
                 "top_speed_kmh": "Top speed", "shot_speed_kmh": "Shot speed", "pass_distance_m": "Pass distance",
                 "avg_pass_difficulty": "Average pass difficulty"}


def metric_label(metric: str) -> str:
    """A caption for a Stats Desk metric: 'player.top_speed_kmh' -> 'Top speed'."""
    name = metric.rsplit(".", 1)[-1]
    return METRIC_LABELS.get(name, name.replace("_", " ").capitalize())


def broadcast_value(fact: Fact) -> str:
    """The fact's value at broadcast precision: '0.33' xG, '14' pressures, '10.3' km."""
    text = f"{fact.value:.{SPOKEN_DECIMALS.get(fact.unit, 2)}f}"
    text = text.rstrip("0").rstrip(".") if "." in text else text
    return "0" if text == "-0" else text


def _minutes(window: tuple[int, int]) -> str:
    return f"{window[0] // 60_000 + 1}′–{max(1, -(-window[1] // 60_000))}′"


def cited_fact(cue: Cue, evidence: Iterable[Fact]) -> Fact | None:
    """The fact behind the cue's first number (or, failing that, the first fact it cites)."""
    facts = {f.id: f for f in evidence}
    claims = sorted(cue.claims, key=lambda c: c.kind != ClaimKind.numeric)
    return next((facts[ref] for c in claims for ref in c.refs if ref in facts), None)


def card_template(template: str, fact: Fact | None) -> Template:
    """A card needs a cited fact to show; without one the cleared line goes out as a lower third."""
    name = "stat_card" if template in AS_STAT_CARD else template
    if name not in TEMPLATES or name == "ifb" or (name == "stat_card" and fact is None):
        name = FALLBACK_TEMPLATE
    return TEMPLATES[name]


def is_rtl(text: str) -> bool:
    for ch in text:
        bidi = unicodedata.bidirectional(ch)
        if bidi in ("R", "AL"):
            return True
        if bidi == "L":
            return False
    return False


def _num_text(v: float) -> str:
    return f"{v:g}" if isinstance(v, float) else str(v)


_SKIP = object()


def _coerce(value: Any, prop: dict[str, Any]) -> Any:
    kind = prop.get("type")
    try:
        if kind == "string":
            out: Any = _num_text(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)
        elif kind == "integer":
            out = round(float(value))
        elif kind == "number":
            out = float(value)
        elif kind == "boolean":
            out = value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes")
        elif kind == "array" and isinstance(value, list):
            item = prop.get("items", {}).get("properties", {})
            return [{k: c for k, v in row.items() if k in item and (c := _coerce(v, item[k])) is not _SKIP}
                    for row in value if isinstance(row, dict)]
        else:
            return _SKIP
    except (TypeError, ValueError, OverflowError):
        return _SKIP
    if prop.get("gddType") == "color-rrggbb":
        out = out.lower()
        if not re.fullmatch(r"#[0-9a-f]{6}", out):
            return _SKIP
    if "enum" in prop and out not in prop["enum"]:
        return _SKIP
    if kind in ("integer", "number"):
        if "minimum" in prop:
            out = max(out, prop["minimum"])
        if "maximum" in prop:
            out = min(out, prop["maximum"])
    if kind == "string" and "maxLength" in prop:
        out = out[: prop["maxLength"]]
    return out


def load_schemas(graphics_dir: Path = GRAPHICS_DIR) -> dict[str, dict[str, Any]]:
    out = {}
    for path in sorted(Path(graphics_dir).rglob("*.ograf.json")):
        manifest = json.loads(path.read_text("utf-8"))
        out[manifest["id"]] = manifest.get("schema", {}).get("properties", {})
    return out


@dataclass
class _Slot:
    key: str
    graphic_id: str
    cue_id: str | None
    priority: int
    start: int
    end: int


def _overlaps(s: _Slot, start: int, end: int) -> bool:
    return s.start < end and s.end > start


def _order(a: GraphicAction) -> tuple[int, int]:
    return a.at_ms, _ORDER[a.action]


class Applied(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: GraphicAction
    ok: bool
    detail: dict[str, Any] = Field(default_factory=dict)


class OGrafError(Exception):
    def __init__(self, status: int, body: Any):
        super().__init__(f"HTTP {status}: {body}")
        self.status, self.body = status, body


class OGrafClient:
    """Async client for the OGraf Server API v1. Works against any compliant server."""

    def __init__(self, http: httpx.AsyncClient, prefix: str = "/ograf/v1"):
        self.http = http
        self.prefix = prefix.rstrip("/")

    async def _call(self, method: str, path: str, body: Any = None, query: dict[str, str] | None = None) -> Any:
        r = await self.http.request(method, f"{self.prefix}{path}", json=body, params=query)
        try:
            data = r.json()
        except ValueError:
            data = {"detail": r.text}
        if r.status_code >= 400:
            raise OGrafError(r.status_code, data)
        return data

    @staticmethod
    def _r(renderer_id: str) -> str:
        return f"/renderers/{quote(renderer_id, safe='')}"

    async def info(self) -> dict[str, Any]:
        return await self._call("GET", "/")

    async def graphics(self) -> dict[str, Any]:
        return await self._call("GET", "/graphics")

    async def graphic(self, graphic_id: str) -> dict[str, Any]:
        return await self._call("GET", f"/graphics/{quote(graphic_id, safe='')}")

    async def renderers(self) -> dict[str, Any]:
        return await self._call("GET", "/renderers")

    async def renderer(self, renderer_id: str) -> dict[str, Any]:
        return await self._call("GET", self._r(renderer_id))

    async def target(self, renderer_id: str, target: dict[str, Any]) -> dict[str, Any]:
        return await self._call("GET", f"{self._r(renderer_id)}/target", query={"renderTarget": json.dumps(target)})

    async def load(self, renderer_id: str, target: dict[str, Any], graphic_id: str, data: Any) -> dict[str, Any]:
        body = {"renderTarget": target, "graphicId": graphic_id, "params": {"data": data}}
        return await self._call("POST", f"{self._r(renderer_id)}/target/graphicInstance/load", body)

    async def _instance_call(self, renderer_id: str, verb: str, target: dict[str, Any], instance_id: str,
                             params: dict[str, Any]) -> dict[str, Any]:
        body = {"renderTarget": target, "graphicInstanceId": instance_id,
                "params": {k: v for k, v in params.items() if v is not None}}
        return await self._call("POST", f"{self._r(renderer_id)}/target/graphicInstance/{verb}", body)

    async def update(self, renderer_id: str, target: dict[str, Any], instance_id: str, data: Any,
                     skip_animation: bool | None = None) -> dict[str, Any]:
        return await self._instance_call(renderer_id, "updateAction", target, instance_id,
                                         {"data": data, "skipAnimation": skip_animation})

    async def play(self, renderer_id: str, target: dict[str, Any], instance_id: str, *, goto: int | None = None,
                   delta: int | None = None, skip_animation: bool | None = None) -> dict[str, Any]:
        return await self._instance_call(renderer_id, "playAction", target, instance_id,
                                         {"goto": goto, "delta": delta, "skipAnimation": skip_animation})

    async def stop(self, renderer_id: str, target: dict[str, Any], instance_id: str,
                   skip_animation: bool | None = None) -> dict[str, Any]:
        return await self._instance_call(renderer_id, "stopAction", target, instance_id,
                                         {"skipAnimation": skip_animation})

    async def custom_action(self, renderer_id: str, target: dict[str, Any], instance_id: str, action_id: str,
                            payload: Any, skip_animation: bool | None = None) -> dict[str, Any]:
        return await self._instance_call(renderer_id, f"customActions/{quote(action_id, safe='')}", target,
                                         instance_id, {"payload": payload, "skipAnimation": skip_animation})

    async def clear(self, renderer_id: str, filters: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._call("PUT", f"{self._r(renderer_id)}/target/graphicInstance/clear", {"filters": filters})

    async def renderer_action(self, renderer_id: str, action_id: str, payload: Any) -> dict[str, Any]:
        return await self._call("POST", f"{self._r(renderer_id)}/customActions/{quote(action_id, safe='')}",
                                {"payload": payload})


class GraphicsOp:
    def __init__(self, *, outputs: dict[str, str] | None = None, languages: dict[str, str] | None = None,
                 graphics_dir: Path = GRAPHICS_DIR, preroll_ms: int = PREROLL_MS, speed: float = 1.0):
        self.outputs = outputs if outputs is not None else {t: t for t in OUTPUTS if t != PRESENTER}
        self.languages = languages if languages is not None else dict(LANGUAGES)
        self.schemas = load_schemas(graphics_dir)
        self.preroll_ms = preroll_ms
        self.speed = speed  # match seconds per wall-clock second
        self.log: deque[str] = deque(maxlen=1_000)
        self._slots: dict[tuple[str, int], list[_Slot]] = {}
        self._queue: list[GraphicAction] = []
        self._instances: dict[str, str] = {}
        self._bugs: dict[str, dict[str, Any]] = {}

    # -- planning

    def plan(self, cue: Cue, territory: str, now_t: int, delay_ms: int = 0,
             evidence: Iterable[Fact] = ()) -> list[GraphicAction]:
        """Timed actions that put an ON_AIR cue on a territory's output (or the presenter strip).

        evidence: the facts sent with the cue; only those its claims cite are used.
        """
        presenter = cue.audience == "presenter" or cue.template == "ifb"
        if presenter and territory != FOLLOWS[PRESENTER]:
            return self._drop(cue.id, territory, f"the presenter strip follows {FOLLOWS[PRESENTER]}")
        verdict = cue.verdicts.get(FOLLOWS.get(territory, territory))
        if verdict is None or verdict.verdict != Verdict.ON_AIR:
            return self._drop(cue.id, territory, "not ON_AIR for this territory")
        renderer = PRESENTER if presenter else self.outputs.get(territory)
        if renderer is None:
            return self._drop(cue.id, territory, "territory has no output")
        fact = cited_fact(cue, evidence)
        tpl = TEMPLATES["ifb"] if presenter else card_template(cue.template, fact)
        key = f"{cue.id}@{renderer}"
        if any(s.key == key and s.end > now_t for slots in self._slots.values() for s in slots):
            return []
        at = now_t + delay_ms
        expires = cue.created_t + cue.max_age_ms + delay_ms
        if at >= expires:
            return self._drop(cue.id, territory, "stale before air")
        slots = self._slots.setdefault((renderer, int(tpl.layer)), [])
        slots[:] = [s for s in slots if s.end > now_t]
        shown = None if tpl.duration_ms is None else self._match_ms(tpl.duration_ms)
        span = (lambda start: expires - start) if shown is None else (lambda start: shown)
        for _ in range(len(slots) + 1):
            blockers = [s for s in slots if _overlaps(s, at, at + span(at)) and not self._beats(tpl, s)]
            if not blockers:
                break
            at = max(s.end for s in blockers) + self._match_ms(GAP_MS)
        if at >= expires:
            return self._drop(cue.id, territory, f"layer {int(tpl.layer)} busy until the cue expires")
        until = at + span(at)
        out: list[GraphicAction] = []
        for victim in [s for s in slots if _overlaps(s, at, until)]:
            out += self._preempt(slots, victim, renderer, int(tpl.layer), at)
        slots.append(_Slot(key, tpl.graphic_id, cue.id, tpl.priority, at, until))
        slots.sort(key=lambda s: s.start)
        data = self.shape(tpl, cue, verdict.text, territory, at, until, fact)
        common = {"renderer_id": renderer, "graphic_id": tpl.graphic_id, "layer": int(tpl.layer), "key": key,
                  "cue_id": cue.id}
        preroll = self._match_ms(self.preroll_ms)
        out += [
            GraphicAction(action="load", data=data, at_ms=max(now_t, at - preroll), until_ms=until, **common),
            GraphicAction(action="play", at_ms=at, until_ms=until, **common),
            GraphicAction(action="stop", at_ms=until, **common),
        ]
        self._enqueue(out)
        return out

    def rebase(self, delta_ms: int) -> None:
        """Move every booking by delta_ms: the match clock restarted (a new run or replay loop), and
        what is booked keeps its wall-clock schedule."""
        self._queue = [a.model_copy(update={"at_ms": a.at_ms + delta_ms,
                                            "until_ms": None if a.until_ms is None else a.until_ms + delta_ms})
                       for a in self._queue]
        for slots in self._slots.values():
            for s in slots:
                s.start, s.end = s.start + delta_ms, s.end + delta_ms

    def retire(self, cue_id: str, now_t: int) -> list[GraphicAction]:
        """Take a cue's graphics off now: the IFB line was spoken, or the producer pulled it."""
        out: list[GraphicAction] = []
        for (renderer, layer), slots in self._slots.items():
            for s in [s for s in slots if s.cue_id == cue_id and s.end > now_t]:
                out += self._preempt(slots, s, renderer, layer, now_t)
        self._enqueue(out)
        return out

    def plan_score(self, state: MatchState, territory: str, now_t: int, delay_ms: int = 0, *, home: str, away: str,
                   home_color: str | None = None, away_color: str | None = None, as_it_stands: bool = False,
                   elsewhere: list[dict[str, Any]] | None = None, minute: int | None = None,
                   added_time: int | None = None, status: str | None = None) -> list[GraphicAction]:
        """Scorebug for the match on a territory's output: load once, then update what changed."""
        renderer = self.outputs.get(territory)
        if renderer is None:
            return []
        if minute is None:
            minute, added_time = _clock(state)
        raw: dict[str, Any] = {
            "matchId": state.match_id, "homeShort": home, "awayShort": away, "homeScore": state.home_goals,
            "awayScore": state.away_goals, "minute": minute, "addedTime": added_time or 0, "status": status or "",
            "asItStands": as_it_stands, "homeColor": home_color, "awayColor": away_color, "elsewhere": elsewhere,
            "dir": "ltr", "lang": self.languages.get(territory),
        }
        data = self._fit(SCOREBUG, {k: v for k, v in raw.items() if v is not None})
        at = now_t + delay_ms
        common = {"renderer_id": renderer, "graphic_id": SCOREBUG, "layer": int(Layer.BUG), "key": f"bug@{renderer}"}
        last = self._bugs.get(renderer)
        if last is None:
            out = [GraphicAction(action="load", data=data, at_ms=at, **common),
                   GraphicAction(action="play", at_ms=at, **common)]
        else:
            diff = {k: v for k, v in data.items() if last.get(k) != v}
            if not diff:
                return []
            out = [GraphicAction(action="update", data=diff, at_ms=at, **common)]
        self._bugs[renderer] = data
        self._enqueue(out)
        return out

    def clear_score(self, territory: str, now_t: int, delay_ms: int = 0) -> list[GraphicAction]:
        renderer = self.outputs.get(territory)
        if renderer is None or self._bugs.pop(renderer, None) is None:
            return []
        out = [GraphicAction(renderer_id=renderer, graphic_id=SCOREBUG, layer=int(Layer.BUG), action="stop",
                             at_ms=now_t + delay_ms, key=f"bug@{renderer}")]
        self._enqueue(out)
        return out

    def _match_ms(self, wall_ms: int) -> int:
        return round(wall_ms * self.speed)

    def _beats(self, tpl: Template, slot: _Slot) -> bool:
        return tpl.priority > slot.priority or (tpl.replace_equal and tpl.priority == slot.priority)

    def _preempt(self, slots: list[_Slot], v: _Slot, renderer: str, layer: int, at: int) -> list[GraphicAction]:
        mine = [a for a in self._queue if a.key == v.key]
        loaded = v.key in self._instances or not any(a.action == "load" for a in mine)
        if v.start < at:
            self._queue = [a for a in self._queue if not (a.key == v.key and a.action == "stop")]
            v.end = at
        else:
            self._queue = [a for a in self._queue if a.key != v.key]
            slots.remove(v)
            if not loaded:
                return []
        self.log.append(f"{v.cue_id} pre-empted on {renderer}/{layer} at {at}")
        return [GraphicAction(renderer_id=renderer, graphic_id=v.graphic_id, layer=layer, action="stop", at_ms=at,
                              key=v.key, cue_id=v.cue_id)]

    def _drop(self, cue_id: str, territory: str, why: str) -> list[GraphicAction]:
        self.log.append(f"{cue_id} not planned for {territory}: {why}")
        return []

    # -- data

    def _fit(self, graphic_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        props = self.schemas.get(graphic_id, {})
        out = {}
        for k, v in raw.items():
            if k in props and (c := _coerce(v, props[k])) is not _SKIP:
                out[k] = c
        return out

    def shape(self, tpl: Template, cue: Cue, text: str, territory: str, at: int, until: int,
              fact: Fact | None = None) -> dict[str, Any]:
        """Graphic data for a cue: the cleared text, figures from the cited fact, labels made here."""
        gid = tpl.graphic_id
        raw: dict[str, Any] = {TEXT_FIELD.get(gid, "name"): text}
        if gid == "talkback-stat-card" and fact is not None:
            raw.update(label=metric_label(fact.metric), value=broadcast_value(fact),
                       evidence=f"n={fact.sample_size} · {_minutes(fact.window)}")
            if fact.unit not in UNITLESS:
                raw["unit"] = fact.unit
        elif gid == "talkback-story-card":
            raw["kind"] = "STORY"
        elif gid == "talkback-ifb":
            # the strip counts down on the presenter's screen, so in wall-clock time
            raw.update(label=IFB_LABELS.get(cue.template, "CUE"), countdownMs=max(0, round((until - at) / self.speed)),
                       cueId=cue.id)
        raw["dir"] = "rtl" if is_rtl(text) else "ltr"
        if lang := self.languages.get(territory):
            raw["lang"] = lang
        return self._fit(gid, raw)

    # -- playout

    def _enqueue(self, actions: list[GraphicAction]) -> None:
        self._queue.extend(actions)
        self._queue.sort(key=_order)

    @property
    def pending(self) -> list[GraphicAction]:
        return list(self._queue)

    def due(self, now_t: int) -> list[GraphicAction]:
        ready = [a for a in self._queue if a.at_ms <= now_t]
        self._queue = [a for a in self._queue if a.at_ms > now_t]
        return ready

    async def tick(self, now_t: int, client: OGrafClient) -> list[Applied]:
        return await self.apply(self.due(now_t), client)

    async def apply(self, actions: list[GraphicAction], client: OGrafClient) -> list[Applied]:
        """Run actions now, in time order, through the OGraf Server API."""
        taken = {id(a) for a in actions}
        self._queue = [a for a in self._queue if id(a) not in taken]
        results = []
        for a in sorted(actions, key=_order):
            try:
                detail = await self._run(a, client)
            except (OGrafError, httpx.HTTPError) as exc:
                results.append(Applied(action=a, ok=False, detail={"error": str(exc)}))
                continue
            ok = "skipped" in detail or int(detail.get("statusCode", 200)) < 400
            results.append(Applied(action=a, ok=ok, detail=detail))
        return results

    async def _run(self, a: GraphicAction, client: OGrafClient) -> dict[str, Any]:
        target = render_target(a.layer)
        if a.action == "load":
            if a.key in self._instances:
                await client.clear(a.renderer_id, [{"graphicInstanceId": self._instances.pop(a.key)}])
            res = await client.load(a.renderer_id, target, a.graphic_id, a.data)
            self._instances[a.key] = res["graphicInstanceId"]
            return res
        iid = self._instances.get(a.key)
        if iid is None:
            return {"skipped": "graphic instance not loaded"}
        if a.action == "update":
            return await client.update(a.renderer_id, target, iid, a.data)
        if a.action == "play":
            return await client.play(a.renderer_id, target, iid)
        res = await client.stop(a.renderer_id, target, iid)
        await client.clear(a.renderer_id, [{"graphicInstanceId": iid}])
        del self._instances[a.key]
        return res


def _clock(state: MatchState) -> tuple[int, int]:
    minute = state.t // 60_000 + 1
    cap = 45 if state.period <= 1 else 90
    return (cap, minute - cap) if minute > cap else (minute, 0)

