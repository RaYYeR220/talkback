"""Graphics Op: turns ON_AIR cues into timed OGraf actions and plays them through the Server API.

The controller talks to the server only through the standard OGraf Server API, so it can drive
any compliant server. Times are match-clock milliseconds; a territory's in-time is now plus its
broadcast delay budget. Each layer holds one graphic at a time: a higher-priority cue pre-empts,
anything else waits for the layer (or is dropped once it would air stale).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

from talkback.ograf.layout import OUTPUTS, PRESENTER, Layer, render_target
from talkback.ograf.spec import GRAPHICS_DIR
from talkback.schemas.models import Cue, MatchState, Verdict

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

STORY_BADGES = {
    "milestone_goals": "MILESTONE", "manager_100": "MILESTONE", "farewell": "FAREWELL", "debut": "DEBUT",
    "former_club": "FORMER CLUB", "unbeaten_run": "STREAK", "relegation_six_pointer": "SIX-POINTER",
    "golden_boot": "GOLDEN BOOT", "clean_sheet_record": "RECORD", "injury_return": "RETURN", "siblings": "BROTHERS",
}
IFB_LABELS = {"story_card": "STORY", "stat_card": "STAT", "counterfactual_card": "WHAT IF", "table_swing": "TABLE",
              "lower_third": "NAME", "player_tag": "PLAYER"}
LANGUAGES = {"world": "en", "uk": "en", "kids": "en", "es": "es", "mena": "ar", "br": "pt"}

# The cleared, localised line always fills the graphic's free-text field; cue.data only supplies
# labels and numbers.
TEXT_FIELD = {
    "talkback-lower-third": "line", "talkback-stat-card": "caption", "talkback-story-card": "line",
    "talkback-counterfactual-card": "caption", "talkback-table-swing": "caption", "talkback-ifb": "text",
}
ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "talkback-lower-third": {"name": ("subject", "player"), "kicker": ("club", "team", "role")},
    "talkback-stat-card": {"subject": ("player", "team"), "label": ("metric", "stat"),
                           "compareLabel": ("baseline_label",), "compareValue": ("baseline", "league_avg")},
    "talkback-story-card": {"title": ("headline",), "kind": ("storyline_kind", "badge")},
    "talkback-counterfactual-card": {"asPlayed": ("baseline", "actual"), "ifNot": ("counterfactual", "cf")},
    "talkback-table-swing": {"club": ("team", "subject"), "causedBy": ("cause", "match")},
    "talkback-player-tag": {"name": ("player", "subject"), "number": ("shirt",)},
}


def _norm(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


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


def _signed(v: float, unit: str) -> str:
    sign = "+" if v > 0 else "−" if v < 0 else "±"
    return f"{sign}{_num_text(abs(v))}{unit}"


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
                 graphics_dir: Path = GRAPHICS_DIR, preroll_ms: int = PREROLL_MS):
        self.outputs = outputs if outputs is not None else {t: t for t in OUTPUTS if t != PRESENTER}
        self.languages = languages if languages is not None else dict(LANGUAGES)
        self.schemas = load_schemas(graphics_dir)
        self.preroll_ms = preroll_ms
        self.log: list[str] = []
        self._slots: dict[tuple[str, int], list[_Slot]] = {}
        self._queue: list[GraphicAction] = []
        self._instances: dict[str, str] = {}
        self._bugs: dict[str, dict[str, Any]] = {}

    # -- planning

    def plan(self, cue: Cue, territory: str, now_t: int, delay_ms: int = 0) -> list[GraphicAction]:
        """Timed actions that put an ON_AIR cue on a territory's output (or the presenter strip)."""
        verdict = cue.verdicts.get(territory)
        if verdict is None or verdict.verdict != Verdict.ON_AIR:
            return self._drop(cue.id, territory, "not ON_AIR for this territory")
        presenter = cue.audience == "presenter" or cue.template == "ifb"
        renderer = PRESENTER if presenter else self.outputs.get(territory)
        if renderer is None:
            return self._drop(cue.id, territory, "territory has no output")
        tpl = TEMPLATES["ifb"] if presenter else TEMPLATES.get(cue.template, TEMPLATES[FALLBACK_TEMPLATE])
        key = f"{cue.id}@{renderer}"
        if any(s.key == key for slots in self._slots.values() for s in slots):
            return []
        at = now_t + delay_ms
        expires = cue.created_t + cue.max_age_ms + delay_ms
        if at >= expires:
            return self._drop(cue.id, territory, "stale before air")
        slots = self._slots.setdefault((renderer, int(tpl.layer)), [])
        slots[:] = [s for s in slots if s.end > now_t]
        span = (lambda start: expires - start) if tpl.duration_ms is None else (lambda start: tpl.duration_ms)
        for _ in range(len(slots) + 1):
            blockers = [s for s in slots if _overlaps(s, at, at + span(at)) and not self._beats(tpl, s)]
            if not blockers:
                break
            at = max(s.end for s in blockers) + GAP_MS
        if at >= expires:
            return self._drop(cue.id, territory, f"layer {int(tpl.layer)} busy until the cue expires")
        until = at + span(at)
        out: list[GraphicAction] = []
        for victim in [s for s in slots if _overlaps(s, at, until)]:
            out += self._preempt(slots, victim, renderer, int(tpl.layer), at)
        slots.append(_Slot(key, tpl.graphic_id, cue.id, tpl.priority, at, until))
        slots.sort(key=lambda s: s.start)
        data = self.shape(tpl, cue, verdict.text, territory, at, until)
        common = {"renderer_id": renderer, "graphic_id": tpl.graphic_id, "layer": int(tpl.layer), "key": key,
                  "cue_id": cue.id}
        out += [
            GraphicAction(action="load", data=data, at_ms=max(now_t, at - self.preroll_ms), until_ms=until, **common),
            GraphicAction(action="play", at_ms=at, until_ms=until, **common),
            GraphicAction(action="stop", at_ms=until, **common),
        ]
        self._enqueue(out)
        return out

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

    def shape(self, tpl: Template, cue: Cue, text: str, territory: str, at: int, until: int) -> dict[str, Any]:
        """Graphic data for a cue: schema-checked, the cleared text in the free-text field."""
        gid = tpl.graphic_id
        props = self.schemas.get(gid, {})
        given = {_norm(k): v for k, v in cue.data.items() if v is not None}
        aliases = ALIASES.get(gid, {})
        raw: dict[str, Any] = {}
        for name in props:
            for alias in (name, *aliases.get(name, ())):
                if _norm(alias) in given:
                    raw[name] = given[_norm(alias)]
                    break
        if gid in TEXT_FIELD:
            raw[TEXT_FIELD[gid]] = text
        elif "name" not in raw:
            raw["name"] = text
        extra = _derived(gid, cue, given, raw, at, until)
        raw.update(extra)
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


def _pick(given: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if _norm(k) in given:
            return given[_norm(k)]
    return None


def _derived(gid: str, cue: Cue, given: dict[str, Any], raw: dict[str, Any], at: int, until: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if gid in ("talkback-stat-card", "talkback-counterfactual-card") and "evidence" not in raw:
        parts = []
        if (n := _pick(given, "n", "sample_size", "sample")) is not None:
            parts.append(f"n={_num_text(n)}")
        lo, hi = _pick(given, "window_from", "from_minute"), _pick(given, "window_to", "to_minute")
        if lo is not None and hi is not None:
            parts.append(f"{_num_text(lo)}′–{_num_text(hi)}′")
        if parts:
            out["evidence"] = " · ".join(parts)
    if gid == "talkback-story-card":
        kind = str(raw.get("kind") or "story")
        out["kind"] = STORY_BADGES.get(kind.lower(), kind.replace("_", " ").upper())
    if gid == "talkback-counterfactual-card":
        unit = str(raw.get("unit", "%"))
        delta_unit = " pts" if unit == "%" else unit
        effect = raw.get("effect")
        if isinstance(effect, (int, float)) and not isinstance(effect, bool):
            out["effect"] = _signed(effect, delta_unit)
        lo, hi = _pick(given, "ci_low", "ci95_low", "ci_lo"), _pick(given, "ci_high", "ci95_high", "ci_hi")
        if "interval" not in raw and lo is not None and hi is not None:
            out["interval"] = f"95% interval {_signed(lo, '')} to {_signed(hi, '')}"
    if gid == "talkback-ifb":
        out["label"] = str(raw.get("label") or IFB_LABELS.get(cue.template, "CUE"))
        out["countdownMs"] = max(0, until - at)
        out["cueId"] = cue.id
    return out
