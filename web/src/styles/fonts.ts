import { Figtree, Geist_Mono, Instrument_Serif, Noto_Sans_Arabic } from "next/font/google";

// Faces are exposed as CSS variables; theme.css decides which variable plays which role.

export const display = Instrument_Serif({
  subsets: ["latin", "latin-ext"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-instrument-serif",
  display: "swap",
});

export const ui = Figtree({
  subsets: ["latin", "latin-ext"],
  variable: "--font-figtree",
  display: "swap",
});

export const mono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
  display: "swap",
});

export const arabic = Noto_Sans_Arabic({
  subsets: ["arabic"],
  variable: "--font-noto-arabic",
  display: "swap",
  preload: false,
});

export const fontVariables = [display.variable, ui.variable, mono.variable, arabic.variable].join(" ");
