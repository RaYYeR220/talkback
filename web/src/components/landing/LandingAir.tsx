"use client";

import { AiredFeed } from "@/components/broadcast/AiredFeed";
import { ProgramMonitor } from "@/components/broadcast/ProgramMonitor";
import { ModeBadge } from "@/components/console/ModeBadge";
import { matchName } from "@/lib/selectors";
import { GalleryProvider, useGallery } from "@/lib/stream";
import styles from "./Landing.module.css";

function Air() {
  const { state } = useGallery();
  const matchId = state.rundown?.match_id ?? state.fixtureOrder[0] ?? null;
  return (
    <div className={styles.air}>
      <div className={styles.airHead}>
        <ModeBadge compact />
        <span className={styles.airMatch}>{matchId ? matchName(state, matchId) : "Waiting for kick-off"}</span>
      </div>
      <ProgramMonitor matchId={matchId} output="uk" size="compact" />
      <AiredFeed output="uk" limit={3} title="Just cleared for air" depth="console" emptyText="The first lines clear a few match-minutes in." />
    </div>
  );
}

export function LandingAir() {
  return (
    <GalleryProvider>
      <Air />
    </GalleryProvider>
  );
}
