/**
 * Talkback scorebug: one match, score, clock, optional "as it stands" flag and an
 * "elsewhere" ticker that cycles the other matches of the round.
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

const TICK_MS = 4000;

function clock(d) {
  if (text(d.status)) return text(d.status);
  const added = Number(d.addedTime) > 0 ? `+${Number(d.addedTime)}` : "";
  return `${Number(d.minute) || 0}${added}′`;
}

function scoreline(m) {
  const minute = Number.isFinite(Number(m.minute)) && m.minute !== undefined ? ` ${Number(m.minute)}′` : "";
  return `${text(m.homeShort)} ${text(m.homeScore ?? 0)}–${text(m.awayScore ?? 0)} ${text(m.awayShort)}${minute}`;
}

export default class TalkbackScorebug extends TalkbackGraphic {
  static defaults = {
    homeShort: "CAL", awayShort: "ASH", homeScore: 0, awayScore: 0, minute: 0, addedTime: 0, status: "",
    homeColor: "", awayColor: "", asItStands: false, asItStandsLabel: "AS IT STANDS", elsewhere: [],
  };

  css() {
    return `
.bug { left: var(--_safe-x); top: var(--_safe-y); display: flex; flex-direction: column; align-items: flex-start; gap: 6px; }
.bug[dir="rtl"] { left: auto; right: var(--_safe-x); align-items: flex-end; }
.row { display: flex; align-items: stretch; height: 50px; font-size: 26px; font-weight: 650; overflow: hidden; }
.team { display: flex; align-items: center; gap: 12px; padding-inline: 16px; min-width: 104px; letter-spacing: 0.04em; }
.chip { width: 4px; align-self: stretch; margin-block: 11px; border-radius: 1px; background: var(--c, var(--_accent)); }
.score { display: flex; align-items: center; gap: 2px; padding-inline: 8px; background: var(--_plate-strong); border-inline: 1px solid var(--_hairline); font-weight: 750; }
.digit { min-width: 1.15em; padding: 3px 6px; text-align: center; border-radius: var(--_radius); }
.sep { color: var(--_muted); font-weight: 500; }
.digit.flash { animation: flash 900ms var(--_ease); }
@keyframes flash { 0%, 35% { background: var(--_accent); color: var(--_on-accent); } 100% { background: transparent; color: inherit; } }
.clock { display: flex; align-items: center; justify-content: center; min-width: 96px; padding-inline: 16px; border-inline-start: 1px solid var(--_hairline); color: var(--_muted); font-weight: 550; }
.ais { font-size: 15px; font-weight: 800; color: var(--_on-accent); background: var(--_accent); padding: 4px 10px; border-radius: var(--_radius); }
.elsewhere { font-size: 18px; font-weight: 550; padding: 6px 12px; color: var(--_muted); transition: opacity 220ms ease; }
.elsewhere.swap { opacity: 0; }
`;
  }

  markup() {
    return `
<div class="root bug">
  <div class="row plate">
    <span class="team home"><i class="chip" data-c="home"></i><span data-f="homeShort"></span></span>
    <span class="score"><span class="digit num" data-f="homeScore"></span><span class="sep">–</span><span class="digit num" data-f="awayScore"></span></span>
    <span class="team away"><span data-f="awayShort"></span><i class="chip" data-c="away"></i></span>
    <span class="clock num" data-f="clock"></span>
  </div>
  <div class="ais caps" data-f="asItStandsLabel"></div>
  <div class="elsewhere plate num" data-f="elsewhere"></div>
</div>`;
  }

  render(d, prev, skip) {
    for (const f of ["homeShort", "awayShort", "homeScore", "awayScore"]) this.setText(f, d[f]);
    this.setText("clock", clock(d));
    this._shadow.querySelector('[data-c="home"]').style.setProperty("--c", text(d.homeColor) || "var(--_accent)");
    this._shadow.querySelector('[data-c="away"]').style.setProperty("--c", text(d.awayColor) || "var(--_accent)");
    this.setText("asItStandsLabel", d.asItStands ? d.asItStandsLabel : "", { hideEmpty: true });
    const others = Array.isArray(d.elsewhere) ? d.elsewhere : [];
    if (others !== prev.elsewhere) this._tick = 0;
    this._showElsewhere();
    if (!skip && prev.homeScore !== undefined) {
      if (Number(d.homeScore) > Number(prev.homeScore)) this._flash("home");
      if (Number(d.awayScore) > Number(prev.awayScore)) this._flash("away");
    }
  }

  _showElsewhere() {
    const others = Array.isArray(this._data.elsewhere) ? this._data.elsewhere : [];
    const el = this.$("elsewhere");
    el.hidden = others.length === 0;
    if (others.length) el.textContent = scoreline(others[(this._tick ?? 0) % others.length]);
  }

  _flash(side) {
    const el = this.$(side === "away" ? "awayScore" : "homeScore");
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
    return el;
  }

  onPlay() {
    clearInterval(this._timer);
    this._timer = setInterval(() => {
      const others = Array.isArray(this._data.elsewhere) ? this._data.elsewhere : [];
      if (others.length < 2) return;
      const el = this.$("elsewhere");
      el.classList.add("swap");
      setTimeout(() => {
        this._tick = (this._tick ?? 0) + 1;
        this._showElsewhere();
        el.classList.remove("swap");
      }, 230);
    }, TICK_MS);
  }

  onStop() {
    clearInterval(this._timer);
  }

  teardown() {
    clearInterval(this._timer);
  }

  async custom(id, payload, skip) {
    if (id !== "flash") return { statusCode: 400, statusMessage: `Unknown custom action: ${text(id)}` };
    const el = this._flash(payload.side === "away" ? "away" : "home");
    if (!skip) await settle(el);
    return { statusCode: 200 };
  }
}
