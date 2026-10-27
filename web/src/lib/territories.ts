import type { Output, Territory, Verdict } from "./types";

export interface TerritoryInfo {
  id: Output;
  code: string;
  label: string;
  language: string;
  lang: string;
  dir: "ltr" | "rtl";
  /** Broadcast delay in match-time milliseconds (MENA airs two minutes behind). */
  delayMs: number;
  note: string;
}

export const TERRITORIES: Territory[] = ["uk", "es", "mena", "kids", "br"];
export const OUTPUTS: Output[] = ["world", ...TERRITORIES];

export const TERRITORY: Record<Output, TerritoryInfo> = {
  world: {
    id: "world",
    code: "WORLD",
    label: "World feed",
    language: "English (source)",
    lang: "en",
    dir: "ltr",
    delayMs: 0,
    note: "International clean feed: the source line of anything cleared in at least one territory.",
  },
  uk: {
    id: "uk",
    code: "UK",
    label: "United Kingdom",
    language: "English",
    lang: "en-GB",
    dir: "ltr",
    delayMs: 0,
    note: "Gambling references blocked; impartial wording.",
  },
  es: {
    id: "es",
    code: "ES",
    label: "Spain",
    language: "Español",
    lang: "es",
    dir: "ltr",
    delayMs: 0,
    note: "Strict gambling ban.",
  },
  mena: {
    id: "mena",
    code: "MENA",
    label: "Middle East & North Africa",
    language: "العربية",
    lang: "ar",
    dir: "rtl",
    delayMs: 120_000,
    note: "Airs two minutes behind; other matches' results are embargoed inside the delay.",
  },
  kids: {
    id: "kids",
    code: "KIDS",
    label: "Kids",
    language: "English (simple)",
    lang: "en",
    dir: "ltr",
    delayMs: 0,
    note: "Minors-safe: no injury detail, no discipline focus, simpler words.",
  },
  br: {
    id: "br",
    code: "BR",
    label: "Brazil",
    language: "Português",
    lang: "pt-BR",
    dir: "ltr",
    delayMs: 0,
    note: "Portuguese desk.",
  },
};

export const VERDICT_LABEL: Record<Verdict, string> = {
  ON_AIR: "On air",
  HOLD_FOR_PRODUCER: "Held",
  KILLED: "Killed",
};

export const VERDICT_SHORT: Record<Verdict, string> = {
  ON_AIR: "AIR",
  HOLD_FOR_PRODUCER: "HELD",
  KILLED: "KILL",
};

export function isTerritory(x: string): x is Territory {
  return (TERRITORIES as string[]).includes(x);
}

export function isOutput(x: string): x is Output {
  return (OUTPUTS as string[]).includes(x);
}
