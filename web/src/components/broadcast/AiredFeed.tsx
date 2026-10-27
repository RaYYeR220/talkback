"use client";

import { TerritoryChip } from "@/components/atoms";
import { useLedger } from "@/components/ledger/LedgerProvider";
import { countdown, humanise, minuteLabel, num } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { airedOn, delayFor, matchShort, sides, storyBadge, storyById } from "@/lib/selectors";
import { useGallery, useSimNow, type AiredItem } from "@/lib/stream";
import { TERRITORY } from "@/lib/territories";
import type { Output } from "@/lib/types";
import styles from "./AiredFeed.module.css";

export type FeedDepth = "casual" | "analyst" | "console";

interface Props {
  output: Output;
  depth?: FeedDepth;
  limit?: number;
  matchId?: string;
  favouriteClub?: string | null;
  onlyFavourite?: boolean;
  title?: string;
  /** Which audiences to include; default: every fan-facing line (no presenter IFB). */
  audiences?: string[];
  emptyText?: string;
}

const FAN_AUDIENCES = ["casual", "analyst", "recap"];

export function AiredFeed({
  output,
  depth = "console",
  limit = 12,
  matchId,
  favouriteClub,
  onlyFavourite = false,
  title = "On air",
  audiences,
  emptyText,
}: Props) {
  const { state } = useGallery();
  const ledger = useLedger();
  const now = useNow(1000);
  const t = useSimNow(1000);
  const info = TERRITORY[output];
  const delay = delayFor(output);
  const allow = audiences ?? (depth === "casual" ? ["casual", "recap"] : FAN_AUDIENCES);

  const involves = (a: AiredItem) => {
    if (!favouriteClub) return false;
    const sd = sides(state, a.match_id);
    return sd?.home === favouriteClub || sd?.away === favouriteClub;
  };

  let items = airedOn(state, output, t, matchId).filter((a) => allow.includes(a.audience));
  if (onlyFavourite && favouriteClub) items = items.filter(involves);
  items = items.slice(-limit * 3).reverse();
  if (favouriteClub && !onlyFavourite) {
    // boost: your club's lines first, newest first within each group
    items = [...items.filter(involves), ...items.filter((a) => !involves(a))];
  }
  items = items.slice(0, limit);

  const queued = delay
    ? state.aired.filter(
        (a) =>
          a.territory === output &&
          a.sim_t + delay > t &&
          allow.includes(a.audience) &&
          (!matchId || a.match_id === matchId) &&
          (!onlyFavourite || !favouriteClub || involves(a)),
      )
    : [];
  const nextQueued = queued[0];
  const nextInMs = nextQueued ? (nextQueued.sim_t + delay - t) / Math.max(0.25, state.clock.rate) : 0;

  return (
    <section className={styles.feed} aria-labelledby={`feed-${output}`}>
      <header className={styles.head}>
        <h2 id={`feed-${output}`} className={styles.title}>
          {title}
        </h2>
        <span className={styles.where}>
          <TerritoryChip territory={output} /> <span className="faint">{info.language}</span>
        </span>
      </header>
      {queued.length ? (
        <p className={styles.queued} role="status">
          {queued.length} line{queued.length > 1 ? "s" : ""} held behind the {info.code} delay
          {now && nextQueued ? <> · next airs in {countdown(nextInMs)}</> : null}
        </p>
      ) : null}
      <ol className={styles.list} aria-live="polite" aria-relevant="additions" lang={info.lang} dir={info.dir}>
        {items.length === 0 ? (
          <li className="empty" dir="ltr" lang="en">
            {emptyText ?? "Nothing cleared for this output yet."}
          </li>
        ) : (
          items.map((a) => {
            const cue = state.cues[a.cue_id];
            const fav = involves(a);
            const minute = cue?.moment_t !== undefined ? Math.floor(cue.moment_t / 60_000) : Math.floor(a.sim_t / 60_000);
            const story = cue?.stories?.[0] ? storyById(state, cue.stories[0]) : undefined;
            const body = (
              <>
                <span className={styles.meta} dir="ltr" lang="en">
                  <span className="mono">{minuteLabel(minute)}</span>
                  <span>{matchShort(state, a.match_id)}</span>
                  {depth !== "casual" ? <span className="faint">{humanise(a.template)}</span> : null}
                  {a.audience === "recap" ? <span className={styles.recap}>Full time</span> : null}
                  {fav ? <span className={styles.fav}>Your club</span> : null}
                </span>
                {depth === "casual" && story ? (
                  <span className={styles.story}>
                    <span className={styles.badge}>{storyBadge(story.kind)}</span>
                    <span className={styles.text}>{a.text}</span>
                  </span>
                ) : (
                  <span className={styles.text}>{a.text}</span>
                )}
                {depth === "analyst" && cue ? (
                  <span className={styles.chips} dir="ltr" lang="en">
                    {cue.claims
                      .filter((c) => c.kind === "numeric" || c.kind === "comparative")
                      .map((c, i) => (
                        <span key={`c${i}`} className="chip" title={`${c.kind} claim`}>
                          {c.span}
                        </span>
                      ))}
                    {(cue.evidence ?? []).map((f) => (
                      <span key={f.id} className={`chip ${styles.evidence}`} title={f.id}>
                        {humanise(f.metric.split(".").pop() ?? f.metric)} {num(f.value, 1)} · n={f.sample_size}
                      </span>
                    ))}
                    {(cue.stories ?? []).map((s) => (
                      <span key={s} className={`chip ${styles.evidence}`}>
                        storyline ref
                      </span>
                    ))}
                  </span>
                ) : null}
              </>
            );
            return (
              <li key={a.id} className={styles.item} data-fav={fav || undefined}>
                {ledger ? (
                  <button type="button" className={styles.button} onClick={() => ledger.open(a.cue_id)}>
                    {body}
                    <span className="sr-only">Open the claim ledger</span>
                  </button>
                ) : (
                  <div className={styles.button}>{body}</div>
                )}
              </li>
            );
          })
        )}
      </ol>
    </section>
  );
}
