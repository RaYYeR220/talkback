import { num } from "@/lib/format";
import { storyBadge } from "@/lib/selectors";
import type { AiredItem, TimedCue } from "@/lib/stream";
import { TERRITORY } from "@/lib/territories";
import type { Fact, Output, Scalar, Story } from "@/lib/types";
import styles from "./GraphicCard.module.css";

// The web overlay for an aired cue. It mirrors the OGraf packages (stat card, story card,
// lower third, counterfactual card, table swing, player tag). The cleared, localised line is
// always the text. Numbers and labels come only from what Clearance checked: the cited facts,
// the Lab's experiments and the gallery's own template data (speed tags) - never from anything
// a model wrote outside the line.

const KICKER: Record<string, string> = {
  stat_card: "Stat",
  story_card: "Story",
  lower_third: "",
  counterfactual_card: "What if",
  table_swing: "Table",
  player_tag: "Player",
};

function pick(data: Record<string, Scalar>, ...keys: string[]): Scalar | undefined {
  for (const k of keys) if (data[k] !== undefined && data[k] !== null && data[k] !== "") return data[k];
  return undefined;
}

const SPOKEN_DECIMALS: Record<string, number> = { count: 0, km: 1, "km/h": 1, m: 1 };

/** A cited fact at broadcast precision, as the line itself is allowed to say it. */
function spoken(f: Fact): string {
  return num(f.value, SPOKEN_DECIMALS[f.unit] ?? 2).replace(/\.0+$|(\.\d*?)0+$/, "$1");
}

function metricLabel(metric: string): string {
  const name = metric.split(".").pop() ?? metric;
  return name.replace(/_kmh$/, "").replace(/_km$/, "").replace(/_/g, " ").replace(/^xg$/, "xG");
}

function asNumber(x: Scalar | undefined): number | undefined {
  if (typeof x === "number") return x;
  if (typeof x === "string" && x.trim() !== "" && !Number.isNaN(Number(x))) return Number(x);
  return undefined;
}

export function GraphicCard({
  item,
  cue,
  output,
  story,
}: {
  item: AiredItem;
  cue?: TimedCue;
  output: Output;
  story?: Story;
}) {
  const t = TERRITORY[output];
  const data = item.data ?? {};
  const template = item.template || "lower_third";
  const kicker = KICKER[template] ?? "";
  const text = <p className={styles.line}>{item.text}</p>;

  let body;
  switch (template) {
    case "player_tag": {
      const name = pick(data, "name", "player", "subject");
      const shirt = pick(data, "shirt", "number");
      const speed = asNumber(pick(data, "speed_kmh"));
      body = (
        <div className={styles.tag}>
          {shirt !== undefined ? <span className={`${styles.shirt} mono`}>{String(shirt)}</span> : null}
          <div>
            {name ? <p className={styles.name}>{String(name)}</p> : null}
            {speed !== undefined ? (
              <p className={`${styles.metric} mono`}>
                {num(speed, 1)} <span>km/h</span>
              </p>
            ) : (
              text
            )}
          </div>
        </div>
      );
      break;
    }
    case "counterfactual_card": {
      const exp = cue?.experiments?.[0];
      const asPlayed = exp?.baseline;
      const ifNot = exp?.counterfactual;
      const max = Math.max(asPlayed ?? 0, ifNot ?? 0, 1e-9);
      body = (
        <>
          {text}
          {asPlayed !== undefined && ifNot !== undefined ? (
            <div className={styles.bars}>
              <span>As played</span>
              <span className={styles.bar} style={{ width: `${(asPlayed / max) * 100}%` }} />
              <span className="mono">{num(asPlayed)}</span>
              <span>If not</span>
              <span className={`${styles.bar} ${styles.barAlt}`} style={{ width: `${(ifNot / max) * 100}%` }} />
              <span className="mono">{num(ifNot)}</span>
            </div>
          ) : null}
        </>
      );
      break;
    }
    case "table_swing": {
      body = text;
      break;
    }
    case "story_card": {
      const badge = story ? storyBadge(story.kind) : undefined;
      body = (
        <>
          {badge ? <span className={styles.badge}>{String(badge).replace(/_/g, " ")}</span> : null}
          {text}
        </>
      );
      break;
    }
    case "stat_card": {
      const fact = cue?.evidence?.[0];
      const label = fact ? metricLabel(fact.metric) : undefined;
      const value = fact ? spoken(fact) : undefined;
      body = (
        <>
          {label !== undefined && value !== undefined ? (
            <p className={`${styles.metric} mono`}>
              {String(value)} <span>{String(label)}</span>
            </p>
          ) : null}
          {text}
        </>
      );
      break;
    }
    default: {
      const name = pick(data, "name", "subject", "player");
      body = (
        <>
          {name ? <p className={styles.name}>{String(name)}</p> : null}
          {text}
        </>
      );
    }
  }

  return (
    <div className={styles.graphic} data-template={template} lang={t.lang} dir={t.dir}>
      {kicker ? <span className={styles.kicker}>{kicker}</span> : null}
      {body}
    </div>
  );
}
