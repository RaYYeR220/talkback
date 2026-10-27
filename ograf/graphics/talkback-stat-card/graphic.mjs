/**
 * Talkback stat card: one headline stat with a comparison bar and an evidence footer.
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

export default class TalkbackStatCard extends TalkbackGraphic {
  static defaults = {
    subject: "", label: "", value: "", unit: "", ratio: 0, compareLabel: "", compareValue: "",
    compareRatio: -1, caption: "", evidence: "",
  };

  css() {
    return `
.card { right: var(--_safe-x); top: 268px; width: 560px; padding: 26px 30px 0; overflow: hidden; }
.card[dir="rtl"] { right: auto; left: var(--_safe-x); }
.subject { font-size: 15px; font-weight: 750; color: var(--_muted); }
.label { font-size: 26px; font-weight: 600; line-height: 1.25; margin-top: 6px; }
.value { display: flex; align-items: baseline; gap: 10px; margin-top: 12px; font-family: var(--_font-display); }
.value .num { font-size: 108px; font-weight: 750; line-height: 1; letter-spacing: -0.02em; }
.unit { font-size: 32px; font-weight: 600; color: var(--_muted); }
.track { position: relative; height: 8px; margin-top: 22px; background: var(--_track); border-radius: var(--_radius); }
.fill { position: absolute; inset-block: 0; inset-inline-start: 0; width: calc(var(--r, 0) * 100%); background: var(--_accent); border-radius: var(--_radius); transition: width 720ms var(--_ease) 120ms; }
.root:not(.on) .fill { width: 0; }
.mark { position: absolute; top: -6px; bottom: -6px; width: 2px; inset-inline-start: calc(var(--c, 0) * 100%); background: var(--_text); }
.cmp { display: flex; justify-content: space-between; gap: 16px; margin-top: 10px; font-size: 17px; color: var(--_muted); }
.caption { font-size: 22px; line-height: 1.38; margin-top: 18px; }
.evidence { margin: 22px -30px 0; padding: 10px 30px 12px; border-top: 1px solid var(--_hairline); font-size: 15px; letter-spacing: 0.02em; color: var(--_muted); text-align: start; }
`;
  }

  markup() {
    return `
<div class="root card plate">
  <div class="subject caps" data-f="subject"></div>
  <div class="label" data-f="label"></div>
  <div class="value"><span class="num" data-f="value"></span><span class="unit" data-f="unit"></span></div>
  <div class="bar" data-f="bar">
    <div class="track"><div class="fill"></div><div class="mark"></div></div>
    <div class="cmp" data-f="cmp"><span data-f="compareLabel"></span><span class="num" data-f="compareValue"></span></div>
  </div>
  <div class="caption" data-f="caption"></div>
  <div class="evidence num" data-f="evidence"></div>
</div>`;
  }

  render(d) {
    for (const f of ["subject", "label", "value", "unit", "caption", "evidence"]) this.setText(f, d[f], { hideEmpty: true });
    this.setText("compareLabel", d.compareLabel);
    this.setText("compareValue", d.compareValue);
    const hasCompare = Number(d.compareRatio) >= 0;
    const track = this._shadow.querySelector(".track");
    track.style.setProperty("--r", String(clamp01(d.ratio)));
    track.style.setProperty("--c", String(clamp01(d.compareRatio)));
    this._shadow.querySelector(".mark").hidden = !hasCompare;
    this.$("cmp").hidden = !(text(d.compareLabel) || text(d.compareValue));
    this.$("bar").hidden = !(Number(d.ratio) > 0 || hasCompare);
  }
}
