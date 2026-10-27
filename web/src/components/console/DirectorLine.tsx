"use client";

import { matchClock } from "@/lib/format";
import { matchName } from "@/lib/selectors";
import { useGallery } from "@/lib/stream";
import styles from "./DirectorLine.module.css";

/** "Now showing X because …" from the Director's world-feed rundown. */
export function DirectorLine({
  following,
  onFollow,
}: {
  following?: boolean;
  onFollow?: () => void;
}) {
  const { state } = useGallery();
  const r = state.rundown;
  if (!r) {
    return (
      <p className={styles.line}>
        <span className="kicker">Director</span> <span className="faint">waiting for the first rundown…</span>
      </p>
    );
  }
  const name = matchName(state, r.match_id);
  let because = r.reason;
  if (because.startsWith(`${name}:`)) because = because.slice(name.length + 1).trim();
  because = because.replace(/_/g, " ");
  return (
    <div className={styles.wrap}>
      <p className={styles.line} aria-live="polite">
        <span className="kicker">Director</span>{" "}
        <span>
          Now showing <strong>{name}</strong> because {because || "it is the busiest match"}.
        </span>{" "}
        <span className={`${styles.since} mono`}>since {matchClock(r.from_t)}</span>
      </p>
      {onFollow ? (
        <button type="button" className="btn btn-sm" aria-pressed={following} onClick={onFollow}>
          {following ? "Following director" : "Follow director"}
        </button>
      ) : null}
    </div>
  );
}
