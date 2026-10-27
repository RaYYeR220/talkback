"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useGallery } from "@/lib/stream";
import styles from "./GoLiveButton.module.css";

function politely(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return "A live matchday is already running. You're watching it.";
    if (err.status === 429) return "Today's live runs are used up. The recorded matchday keeps playing.";
    if (err.status === 0) return "The gallery service isn't reachable right now.";
    return `The service said no (${err.status}): ${err.message}`;
  }
  return "Something went wrong starting the matchday.";
}

export function GoLiveButton() {
  const { state } = useGallery();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ tone: "ok" | "warn"; text: string } | null>(null);
  const live = state.mode === "live";

  const start = async () => {
    setBusy(true);
    setNote(null);
    try {
      const r = await api.goLive();
      setNote({ tone: "ok", text: `Kick-off. Live run ${r.run} is starting.` });
    } catch (err) {
      setNote({ tone: "warn", text: politely(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.wrap}>
      <button
        type="button"
        className={`btn btn-sm ${live ? "" : "btn-primary btn-tally"}`}
        onClick={start}
        disabled={busy || live}
        aria-describedby={note ? "golive-note" : undefined}
        title={live ? "A live matchday is running" : "Start a live matchday (ten matches, compressed time)"}
      >
        {live ? "Live now" : busy ? "Starting…" : "Go live"}
      </button>
      <p id="golive-note" className={styles.note} data-tone={note?.tone} role="status" aria-live="polite">
        {note?.text ?? ""}
      </p>
    </div>
  );
}
