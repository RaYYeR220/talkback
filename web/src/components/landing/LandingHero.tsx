"use client";

import Link from "next/link";
import { useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { PitchCanvas } from "@/components/pitch/PitchCanvas";
import { SiteHeader } from "@/components/site/SiteHeader";
import { matchClock, minuteLabel } from "@/lib/format";
import { airedOn, matchName, minuteAt, sides, storyBadge } from "@/lib/selectors";
import { GalleryProvider, useGallery, useSimNow, type GalleryState } from "@/lib/stream";
import type { Story } from "@/lib/types";
import { clubShort, LEAGUE_NAME, player } from "@/lib/world";
import styles from "./Landing.module.css";

/** Where the programme monitor hangs on the wall (top row, fourth from the left), as in a real gallery. */
const PGM_SLOT = 3;
const WALL_SIZE = 10;

type Prefer = "buried" | "aired";

const RANK: Record<Prefer, Record<string, number>> = {
  // a story that is due and has not aired is the buried one
  buried: { live: 0, surfaced: 1, resolved: 2 },
  // the programme's lower third only ever carries a story that has aired
  aired: { surfaced: 0, resolved: 1 },
};

function aired(state: GalleryState, s: Story): boolean {
  return s.status === "surfaced" || (s.status === "resolved" && Boolean(state.airedStories[s.id] || state.everSurfaced[s.id]));
}

function pickStory(state: GalleryState, matchId: string, prefer: Prefer): Story | undefined {
  const rank = RANK[prefer];
  let best: Story | undefined;
  for (const s of state.boards[matchId] ?? []) {
    const r = rank[s.status];
    if (r === undefined) continue;
    if (s.status === "resolved" && !aired(state, s)) continue;
    if (!best || r < rank[best.status]) best = s;
  }
  return best;
}

function subjectName(s: Story): string {
  const id = s.subjects[0];
  if (id) {
    const p = player(id);
    if (p) return p.name;
    if (/^C\d+$/.test(id)) return clubShort(id);
  }
  return s.summary.split(/\s+/).slice(0, 2).join(" ");
}

const surname = (name: string) => name.trim().split(/\s+/).slice(-1)[0] ?? name;

/** "Mamadou Rademeyer: top speed 33.5 km/h" → ["Rademeyer", "top speed 33.5 km/h"], as a lower third sets it. */
function captionParts(text: string): [string, string] {
  const i = text.indexOf(":");
  if (i > 0 && i <= 40) return [surname(text.slice(0, i)), text.slice(i + 1).trim()];
  return [text, ""];
}

function matchdayOf(state: GalleryState): string | null {
  const m = /^MD(\d+)/.exec(state.fixtureOrder[0] ?? "");
  return m ? `MD${m[1]}` : null;
}

/** The fixtures as hung on the wall: the Director's world-feed match is routed to the programme monitor. */
function wallOrder(ids: string[], pgm: string | null): string[] {
  if (!pgm || !ids.includes(pgm)) return ids.slice(0, WALL_SIZE);
  const rest = ids.filter((id) => id !== pgm).slice(0, WALL_SIZE - 1);
  rest.splice(Math.min(PGM_SLOT, rest.length), 0, pgm);
  return rest;
}

function HeroMeta() {
  const { state } = useGallery();
  const t = useSimNow(1000);
  const md = matchdayOf(state);
  const conn = state.connection === "open" ? null : state.connection === "connecting" ? "connecting…" : "reconnecting…";
  return (
    <p className={styles.meta}>
      <span className={styles.x}>{state.mode === "live" ? "Live" : "Replay"} · Director ·</span>
      <span className={styles.rec}>
        <span aria-hidden="true">● </span>PGM
      </span>
      <span className={styles.x}>
        {LEAGUE_NAME}
        {md ? ` · ${md}` : ""} ·
      </span>
      {conn ? (
        <span role="status">{conn}</span>
      ) : (
        <b aria-label={`Match time ${matchClock(t)}`}>{matchClock(t)}</b>
      )}
    </p>
  );
}

interface MonitorProps {
  id: string;
  pgm: boolean;
  pinned: boolean;
  tabbable: boolean;
  t: number;
  onPin: (id: string) => void;
  onKey: (e: KeyboardEvent<HTMLButtonElement>, id: string) => void;
  onFocusIn: (id: string) => void;
}

function Monitor({ id, pgm, pinned, tabbable, t, onPin, onKey, onFocusIn }: MonitorProps) {
  const { state } = useGallery();
  const sd = sides(state, id);
  const home = sd?.home ?? "";
  const away = sd?.away ?? "";
  const sc = state.scores[id];
  const score = sc?.score ?? [0, 0];
  const minute = minuteLabel(minuteAt(state, id, t), sc?.finished);
  const fx = `${clubShort(home)} ${score[0]}–${score[1]} ${clubShort(away)} · ${minute}`;

  const story = pickStory(state, id, "buried");
  const buried = story?.status === "live";
  const storyLine = story
    ? `${surname(subjectName(story))} · ${storyBadge(story.kind)} · ${buried ? "Not on air" : "Aired"}`
    : null;
  // the programme's lower third: an aired storyline, else the last line the world feed aired for this match
  const airedStory = pgm ? pickStory(state, id, "aired") : undefined;
  const lastLine = pgm && !airedStory ? airedOn(state, "world", t, id).slice(-1)[0] : undefined;
  const l3: [string, string] | null = airedStory
    ? [surname(subjectName(airedStory)), storyBadge(airedStory.kind)]
    : lastLine
      ? captionParts(lastLine.text)
      : null;

  const label = `${matchName(state, id)}, ${score[0]}–${score[1]}, ${minute}${pgm ? ", on the world feed" : ""}. ${
    story ? `Storyline: ${story.summary} ${buried ? "Due, not on air yet." : "It has aired."}` : "No storyline due."
  }`;

  return (
    <button
      type="button"
      className={styles.mon}
      data-mon={id}
      data-pgm={pgm || undefined}
      data-story={storyLine ? "" : undefined}
      aria-pressed={pinned}
      aria-label={label}
      tabIndex={tabbable ? 0 : -1}
      onClick={() => onPin(id)}
      onKeyDown={(e) => onKey(e, id)}
      onFocus={() => onFocusIn(id)}
    >
      <span className={styles.scr}>
        <PitchCanvas
          matchId={id}
          home={home}
          away={away}
          hz={pgm ? 4 : 1}
          smooth={pgm}
          tone="mono"
          label=""
          className={styles.canvas}
        />
        {l3 ? (
          <span className={styles.l3} aria-hidden="true">
            <i />
            <span>
              {l3[0]}
              {l3[1] ? <b>{l3[1]}</b> : null}
            </span>
          </span>
        ) : null}
      </span>
      <span className={`umd ${styles.umd}`} aria-hidden="true">
        <span className="lamp" data-on={pgm ? "pgm" : undefined} />
        <span className={styles.fx}>{fx}</span>
        {storyLine ? (
          <span className={styles.st} data-buried={buried || undefined}>
            {storyLine}
          </span>
        ) : null}
      </span>
    </button>
  );
}

function Standby() {
  return (
    <div className={styles.mon} aria-hidden="true">
      <span className={styles.scr}>
        <PitchCanvas matchId={null} home="" away="" hz={1} tone="mono" label="" className={styles.canvas} />
      </span>
      <span className={`umd ${styles.umd}`}>
        <span className="lamp" />
        <span className={styles.fx}>Standby</span>
      </span>
    </div>
  );
}

function Wall() {
  const { state } = useGallery();
  const t = useSimNow(1000);
  const ref = useRef<HTMLUListElement>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const ids = state.fixtureOrder.length ? state.fixtureOrder : Object.keys(state.scores);
  const pgm = state.rundown?.match_id ?? null;
  const order = wallOrder(ids, pgm);
  const tabStop = cursor && order.includes(cursor) ? cursor : (order[PGM_SLOT] ?? order[0]);

  const onKey = (e: KeyboardEvent<HTMLButtonElement>, id: string) => {
    const i = order.indexOf(id);
    const cols = 5;
    let j = -1;
    if (e.key === "ArrowRight") j = Math.min(order.length - 1, i + 1);
    else if (e.key === "ArrowLeft") j = Math.max(0, i - 1);
    else if (e.key === "ArrowDown") j = i + cols < order.length ? i + cols : i;
    else if (e.key === "ArrowUp") j = i - cols >= 0 ? i - cols : i;
    else if (e.key === "Home") j = 0;
    else if (e.key === "End") j = order.length - 1;
    else if (e.key === "Escape") {
      setPinned(null);
      return;
    }
    if (j < 0) return;
    e.preventDefault();
    const next = order[j];
    setCursor(next);
    ref.current?.querySelector<HTMLButtonElement>(`[data-mon="${next}"]`)?.focus();
  };

  return (
    <div className={styles.wallwrap}>
      {order.length ? (
        <ul
          ref={ref}
          className={styles.wall}
          aria-label="The ten-match wall. Focus a monitor to rack focus and read its storyline; arrow keys move along the wall."
        >
          {order.map((id) => (
            <li key={id}>
              <Monitor
                id={id}
                pgm={id === pgm}
                pinned={pinned === id}
                tabbable={id === tabStop}
                t={t}
                onPin={(m) => setPinned((p) => (p === m ? null : m))}
                onKey={onKey}
                onFocusIn={setCursor}
              />
            </li>
          ))}
        </ul>
      ) : (
        <div className={styles.wall} aria-hidden="true">
          {Array.from({ length: WALL_SIZE }, (_, i) => (
            <Standby key={i} />
          ))}
        </div>
      )}
    </div>
  );
}

function Stage() {
  return (
    <div className={styles.stage}>
      <div className={styles.ground} aria-hidden="true" />
      <section className={styles.copy} aria-labelledby="claim">
        <p className={`eyebrow ${styles.eyebrow}`}>Ten matches · five territories · one gallery</p>
        <h1 id="claim" className={styles.claim}>
          <span>The stat was right.</span> <span>The story was missing.</span>
        </h1>
        <div className={styles.foot}>
          <Link href="/gallery" className={styles.cta}>
            <i aria-hidden="true" />
            Watch the matchday
          </Link>
          <p className={styles.sub}>
            Talkback is the editorial gallery for a whole matchday. Its agents find the storylines a busy afternoon
            buries, prove every line they want to say, and clear each one for every territory it airs in, before it
            reaches the presenter&apos;s ear.
          </p>
        </div>
      </section>
      <Wall />
      <div className={styles.scrim} aria-hidden="true" />
      <p className={styles.hint} aria-hidden="true">
        Hover or tab to a monitor
        <br />
        <b>rack focus → its storyline</b>
      </p>
    </div>
  );
}

/** The landing page shell: the bar laid over the stage, then the stage, then the page's own sections. */
export function LandingHero({ children }: { children?: ReactNode }) {
  return (
    <GalleryProvider>
      <div className={styles.page}>
        <SiteHeader current="/" overlay>
          <HeroMeta />
        </SiteHeader>
        <main id="main">
          <Stage />
          {children}
        </main>
      </div>
    </GalleryProvider>
  );
}
