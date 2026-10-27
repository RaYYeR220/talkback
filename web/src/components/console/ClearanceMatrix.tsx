"use client";

import { useState } from "react";
import { TerritoryChip, VerdictChip } from "@/components/atoms";
import { useLedger } from "@/components/ledger/LedgerProvider";
import { matchClock } from "@/lib/format";
import { matchShort, recentCues, verdictCounts } from "@/lib/selectors";
import { useGallery } from "@/lib/stream";
import { TERRITORIES, TERRITORY, VERDICT_LABEL, VERDICT_SHORT } from "@/lib/territories";
import type { Territory } from "@/lib/types";
import styles from "./ClearanceMatrix.module.css";

export function ClearanceMatrix({ matchId, limit = 14 }: { matchId: string | null; limit?: number }) {
  const { state } = useGallery();
  const ledger = useLedger();
  const [scope, setScope] = useState<"all" | "match">("all");
  const [cell, setCell] = useState<{ cue: string; territory: Territory } | null>(null);
  const cues = recentCues(state, limit, scope === "match" && matchId ? matchId : undefined);
  const counts = verdictCounts(cues);
  const picked = cell ? state.cues[cell.cue] : undefined;
  const pickedVerdict = picked && cell ? picked.verdicts[cell.territory] : undefined;

  return (
    <section className="panel" aria-labelledby="matrix-title">
      <header className="panel-head">
        <h2 id="matrix-title">Clearance matrix</h2>
        <div className="segmented" role="group" aria-label="Which cues">
          <button type="button" aria-pressed={scope === "all"} onClick={() => setScope("all")}>
            All matches
          </button>
          <button type="button" aria-pressed={scope === "match"} onClick={() => setScope("match")} disabled={!matchId}>
            This match
          </button>
        </div>
      </header>
      <p className={styles.summary}>
        <span>
          <VerdictChip verdict="ON_AIR" short /> {counts.ON_AIR}
        </span>
        <span>
          <VerdictChip verdict="HOLD_FOR_PRODUCER" short /> {counts.HOLD_FOR_PRODUCER}
        </span>
        <span>
          <VerdictChip verdict="KILLED" short /> {counts.KILLED}
        </span>
        <span className="faint">cue × territory, last {cues.length} cues</span>
      </p>
      {cues.length === 0 ? (
        <p className="empty">No cues cleared yet.</p>
      ) : (
        <div className={styles.scroll}>
          <table className={styles.table}>
            <caption className="sr-only">
              Each row is a cue; each column a territory desk. Select a cell to see the reasons and the localised line.
            </caption>
            <thead>
              <tr>
                <th scope="col" className={styles.lineCol}>
                  Line
                </th>
                {TERRITORIES.map((t) => (
                  <th key={t} scope="col" className={styles.tCol}>
                    <span className="territory" data-territory={t}>
                      {TERRITORY[t].code}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {cues.map((c) => (
                <tr key={c.id}>
                  <th scope="row" className={styles.lineCell}>
                    <button
                      type="button"
                      className={styles.lineBtn}
                      onClick={() => ledger?.open(c.id)}
                      title="Open the claim ledger"
                    >
                      <span className={`${styles.lineMeta} mono`}>
                        {matchClock(c.moment_t ?? c.sim_t)} · {matchShort(state, c.match_id)} · {c.audience}
                      </span>
                      <span className={styles.lineText}>{c.text}</span>
                    </button>
                  </th>
                  {TERRITORIES.map((t) => {
                    const v = c.verdicts[t];
                    const active = cell?.cue === c.id && cell.territory === t;
                    if (!v)
                      return (
                        <td key={t} className={styles.cell}>
                          <span className="faint">–</span>
                        </td>
                      );
                    return (
                      <td key={t} className={styles.cell}>
                        <button
                          type="button"
                          className={styles.verdict}
                          data-verdict={v.verdict}
                          aria-pressed={active}
                          aria-label={`${TERRITORY[t].label}: ${VERDICT_LABEL[v.verdict]}`}
                          onClick={() => setCell(active ? null : { cue: c.id, territory: t })}
                        >
                          {VERDICT_SHORT[v.verdict]}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className={styles.detail} aria-live="polite">
        {picked && pickedVerdict && cell ? (
          <>
            <p className={styles.detailHead}>
              <TerritoryChip territory={cell.territory} /> <VerdictChip verdict={pickedVerdict.verdict} />
              <span className="faint">{TERRITORY[cell.territory].note}</span>
            </p>
            <p lang={TERRITORY[cell.territory].lang} dir={TERRITORY[cell.territory].dir} className={styles.localised}>
              {pickedVerdict.text}
            </p>
            {pickedVerdict.reasons.length ? (
              <ul className={styles.reasons}>
                {pickedVerdict.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            ) : (
              <p className="faint">Cleared with no objections.</p>
            )}
          </>
        ) : (
          <p className="faint">Select a cell to see why that desk aired, held or killed the line.</p>
        )}
      </div>
    </section>
  );
}
