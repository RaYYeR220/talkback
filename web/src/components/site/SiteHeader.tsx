import Link from "next/link";
import type { ReactNode } from "react";
import styles from "./SiteHeader.module.css";

const NAV = [
  { href: "/gallery", label: "Console" },
  { href: "/fan", label: "Fan" },
  { href: "/proof", label: "Proof" },
];

export function Brand() {
  return (
    <Link href="/" className={styles.brand} aria-label="Talkback home">
      <span className={styles.mark} aria-hidden="true" />
      <span className={styles.word}>Talkback</span>
    </Link>
  );
}

export function SiteHeader({ current, children }: { current?: string; children?: ReactNode }) {
  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <Brand />
        <nav aria-label="Main" className={styles.nav}>
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} aria-current={current === n.href ? "page" : undefined}>
              {n.label}
            </Link>
          ))}
        </nav>
        {children ? <div className={styles.slot}>{children}</div> : null}
      </div>
    </header>
  );
}
