"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

/** Wall-clock milliseconds, re-rendering every `intervalMs`. Starts at 0 on the server. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(0);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0);
    const id = setInterval(tick, intervalMs);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [intervalMs]);
  return now;
}

function subscribeMedia(query: string) {
  return (cb: () => void) => {
    const mq = window.matchMedia(query);
    mq.addEventListener("change", cb);
    return () => mq.removeEventListener("change", cb);
  };
}

export function useMediaQuery(query: string, serverValue = false): boolean {
  return useSyncExternalStore(
    subscribeMedia(query),
    () => window.matchMedia(query).matches,
    () => serverValue,
  );
}

export const usePrefersReducedMotion = () => useMediaQuery("(prefers-reduced-motion: reduce)");

const noopSubscribe = () => () => undefined;

/** Reads a URL search param once on the client (no Suspense boundary needed). */
export function useSearchFlag(name: string): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => new URLSearchParams(window.location.search).get(name) === "1",
    () => false,
  );
}

/** useState persisted to localStorage; storage failures (private mode, blocked) fall back to memory. */
export function useStoredState<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(initial);
  useEffect(() => {
    let stored: T | undefined;
    try {
      const raw = window.localStorage.getItem(key);
      if (raw !== null) stored = JSON.parse(raw) as T;
    } catch {
      stored = undefined;
    }
    if (stored === undefined) return;
    const t = setTimeout(() => setValue(stored as T), 0);
    return () => clearTimeout(t);
  }, [key]);
  const set = useCallback(
    (v: T) => {
      setValue(v);
      try {
        window.localStorage.setItem(key, JSON.stringify(v));
      } catch {
        /* storage unavailable */
      }
    },
    [key],
  );
  return [value, set];
}
