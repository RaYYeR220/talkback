"use client";

import { healthOf, type Health } from "@/components/atoms";
import { useLedger } from "@/components/ledger/LedgerProvider";
import { duration, humanise, matchClock } from "@/lib/format";
import { cuesForMoment, matchShort } from "@/lib/selectors";
import { useGallery, useSimNow, type AgentRun } from "@/lib/stream";
import styles from "./AgentStrip.module.css";

const STAGES = [
  { id: "archivist", label: "Archivist" },
  { id: "lab", label: "Lab" },
  { id: "writer", label: "Writer" },
  { id: "clearance", label: "Clearance" },
] as const;

interface Cell {
  health: Health;
  ms?: number;
  note?: string;
}

function cellsFor(run: AgentRun, status: Record<string, string> | undefined, timings: Record<string, number> | undefined) {
  const out: Record<string, Cell> = {};
  for (const s of STAGES) {
    const st = status?.[s.id];
    const ms = timings?.[s.id];
    if (run.stage === "error") out[s.id] = { health: "failed", note: run.error };
    else if (run.stage === "started") out[s.id] = { health: "running" };
    else if (s.id === "clearance") out[s.id] = { health: ms !== undefined || status ? "ok" : "pending", ms };
    else if (st) out[s.id] = { health: healthOf(st), ms, note: st === "ok" ? undefined : st };
    else if (status?.template) out[s.id] = { health: "skipped", note: "templated" };
    else out[s.id] = { health: "pending", ms };
  }
  return out;
}

const SYMBOL: Record<Health, string> = {
  ok: "●",
  degraded: "◐",
  failed: "✕",
  skipped: "○",
  pending: "·",
  running: "…",
};

export function AgentStrip({ limit = 8 }: { limit?: number }) {
  const { state } = useGallery();
  const ledger = useLedger();
  const simNow = useSimNow(1000);
  const runs = state.agentOrder
    .slice(-limit)
    .reverse()
    .map((id) => state.agents[id])
    .filter(Boolean);

  let degraded = 0;
  let failed = 0;
  for (const r of runs) {
    const cue = cuesForMoment(state, r.momentId)[0];
    if (r.stage === "error") failed += 1;
    else if (cue?.status && Object.values(cue.status).some((v) => healthOf(v) === "degraded")) degraded += 1;
  }

  return (
    <section className="panel" aria-labelledby="agents-title">
      <header className="panel-head">
        <h2 id="agents-title">Agents</h2>
        <span className={styles.health} data-state={failed ? "failed" : degraded ? "degraded" : "ok"}>
          {failed ? `${failed} failed` : degraded ? `${degraded} degraded` : "all healthy"}
        </span>
      </header>
      {runs.length === 0 ? (
        <p className="empty">No workflow runs yet. The Spotter wakes the crew when a moment clears salience.</p>
      ) : (
        <div className={styles.scroll}>
          <table className={styles.table}>
            <caption className="sr-only">Recent workflow runs and each agent&apos;s status and time</caption>
            <thead>
              <tr>
                <th scope="col">Moment</th>
                {STAGES.map((s) => (
                  <th key={s.id} scope="col">
                    {s.label}
                  </th>
                ))}
                <th scope="col">Total</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const cue = cuesForMoment(state, r.momentId)[0];
                const cells = cellsFor(r, cue?.status, cue?.timings);
                const running = r.stage === "started";
                const moment = state.moments[r.momentId];
                const kind =
                  r.kind ?? moment?.kind ?? cue?.moment_kind ?? (r.momentId.includes("-story-") ? "storyline" : "moment");
                const at = moment?.t ?? r.simT;
                const elapsed = (simNow - r.simT) / Math.max(0.25, state.clock.rate);
                return (
                  <tr key={r.momentId}>
                    <th scope="row">
                      <button
                        type="button"
                        className={styles.moment}
                        disabled={!cue || !ledger}
                        onClick={() => cue && ledger?.open(cue.id)}
                        title={r.trace?.length ? `trace: ${r.trace.join(" → ")}` : undefined}
                      >
                        <span className="mono">
                          {matchClock(at)} · {matchShort(state, r.matchId)}
                        </span>
                        <span>{humanise(kind)}</span>
                      </button>
                    </th>
                    {running ? (
                      <td colSpan={STAGES.length} className="health" data-health="running">
                        <span aria-hidden="true">…</span> in flight
                      </td>
                    ) : null}
                    {running ? null : STAGES.map((s) => {
                      const c = cells[s.id];
                      return (
                        <td key={s.id} className="health" data-health={c.health} title={c.note}>
                          <span aria-hidden="true">{SYMBOL[c.health]}</span>{" "}
                          <span className={styles.ms}>
                            {c.ms !== undefined && c.health !== "skipped" ? duration(c.ms) : c.health === "skipped" ? "skip" : c.health}
                          </span>
                        </td>
                      );
                    })}
                    <td className="mono">
                      {running ? duration(Math.max(0, elapsed)) : r.stage === "error" ? "error" : duration(r.ms)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className={styles.legend}>
        <span className="health" data-health="ok">
          ● ok
        </span>
        <span className="health" data-health="degraded">
          ◐ degraded (fallback)
        </span>
        <span className="health" data-health="failed">
          ✕ failed
        </span>
        <span className="health" data-health="skipped">
          ○ skipped
        </span>
      </p>
    </section>
  );
}
