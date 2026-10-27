"use client";

import { useEffect, useRef, useState } from "react";
import { TerritoryChip, VerdictChip } from "@/components/atoms";
import { api, ApiError } from "@/lib/api";
import { duration, humanise, matchClock, num, windowLabel } from "@/lib/format";
import { matchName } from "@/lib/selectors";
import { useGallery } from "@/lib/stream";
import { TERRITORIES, TERRITORY } from "@/lib/territories";
import type { Cue, LedgerResponse, Output } from "@/lib/types";
import { player } from "@/lib/world";
import { LabChart } from "./LabChart";
import styles from "./LedgerDrawer.module.css";

const STRENGTH = ["descriptive", "hedged", "firm", "absolute"];
const STAGES = ["archivist", "lab", "writer", "clearance"];

interface Loaded {
  id: string;
  data?: LedgerResponse;
  error?: string;
}

export function LedgerDrawer({ cueId, onClose }: { cueId: string | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const { state } = useGallery();
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (cueId && !d.open) d.showModal();
    if (!cueId && d.open) d.close();
  }, [cueId]);

  useEffect(() => {
    if (!cueId) return;
    const ctrl = new AbortController();
    api
      .ledger(cueId, ctrl.signal)
      .then((data) => setLoaded({ id: cueId, data }))
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        const msg =
          err instanceof ApiError && err.status === 404
            ? "The service no longer holds this entry (the replay has looped). Showing the copy from the stream."
            : "Couldn't reach the ledger. Showing the copy from the stream.";
        setLoaded({ id: cueId, error: msg });
      });
    return () => ctrl.abort();
  }, [cueId]);

  const current = loaded && loaded.id === cueId ? loaded : null;
  const cue: Cue | undefined = current?.data?.cue ?? (cueId ? state.cues[cueId] : undefined);
  const events = current?.data ? Object.values(current.data.events).sort((a, b) => a.t - b.t) : [];

  return (
    <dialog
      ref={ref}
      className={styles.drawer}
      aria-labelledby="ledger-title"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className={styles.inner}>
        <header className={styles.head}>
          <div>
            <p className="kicker">Claim ledger</p>
            <h2 id="ledger-title" className={styles.title}>
              {cue ? matchName(state, cue.match_id) : "Cue"}
            </h2>
            {cue ? <p className={`${styles.id} mono`}>{cue.id}</p> : null}
          </div>
          <button type="button" className="btn btn-sm" onClick={onClose} autoFocus>
            Close
          </button>
        </header>

        {!cue ? (
          <p className="empty">{current ? "This cue isn't in the ledger." : "Loading…"}</p>
        ) : (
          <div className={styles.body}>
            {current?.error ? <p className={styles.notice}>{current.error}</p> : null}

            <section className={styles.section} aria-labelledby="l-text">
              <h3 id="l-text" className="kicker">
                Line
              </h3>
              <blockquote className={styles.quote}>{cue.text}</blockquote>
              <dl className={styles.meta}>
                <div>
                  <dt>Audience</dt>
                  <dd>{cue.audience}</dd>
                </div>
                <div>
                  <dt>Template</dt>
                  <dd>{humanise(cue.template)}</dd>
                </div>
                {cue.moment_kind ? (
                  <div>
                    <dt>Moment</dt>
                    <dd>{humanise(cue.moment_kind)}</dd>
                  </div>
                ) : null}
                {cue.moment_t !== undefined ? (
                  <div>
                    <dt>At</dt>
                    <dd className="mono">{matchClock(cue.moment_t)}</dd>
                  </div>
                ) : null}
                <div>
                  <dt>Latency</dt>
                  <dd className="mono">
                    {duration(
                      cue.latency_ms ??
                        (cue.timings && Object.keys(cue.timings).length
                          ? Object.values(cue.timings).reduce((a, b) => a + b, 0)
                          : undefined),
                    )}
                  </dd>
                </div>
                {cue.data?.revision_of ? (
                  <div>
                    <dt>Revision of</dt>
                    <dd className="mono">{String(cue.data.revision_of)}</dd>
                  </div>
                ) : null}
              </dl>
              {cue.data?.original_text ? (
                <p className={styles.small}>
                  First draft (refused): <q>{String(cue.data.original_text)}</q>
                  {cue.data.first_refusal ? <> — {String(cue.data.first_refusal)}</> : null}
                </p>
              ) : null}
            </section>

            <section className={styles.section} aria-labelledby="l-claims">
              <h3 id="l-claims" className="kicker">
                Claims ({cue.claims.length})
              </h3>
              {cue.claims.length ? (
                <ul className={styles.list}>
                  {cue.claims.map((c, i) => (
                    <li key={i} className={styles.claim}>
                      <p>
                        <mark className={styles.span}>{c.span}</mark>{" "}
                        <span className="chip">{c.kind}</span>{" "}
                        <span className="chip" title="wording strength level">
                          {STRENGTH[c.strength] ?? c.strength}
                        </span>
                      </p>
                      <p className={styles.small}>
                        subject <span className="mono">{c.subject ?? "–"}</span>
                        {c.value !== null && c.value !== undefined && c.kind === "numeric" ? (
                          <>
                            {" "}
                            · value <span className="mono">{num(c.value)}</span>
                          </>
                        ) : null}
                      </p>
                      {c.refs.length ? (
                        <p className={styles.refs}>
                          {c.refs.map((r) => (
                            <code key={r} className={styles.ref}>
                              {r}
                            </code>
                          ))}
                        </p>
                      ) : (
                        <p className={styles.small}>no refs</p>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className={styles.small}>No checkable claims in this line.</p>
              )}
            </section>

            {cue.evidence?.length ? (
              <section className={styles.section} aria-labelledby="l-facts">
                <h3 id="l-facts" className="kicker">
                  Cited facts
                </h3>
                <ul className={styles.list}>
                  {cue.evidence.map((f) => (
                    <li key={f.id} className={styles.fact}>
                      <span className={`${styles.factValue} mono`}>
                        {num(f.value)} <span>{f.unit}</span>
                      </span>
                      <span>
                        {humanise(f.metric)} · <span className="mono">{player(f.subject)?.name ?? f.subject}</span>
                      </span>
                      <span className={`${styles.small} mono`}>
                        n={f.sample_size} · {windowLabel(f.window)} · {f.evidence.length} events
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {cue.experiments?.length ? (
              <section className={styles.section} aria-labelledby="l-lab">
                <h3 id="l-lab" className="kicker">
                  Lab
                </h3>
                {cue.experiments.map((x) => (
                  <LabChart key={x.id} experiment={x} />
                ))}
                {cue.lab_conclusion ? <p className={styles.small}>{cue.lab_conclusion}</p> : null}
              </section>
            ) : cue.status?.lab ? (
              <section className={styles.section} aria-labelledby="l-lab">
                <h3 id="l-lab" className="kicker">
                  Lab
                </h3>
                <p className={styles.small}>
                  {cue.status.lab === "skipped"
                    ? "No experiment: the line makes no causal claim."
                    : `Lab status: ${cue.status.lab}`}
                </p>
              </section>
            ) : null}

            <section className={styles.section} aria-labelledby="l-verdicts">
              <h3 id="l-verdicts" className="kicker">
                Clearance
              </h3>
              {cue.universal_reasons?.length ? (
                <div className={styles.universal}>
                  <p className={styles.small}>Universal checks</p>
                  <ul className={styles.reasons}>
                    {cue.universal_reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className={styles.small}>Universal checks passed.</p>
              )}
              <ul className={styles.list}>
                {TERRITORIES.filter((t) => cue.verdicts[t]).map((t) => {
                  const v = cue.verdicts[t];
                  const info = TERRITORY[t as Output];
                  return (
                    <li key={t} className={styles.verdict}>
                      <p className={styles.verdictHead}>
                        <TerritoryChip territory={t} /> <VerdictChip verdict={v.verdict} />
                      </p>
                      <p lang={info.lang} dir={info.dir} className={styles.localised}>
                        {v.text}
                      </p>
                      {v.reasons.length ? (
                        <ul className={styles.reasons}>
                          {v.reasons.map((r, i) => (
                            <li key={i}>{r}</li>
                          ))}
                        </ul>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </section>

            {cue.timings && Object.keys(cue.timings).length ? (
              <section className={styles.section} aria-labelledby="l-timings">
                <h3 id="l-timings" className="kicker">
                  Timings
                </h3>
                <Timings timings={cue.timings} status={cue.status} />
              </section>
            ) : null}

            <section className={styles.section} aria-labelledby="l-events">
              <h3 id="l-events" className="kicker">
                Evidence events
              </h3>
              {!current ? (
                <p className={styles.small}>Loading the walk-back…</p>
              ) : events.length ? (
                <div className={styles.tableWrap}>
                  <table className={styles.events}>
                    <thead>
                      <tr>
                        <th scope="col">Time</th>
                        <th scope="col">Event</th>
                        <th scope="col">Player</th>
                        <th scope="col">Outcome</th>
                        <th scope="col">x, y</th>
                      </tr>
                    </thead>
                    <tbody>
                      {events.map((e) => (
                        <tr key={e.id}>
                          <td className="mono">{matchClock(e.t)}</td>
                          <td>{humanise(e.type)}</td>
                          <td>{e.player_id ? (player(e.player_id)?.name ?? e.player_id) : "–"}</td>
                          <td>{e.outcome === "none" ? "–" : e.outcome}</td>
                          <td className="mono">
                            {e.x !== null && e.y !== null ? `${num(e.x, 1)}, ${num(e.y, 1)}` : "–"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className={styles.small}>
                  No match events behind this line{cue.evidence?.length ? "" : " (it cites season records, not play)"}.
                </p>
              )}
            </section>
          </div>
        )}
      </div>
    </dialog>
  );
}

function Timings({ timings, status }: { timings: Record<string, number>; status?: Record<string, string> }) {
  const keys = [...STAGES.filter((k) => k in timings), ...Object.keys(timings).filter((k) => !STAGES.includes(k))];
  const max = Math.max(1, ...keys.map((k) => timings[k] ?? 0));
  return (
    <ul className={styles.timings}>
      {keys.map((k) => (
        <li key={k}>
          <span>{k}</span>
          <span className={styles.timingTrack}>
            <span className={styles.timingBar} style={{ width: `${((timings[k] ?? 0) / max) * 100}%` }} />
          </span>
          <span className="mono">{duration(timings[k])}</span>
          <span className={styles.small}>{status?.[k] ?? ""}</span>
        </li>
      ))}
    </ul>
  );
}
