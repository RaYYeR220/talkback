export function pct(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "–";
  const v = x * 100;
  if (v > 0 && v < 1 && digits === 0) return "<1%";
  if (v < 100 && v > 99 && digits === 0) return ">99%";
  return `${v.toFixed(digits)}%`;
}

export function signedPts(delta: number, digits = 0): string {
  const v = delta * 100;
  const s = v.toFixed(digits);
  return `${v > 0 ? "+" : v < 0 ? "−" : "±"}${s.replace("-", "")} pts`;
}

/** Match-time ms → "mm:ss". */
export function matchClock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function minuteLabel(minute: number | undefined, finished = false): string {
  if (finished) return "FT";
  if (minute === undefined) return "–";
  if (minute <= 0) return "KO";
  return `${minute}′`;
}

export function duration(ms: number | undefined | null): string {
  if (ms === undefined || ms === null) return "–";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

export function num(x: number | null | undefined, digits = 2): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "–";
  if (Number.isInteger(x)) return String(x);
  return x.toFixed(digits);
}

export function windowLabel(w: [number, number] | undefined): string {
  if (!w) return "–";
  return `${matchClock(w[0])}–${matchClock(w[1])}`;
}

export function humanise(id: string): string {
  return id.replace(/[_.]+/g, " ").replace(/\s+/g, " ").trim();
}

export function countdown(msLeft: number): string {
  const s = Math.max(0, Math.ceil(msLeft / 1000));
  return `0:${String(s).padStart(2, "0")}`;
}
