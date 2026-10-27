"use client";

import { StatusChip } from "@/components/atoms";
import { useLedger } from "@/components/ledger/LedgerProvider";
import { pct } from "@/lib/format";
import { matchdayRecall, matchShort, storyBadge, storyRecall } from "@/lib/selectors";
import { useGallery } from "@/lib/stream";
import type { Story } from "@/lib/types";
import styles from "./StoryBoard.module.css";

const ORDER: Record<string, number> = { live: 0, surfaced: 1, resolved: 2, latent: 3 };

function airedCueFor(state: ReturnType<typeof useGallery>["state"], story: Story): string | undefined {
  for (let i = state.cueOrder.length - 1; i >= 0; i--) {
    const c = state.cues[state.cueOrder[i]];
    if (!c) continue;
    const cites = c.stories?.includes(story.id) || c.claims.some((cl) => cl.refs.includes(story.id));
    if (cites && Object.values(c.verdicts).some((v) => v.verdict === "ON_AIR")) return c.id;
  }
  return undefined;
}

export function StoryBoard({ matchId }: { matchId: string | null }) {
  const { state } = useGallery();
  const ledger = useLedger();
  const stories = matchId ? (state.boards[matchId] ?? []) : [];
  const recall = storyRecall(state, stories);
  const day = matchdayRecall(state);
  const sorted = [...stories].sort((a, b) => (ORDER[a.status] ?? 9) - (ORDER[b.status] ?? 9));

  return (
    <section className="panel" aria-labelledby="storyboard-title">
      <header className="panel-head">
        <h2 id="storyboard-title">Story board</h2>
        <span className="kicker">{matchId ? matchShort(state, matchId) : ""}</span>
      </header>
      <div className={styles.recall}>
        <div className={styles.recallHead}>
          <span>Story recall</span>
          <span className="mono">
            {recall.surfaced}/{recall.eligible} {recall.ratio !== null ? `· ${pct(recall.ratio)}` : ""}
          </span>
        </div>
        <div
          className="meter"
          role="meter"
          aria-label="Story recall for this match"
          aria-valuemin={0}
          aria-valuemax={Math.max(1, recall.eligible)}
          aria-valuenow={recall.surfaced}
        >
          <span style={{ width: `${(recall.ratio ?? 0) * 100}%` }} />
        </div>
        <p className={styles.note}>
          Surfaced, or resolved with air, out of every story that went live. Matchday:{" "}
          <span className="mono">
            {day.surfaced}/{day.eligible}
          </span>
          .
        </p>
      </div>
      {sorted.length === 0 ? (
        <p className="empty">The Archivist hasn&apos;t posted stories for this match yet.</p>
      ) : (
        <ul className={styles.list}>
          {sorted.map((s) => {
            const cueId = s.status === "latent" ? undefined : airedCueFor(state, s);
            return (
              <li key={s.id} className={styles.story} data-status={s.status}>
                <div className={styles.top}>
                  <span className={styles.badge}>{storyBadge(s.kind)}</span>
                  <StatusChip status={s.status} />
                </div>
                <p className={styles.summary}>{s.summary}</p>
                {cueId && ledger ? (
                  <button type="button" className={styles.link} onClick={() => ledger.open(cueId)}>
                    See the line that aired it
                  </button>
                ) : s.status === "live" ? (
                  <p className={styles.due}>Due: not on air yet</p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
