import { humanise, num } from "@/lib/format";
import type { Experiment } from "@/lib/types";
import styles from "./LedgerDrawer.module.css";

/** As played vs counterfactual, two bars, with the effect and its 95% interval. */
export function LabChart({ experiment: x }: { experiment: Experiment }) {
  const max = Math.max(Math.abs(x.baseline), Math.abs(x.counterfactual), 1e-9);
  const excludesZero = x.ci95[0] > 0 || x.ci95[1] < 0;
  const describe = x.intervention?.describe;
  return (
    <figure className={styles.lab}>
      <figcaption className={styles.small}>
        {humanise(x.metric)}
        {describe ? <> · if {String(describe)}</> : null}
      </figcaption>
      <div className={styles.labBars} role="img" aria-label={`As played ${num(x.baseline)}, counterfactual ${num(x.counterfactual)}`}>
        <span>As played</span>
        <span className={styles.labTrack}>
          <span className={styles.labBar} style={{ width: `${(Math.abs(x.baseline) / max) * 100}%` }} />
        </span>
        <span className="mono">{num(x.baseline)}</span>
        <span>Counterfactual</span>
        <span className={styles.labTrack}>
          <span
            className={`${styles.labBar} ${styles.labBarAlt}`}
            style={{ width: `${(Math.abs(x.counterfactual) / max) * 100}%` }}
          />
        </span>
        <span className="mono">{num(x.counterfactual)}</span>
      </div>
      <p className={styles.small}>
        Effect <span className="mono">{num(x.effect, 3)}</span>, 95% CI{" "}
        <span className="mono">
          [{num(x.ci95[0], 3)}, {num(x.ci95[1], 3)}]
        </span>
        , n=<span className="mono">{x.n}</span> rollouts.{" "}
        <strong data-supported={excludesZero}>
          {excludesZero ? "The interval excludes zero: causal wording allowed." : "No clear effect: causal wording not allowed."}
        </strong>
      </p>
    </figure>
  );
}
