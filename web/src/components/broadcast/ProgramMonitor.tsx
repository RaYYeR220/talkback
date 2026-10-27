"use client";

import { PitchCanvas } from "@/components/pitch/PitchCanvas";
import { OGRAF_DEFAULT, OGRAF_RENDERER } from "@/lib/api";
import { matchClock, minuteLabel } from "@/lib/format";
import { useSearchFlag } from "@/lib/hooks";
import { airedOn, delayFor, matchName, minuteAt, scoreAt, sides, storyById } from "@/lib/selectors";
import { useGallery, useSimNow } from "@/lib/stream";
import { TERRITORY } from "@/lib/territories";
import type { Output } from "@/lib/types";
import { clubShort } from "@/lib/world";
import { GraphicCard } from "./GraphicCard";
import styles from "./ProgramMonitor.module.css";

/** How long (wall ms) a graphic stays up on the web overlay after it airs. */
const GRAPHIC_HOLD_MS = 25_000;

export type Renderer = "web" | "ograf";

interface Props {
  matchId: string | null;
  output: Output;
  /**
   * "web" draws the overlay in React. "ograf" swaps in the backend's OGraf renderer page
   * (/ograf/renderer/index.html?renderer=<output>) as a transparent layer over the pitch.
   * Defaults to NEXT_PUBLIC_OGRAF=1 or ?ograf=1, else "web".
   */
  renderer?: Renderer;
  size?: "full" | "compact";
}

export function ProgramMonitor({ matchId, output, renderer, size = "full" }: Props) {
  const { state } = useGallery();
  const ografFlag = useSearchFlag("ograf");
  const mode: Renderer = renderer ?? (OGRAF_DEFAULT || ografFlag ? "ograf" : "web");
  const delay = delayFor(output);
  const info = TERRITORY[output];
  const now = useSimNow(500);
  const tView = Math.max(0, now - delay);
  const sd = matchId ? sides(state, matchId) : null;
  const home = sd?.home ?? "";
  const away = sd?.away ?? "";

  const live = matchId ? state.scores[matchId] : undefined;
  const shown = matchId ? (delay ? scoreAt(state, matchId, tView) : null) : null;
  const score = delay ? (shown?.score ?? [0, 0]) : (live?.score ?? [0, 0]);
  const reds = delay ? (shown?.reds ?? [0, 0]) : (live?.reds ?? [0, 0]);
  const minute = matchId ? (delay ? Math.floor(tView / 60_000) : minuteAt(state, matchId, now)) : undefined;
  const finished = !delay && live?.finished;

  const lines = matchId ? airedOn(state, output, tView, matchId) : [];
  const latest = lines[lines.length - 1];
  const upFor = latest ? (tView - (latest.sim_t + delay)) / Math.max(0.25, state.clock.rate) : Infinity;
  const graphic = latest && upFor < GRAPHIC_HOLD_MS ? latest : null;
  const cue = graphic ? state.cues[graphic.cue_id] : undefined;
  const story = cue?.stories?.[0] ? storyById(state, cue.stories[0]) : undefined;

  const label = matchId
    ? `Program monitor, ${info.label} output: ${matchName(state, matchId)}, ${score[0]}–${score[1]}`
    : "Program monitor: no match selected";

  return (
    <figure className={styles.monitor} data-size={size} aria-label={label}>
      <div className={styles.screen}>
        <PitchCanvas
          matchId={matchId}
          home={home}
          away={away}
          hz={5}
          delayMs={delay}
          smooth
          numbers={size === "full"}
          label={matchId ? `Tracking view of ${matchName(state, matchId)}` : "No match selected"}
        />
        {matchId ? (
          <div className={styles.bug} aria-hidden="true">
            <span className={styles.bugTeam}>{clubShort(home)}</span>
            <span className={`${styles.bugScore} mono`}>
              {score[0]}–{score[1]}
            </span>
            <span className={styles.bugTeam}>{clubShort(away)}</span>
            <span className={`${styles.bugMin} mono`}>{minuteLabel(minute, finished)}</span>
            {reds[0] || reds[1] ? (
              <span className={styles.bugReds} title="red cards">
                {reds[0]}·{reds[1]}
              </span>
            ) : null}
          </div>
        ) : null}
        <div className={styles.out} aria-hidden="true">
          <span className="territory" data-territory={output}>
            {info.code}
          </span>
          {delay ? <span className={styles.delay}>+{matchClock(delay)} delay</span> : null}
        </div>
        {mode === "ograf" ? (
          // OGraf hook: the backend's renderer page draws this output's graphics over the pitch.
          <iframe
            className={styles.ograf}
            src={OGRAF_RENDERER(output)}
            title={`OGraf renderer, ${info.label} output`}
          />
        ) : graphic ? (
          <GraphicCard key={graphic.id} item={graphic} cue={cue} output={output} story={story} />
        ) : null}
      </div>
    </figure>
  );
}
