"use client";

import { PitchCanvas } from "@/components/pitch/PitchCanvas";
import { minuteLabel } from "@/lib/format";
import { useMediaQuery } from "@/lib/hooks";
import { matchName, minuteAt, sides } from "@/lib/selectors";
import { useGallery, useSimNow } from "@/lib/stream";
import { clubShort } from "@/lib/world";
import styles from "./MatchWall.module.css";

function Reds({ n }: { n: number }) {
  if (!n) return null;
  return (
    <span className={styles.reds} aria-label={`${n} red card${n > 1 ? "s" : ""}`}>
      {Array.from({ length: n }, (_, i) => (
        <span key={i} className={styles.red} aria-hidden="true" />
      ))}
    </span>
  );
}

export function MatchWall({ selected, onSelect }: { selected: string | null; onSelect: (id: string) => void }) {
  const { state } = useGallery();
  const minis = useMediaQuery("(min-width: 48rem)");
  const ids = state.fixtureOrder.length ? state.fixtureOrder : Object.keys(state.scores);
  const onScreen = state.rundown?.match_id;
  const t = useSimNow(5000);

  if (!ids.length) {
    return <p className="empty">Waiting for the matchday to start…</p>;
  }

  return (
    <ul className={styles.wall} aria-label="Ten-match wall">
      {ids.map((id) => {
        const sc = state.scores[id];
        const sd = sides(state, id);
        const home = sd?.home ?? "";
        const away = sd?.away ?? "";
        const score = sc?.score ?? [0, 0];
        const reds = sc?.reds ?? [0, 0];
        const minute = minuteAt(state, id, t);
        const last = [...state.ticker].reverse().find((x) => x.match_id === id && x.type !== "shot");
        const isSel = id === selected;
        const isDirector = id === onScreen;
        return (
          <li key={id}>
            <button
              type="button"
              className={styles.card}
              aria-pressed={isSel}
              data-director={isDirector || undefined}
              onClick={() => onSelect(id)}
              aria-label={`${matchName(state, id)}, ${score[0]}–${score[1]}, ${minuteLabel(minute, sc?.finished)}${
                isDirector ? ", on the world feed" : ""
              }`}
            >
              {minis ? (
                <span className={styles.mini} aria-hidden="true">
                  <PitchCanvas matchId={id} home={home} away={away} hz={1} label="" />
                </span>
              ) : null}
              <span className={styles.row}>
                <span className={styles.team}>
                  {clubShort(home)}
                  <Reds n={reds[0]} />
                </span>
                <span className={`${styles.score} mono`}>
                  {score[0]}–{score[1]}
                </span>
                <span className={`${styles.team} ${styles.away}`}>
                  <Reds n={reds[1]} />
                  {clubShort(away)}
                </span>
              </span>
              <span className={styles.foot}>
                <span className="mono">{minuteLabel(minute, sc?.finished)}</span>
                {isDirector ? <span className={styles.onair}>On screen</span> : null}
                {!isDirector && last ? (
                  <span className={styles.last}>
                    {last.type === "goal" ? "Goal" : last.type === "card" ? `${last.outcome} card` : last.type}{" "}
                    {last.player ? `· ${last.player.split(" ").slice(-1)[0]}` : ""}
                  </span>
                ) : null}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
