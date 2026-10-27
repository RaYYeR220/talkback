"use client";

import { useId } from "react";
import { AiredFeed } from "@/components/broadcast/AiredFeed";
import { OutputSwitch } from "@/components/broadcast/OutputSwitch";
import { ProgramMonitor } from "@/components/broadcast/ProgramMonitor";
import { ModeBadge } from "@/components/console/ModeBadge";
import { DirectorLine } from "@/components/console/DirectorLine";
import { LedgerProvider } from "@/components/ledger/LedgerProvider";
import { SiteHeader } from "@/components/site/SiteHeader";
import { useStoredState } from "@/lib/hooks";
import { airedOn, fixtureOfClub, matchName, storyBadge, storyById, withheldOn } from "@/lib/selectors";
import { GalleryProvider, useGallery, useSimNow } from "@/lib/stream";
import { isTerritory, TERRITORIES, TERRITORY } from "@/lib/territories";
import type { Territory } from "@/lib/types";
import { allClubs, clubName } from "@/lib/world";
import styles from "./FanView.module.css";

type Depth = "casual" | "analyst";

function StoryCards({ territory, club }: { territory: Territory; club: string | null }) {
  const { state } = useGallery();
  const t = useSimNow(1000);
  const info = TERRITORY[territory];
  const seen = new Set<string>();
  const cards = airedOn(state, territory, t)
    .reverse()
    .filter((a) => {
      const cue = state.cues[a.cue_id];
      const sid = cue?.stories?.[0];
      if (!sid || seen.has(sid)) return false;
      seen.add(sid);
      return true;
    })
    .sort((a, b) => {
      if (!club) return 0;
      const fa = state.fixtures[a.match_id];
      const fb = state.fixtures[b.match_id];
      const ia = fa && (fa.home === club || fa.away === club) ? 0 : 1;
      const ib = fb && (fb.home === club || fb.away === club) ? 0 : 1;
      return ia - ib;
    })
    .slice(0, 4);

  return (
    <section className={styles.stories} aria-labelledby="stories-title">
      <h2 id="stories-title" className={styles.h2}>
        Stories on air
      </h2>
      {cards.length === 0 ? (
        <p className="empty">No storyline has cleared for {info.label} yet. They land when a story&apos;s moment comes.</p>
      ) : (
        <ul className={styles.cards}>
          {cards.map((a) => {
            const cue = state.cues[a.cue_id];
            const story = cue?.stories?.[0] ? storyById(state, cue.stories[0]) : undefined;
            return (
              <li key={a.id} className={styles.card}>
                <span className={styles.badge}>{story ? storyBadge(story.kind) : "Story"}</span>
                <p lang={info.lang} dir={info.dir} className={styles.cardText}>
                  {a.text}
                </p>
                <span className="faint">{matchName(state, a.match_id)}</span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function Withheld({ territory }: { territory: Territory }) {
  const { state } = useGallery();
  const info = TERRITORY[territory];
  const { total, reasons } = withheldOn(state, territory);
  return (
    <section className={styles.withheld} aria-labelledby="withheld-title">
      <h2 id="withheld-title" className={styles.h2}>
        What didn&apos;t air in {info.label}, and why
      </h2>
      {total === 0 ? (
        <p className="faint">Nothing has been held back from this feed so far.</p>
      ) : (
        <>
          <p className="muted">
            {total} line{total > 1 ? "s" : ""} never reached you. The gate keeps the reasons, not the lines.
          </p>
          <ul className={styles.reasonList}>
            {reasons.slice(0, 6).map(([r, n]) => (
              <li key={r}>
                <span>{r}</span>
                <span className="mono">{n}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function FanBody() {
  const { state } = useGallery();
  const ids = { club: useId(), only: useId(), follow: useId() };
  const [territoryRaw, setTerritory] = useStoredState<string>("talkback.fan.territory", "uk");
  const [depth, setDepth] = useStoredState<Depth>("talkback.fan.depth", "casual");
  const [club, setClub] = useStoredState<string | null>("talkback.fan.club", null);
  const [only, setOnly] = useStoredState<boolean>("talkback.fan.only", false);
  const [followClub, setFollowClub] = useStoredState<boolean>("talkback.fan.followClub", false);
  const territory: Territory = isTerritory(territoryRaw) ? territoryRaw : "uk";
  const info = TERRITORY[territory];
  const clubMatch = club ? fixtureOfClub(state, club) : undefined;
  const director = state.rundown?.match_id ?? state.fixtureOrder[0] ?? null;
  const watching = followClub && clubMatch ? clubMatch : director;

  return (
    <>
      <SiteHeader current="/fan">
        <ModeBadge compact />
      </SiteHeader>
      <main id="main" className={styles.main}>
        <header className={styles.intro}>
          <p className="eyebrow">Fan view</p>
          <h1 className={`display ${styles.title}`}>Your matchday</h1>
          <p className="muted">
            Every line here was cleared for your territory. Pick where you watch, how deep you want it, and your club.
          </p>
        </header>

        <form className={styles.controls} onSubmit={(e) => e.preventDefault()} aria-label="Your feed">
          <div className="field">
            <span className="field-label">Territory · language</span>
            <OutputSwitch
              value={territory}
              onChange={(o) => setTerritory(o)}
              outputs={TERRITORIES}
              label="Territory and language"
            />
          </div>
          <div className="field">
            <span className="field-label">Depth</span>
            <div className="segmented" role="group" aria-label="Depth">
              {(["casual", "analyst"] as Depth[]).map((d) => (
                <button key={d} type="button" aria-pressed={depth === d} onClick={() => setDepth(d)}>
                  {d === "casual" ? "Casual fan" : "Analyst"}
                </button>
              ))}
            </div>
          </div>
          <div className="field">
            <label className="field-label" htmlFor={ids.club}>
              Favourite club
            </label>
            <select
              id={ids.club}
              className="select"
              value={club ?? ""}
              onChange={(e) => setClub(e.target.value || null)}
            >
              <option value="">No favourite</option>
              {allClubs().map((c) => (
                <option key={c.id} value={c.id}>
                  {clubName(c.id, state.fixtures)}
                </option>
              ))}
            </select>
          </div>
          <div className={styles.checks}>
            <label className={styles.check} htmlFor={ids.only}>
              <input id={ids.only} type="checkbox" checked={only} disabled={!club} onChange={(e) => setOnly(e.target.checked)} />
              Only my club
            </label>
            <label className={styles.check} htmlFor={ids.follow}>
              <input
                id={ids.follow}
                type="checkbox"
                checked={followClub}
                disabled={!club}
                onChange={(e) => setFollowClub(e.target.checked)}
              />
              Watch my club&apos;s match
            </label>
          </div>
        </form>

        <div className={styles.layout}>
          <div className={styles.watch}>
            <ProgramMonitor matchId={watching} output={territory} />
            {followClub && clubMatch ? (
              <p className="muted">Watching {matchName(state, clubMatch)}.</p>
            ) : (
              <DirectorLine />
            )}
            <p className={styles.note}>
              <span className="territory" data-territory={territory}>
                {info.code}
              </span>{" "}
              {info.note}
            </p>
            {depth === "casual" ? <StoryCards territory={territory} club={club} /> : <Withheld territory={territory} />}
          </div>
          <AiredFeed
            output={territory}
            depth={depth}
            limit={14}
            favouriteClub={club}
            onlyFavourite={only}
            title={depth === "analyst" ? "Your feed · with the evidence" : "Your feed"}
            emptyText={only ? "Nothing cleared for your club yet." : undefined}
          />
        </div>
      </main>
    </>
  );
}

export function FanView() {
  return (
    <GalleryProvider>
      <LedgerProvider>
        <FanBody />
      </LedgerProvider>
    </GalleryProvider>
  );
}
