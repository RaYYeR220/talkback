"use client";

import { useEffect, useRef } from "react";
import { api } from "./api";
import { useGallery, useSimClock } from "./stream";
import type { FrameResponse } from "./types";

export interface FrameBuffer {
  prev: FrameResponse | null;
  next: FrameResponse | null;
  /** performance.now() when `next` arrived */
  at: number;
  interval: number;
  /** bumps on every new frame so passive canvases know when to redraw */
  version: number;
}

const empty = (hz: number): FrameBuffer => ({ prev: null, next: null, at: 0, interval: 1000 / hz, version: 0 });

/**
 * Polls /api/frames for one match at `hz`, at the gallery's current match time minus
 * `delayMs` (delayed outputs see the pitch as their viewers do). The result is a ref so
 * the canvas can interpolate in its own animation loop without re-rendering React.
 */
export function useFrames(matchId: string | null, hz: number, delayMs = 0) {
  const simNow = useSimClock();
  const { state } = useGallery();
  const buf = useRef<FrameBuffer>(empty(hz));
  // No polling while the stream is down: the service is probably unreachable too.
  const online = useRef(state.connection === "open");
  useEffect(() => {
    online.current = state.connection === "open";
  }, [state.connection]);

  useEffect(() => {
    buf.current = empty(hz);
    if (!matchId) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let ctrl: AbortController | null = null;
    let failures = 0;
    const period = 1000 / hz;

    const tick = async () => {
      if (stopped) return;
      if (document.hidden || !online.current) {
        timer = setTimeout(tick, 1000);
        return;
      }
      const started = performance.now();
      ctrl = new AbortController();
      try {
        const f = await api.frame(matchId, simNow() - delayMs, ctrl.signal);
        if (stopped) return;
        failures = 0;
        const b = buf.current;
        if (!b.next || f.t !== b.next.t) {
          buf.current = { prev: b.next, next: f, at: performance.now(), interval: period, version: b.version + 1 };
        }
      } catch {
        failures += 1;
      }
      if (stopped) return;
      const wait = failures ? Math.min(5000, period * 2 ** failures) : Math.max(0, period - (performance.now() - started));
      timer = setTimeout(tick, wait);
    };
    tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
      ctrl?.abort();
    };
  }, [matchId, hz, delayMs, simNow]);

  return buf;
}
