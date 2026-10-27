import Link from "next/link";
import { LandingAir } from "@/components/landing/LandingAir";
import styles from "@/components/landing/Landing.module.css";
import { SiteFooter } from "@/components/site/SiteFooter";
import { SiteHeader } from "@/components/site/SiteHeader";

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
  { name: "Director", kind: "scoring + model", role: "picks the world feed; runs the live table and its swings" },
];

export default function Home() {
  return (
    <>
      <SiteHeader current="/" />
      <main id="main">
        <section className={styles.hero} aria-labelledby="claim">
          <div className={styles.heroText}>
            <p className="kicker">Ten matches at once · five territories · one gallery</p>
            <h1 id="claim" className={`display ${styles.claim}`}>
              The stat was right. <em>The story was missing.</em>
            </h1>
            <p className={styles.lede}>
              Talkback is the editorial gallery for a whole matchday. Its agents find the storylines a busy afternoon
              buries, prove every line they want to say, and clear each one for every territory it airs in, before it
              reaches the presenter&apos;s ear.
            </p>
            <div className={styles.cta}>
              <Link href="/gallery" className="btn btn-primary">
                Watch the matchday
              </Link>
            </div>
          </div>
          <LandingAir />
        </section>

        <section className={styles.section} aria-labelledby="how">
          <h2 id="how" className={`display ${styles.h2}`}>
            How it works
          </h2>
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
          <h2 id="crew" className={`display ${styles.h2}`}>
            The crew
          </h2>
          <p className={styles.sectionLede}>
            One workflow per moment, ten matches in parallel. The gate is never the author of what it checks, and any
            error, timeout or unreadable answer kills the line. Above the matches, the <strong>Director</strong> works
            the whole matchday: it cuts the world feed, and it runs the live table with title, top-four and relegation
            chances, explaining every swing by the match that caused it.
          </p>
          <ol className={styles.crew}>
            {CREW.map((a) => (
              <li key={a.name} className={styles.agent}>
                <span className={styles.agentName}>{a.name}</span>
                <span className={`${styles.agentKind} mono`}>{a.kind}</span>
                <span className={styles.agentRole}>{a.role}</span>
              </li>
            ))}
          </ol>
        </section>

        <section className={styles.section} aria-labelledby="go">
          <h2 id="go" className="sr-only">
            Where to next
          </h2>
          <ul className={styles.links}>
            <li>
              <Link href="/gallery" className={styles.linkCard}>
                <span className={styles.linkTitle}>Console</span>
                <span>The wall, the program monitor, the story board, the clearance matrix and the producer seat.</span>
              </Link>
            </li>
            <li>
              <Link href="/fan" className={styles.linkCard}>
                <span className={styles.linkTitle}>Fan view</span>
                <span>Pick your territory, depth and club, and get the lines cleared for you.</span>
              </Link>
            </li>
            <li>
              <Link href="/proof" className={styles.linkCard}>
                <span className={styles.linkTitle}>Proof</span>
                <span>Story Recall against a single-model baseline, and everything else we measure.</span>
              </Link>
            </li>
          </ul>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
