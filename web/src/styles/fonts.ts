import { Barlow_Condensed, IBM_Plex_Mono, Noto_Sans_Arabic, Schibsted_Grotesk } from "next/font/google";

// Faces are exposed as CSS variables; theme.css decides which variable plays which role.

/** Display and UI text: one grotesk, 400 for body, 500 for headings and the claim. */
export const grotesk = Schibsted_Grotesk({
  subsets: ["latin", "latin-ext"],
  variable: "--font-schibsted",
  display: "swap",
});

/** Under-monitor displays, tallies and on-screen captions. */
export const condensed = Barlow_Condensed({
  subsets: ["latin", "latin-ext"],
  weight: ["500", "600"],
  variable: "--font-barlow-condensed",
  display: "swap",
});

/** Labels, clocks and data. */
export const mono = IBM_Plex_Mono({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const arabic = Noto_Sans_Arabic({
  subsets: ["arabic"],
  variable: "--font-noto-arabic",
  display: "swap",
  preload: false,
});

export const fontVariables = [grotesk.variable, condensed.variable, mono.variable, arabic.variable].join(" ");
