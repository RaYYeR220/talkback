import world from "@/data/world.json";
import type { Fixture } from "./types";

// Snapshot of the fictional league (club names, colours, squad numbers), produced by
// `node scripts/sync-world.mjs <run>/world.json`. Live fixtures from the stream win over it.

interface ClubInfo {
  name: string;
  short: string;
  city: string;
  primary: string;
  secondary: string;
}

const CLUBS = world.clubs as Record<string, ClubInfo>;
const PLAYERS = world.players as unknown as Record<string, [string, number, string]>;

export const LEAGUE_NAME: string = world.league;
export const SEASON: string = world.season;

export function club(id: string | null | undefined): ClubInfo | undefined {
  return id ? CLUBS[id] : undefined;
}

export function clubName(id: string | null | undefined, fixtures?: Record<string, Fixture>): string {
  if (!id) return "";
  if (fixtures) {
    for (const f of Object.values(fixtures)) {
      if (f.home === id) return f.home_name;
      if (f.away === id) return f.away_name;
    }
  }
  return CLUBS[id]?.name ?? id;
}

export function clubShort(id: string | null | undefined): string {
  if (!id) return "";
  return CLUBS[id]?.short ?? id.slice(0, 3).toUpperCase();
}

export function allClubs(): { id: string; name: string }[] {
  return Object.entries(CLUBS)
    .map(([id, c]) => ({ id, name: c.name }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** "C10-P21" → "C10". */
export function clubOfPlayer(playerId: string): string {
  const i = playerId.indexOf("-");
  return i > 0 ? playerId.slice(0, i) : playerId;
}

export function player(id: string): { name: string; shirt: number; position: string } | undefined {
  const p = PLAYERS[id];
  return p ? { name: p[0], shirt: p[1], position: p[2] } : undefined;
}

function hexToRgb(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Black or white, whichever reads better on `hex` (for shirt numbers). */
export function inkOn(hex: string, light = "#ffffff", dark = "#111111"): string {
  const c = hexToRgb(hex);
  if (!c) return light;
  const [r, g, b] = c.map((v) => {
    const x = v / 255;
    return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
  });
  const L = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return L > 0.3 ? dark : light;
}

function distance(a: string, b: string): number {
  const x = hexToRgb(a);
  const y = hexToRgb(b);
  if (!x || !y) return 999;
  return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]);
}

/**
 * Kit colours for a fixture: [fill, trim] per side. The away side switches to its
 * second colour when the two primaries are too close to tell apart on the pitch.
 */
export function kitColours(
  homeId: string,
  awayId: string,
  fallback: { home: string; away: string },
): { home: [string, string]; away: [string, string] } {
  const h = CLUBS[homeId];
  const a = CLUBS[awayId];
  const home: [string, string] = h ? [h.primary, h.secondary] : [fallback.home, fallback.home];
  let away: [string, string] = a ? [a.primary, a.secondary] : [fallback.away, fallback.away];
  if (distance(home[0], away[0]) < 110) away = [away[1], away[0]];
  return { home, away };
}
