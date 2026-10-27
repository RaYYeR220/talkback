import Link from "next/link";
import { LandingHero } from "@/components/landing/LandingHero";
import styles from "@/components/landing/Landing.module.css";
import { SiteFooter } from "@/components/site/SiteFooter";

const STEPS = [
  {
    verb: "Find the story",
    body: "The Spotter ranks moments across all ten matches. The Archivist keeps a story board per match from season records: the player on 99 goals, the farewell, the old club. When a story's trigger fires, it is due on air.",
  },
  {
    verb: "Prove the line",
    body: "The Writer drafts with structured claims. Every number must match a computed fact about the same player. Words like “dominant” need the sample size to back them, and causal verbs need a Lab experiment whose interval excludes zero.",
  },
  {
    verb: "Clear it for every territory",
    body: "Each territory desk localises the line and applies its own pack: gambling bans, a two-minute delay with a results embargo, a minors-safe feed. The same line can air in one market, wait for the producer in another, and die in a third.",
  },
];

const CREW = [
  { name: "Spotter", kind: "rules + model", role: "turns triggers into ranked moments" },
  { name: "Archivist", kind: "model + tools", role: "hunts season storylines; keeps the story board" },
  { name: "Lab", kind: "model + simulator", role: "re-runs the match to test a causal claim" },
  { name: "Writer", kind: "model", role: "drafts analyst, casual and presenter lines with claims" },
  { name: "Clearance", kind: "code + judge", role: "numbers, subjects, wording strength, staleness" },
  { name: "Territory desks", kind: "pack + localiser", role: "UK · ES · MENA · KIDS · BR, in parallel" },
  { name: "Producer", kind: "human", role: "approves or rejects holds; silence means not aired" },
  { name: "Graphics Op", kind: "code", role: "plays cleared cues as OGraf graphics per output" },
  { name: "Prompter", kind: "code", role: "times presenter cues into the talkback ear" },
  { name: "Director", kind: "scoring + model", role: "picks the world feed; runs the live table and its swings", pgm: true },
];

const LINKS = [
  {
    href: "/gallery",
    title: "Console",
    body: "The wall, the program monitor, the story board, the clearance matrix and the producer seat.",
  },
  { href: "/fan", title: "Fan view", body: "Pick your territory, depth and club, and get the lines cleared for you." },
  {
    href: "/proof",
    title: "Proof",
    body: "Story Recall against a single-model baseline, and everything else we measure.",
  },
];

export default function Home() {
  return (
    <>
      <LandingHero>
        <section className={styles.section} aria-labelledby="how">
          <header className={styles.sectionHead}>
            <p className="eyebrow">The signal path</p>
            <h2 id="how" className={`display ${styles.h2}`}>
              How it works
            </h2>
          </header>
          <ol className={styles.steps}>
            {STEPS.map((s, i) => (
              <li key={s.verb} className={styles.step}>
                <span className={`${styles.num} mono`}>0{i + 1}</span>
                <h3 className={styles.verb}>{s.verb}</h3>
                <p>{s.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className={styles.section} aria-labelledby="crew">
          <header className={styles.sectionHead}>
            <p className="eyebrow">Ten seats · one gallery</p>
            <h2 id="crew" className={`display ${styles.h2}`}>
              The crew
            </h2>
          </header>
          <p className={styles.sectionLede}>
            One workflow per moment, ten matches in parallel. The gate is never the author of what it checks, and any
            error, timeout or unreadable answer kills the line. Above the matches, the <strong>Director</strong> works
            the whole matchday: it cuts the world feed, and it runs the live table with title, top-four and relegation
            chances, explaining every swing by the match that caused it.
          </p>
          <ol className={styles.crew}>
            {CREW.map((a, i) => (
              <li key={a.name} className={styles.agent} data-pgm={a.pgm || undefined}>
                <span className={styles.agentScreen}>
                  <span className={`${styles.agentKind} mono`}>{a.kind}</span>
                  <span className={styles.agentRole}>{a.role}</span>
                </span>
                <span className={`umd ${styles.agentUmd}`}>
                  <span className="lamp" data-on={a.pgm ? "pgm" : undefined} aria-hidden="true" />
                  <span className={`${styles.agentNo} mono`} aria-hidden="true">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className={styles.agentName}>{a.name}</span>
                </span>
              </li>
            ))}
          </ol>
        </section>

        <section className={styles.section} aria-labelledby="go">
          <h2 id="go" className="sr-only">
            Where to next
          </h2>
          <ul className={styles.links}>
            {LINKS.map((l) => (
              <li key={l.href}>
                <Link href={l.href} className={styles.linkCard}>
                  <span className={styles.linkScreen}>
                    <span className={styles.linkTitle}>{l.title}</span>
                    <span>{l.body}</span>
                  </span>
                  <span className={`umd ${styles.linkUmd}`} aria-hidden="true">
                    <span className="lamp" />
                    <span>{l.href}</span>
                    <span className={styles.arrow}>→</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </LandingHero>
      <SiteFooter />
    </>
  );
}
