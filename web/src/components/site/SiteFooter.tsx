import { LEAGUE_NAME } from "@/lib/world";
import styles from "./SiteFooter.module.css";

export function SiteFooter() {
  return (
    <footer className={styles.footer}>
      <div className={styles.inner}>
        <p>
          {LEAGUE_NAME} is fictional: invented clubs, players and seasons, simulated matches. No real data.
        </p>
        <p>
          Territory packs are illustrative editorial templates, not legal advice. Table chances come from simulated
          finishes of the season.
        </p>
      </div>
    </footer>
  );
}
