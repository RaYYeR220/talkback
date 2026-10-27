"""OGraf Server API v1 on FastAPI, driving browser renderer pages over a WebSocket.

There is one renderer per output. The server owns the render state (graphic instances per
layer). Renderer pages are viewports: they run each command on the graphic's web component and
answer with the graphic's return payload, which the server hands back to the controller. A page
that connects late, or reconnects, is replayed the current state.
"""

from __future__ import annotations

import asyncio
import functools
import itertools
import json
import logging
import mimetypes
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, ValidationError

from talkback.ograf.layout import LAYERS, OUTPUTS
from talkback.ograf.spec import GRAPHICS_DIR, RENDERER_DIR, manifest_validator

log = logging.getLogger(__name__)

mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/javascript", ".js")

# The Server API requires a numeric currentStep; the Graphic spec says "undefined" at the end.
# -1 is the spec's own encoding of "not on a step" (target = -1 + delta from the start state).
END_STEP = -1
OFFLINE = "No renderer page connected; state kept and replayed on connect"
RENDERER_ACTIONS = [{
    "id": "identify", "name": "Identify",
    "description": "Show the renderer id on every connected page for a few seconds", "schema": None,
}]


# ---- wire models -------------------------------------------------------------------------------
# OGraf payloads are open (VendorExtend: any request may carry v_* fields), so these allow extras.

class _Wire(BaseModel):
    model_config = ConfigDict(extra="allow")


class _LoadParams(_Wire):
    data: Any


class LoadBody(_Wire):
    renderTarget: dict[str, Any]
    graphicId: str
    params: _LoadParams


class _UpdateParams(_Wire):
    data: Any
    skipAnimation: bool | None = None


class _PlayParams(_Wire):
    delta: float | None = None
    goto: float | None = None
    skipAnimation: bool | None = None


class _StopParams(_Wire):
    skipAnimation: bool | None = None


class _CustomParams(_Wire):
    payload: Any
    skipAnimation: bool | None = None


class _Targeted(_Wire):
    renderTarget: dict[str, Any]
    graphicInstanceId: str


class UpdateBody(_Targeted):
    params: _UpdateParams


class PlayBody(_Targeted):
    params: _PlayParams


class StopBody(_Targeted):
    params: _StopParams


class CustomBody(_Targeted):
    params: _CustomParams


class _Filter(_Wire):
    renderTarget: dict[str, Any] | None = None
    graphicId: str | None = None
    graphicInstanceId: str | None = None


class ClearBody(_Wire):
    filters: list[_Filter]


class RendererActionBody(_Wire):
    payload: Any
    skipAnimation: bool | None = None


# ---- state -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class GraphicPackage:
    manifest: dict[str, Any]
    path: Path
    rel_dir: str

    @property
    def id(self) -> str:
        return self.manifest["id"]

    @property
    def step_count(self) -> int:
        return int(self.manifest.get("stepCount", 1))

    @property
    def list_info(self) -> dict[str, Any]:
        info = {"id": self.id, "name": self.manifest["name"]}
        if "description" in self.manifest:
            info["description"] = self.manifest["description"]
        if "thumbnails" in self.manifest:
            info["thumbnails"] = self.manifest["thumbnails"]
        return info

    def main_url(self, graphics_url: str) -> str:
        parts = [graphics_url.rstrip("/"), self.rel_dir, self.manifest["main"]]
        return "/".join(p for p in parts if p)


def load_packages(root: Path) -> dict[str, GraphicPackage]:
    validator = manifest_validator()
    packages: dict[str, GraphicPackage] = {}
    for path in sorted(Path(root).rglob("*.ograf.json")):
        manifest = json.loads(path.read_text("utf-8"))
        errors = [e.message for e in validator.iter_errors(manifest)]
        if errors:
            log.warning("skipping %s: %s", path, errors[:3])
            continue
        if manifest["id"] in packages:
            log.warning("skipping %s: duplicate graphic id %s", path, manifest["id"])
            continue
        rel = path.parent.relative_to(root).as_posix()
        packages[manifest["id"]] = GraphicPackage(manifest=manifest, path=path, rel_dir="" if rel == "." else rel)
    return packages


def target_step(current: int | None, step_count: int, goto: float | None = None,
                delta: float | None = None) -> int | None:
    """OGraf step resolution. None means the graphic transitions to its end."""
    if goto is not None and goto >= 0:
        target = int(goto)
    else:
        target = (-1 if current is None else current) + int(1 if delta is None else delta)
    if step_count == 0 or (step_count > 0 and target >= step_count):
        return None
    return max(target, 0)


@dataclass
class Instance:
    id: str
    graphic: GraphicPackage
    layer: int
    data: Any
    step: int | None = None


class RendererGone(Exception):
    pass


class GraphicError(Exception):
    pass


class _Page:
    """One connected renderer page, spoken to in JSON-RPC 2.0."""

    def __init__(self, send: Callable[[str], Awaitable[None]]):
        self._send = send
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}

    async def request(self, method: str, params: dict[str, Any]) -> asyncio.Future:
        rid = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await self._send(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}))
        except Exception as exc:  # noqa: BLE001 - any send failure means the page is gone
            self._pending.pop(rid, None)
            fut.set_exception(RendererGone(str(exc)))
        return fut

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}))

    def receive(self, text: str) -> None:
        try:
            msg = json.loads(text)
        except ValueError:
            return
        if not isinstance(msg, dict) or "id" not in msg or not ("result" in msg or "error" in msg):
            return
        fut = self._pending.pop(msg["id"], None)
        if fut is None or fut.done():
            return
        if "error" in msg:
            err = msg["error"] if isinstance(msg["error"], dict) else {"message": str(msg["error"])}
            fut.set_exception(GraphicError(str(err.get("message", "graphic error"))))
        else:
            fut.set_result(msg["result"])

    def close(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RendererGone("page disconnected"))
        self._pending.clear()


@dataclass
class _Renderer:
    id: str
    name: str
    description: str
    instances: dict[str, Instance] = field(default_factory=dict)
    pages: list[_Page] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class _Problem(Exception):
    def __init__(self, status: int, title: str, detail: str = ""):
        super().__init__(detail or title)
        self.status, self.title, self.detail = status, title, detail

    def response(self) -> JSONResponse:
        body: dict[str, Any] = {"type": "about:blank", "title": self.title, "status": self.status}
        if self.detail:
            body["detail"] = self.detail
        return JSONResponse(body, status_code=self.status)


def _problems(fn):
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except _Problem as p:
            return p.response()
    return wrapper


async def _body[M: BaseModel](request: Request, model: type[M]) -> M:
    try:
        raw = await request.json()
    except ValueError as exc:
        raise _Problem(400, "Bad Request", "request body is not JSON") from exc
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise _Problem(400, "Bad Request", f"{where}: {first['msg']}") from exc


def _payload(result: Any) -> dict[str, Any]:
    # A graphic action resolving to undefined MUST be treated as { statusCode: 200 }.
    if not isinstance(result, dict):
        return {"statusCode": 200}
    return {**result, "statusCode": result.get("statusCode", 200)}


def _merge(old: Any, new: Any) -> Any:
    return {**old, **new} if isinstance(old, dict) and isinstance(new, dict) else new


# ---- server ------------------------------------------------------------------------------------

class OGrafServer:
    def __init__(self, graphics_dir: Path = GRAPHICS_DIR, renderer_dir: Path = RENDERER_DIR, *,
                 outputs: dict[str, tuple[str, str]] | None = None,
                 layers: dict[int, tuple[str, str]] | None = None,
                 resolution: tuple[int, int] = (1920, 1080), frame_rate: float = 50,
                 timeout_s: float = 5.0, name: str = "Talkback OGraf Server"):
        self.graphics_dir = Path(graphics_dir)
        self.renderer_dir = Path(renderer_dir)
        self.graphics = load_packages(self.graphics_dir)
        self.layers = {int(k): v for k, v in (layers or LAYERS).items()}
        self.renderers = {rid: _Renderer(rid, n, d) for rid, (n, d) in (outputs or OUTPUTS).items()}
        self.render_characteristics = {
            "resolution": {"width": resolution[0], "height": resolution[1]},
            "frameRate": frame_rate, "accessToPublicInternet": True,
        }
        self.timeout_s = timeout_s
        self.name = name
        self.graphics_url = "/ograf/graphics"
        self.router = self._api_router()
        self.ws_router = self._ws_router()

    def mount(self, app: FastAPI, prefix: str = "/ograf/v1", base: str = "/ograf") -> None:
        """API at `prefix`, renderer sockets at {base}/ws/{rendererId}, files under {base}/."""
        self.graphics_url = f"{base}/graphics"
        app.include_router(self.router, prefix=prefix)
        app.include_router(self.ws_router, prefix=base)
        app.mount(f"{base}/graphics", StaticFiles(directory=self.graphics_dir), name="ograf-graphics")
        app.mount(f"{base}/renderer", StaticFiles(directory=self.renderer_dir, html=True), name="ograf-renderer")

    # -- lookups

    def _renderer(self, renderer_id: str) -> _Renderer:
        r = self.renderers.get(renderer_id)
        if r is None:
            raise _Problem(404, "Not Found", f"no Renderer {renderer_id!r}")
        return r

    def _layer(self, target: Any) -> int:
        layer = target.get("layer") if isinstance(target, dict) else None
        if isinstance(layer, float) and layer.is_integer():
            layer = int(layer)
        if isinstance(layer, bool) or not isinstance(layer, int) or layer not in self.layers:
            raise _Problem(404, "Not Found", f"no RenderTarget {json.dumps(target)}")
        return layer

    def _instance(self, r: _Renderer, body: _Targeted) -> Instance:
        layer = self._layer(body.renderTarget)
        inst = r.instances.get(body.graphicInstanceId)
        if inst is None or inst.layer != layer:
            raise _Problem(404, "Not Found", f"no GraphicInstance {body.graphicInstanceId!r} on that RenderTarget")
        return inst

    def _target_schema(self) -> dict[str, Any]:
        ids = sorted(self.layers)
        return {"type": "object", "required": ["layer"], "properties": {"layer": {
            "type": "integer", "description": "Layer; higher layers render in front",
            "gddType": "select", "enum": ids, "gddOptions": {"labels": {str(i): self.layers[i][0] for i in ids}},
        }}}

    def _target_info(self, r: _Renderer, layer: int) -> dict[str, Any]:
        name, description = self.layers[layer]
        return {
            "renderTarget": {"layer": layer}, "name": name, "description": description,
            "graphicInstances": [{"graphicInstanceId": i.id, "graphic": i.graphic.list_info}
                                 for i in r.instances.values() if i.layer == layer],
        }

    def renderer_info(self, renderer_id: str) -> dict[str, Any]:
        r = self._renderer(renderer_id)
        n = len(r.pages)
        status = ({"status": "OK", "message": f"{n} page(s) connected"} if n
                  else {"status": "WARNING", "message": OFFLINE})
        return {
            "id": r.id, "name": r.name, "description": r.description, "customActions": RENDERER_ACTIONS,
            "renderCharacteristics": self.render_characteristics, "renderTargetSchema": self._target_schema(),
            "status": status, "renderTargets": [self._target_info(r, layer) for layer in sorted(self.layers)],
        }

    # -- renderer pages

    def _load_message(self, inst: Instance, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "graphicInstanceId": inst.id, "renderTarget": {"layer": inst.layer},
            "graphic": {"id": inst.graphic.id, "main": inst.graphic.main_url(self.graphics_url)},
            "params": {**params, "renderType": "realtime", "renderCharacteristics": self.render_characteristics},
        }

    async def _send_all(self, r: _Renderer, method: str, params: dict[str, Any]) -> list[asyncio.Future]:
        return [await page.request(method, params) for page in list(r.pages)]

    async def _collect(self, futures: list[asyncio.Future]) -> dict[str, Any] | None:
        """The first page's answer; None when no page is connected."""
        if not futures:
            return None
        results = await asyncio.gather(*(asyncio.wait_for(f, self.timeout_s) for f in futures),
                                       return_exceptions=True)
        for res in results:
            if not isinstance(res, BaseException):
                return _payload(res)
        for res in results:
            if isinstance(res, GraphicError):
                raise res
            if isinstance(res, TimeoutError):
                raise _Problem(500, "Renderer Timeout", f"no answer from the renderer page in {self.timeout_s:g} s")
        return None

    async def _run(self, r: _Renderer, method: str, params: dict[str, Any],
                   mutate: Callable[[], None] = lambda: None) -> dict[str, Any] | None:
        async with r.lock:
            mutate()
            futures = await self._send_all(r, method, params)
        try:
            return await self._collect(futures)
        except GraphicError as exc:
            raise _Problem(550, "Graphic Error", f"{method}() threw: {exc}") from exc

    async def attach(self, renderer_id: str, send: Callable[[str], Awaitable[None]]) -> _Page:
        """Register a page and replay the renderer's current state to it."""
        r = self.renderers[renderer_id]
        page = _Page(send)
        async with r.lock:
            await page.notify("hello", {"rendererId": r.id, "renderCharacteristics": self.render_characteristics})
            for inst in r.instances.values():
                await page.notify("load", self._load_message(inst, {"data": inst.data}))
                if inst.step is not None:
                    await page.notify("playAction", {"graphicInstanceId": inst.id,
                                                     "params": {"goto": inst.step, "skipAnimation": True}})
            r.pages.append(page)
        return page

    def detach(self, renderer_id: str, page: _Page) -> None:
        r = self.renderers[renderer_id]
        if page in r.pages:
            r.pages.remove(page)
        page.close()

    def _ws_router(self) -> APIRouter:
        router = APIRouter()

        @router.websocket("/ws/{renderer_id}")
        async def renderer_socket(websocket: WebSocket, renderer_id: str) -> None:
            if renderer_id not in self.renderers:
                await websocket.close(code=4404)
                return
            await websocket.accept()
            page = await self.attach(renderer_id, websocket.send_text)
            try:
                while True:
                    page.receive(await websocket.receive_text())
            except WebSocketDisconnect:
                pass
            finally:
                self.detach(renderer_id, page)

        return router

    # -- the Server API

    def _api_router(self) -> APIRouter:
        router = APIRouter(tags=["OGraf Server API"])

        @router.get("")
        @router.get("/")
        async def server_info() -> dict[str, Any]:
            return {"name": self.name, "version": "1.0",
                    "description": "Spec-compliant OGraf v1 server with one browser renderer per output",
                    "author": {"name": "Talkback"}}

        @router.get("/graphics")
        async def list_graphics() -> dict[str, Any]:
            return {"graphics": [g.list_info for g in self.graphics.values()]}

        @router.get("/graphics/{graphicId}")
        @_problems
        async def get_graphic(graphicId: str):
            g = self.graphics.get(graphicId)
            if g is None:
                raise _Problem(404, "Not Found", f"no Graphic {graphicId!r}")
            stamp = datetime.fromtimestamp(g.path.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            # server-api.yaml lists `manifest` as required but only defines `graphic`; send both.
            return {"graphic": g.manifest, "manifest": g.manifest, "metadata": {"createdAt": stamp, "updatedAt": stamp}}

        @router.get("/renderers")
        async def list_renderers() -> dict[str, Any]:
            return {"renderers": [{"id": r.id, "name": r.name, "description": r.description}
                                  for r in self.renderers.values()]}

        @router.get("/renderers/{rendererId}")
        @_problems
        async def get_renderer(rendererId: str):
            return {"renderer": self.renderer_info(rendererId)}

        @router.get("/renderers/{rendererId}/target")
        @_problems
        async def get_target(rendererId: str, renderTarget: str | None = None):
            r = self._renderer(rendererId)
            if renderTarget is None:
                raise _Problem(400, "Bad Request", "renderTarget query parameter is required")
            try:
                target = json.loads(renderTarget)
            except ValueError as exc:
                raise _Problem(400, "Bad Request", "renderTarget must be a JSON-stringified RenderTargetIdentifier") from exc
            return self._target_info(r, self._layer(target))

        @router.post("/renderers/{rendererId}/customActions/{customActionId}")
        @_problems
        async def renderer_action(rendererId: str, customActionId: str, request: Request):
            r = self._renderer(rendererId)
            body = await _body(request, RendererActionBody)
            if customActionId not in {a["id"] for a in RENDERER_ACTIONS}:
                raise _Problem(404, "Not Found", f"no CustomAction {customActionId!r} on this Renderer")
            params = {"id": customActionId, **body.model_dump(exclude_none=True)}
            res = await self._run(r, "rendererAction", params)
            return {"result": {"pages": len(r.pages), **((res or {}).get("result") or {})}}

        @router.put("/renderers/{rendererId}/target/graphicInstance/clear")
        @_problems
        async def clear(rendererId: str, request: Request):
            r = self._renderer(rendererId)
            body = await _body(request, ClearBody)
            gone = [i for i in r.instances.values() if not body.filters or any(self._matches(i, f) for f in body.filters)]

            def drop() -> None:
                for i in gone:
                    r.instances.pop(i.id, None)

            if gone:
                try:
                    await self._run(r, "clear", {"graphicInstanceIds": [i.id for i in gone]}, drop)
                except _Problem as p:
                    log.warning("renderer %s clear: %s", r.id, p)
            return {"graphicInstances": [{"renderTarget": {"layer": i.layer}, "graphicInstanceId": i.id} for i in gone]}

        @router.post("/renderers/{rendererId}/target/graphicInstance/load")
        @_problems
        async def load(rendererId: str, request: Request):
            r = self._renderer(rendererId)
            body = await _body(request, LoadBody)
            layer = self._layer(body.renderTarget)
            g = self.graphics.get(body.graphicId)
            if g is None:
                raise _Problem(404, "Not Found", f"no Graphic {body.graphicId!r}")
            if not g.manifest["supportsRealTime"]:
                raise _Problem(400, "Bad Request", f"{g.id} does not support real-time rendering")
            inst = Instance(id=f"gi-{uuid.uuid4().hex[:12]}", graphic=g, layer=layer, data=body.params.data)
            message = self._load_message(inst, body.params.model_dump())
            try:
                res = await self._run(r, "load", message, lambda: r.instances.__setitem__(inst.id, inst))
            except _Problem:
                r.instances.pop(inst.id, None)
                async with r.lock:
                    for page in list(r.pages):
                        await page.notify("clear", {"graphicInstanceIds": [inst.id]})
                raise
            res = res or {"statusCode": 200, "statusMessage": OFFLINE}
            return {**res, "graphicInstanceId": inst.id}

        @router.post("/renderers/{rendererId}/target/graphicInstance/updateAction")
        @_problems
        async def update_action(rendererId: str, request: Request):
            r = self._renderer(rendererId)
            body = await _body(request, UpdateBody)
            inst = self._instance(r, body)

            def merge() -> None:
                inst.data = _merge(inst.data, body.params.data)

            res = await self._run(r, "updateAction", self._action(inst, body.params), merge)
            return {**(res or {"statusCode": 200, "statusMessage": OFFLINE}), "graphicInstanceId": inst.id}

        @router.post("/renderers/{rendererId}/target/graphicInstance/playAction")
        @_problems
        async def play_action(rendererId: str, request: Request):
            r = self._renderer(rendererId)
            body = await _body(request, PlayBody)
            inst = self._instance(r, body)
            predicted = target_step(inst.step, inst.graphic.step_count, body.params.goto, body.params.delta)

            def step() -> None:
                inst.step = predicted

            res = await self._run(r, "playAction", self._action(inst, body.params), step)
            if res is None:
                res = {"statusCode": 200, "statusMessage": OFFLINE}
            else:
                got = res.get("currentStep")
                inst.step = int(got) if isinstance(got, (int, float)) and not isinstance(got, bool) and got >= 0 else None
            return {**res, "graphicInstanceId": inst.id, "currentStep": END_STEP if inst.step is None else inst.step}

        @router.post("/renderers/{rendererId}/target/graphicInstance/stopAction")
        @_problems
        async def stop_action(rendererId: str, request: Request):
            r = self._renderer(rendererId)
            body = await _body(request, StopBody)
            inst = self._instance(r, body)

            def stop() -> None:
                inst.step = None

            res = await self._run(r, "stopAction", self._action(inst, body.params), stop)
            return {**(res or {"statusCode": 200, "statusMessage": OFFLINE}), "graphicInstanceId": inst.id}

        @router.post("/renderers/{rendererId}/target/graphicInstance/customActions/{customActionId}")
        @_problems
        async def custom_action(rendererId: str, customActionId: str, request: Request):
            r = self._renderer(rendererId)
            body = await _body(request, CustomBody)
            inst = self._instance(r, body)
            params = {"id": customActionId, **body.params.model_dump(exclude_none=True)}
            res = await self._run(r, "customAction", {"graphicInstanceId": inst.id, "params": params})
            return {**(res or {"statusCode": 200, "statusMessage": OFFLINE}), "graphicInstanceId": inst.id}

        return router

    @staticmethod
    def _action(inst: Instance, params: BaseModel) -> dict[str, Any]:
        return {"graphicInstanceId": inst.id, "params": params.model_dump(exclude_none=True)}

    def _matches(self, inst: Instance, f: _Filter) -> bool:
        if f.graphicInstanceId is not None and f.graphicInstanceId != inst.id:
            return False
        if f.graphicId is not None and f.graphicId != inst.graphic.id:
            return False
        if f.renderTarget is not None:
            try:
                return self._layer(f.renderTarget) == inst.layer
            except _Problem:
                return False
        return True


def create_app(server: OGrafServer | None = None, **kwargs: Any) -> FastAPI:
    """A standalone app: the API under /ograf/v1, renderer pages at /ograf/renderer/?renderer=<id>."""
    app = FastAPI(title="Talkback OGraf Server")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "PUT", "POST", "HEAD", "OPTIONS", "DELETE"],
                       allow_headers=["Content-Type", "Accept"], max_age=3600)
    server = server or OGrafServer(**kwargs)
    server.mount(app)
    app.state.ograf = server
    return app
