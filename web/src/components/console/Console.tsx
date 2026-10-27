"use client";

import { useState } from "react";
import { AiredFeed } from "@/components/broadcast/AiredFeed";
import { OutputSwitch } from "@/components/broadcast/OutputSwitch";
import { ProgramMonitor } from "@/components/broadcast/ProgramMonitor";
import { LedgerProvider } from "@/components/ledger/LedgerProvider";
import { SiteHeader } from "@/components/site/SiteHeader";
import { matchName } from "@/lib/selectors";
import { GalleryProvider, useGallery } from "@/lib/stream";
import { TERRITORY } from "@/lib/territories";
import type { Output } from "@/lib/types";
import { AgentStrip } from "./AgentStrip";
import { ClearanceMatrix } from "./ClearanceMatrix";
import styles from "./Console.module.css";
import { DirectorLine } from "./DirectorLine";
import { GoLiveButton } from "./GoLiveButton";
import { LiveTable } from "./LiveTable";
import { MatchWall } from "./MatchWall";
import { ModeBadge } from "./ModeBadge";
import { ProducerQueue } from "./ProducerQueue";
import { StoryBoard } from "./StoryBoard";

function ConsoleBody() {
  const { state } = useGallery();
  const [picked, setPicked] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [output, setOutput] = useState<Output>("uk");
  const fallback = state.fixtureOrder[0] ?? null;
  const selected = (follow ? state.rundown?.match_id : picked) ?? picked ?? fallback;

  const select = (id: string) => {
    setPicked(id);
    setFollow(false);
  };

  return (
    <>
      <SiteHeader current="/gallery">
        <ModeBadge />
        <GoLiveButton />
      </SiteHeader>
      <main id="main" className={styles.main}>
        <h1 className="sr-only">Talkback console</h1>
        <section aria-label="Matches" className={styles.wall}>
          <MatchWall selected={selected} onSelect={select} />
        </section>

        <div className={styles.grid}>
          <section className={`panel ${styles.program}`} aria-labelledby="program-title">
            <header className="panel-head">
              <h2 id="program-title">
                Program <span className="faint">· {selected ? matchName(state, selected) : "no match"}</span>
              </h2>
              <OutputSwitch value={output} onChange={setOutput} />
            </header>
            <div className={styles.programBody}>
              <ProgramMonitor matchId={selected} output={output} />
              <DirectorLine following={follow} onFollow={() => setFollow(!follow)} />
              <p className={styles.outNote}>
                <span className="territory" data-territory={output}>
                  {TERRITORY[output].code}
                </span>{" "}
                {TERRITORY[output].note}
              </p>
              <AiredFeed output={output} matchId={selected ?? undefined} limit={5} title="On air, this match" depth="console" audiences={["casual", "analyst", "recap", "presenter"]} />
            </div>
          </section>

          <div className={styles.side}>
            <ProducerQueue />
            <ClearanceMatrix matchId={selected} />
          </div>

          <div className={styles.lower}>
            <StoryBoard matchId={selected} />
            <AgentStrip />
            <LiveTable />
          </div>
        </div>
      </main>
    </>
  );
}

export function Console() {
  return (
    <GalleryProvider>
      <LedgerProvider>
        <ConsoleBody />
      </LedgerProvider>
    </GalleryProvider>
  );
}
