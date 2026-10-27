import type { AiredItem, GalleryState, ScorePoint, TimedCue } from "./stream";
import { TERRITORY } from "./territories";
import type { Output, Story, Verdict } from "./types";
import { clubName, clubShort } from "./world";

export function matchName(s: GalleryState, id: string | null | undefined): string {
  if (!id) return "";
  const f = s.fixtures[id];
  if (f) return `${f.home_name} v ${f.away_name}`;
  const sc = s.scores[id];
  if (sc) return `${clubName(sc.home)} v ${clubName(sc.away)}`;
  return id;
}

export function matchShort(s: GalleryState, id: string | null | undefined): string {
  if (!id) return "";
  const f = s.fixtures[id];
  if (f) return `${clubShort(f.home)} v ${clubShort(f.away)}`;
  const sc = s.scores[id];
  if (sc) return `${sc.home_short} v ${sc.away_short}`;
  return id;
}

export function sides(s: GalleryState, id: string): { home: string; away: string } | null {
  const f = s.fixtures[id];
  if (f) return { home: f.home, away: f.away };
  const sc = s.scores[id];
  return sc ? { home: sc.home, away: sc.away } : null;
}

/** The score as it stood at match time `t` (for delayed outputs). */
export function scoreAt(s: GalleryState, id: string, t: number): ScorePoint | null {
  const log = s.scoreLog[id];
  if (!log?.length) return null;
  let best: ScorePoint | null = null;
  for (const p of log) {
    if (p.sim_t <= t) best = p;
    else break;
  }
  return best;
}

export function minuteAt(s: GalleryState, id: string, simNow: number): number | undefined {
  const m = s.minutes[id];
  if (!m) return simNow > 0 ? Math.floor(simNow / 60_000) : undefined;
  return m.minute + Math.max(0, Math.floor((simNow - m.sim_t) / 60_000));
}

export function delayFor(output: Output): number {
  return TERRITORY[output].delayMs;
}

/**
 * Lines that have aired on an output, oldest first, as seen at match time `t`. The world feed is the international
 * English output, so it carries exactly what cleared for the UK: a line killed in English never reaches it because
 * a translation of it aired somewhere else.
 */
export function airedOn(s: GalleryState, output: Output, t = Infinity, matchId?: string): AiredItem[] {
  const delay = delayFor(output);
  const visible = (a: AiredItem) => a.sim_t + delay <= t && (!matchId || a.match_id === matchId);
  if (output !== "world") return s.aired.filter((a) => a.territory === output && visible(a));
  return s.aired
    .filter((a) => a.territory === "uk" && visible(a))
    .map((a) => ({ ...a, id: `${a.cue_id}:world` }));
}

export interface Recall {
  surfaced: number;
  eligible: number;
  ratio: number | null;
}

/** Story Recall: (surfaced + resolved-with-air) / (live + surfaced + resolved). Latent stories don't count. */
export function storyRecall(s: GalleryState, stories: Story[]): Recall {
  let eligible = 0;
  let surfaced = 0;
  for (const st of stories) {
    if (st.status === "latent") continue;
    eligible += 1;
    if (st.status === "surfaced") surfaced += 1;
    else if (st.status === "resolved" && (s.airedStories[st.id] || s.everSurfaced[st.id])) surfaced += 1;
  }
  return { surfaced, eligible, ratio: eligible ? surfaced / eligible : null };
}

export function matchdayRecall(s: GalleryState): Recall {
  return storyRecall(s, Object.values(s.boards).flat());
}

export function recentCues(s: GalleryState, limit: number, matchId?: string): TimedCue[] {
  const out: TimedCue[] = [];
  for (let i = s.cueOrder.length - 1; i >= 0 && out.length < limit; i--) {
    const c = s.cues[s.cueOrder[i]];
    if (c && (!matchId || c.match_id === matchId)) out.push(c);
  }
  return out;
}

/** Why lines did not air on one territory: reason families ("stale", "attribution", …) with counts. */
export function withheldOn(s: GalleryState, territory: string): { total: number; reasons: [string, number][] } {
  let total = 0;
  const by = new Map<string, number>();
  for (const id of s.cueOrder) {
    const v = s.cues[id]?.verdicts[territory];
    if (!v || v.verdict === "ON_AIR") continue;
    total += 1;
    const families = new Set(v.reasons.map((r) => r.split(":")[0].trim() || "other"));
    if (!families.size) families.add(v.verdict === "HOLD_FOR_PRODUCER" ? "held for the producer" : "other");
    for (const f of families) by.set(f, (by.get(f) ?? 0) + 1);
  }
  return { total, reasons: [...by.entries()].sort((a, b) => b[1] - a[1]) };
}

export function verdictCounts(cues: TimedCue[]): Record<Verdict, number> {
  const n: Record<Verdict, number> = { ON_AIR: 0, HOLD_FOR_PRODUCER: 0, KILLED: 0 };
  for (const c of cues) for (const v of Object.values(c.verdicts)) n[v.verdict] += 1;
  return n;
}

/** First cue produced by a workflow run. */
export function cuesForMoment(s: GalleryState, momentId: string): TimedCue[] {
  const out: TimedCue[] = [];
  for (const id of s.cueOrder) {
    const c = s.cues[id];
    if (c?.moment_id === momentId) out.push(c);
  }
  return out;
}

export function storyById(s: GalleryState, id: string): Story | undefined {
  for (const stories of Object.values(s.boards)) {
    const hit = stories.find((st) => st.id === id);
    if (hit) return hit;
  }
  return undefined;
}

export function fixtureOfClub(s: GalleryState, clubId: string): string | undefined {
  for (const f of Object.values(s.fixtures)) if (f.home === clubId || f.away === clubId) return f.match_id;
  return undefined;
}

export const STORY_BADGES: Record<string, string> = {
  milestone_goals: "Milestone",
  manager_100: "Milestone",
  farewell: "Farewell",
  debut: "Debut",
  former_club: "Former club",
  unbeaten_run: "Streak",
  relegation_six_pointer: "Six-pointer",
  golden_boot: "Golden boot",
  clean_sheet_record: "Record",
  injury_return: "Return",
  siblings: "Brothers",
  milestone_apps: "Milestone",
};

export function storyBadge(kind: string): string {
  return STORY_BADGES[kind] ?? kind.replace(/_/g, " ");
}
