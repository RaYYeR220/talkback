"use client";

import { useState } from "react";
import { TerritoryChip } from "@/components/atoms";
import { api, ApiError } from "@/lib/api";
import { countdown } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { matchShort } from "@/lib/selectors";
import { useGallery, type HoldEntry } from "@/lib/stream";
import styles from "./ProducerQueue.module.css";

type Choice = "approve" | "reject";

function HoldCard({ hold, live, now }: { hold: HoldEntry; live: boolean; now: number }) {
  const { state } = useGallery();
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const left = now ? hold.expiresAt - now : hold.expires_in_s * 1000;
  const expired = left <= 0;
  const total = hold.expires_in_s * 1000;
  const disabled = !live || expired || sending;
  const allChosen = hold.holds.every((h) => choices[h.cue_id]);

  const send = async (decisions: Record<string, Choice>) => {
    setSending(true);
    setError(null);
    try {
      await api.decide(hold.id, decisions);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.status === 404
            ? "Too late: this hold expired and did not air."
            : err.status === 409
              ? "The producer seat is only open during a live matchday."
              : err.message
          : "Couldn't send the decision.",
      );
      setSending(false);
    }
  };
  const all = (c: Choice) => Object.fromEntries(hold.holds.map((h) => [h.cue_id, c])) as Record<string, Choice>;

  return (
    <li className={styles.hold} data-expired={expired || undefined}>
      <div className={styles.top}>
        <span className="mono">{matchShort(state, hold.match_id)}</span>
        <span className={`${styles.timer} mono`} aria-label={expired ? "expired" : `expires in ${Math.ceil(left / 1000)} seconds`}>
          {expired ? "expired · not aired" : countdown(left)}
        </span>
      </div>
      <div className={styles.track} aria-hidden="true">
        <span style={{ width: `${Math.max(0, Math.min(1, left / total)) * 100}%` }} />
      </div>
      <ul className={styles.cues}>
        {hold.holds.map((h) => (
          <li key={h.cue_id} className={styles.cue}>
            <p className={styles.text}>{h.text}</p>
            <p className={styles.where}>
              Held for {h.territories.map((t) => <TerritoryChip key={t} territory={t} />)}
            </p>
            {h.reasons.length ? (
              <ul className={styles.reasons}>
                {h.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            ) : null}
            <div className={styles.actions} role="group" aria-label="Decision for this line">
              <button
                type="button"
                className="btn btn-sm btn-approve"
                aria-pressed={choices[h.cue_id] === "approve"}
                disabled={disabled}
                onClick={() => setChoices({ ...choices, [h.cue_id]: "approve" })}
              >
                Approve
              </button>
              <button
                type="button"
                className="btn btn-sm btn-reject"
                aria-pressed={choices[h.cue_id] === "reject"}
                disabled={disabled}
                onClick={() => setChoices({ ...choices, [h.cue_id]: "reject" })}
              >
                Reject
              </button>
            </div>
          </li>
        ))}
      </ul>
      <div className={styles.send}>
        <button type="button" className="btn btn-sm btn-primary" disabled={disabled || !allChosen} onClick={() => send(choices)}>
          {sending ? "Sending…" : "Send decision"}
        </button>
        {hold.holds.length > 1 ? (
          <>
            <button type="button" className="btn btn-sm" disabled={disabled} onClick={() => send(all("approve"))}>
              Approve all
            </button>
            <button type="button" className="btn btn-sm" disabled={disabled} onClick={() => send(all("reject"))}>
              Reject all
            </button>
          </>
        ) : null}
      </div>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
    </li>
  );
}

export function ProducerQueue() {
  const { state } = useGallery();
  const now = useNow(250);
  const live = state.mode === "live";
  const holds = Object.values(state.holds).sort((a, b) => a.expiresAt - b.expiresAt);
  const resolved = Object.values(state.resolved)
    .sort((a, b) => b.at - a.at)
    .slice(0, 4);

  return (
    <section className="panel" aria-labelledby="producer-title">
      <header className="panel-head">
        <h2 id="producer-title">Producer queue</h2>
        <span className="kicker">{holds.length} held</span>
      </header>
      {!live ? (
        <p className={styles.seat}>
          The producer seat opens during a live matchday. In a replay the holds were already decided when the run was
          recorded, so the buttons stay off. Unanswered holds expire and do not air.
        </p>
      ) : null}
      {holds.length ? (
        <ul className={styles.list}>
          {holds.map((h) => (
            <HoldCard key={h.id} hold={h} live={live} now={now} />
          ))}
        </ul>
      ) : (
        <p className="empty">Nothing waiting. Sensitive lines (injury, discipline, referees) land here.</p>
      )}
      {resolved.length ? (
        <div className={styles.resolved}>
          <p className="kicker">Recently decided</p>
          <ul>
            {resolved.map((r) => {
              const vals = Object.values(r.decision);
              const label = vals.every((v) => v === "approve")
                ? "approved"
                : vals.every((v) => v === "expired")
                  ? "expired"
                  : vals.every((v) => v === "reject")
                    ? "rejected"
                    : "mixed";
              return (
                <li key={r.id} className={styles.resolvedItem}>
                  <span className="mono">{r.id.split("-").slice(1, 3).join("-")}</span>
                  <span data-decision={label}>{label}</span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
