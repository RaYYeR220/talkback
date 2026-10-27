import type { Metadata } from "next";
import { ProofView } from "@/components/proof/ProofView";
import { SiteFooter } from "@/components/site/SiteFooter";
import { SiteHeader } from "@/components/site/SiteHeader";
import styles from "@/components/proof/ProofPage.module.css";

export const metadata: Metadata = {
  title: "Proof",
  description: "The pre-registered evaluation: Story Recall against a single-model baseline, an ablation and a negative control.",
};

export default function ProofPage() {
  return (
    <>
      <SiteHeader current="/proof" />
      <main id="main" className={styles.main}>
        <header className={styles.intro}>
          <p className="eyebrow">Pre-registered evaluation</p>
          <h1 className={`display ${styles.title}`}>Proof</h1>
          <p className="muted">
            Every number on the console traces back to an event. This page holds the system to the same standard: did
            the stories that had to surface reach air, and what did the gate stop? Ties and losses are published as
            they come out.
          </p>
        </header>
        <ProofView />
      </main>
      <SiteFooter />
    </>
  );
}
