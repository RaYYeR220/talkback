/**
 * OGraf renderer page. `?renderer=<id>` connects to the Talkback OGraf Server over a WebSocket
 * (JSON-RPC 2.0) and runs its commands on the graphics' web components, one layer per
 * RenderTarget, on a transparent 1920x1080 stage. `?demo=1` plays a local sample rundown instead.
 *
 * Options: server=<url of the /ograf/ base>, bg=grey|checker|pitch, debug=1, fonts=0, rtl=1, ifb=1.
 */

const q = new URLSearchParams(location.search);
const rendererId = q.get("renderer") || "world";
const base = new URL(q.get("server") || "../", location.href);
const stage = document.getElementById("stage");
const badge = document.getElementById("badge");
const RC = { resolution: { width: 1920, height: 1080 }, frameRate: 50, accessToPublicInternet: true };

if (q.get("bg")) document.body.classList.add(`bg-${q.get("bg")}`);
if (q.get("debug")) document.body.classList.add("debug");
if (q.get("fonts") !== "0") {
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = "https://fonts.googleapis.com/css2?family=Inter:wght@400..800&family=Noto+Sans+Arabic:wght@400..800&display=swap";
  document.head.append(link);
}

function fit() {
  const s = Math.min(innerWidth / 1920, innerHeight / 1080);
  stage.style.transform = `translate(${(innerWidth - 1920 * s) / 2}px, ${(innerHeight - 1080 * s) / 2}px) scale(${s})`;
}
addEventListener("resize", fit);
fit();

let lastStatus = "";

function status(msg) {
  lastStatus = `${rendererId} · ${msg}`;
  if (!badge.classList.contains("identify")) badge.textContent = lastStatus;
}

// ---- graphics ----------------------------------------------------------------------------------

const tags = new Map();
let tagSeq = 0;

function tagFor(url) {
  if (!tags.has(url)) {
    const p = import(url).then((mod) => {
      if (typeof mod.default !== "function") throw new Error(`${url} has no default export`);
      const tag = `ograf-graphic-${++tagSeq}`;
      customElements.define(tag, mod.default);
      return tag;
    });
    p.catch(() => tags.delete(url));
    tags.set(url, p);
  }
  return tags.get(url);
}

const instances = new Map();

function layerFor(target) {
  const z = Number(target?.layer) || 0;
  let el = stage.querySelector(`:scope > .layer[data-layer="${z}"]`);
  if (!el) {
    el = document.createElement("div");
    el.className = "layer";
    el.dataset.layer = String(z);
    el.style.zIndex = String(z);
    stage.append(el);
  }
  return el;
}

const ok = (r) => (r === undefined || r === null ? { statusCode: 200 } : r);

async function disposeEntry(entry) {
  await entry.ready.catch(() => undefined);
  if (!entry.el) return;
  entry.el.remove();
  try {
    await entry.el.dispose({});
  } catch (err) {
    console.warn("dispose failed", err);
  }
}

function drop(id) {
  const entry = instances.get(id);
  if (!entry) return Promise.resolve();
  instances.delete(id);
  return disposeEntry(entry);
}

function action(method) {
  return async ({ graphicInstanceId, params }) => {
    const entry = instances.get(graphicInstanceId);
    if (!entry) throw new Error(`No graphicInstance ${graphicInstanceId}`);
    await entry.ready;
    return ok(await entry.el[method](params ?? {}));
  };
}

export const handlers = {
  hello({ rendererId: id }) {
    status(`connected to ${id}`);
  },
  load({ graphicInstanceId, renderTarget, graphic, params }) {
    const prior = instances.get(graphicInstanceId);
    const entry = { el: null, graphic: graphic.id, layer: renderTarget?.layer };
    entry.ready = (async () => {
      if (prior) await disposeEntry(prior);
      const tag = await tagFor(new URL(graphic.main, base).href);
      const el = document.createElement(tag);
      el.dataset.graphic = graphic.id;
      el.dataset.instance = graphicInstanceId;
      entry.el = el;
      layerFor(renderTarget).append(el);
      return el.load({ renderType: "realtime", renderCharacteristics: RC, ...params });
    })();
    instances.set(graphicInstanceId, entry);
    return entry.ready.then(ok);
  },
  updateAction: action("updateAction"),
  playAction: action("playAction"),
  stopAction: action("stopAction"),
  customAction: action("customAction"),
  async clear({ graphicInstanceIds = [] }) {
    await Promise.all(graphicInstanceIds.map(drop));
    return { statusCode: 200 };
  },
  rendererAction({ id }) {
    if (id !== "identify") throw new Error(`Unknown renderer action ${id}`);
    badge.textContent = rendererId;
    badge.classList.add("identify");
    setTimeout(() => {
      badge.classList.remove("identify");
      badge.textContent = lastStatus;
    }, 3000);
    return { statusCode: 200, result: { rendererId } };
  },
};

function resetLocal() {
  for (const id of [...instances.keys()]) drop(id);
}

// ---- server link -------------------------------------------------------------------------------

function onMessage(ws, raw) {
  let msg;
  try {
    msg = JSON.parse(raw);
  } catch {
    return;
  }
  if (!msg || typeof msg.method !== "string") return;
  const reply = (body) => {
    if (msg.id !== undefined && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ jsonrpc: "2.0", id: msg.id, ...body }));
  };
  const fn = handlers[msg.method];
  if (!fn) {
    reply({ error: { code: -32601, message: `Unknown method ${msg.method}` } });
    return;
  }
  let pending;
  try {
    pending = Promise.resolve(fn(msg.params || {}));
  } catch (err) {
    pending = Promise.reject(err);
  }
  pending.then(
    (result) => reply({ result: result ?? null }),
    (err) => {
      console.error(msg.method, err);
      reply({ error: { code: -32000, message: String(err?.message || err) } });
    },
  );
}

let retry = 0;

function connect() {
  const url = new URL(`ws/${encodeURIComponent(rendererId)}`, base);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(url);
  ws.addEventListener("open", () => {
    retry = 0;
    resetLocal();
    status("connected");
  });
  ws.addEventListener("message", (ev) => onMessage(ws, ev.data));
  ws.addEventListener("close", () => {
    status("offline");
    setTimeout(connect, Math.min(5000, 250 * 2 ** retry++));
  });
}

window.ograf = { rendererId, instances, handlers };

if (q.get("demo")) {
  status("demo");
  const rtl = q.get("rtl") === "1" || rendererId === "mena";
  const ifb = q.get("ifb") === "1" || rendererId === "presenter";
  import("./demo.mjs").then((demo) => demo.run({ handlers, rtl, ifb }));
} else {
  status("connecting");
  connect();
}
