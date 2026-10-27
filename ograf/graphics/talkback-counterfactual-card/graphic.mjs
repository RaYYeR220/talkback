/**
 * Talkback counterfactual card: a metric as played against the simulated "if not",
 * with the effect and its 95% interval.
 * OGraf v1 graphic: https://ograf.ebu.io/v1/specification/docs/Specification.html
 */

// ---- talkback ograf base: keep this block identical in every graphic ----
const FRAME_W = 1920;
const FRAME_H = 1080;

const BASE_CSS = `
:host {
  position: absolute; inset: 0; display: block; overflow: hidden; pointer-events: none;
  --_font: var(--tb-font, "Inter", "Segoe UI", "Noto Sans Arabic", system-ui, sans-serif);
  --_font-display: var(--tb-font-display, var(--_font));
  --_plate: var(--tb-plate, rgba(11, 13, 17, 0.84));
  --_plate-strong: var(--tb-plate-strong, rgba(6, 7, 10, 0.94));
  --_hairline: var(--tb-hairline, rgba(255, 255, 255, 0.16));
  --_text: var(--tb-text, #f3f4f6);
  --_muted: var(--tb-muted, rgba(243, 244, 246, 0.64));
  --_accent: var(--tb-accent, #e9c46a);
  --_on-accent: var(--tb-on-accent, #111318);
  --_good: var(--tb-good, #5fd39b);
  --_bad: var(--tb-bad, #ff7b6b);
  --_track: var(--tb-track, rgba(255, 255, 255, 0.1));
  --_radius: var(--tb-radius, 2px);
  --_blur: var(--tb-blur, 12px);
  --_safe-x: var(--tb-safe-x, 96px);
  --_safe-y: var(--tb-safe-y, 54px);
  --_in: var(--tb-in-ms, 420ms);
  --_out: var(--tb-out-ms, 260ms);
  --_ease: var(--tb-ease, cubic-bezier(0.2, 0.75, 0.15, 1));
}
* { box-sizing: border-box; margin: 0; padding: 0; }
[hidden] { display: none !important; }
.frame {
  position: absolute; left: 0; top: 0; width: ${FRAME_W}px; height: ${FRAME_H}px;
  transform-origin: 0 0; transform: scale(var(--_scale, 1));
  font-family: var(--_font); color: var(--_text);
  font-feature-settings: "tnum" 1, "lnum" 1; font-variant-numeric: tabular-nums lining-nums;
  -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;
}
.plate {
  background: var(--_plate); border: 1px solid var(--_hairline); border-radius: var(--_radius);
  backdrop-filter: blur(var(--_blur)); -webkit-backdrop-filter: blur(var(--_blur));
}
.num { direction: ltr; unicode-bidi: isolate; white-space: nowrap; }
.caps { text-transform: uppercase; letter-spacing: 0.08em; }
[dir="rtl"] .caps { letter-spacing: 0; }
.root {
  position: absolute; opacity: 0; transform: translate3d(0, 12px, 0);
  transition: opacity var(--_out) ease-in, transform var(--_out) ease-in;
}
.root.on {
  opacity: 1; transform: none;
  transition: opacity var(--_in) var(--_ease), transform var(--_in) var(--_ease);
}
.cut, .cut * { transition: none !important; animation: none !important; }
@media (prefers-reduced-motion: reduce) {
  .root, .root * { transition-duration: 1ms !important; animation-duration: 1ms !important; }
}
`;

function settle(el, maxMs = 2500) {
  void el.offsetWidth;
  const running = el.getAnimations({ subtree: true })
    .filter((a) => a.effect?.getComputedTiming?.().iterations !== Infinity)
    .map((a) => a.finished.catch(() => undefined));
  return Promise.race([Promise.all(running), new Promise((ok) => setTimeout(ok, maxMs))]);
}

function text(v) {
  return v === undefined || v === null ? "" : String(v);
}

function fmt(v, decimals = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(Math.max(0, Math.min(3, decimals | 0))) : "";
}

function clamp01(v) {
  const n = Number(v);
  return Number.isFinite(n) ? Math.min(1, Math.max(0, n)) : 0;
}

class TalkbackGraphic extends HTMLElement {
  static stepCount = 1;
  static defaults = {};

  constructor() {
    super();
    this._shadow = this.attachShadow({ mode: "open" });
    this._data = {};
    this._step = undefined;
    this._root = null;
    this._resize = null;
  }

  async load({ data, renderType = "realtime", renderCharacteristics } = {}) {
    if (renderType !== "realtime") {
      return { statusCode: 400, statusMessage: "Only real-time rendering is supported" };
    }
    this._data = { ...this.constructor.defaults, ...(data && typeof data === "object" ? data : {}) };
    this._step = undefined;
    this._shadow.innerHTML = `<style>${BASE_CSS}${this.css()}</style><div class="frame">${this.markup()}</div>`;
    this._frame = this._shadow.querySelector(".frame");
    this._root = this._shadow.querySelector(".root");
    this._fit(renderCharacteristics);
    this._resize = new ResizeObserver(() => this._fit());
    this._resize.observe(this);
    await this._apply(true, {});
    return { statusCode: 200 };
  }

  async dispose() {
    this._resize?.disconnect();
    this.teardown();
    this._shadow.innerHTML = "";
    this._root = null;
    return { statusCode: 200 };
  }

  async updateAction({ data, skipAnimation = false } = {}) {
    const prev = this._data;
    this._data = { ...this._data, ...(data && typeof data === "object" ? data : {}) };
    await this._apply(skipAnimation, prev);
    return { statusCode: 200 };
  }

  async playAction({ goto, delta, skipAnimation = false } = {}) {
    const target = this._targetStep({ goto, delta });
    if (target === undefined) {
      await this._transition(false, skipAnimation);
      this._step = undefined;
      this.onStop();
      return { statusCode: 200, currentStep: undefined };
    }
    this._step = target;
    this.onPlay(skipAnimation);
    await this._transition(true, skipAnimation);
    return { statusCode: 200, currentStep: this._step };
  }

  async stopAction({ skipAnimation = false } = {}) {
    this._step = undefined;
    this.onStop();
    await this._transition(false, skipAnimation);
    return { statusCode: 200 };
  }

  async customAction({ id, payload, skipAnimation = false } = {}) {
    return this.custom(id, payload ?? {}, skipAnimation);
  }

  _targetStep({ goto, delta } = {}) {
    const count = this.constructor.stepCount;
    const target = Number.isInteger(goto) && goto >= 0
      ? goto
      : (this._step ?? -1) + (Number.isFinite(delta) ? Math.trunc(delta) : 1);
    if (count === 0 || (count > 0 && target >= count)) return undefined;
    return Math.max(0, target);
  }

  _fit(rc) {
    if (!this._frame) return;
    const w = this.clientWidth || rc?.resolution?.width || FRAME_W;
    const h = this.clientHeight || rc?.resolution?.height || FRAME_H;
    this._frame.style.setProperty("--_scale", String(Math.min(w / FRAME_W, h / FRAME_H)));
  }

  async _apply(skip, prev) {
    if (!this._root) return;
    const d = this._data;
    this._root.dir = d.dir === "rtl" ? "rtl" : "ltr";
    if (d.lang) this._root.lang = String(d.lang);
    else this._root.removeAttribute("lang");
    if (skip) this._root.classList.add("cut");
    this.render(d, prev, skip);
    if (skip) {
      void this._root.offsetWidth;
      this._root.classList.remove("cut");
    } else if (this._step !== undefined) {
      await settle(this._root);
    }
  }

  async _transition(on, skip) {
    const root = this._root;
    if (!root) return;
    if (skip) {
      root.classList.add("cut");
      root.classList.toggle("on", on);
      void root.offsetWidth;
      root.classList.remove("cut");
      return;
    }
    root.classList.toggle("on", on);
    await settle(root);
  }

  $(name) {
    return this._shadow.querySelector(`[data-f="${name}"]`);
  }

  setText(name, value, { hideEmpty = false } = {}) {
    for (const el of this._shadow.querySelectorAll(`[data-f="${name}"]`)) {
      el.textContent = text(value);
      if (hideEmpty) el.hidden = text(value) === "";
    }
  }

  css() { return ""; }
  markup() { return `<div class="root"></div>`; }
  render(_data, _prev, _skip) {}
  onPlay(_skip) {}
  onStop() {}
  teardown() {}
  custom(id) { return { statusCode: 400, statusMessage: `Unknown custom action: ${text(id)}` }; }
}
// ---- end talkback ograf base ----

export default class TalkbackCounterfactualCard extends TalkbackGraphic {
  static defaults = {
    title: "", metric: "", asPlayedLabel: "As played", ifNotLabel: "If not", asPlayed: 0, ifNot: 0,
    max: 100, unit: "%", decimals: 0, effect: "", interval: "", caption: "", evidence: "",
  };

  css() {
    return `
.cf { right: var(--_safe-x); top: 250px; width: 620px; padding: 26px 30px 0; overflow: hidden; }
.cf[dir="rtl"] { right: auto; left: var(--_safe-x); }
.metric { font-size: 15px; font-weight: 750; color: var(--_muted); }
.title { font-family: var(--_font-display); font-size: 32px; font-weight: 700; line-height: 1.18; margin-top: 8px; }
.rows { display: grid; gap: 14px; margin-top: 24px; }
.row { display: grid; grid-template-columns: 132px 1fr 92px; align-items: center; gap: 16px; }
.lbl { font-size: 18px; color: var(--_muted); }
.track { position: relative; height: 16px; background: var(--_track); border-radius: var(--_radius); }
.fill { position: absolute; inset-block: 0; inset-inline-start: 0; width: calc(var(--r, 0) * 100%); border-radius: var(--_radius); transition: width 760ms var(--_ease) 140ms; }
.root:not(.on) .fill { width: 0; }
.a .fill { background: var(--_text); }
.b .fill { border: 1px solid var(--_accent); background: repeating-linear-gradient(135deg, var(--_accent) 0 5px, transparent 5px 10px); }
.val { font-size: 28px; font-weight: 700; text-align: end; }
.effect { display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px 16px; margin-top: 24px; }
.big { font-family: var(--_font-display); font-size: 56px; font-weight: 750; line-height: 1; color: var(--_accent); }
.ci { font-size: 19px; color: var(--_muted); }
.caption { font-size: 22px; line-height: 1.38; margin-top: 16px; }
.evidence { margin: 22px -30px 0; padding: 10px 30px 12px; border-top: 1px solid var(--_hairline); font-size: 15px; letter-spacing: 0.02em; color: var(--_muted); text-align: start; }
`;
  }

  markup() {
    return `
<div class="root cf plate">
  <div class="metric caps" data-f="metric"></div>
  <div class="title" data-f="title"></div>
  <div class="rows">
    <div class="row a"><span class="lbl" data-f="asPlayedLabel"></span><div class="track"><div class="fill"></div></div><span class="val num" data-f="asPlayedText"></span></div>
    <div class="row b"><span class="lbl" data-f="ifNotLabel"></span><div class="track"><div class="fill"></div></div><span class="val num" data-f="ifNotText"></span></div>
  </div>
  <div class="effect"><span class="big num" data-f="effect"></span><span class="ci num" data-f="interval"></span></div>
  <div class="caption" data-f="caption"></div>
  <div class="evidence num" data-f="evidence"></div>
</div>`;
  }

  render(d) {
    for (const f of ["metric", "title", "effect", "interval", "caption", "evidence"]) this.setText(f, d[f], { hideEmpty: true });
    this.setText("asPlayedLabel", d.asPlayedLabel);
    this.setText("ifNotLabel", d.ifNotLabel);
    const max = Number(d.max) > 0 ? Number(d.max) : 100;
    this.setText("asPlayedText", `${fmt(d.asPlayed, d.decimals)}${text(d.unit)}`);
    this.setText("ifNotText", `${fmt(d.ifNot, d.decimals)}${text(d.unit)}`);
    this._shadow.querySelector(".a .track").style.setProperty("--r", String(clamp01(Number(d.asPlayed) / max)));
    this._shadow.querySelector(".b .track").style.setProperty("--r", String(clamp01(Number(d.ifNot) / max)));
  }
}
