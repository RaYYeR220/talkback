"use client";

import { pct, signedPts } from "@/lib/format";
import { fixtureOfClub, matchShort } from "@/lib/selectors";
import { useGallery } from "@/lib/stream";
import type { Swing, TableRow } from "@/lib/types";
import { clubName, clubShort } from "@/lib/world";
import styles from "./LiveTable.module.css";

const METRIC: Record<string, string> = { title: "title", top4: "top 4", relegation: "relegation" };

function Arrow({ delta, invert = false }: { delta: number; invert?: boolean }) {
  if (Math.abs(delta) < 0.005) return null;
  const up = delta > 0;
  const good = invert ? !up : up;
  return (
    <span className={styles.arrow} data-good={good} aria-hidden="true">
      {up ? "▲" : "▼"}
    </span>
  );
}

export function LiveTable({ compact = false }: { compact?: boolean }) {
  const { state } = useGallery();
  const table = state.table;
  const prev = new Map<string, TableRow>((state.prevTable?.rows ?? []).map((r) => [r.club_id, r]));
  const swings = new Map<string, Swing[]>();
  for (const s of table?.swings ?? []) swings.set(s.club_id, [...(swings.get(s.club_id) ?? []), s]);

  return (
    <section className="panel" aria-labelledby="table-title">
      <header className="panel-head">
        <h2 id="table-title">As it stands</h2>
        <span className="kicker">chances from 1,500 simulated finishes</span>
      </header>
      {!table ? (
        <p className="empty">The Director posts the live table every 30 match-seconds.</p>
      ) : (
        <>
          {table.swings.length ? (
            <ul className={styles.swings} aria-label="Biggest swings">
              {table.swings.slice(0, 3).map((s, i) => {
                const fid = fixtureOfClub(state, s.club_id);
                const sc = fid ? state.scores[fid] : undefined;
                return (
                  <li key={`${s.club_id}-${s.metric}-${i}`}>
                    <strong>{clubName(s.club_id, state.fixtures)}</strong> {METRIC[s.metric] ?? s.metric}{" "}
                    <span className="mono">
                      {pct(s.before)} → {pct(s.after)}
                    </span>{" "}
                    <span className={styles.delta} data-good={s.metric === "relegation" ? s.after < s.before : s.after > s.before}>
                      {signedPts(s.after - s.before)}
                    </span>
                    {fid ? (
                      <span className="faint">
                        {" "}
                        · caused by {matchShort(state, fid)}
                        {sc ? ` ${sc.score[0]}–${sc.score[1]}` : ""}
                      </span>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : null}
          <div className={styles.scroll}>
            <table className={styles.table} data-compact={compact || undefined}>
              <caption className="sr-only">
                Live league table with title, top-four and relegation chances, and the match behind each swing.
              </caption>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">Club</th>
                  <th scope="col" className={styles.n}>
                    Pts
                  </th>
                  <th scope="col" className={styles.n}>
                    Title
                  </th>
                  <th scope="col" className={styles.n}>
                    Top 4
                  </th>
                  <th scope="col" className={styles.n}>
                    Rel.
                  </th>
                </tr>
              </thead>
              <tbody>
                {table.rows.map((r) => {
                  const p = prev.get(r.club_id);
                  const sw = swings.get(r.club_id);
                  const fid = fixtureOfClub(state, r.club_id);
                  const moved = p ? p.position - r.position : 0;
                  return (
                    <tr key={r.club_id} data-zone={r.position <= 4 ? "top4" : r.position >= 18 ? "relegation" : undefined}>
                      <td className="mono">
                        {r.position}
                        {moved ? (
                          <span className={styles.moved} data-good={moved > 0} aria-label={moved > 0 ? `up ${moved}` : `down ${-moved}`}>
                            {moved > 0 ? "▲" : "▼"}
                          </span>
                        ) : null}
                      </td>
                      <th scope="row" className={styles.club}>
                        <span className={styles.short}>{clubShort(r.club_id)}</span>
                        <span className={styles.name}>{clubName(r.club_id, state.fixtures)}</span>
                        {sw?.length && fid ? (
                          <span className={styles.cause} title={sw.map((s) => `${METRIC[s.metric] ?? s.metric} ${pct(s.before)} → ${pct(s.after)}`).join("; ")}>
                            via {matchShort(state, fid)}
                          </span>
                        ) : null}
                      </th>
                      <td className={`${styles.n} mono`}>{r.points}</td>
                      <td className={`${styles.n} mono`}>
                        {pct(r.title)}
                        {p ? <Arrow delta={r.title - p.title} /> : null}
                      </td>
                      <td className={`${styles.n} mono`}>
                        {pct(r.top4)}
                        {p ? <Arrow delta={r.top4 - p.top4} /> : null}
                      </td>
                      <td className={`${styles.n} mono`}>
                        {pct(r.relegation)}
                        {p ? <Arrow delta={r.relegation - p.relegation} invert /> : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
