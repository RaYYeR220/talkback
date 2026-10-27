"use client";

import { useEffect, useRef } from "react";
import { useFrames } from "@/lib/frames";
import { usePrefersReducedMotion } from "@/lib/hooks";
import { clubOfPlayer, inkOn, kitColours, player } from "@/lib/world";
import styles from "./PitchCanvas.module.css";

const L = 105;
const W = 68;

interface Props {
  matchId: string | null;
  home: string;
  away: string;
  hz: number;
  delayMs?: number;
  /** Interpolate between polled frames every animation frame (program monitor). */
  smooth?: boolean;
  /** Draw shirt numbers on the players. */
  numbers?: boolean;
  label: string;
  className?: string;
}

interface Palette {
  pitch: string;
  stripe: string;
  line: string;
  ink: string;
  shadow: string;
  homeFallback: string;
  awayFallback: string;
  mono: string;
  faint: string;
}

function readPalette(el: Element): Palette {
  const cs = getComputedStyle(el);
  const v = (name: string, fb: string) => cs.getPropertyValue(name).trim() || fb;
  return {
    pitch: v("--pitch", "#16201a"),
    stripe: v("--pitch-stripe", "#19241d"),
    line: v("--pitch-line", "rgba(255,255,255,.25)"),
    ink: v("--pitch-ink", "#f4f3ee"),
    shadow: v("--pitch-shadow", "rgba(0,0,0,.45)"),
    homeFallback: v("--home-fallback", "#e8e6df"),
    awayFallback: v("--away-fallback", "#ff6b35"),
    mono: v("--font-mono", "monospace"),
    faint: v("--fg-faint", "#6d6c66"),
  };
}

function drawPitch(ctx: CanvasRenderingContext2D, w: number, h: number, p: Palette) {
  const sx = w / L;
  const sy = h / W;
  ctx.fillStyle = p.pitch;
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = p.stripe;
  for (let i = 0; i < 12; i += 2) ctx.fillRect((i * w) / 12, 0, w / 12, h);

  ctx.strokeStyle = p.line;
  ctx.lineWidth = Math.max(1, w / 520);
  const inset = ctx.lineWidth / 2;
  ctx.strokeRect(inset, inset, w - 2 * inset, h - 2 * inset);
  ctx.beginPath();
  ctx.moveTo(w / 2, 0);
  ctx.lineTo(w / 2, h);
  ctx.stroke();
  ctx.beginPath();
  ctx.ellipse(w / 2, h / 2, 9.15 * sx, 9.15 * sy, 0, 0, Math.PI * 2);
  ctx.stroke();
  // penalty and goal areas
  const boxW = 16.5 * sx;
  const boxH = 40.32 * sy;
  const sixW = 5.5 * sx;
  const sixH = 18.32 * sy;
  ctx.strokeRect(inset, (h - boxH) / 2, boxW, boxH);
  ctx.strokeRect(w - boxW - inset, (h - boxH) / 2, boxW, boxH);
  ctx.strokeRect(inset, (h - sixH) / 2, sixW, sixH);
  ctx.strokeRect(w - sixW - inset, (h - sixH) / 2, sixW, sixH);
  ctx.fillStyle = p.line;
  for (const x of [11 * sx, w / 2, w - 11 * sx]) {
    ctx.beginPath();
    ctx.arc(x, h / 2, Math.max(1, w / 400), 0, Math.PI * 2);
    ctx.fill();
  }
}

export function PitchCanvas({ matchId, home, away, hz, delayMs = 0, smooth = false, numbers = false, label, className }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frames = useFrames(matchId, hz, delayMs);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let palette = readPalette(canvas);
    let paletteAt = performance.now();
    let kits = kitColours(home, away, { home: palette.homeFallback, away: palette.awayFallback });
    let cssW = 0;
    let cssH = 0;
    let dirty = true;
    let drawnVersion = -1;
    let raf = 0;
    const interpolate = smooth && !reduced;

    const resize = () => {
      const r = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      cssW = r.width;
      cssH = r.height;
      canvas.width = Math.max(1, Math.round(r.width * dpr));
      canvas.height = Math.max(1, Math.round(r.height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      dirty = true;
    };
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();

    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      if (now - paletteAt > 2000) {
        palette = readPalette(canvas);
        kits = kitColours(home, away, { home: palette.homeFallback, away: palette.awayFallback });
        paletteAt = now;
        dirty = true;
      }
      const b = frames.current;
      const k = interpolate && b.prev ? Math.min(1, Math.max(0, (now - b.at) / b.interval)) : 1;
      if (!dirty && b.version === drawnVersion && k >= 1) return;
      dirty = false;
      drawnVersion = b.version;
      const w = cssW;
      const h = cssH;
      if (!w || !h) return;
      drawPitch(ctx, w, h, palette);
      const next = b.next;
      if (!next) {
        ctx.fillStyle = palette.faint;
        ctx.font = `${Math.max(10, w / 48)}px ${palette.mono}`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(matchId ? "waiting for tracking" : "no match selected", w / 2, h / 2);
        return;
      }
      const sx = w / L;
      const sy = h / W;
      const prevPos = new Map<string, [number, number]>();
      if (k < 1 && b.prev) b.prev.ids.forEach((id, i) => prevPos.set(id, b.prev!.pos[i]));
      const r = Math.max(2, Math.min(10, sx * (numbers ? 1.2 : 1.05)));
      ctx.lineWidth = Math.max(1, r / 4);
      for (let i = 0; i < next.ids.length; i++) {
        const id = next.ids[i];
        let [x, y] = next.pos[i];
        const p = prevPos.get(id);
        if (p) {
          x = p[0] + (x - p[0]) * k;
          y = p[1] + (y - p[1]) * k;
        }
        const kit = clubOfPlayer(id) === home ? kits.home : kits.away;
        const px = x * sx;
        const py = y * sy;
        ctx.beginPath();
        ctx.arc(px, py, r, 0, Math.PI * 2);
        ctx.fillStyle = kit[0];
        ctx.fill();
        ctx.strokeStyle = kit[1];
        ctx.stroke();
        if (numbers && r >= 6) {
          const shirt = player(id)?.shirt;
          if (shirt !== undefined) {
            ctx.fillStyle = inkOn(kit[0], palette.ink, palette.pitch);
            ctx.font = `600 ${Math.round(r * 1.05)}px ${palette.mono}`;
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText(String(shirt), px, py + 0.5);
          }
        }
      }
      // ball (z lifts it: shadow stays on the ground)
      let [bx, by, bz] = next.ball;
      if (k < 1 && b.prev) {
        const [px, py, pz] = b.prev.ball;
        bx = px + (bx - px) * k;
        by = py + (by - py) * k;
        bz = pz + (bz - pz) * k;
      }
      const br = Math.max(1.6, r * 0.55);
      ctx.fillStyle = palette.shadow;
      ctx.beginPath();
      ctx.arc(bx * sx, by * sy, br, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = palette.ink;
      ctx.beginPath();
      ctx.arc(bx * sx, by * sy - Math.min(bz, 8) * sy * 0.6, br, 0, Math.PI * 2);
      ctx.fill();
    };
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [frames, home, away, smooth, reduced, numbers, matchId]);

  return (
    <canvas ref={canvasRef} className={`${styles.canvas} ${className ?? ""}`} role="img" aria-label={label} />
  );
}
