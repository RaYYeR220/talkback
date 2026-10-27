"use client";

import { matchClock } from "@/lib/format";
import { useGallery, useSimNow } from "@/lib/stream";
import styles from "./ModeBadge.module.css";

function recordedLabel(epochS: number | undefined): string | null {
  if (!epochS) return null;
  const d = new Date(epochS * 1000);
  return d.toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function ModeBadge({ compact = false }: { compact?: boolean }) {
  const { state } = useGallery();
  const t = useSimNow(500);
  const live = state.mode === "live";
  const label = state.runLabel?.replace(/^replay:/, "") ?? "";
  const recorded = recordedLabel(state.run?.recorded);
  const conn =
    state.connection === "open" ? null : state.connection === "connecting" ? "connecting…" : "reconnecting…";

  return (
    <div className={styles.wrap}>
      <span className={styles.badge} data-mode={state.mode}>
        <span className={styles.dot} aria-hidden="true" />
        {live ? "Live" : state.mode === "replay" ? "Replay" : "Idle"}
      </span>
      {!compact && label ? (
        <span className={`${styles.meta} mono`} title={recorded ? `recorded ${recorded}` : undefined}>
          {label}
          {recorded ? <span className={styles.rec}> · rec {recorded}</span> : null}
        </span>
      ) : null}
      <span className={`${styles.clock} mono`} aria-label="Match time">
        {matchClock(t)}
      </span>
      {conn ? (
        <span className={styles.conn} role="status">
          {conn}
        </span>
      ) : null}
    </div>
  );
}
