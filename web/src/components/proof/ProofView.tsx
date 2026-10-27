"use client";

import { useEffect, useState } from "react";
import { duration, pct } from "@/lib/format";
import { TERRITORIES, TERRITORY } from "@/lib/territories";
import styles from "./ProofView.module.css";

interface Metric {
  id: string;
  label: string;
  description: string;
  unit: "ratio" | "count" | string;
  better: "higher" | "lower";
  headline?: boolean;
  values: Record<string, number | null>;
}

interface Summary {
  provisional: boolean;
  note?: string;
  generated_at: string | null;
  run: string | null;
  setup?: {
    matchdays?: number;
    matches_per_matchday?: number;
    seeds?: string | (string | number)[];
    sealed_key_sha256?: string | (string | null)[];
  };
  systems: { id: string; label: string; description: string }[];
  metrics: Metric[];
  clearance?: {
    description?: string;
    territories: Record<string, { bait_caught: number | null; bait_total: number | null; false_kills: number | null }>;
  };
  latency?: { description?: string; p50_ms: number | null; p95_ms: number | null };
  cost?: { description?: string; per_match_usd: number | null; per_matchday_usd: number | null };
  reproduce?: string[];
}

function fmt(m: Metric, v: number | null | undefined) {
  if (v === null || v === undefined) return "pending";
  return m.unit === "ratio" ? pct(v) : String(v);
}

function usd(v: number | null | undefined) {
  if (v === null || v === undefined) return "pending";
  return `$${v.toFixed(2)}`;
}

/** A field the scorecard writes either as one string or as a list. */
function listOf(v: string | (string | number | null)[] | undefined): string[] {
  if (v == null) return [];
  return (Array.isArray(v) ? v : [v]).filter((x) => x != null && x !== "").map(String);
}

export function ProofView({ src = "/eval/summary.json" }: { src?: string }) {
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    fetch(src, { cache: "no-store", signal: ctrl.signal })
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.json() as Promise<Summary>;
      })
      .then(setData)
      .catch(() => {
        if (!ctrl.signal.aborted) setError("The scorecard file couldn't be loaded.");
      });
    return () => ctrl.abort();
  }, [src]);

  if (error) return <p className="empty">{error}</p>;
  if (!data) return <p className="empty">Loading the scorecard…</p>;

  const sample = data.provisional;
  const headline = data.metrics.find((m) => m.headline) ?? data.metrics[0];
  const max = Math.max(1e-9, ...data.systems.map((s) => headline?.values[s.id] ?? 0));

  return (
    <div className={styles.wrap} data-sample={sample || undefined}>
      {sample ? (
        <div className={styles.banner} role="note">
          <strong>Provisional · sample values</strong>
          <span>{data.note ?? "These numbers are placeholders, not results."}</span>
        </div>
      ) : null}

      {headline ? (
        <section className={styles.headline} aria-labelledby="headline-title">
          <div>
            <p className="kicker">Headline metric</p>
            <h2 id="headline-title" className={`display ${styles.h2}`}>
              {headline.label}
            </h2>
            <p className="muted">{headline.description}</p>
          </div>
          <ul className={styles.bars}>
            {data.systems.map((s) => {
              const v = headline.values[s.id];
              return (
                <li key={s.id} data-system={s.id}>
                  <span className={styles.barLabel}>{s.label}</span>
                  <span className={styles.barTrack}>
                    <span className={styles.bar} style={{ width: `${((v ?? 0) / max) * 100}%` }} />
                  </span>
                  <span className={`${styles.barValue} mono`}>
                    {fmt(headline, v)}
                    {sample ? <span className={styles.tag}>sample</span> : null}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      <section className={styles.section} aria-labelledby="score-title">
        <h2 id="score-title" className={styles.h3}>
          Scorecard
        </h2>
        <div className={styles.scroll}>
          <table className={styles.table}>
            <caption className="sr-only">Each metric for each system compared</caption>
            <thead>
              <tr>
                <th scope="col">Metric</th>
                {data.systems.map((s) => (
                  <th key={s.id} scope="col" className={styles.n} title={s.description}>
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.metrics.map((m) => (
                <tr key={m.id}>
                  <th scope="row">
                    <span className={styles.metric}>{m.label}</span>
                    <span className={styles.desc}>
                      {m.description} <span className="faint">({m.better} is better)</span>
                    </span>
                  </th>
                  {data.systems.map((s) => (
                    <td key={s.id} className={`${styles.n} mono`} data-sample={sample || undefined}>
                      {fmt(m, m.values[s.id])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className={styles.systems}>
          {data.systems.map((s) => (
            <li key={s.id}>
              <strong>{s.label}.</strong> {s.description}
            </li>
          ))}
        </ul>
      </section>

      {data.clearance ? (
        <section className={styles.section} aria-labelledby="clear-title">
          <h2 id="clear-title" className={styles.h3}>
            Clearance accuracy by territory
          </h2>
          {data.clearance.description ? <p className="muted">{data.clearance.description}</p> : null}
          <div className={styles.scroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Territory</th>
                  <th scope="col" className={styles.n}>
                    Bait caught
                  </th>
                  <th scope="col" className={styles.n}>
                    False kills
                  </th>
                </tr>
              </thead>
              <tbody>
                {TERRITORIES.filter((t) => data.clearance?.territories[t]).map((t) => {
                  const c = data.clearance!.territories[t];
                  return (
                    <tr key={t}>
                      <th scope="row">
                        <span className="territory" data-territory={t}>
                          {TERRITORY[t].code}
                        </span>{" "}
                        <span className="muted">{TERRITORY[t].note}</span>
                      </th>
                      <td className={`${styles.n} mono`} data-sample={sample || undefined}>
                        {c.bait_caught ?? "–"}/{c.bait_total ?? "–"}
                      </td>
                      <td className={`${styles.n} mono`} data-sample={sample || undefined}>
                        {c.false_kills ?? "pending"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <section className={styles.section} aria-labelledby="ops-title">
        <h2 id="ops-title" className={styles.h3}>
          Latency and cost
        </h2>
        <dl className={styles.tiles}>
          <div className={styles.tile} data-sample={sample || undefined}>
            <dt>Latency p50</dt>
            <dd className="mono">{data.latency?.p50_ms != null ? duration(data.latency.p50_ms) : "pending"}</dd>
          </div>
          <div className={styles.tile} data-sample={sample || undefined}>
            <dt>Latency p95</dt>
            <dd className="mono">{data.latency?.p95_ms != null ? duration(data.latency.p95_ms) : "pending"}</dd>
          </div>
          <div className={styles.tile} data-sample={sample || undefined}>
            <dt>Cost per match</dt>
            <dd className="mono">{usd(data.cost?.per_match_usd)}</dd>
          </div>
          <div className={styles.tile} data-sample={sample || undefined}>
            <dt>Cost per matchday</dt>
            <dd className="mono">{usd(data.cost?.per_matchday_usd)}</dd>
          </div>
        </dl>
        {data.latency?.description ? <p className="faint">{data.latency.description}</p> : null}
      </section>

      <section className={styles.section} aria-labelledby="repro-title">
        <h2 id="repro-title" className={styles.h3}>
          Reproduce
        </h2>
        {data.setup ? (
          <p className="muted">
            {data.setup.matchdays ?? "–"} matchdays × {data.setup.matches_per_matchday ?? "–"} matches, seeds{" "}
            {listOf(data.setup.seeds).join(", ") || "–"}. Sealed answer keys (SHA-256):
          </p>
        ) : null}
        {data.setup && listOf(data.setup.sealed_key_sha256).length ? (
          <ul className={styles.hashes}>
            {listOf(data.setup.sealed_key_sha256).map((h) => (
              <li key={h}>
                <code className="mono">{h}</code>
              </li>
            ))}
          </ul>
        ) : null}
        {data.setup && !listOf(data.setup.sealed_key_sha256).length ? (
          <p className="muted">
            <code className="mono">–</code>.
          </p>
        ) : null}
        {data.reproduce?.length ? (
          <pre className={styles.code}>
            <code>{data.reproduce.join("\n")}</code>
          </pre>
        ) : null}
      </section>
    </div>
  );
}
