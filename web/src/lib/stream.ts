"use client";

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  type ReactNode,
} from "react";
import { api, API_BASE } from "./api";
import { useNow } from "./hooks";
import type {
  AgentData,
  AiredData,
  ClockStats,
  Cue,
  Fixture,
  HoldData,
  HoldResolvedData,
  Message,
  MessageKind,
  MomentData,
  Mode,
  RunData,
  RundownData,
  ScoreData,
  StateResponse,
  Story,
  TableData,
  TickerData,
} from "./types";

// One SSE connection per page, a reducer that tolerates the stream's catch-up burst
// (the service replays the latest message per key on connect, in no particular order),
// duplicates from /api/state hydration, and replay loops (a newer `run: started` resets).

const KINDS: MessageKind[] = [
  "run",
  "score",
  "ticker",
  "moment",
  "agent",
  "hold",
  "hold_resolved",
  "cue",
  "aired",
  "board",
  "table",
  "rundown",
  "clock",
];

const CAP = { ticker: 80, moments: 240, agents: 60, cues: 160, aired: 320, scores: 60 };
/** How far past the last message the client clock may run on its own (match ms). */
const MAX_EXTRAPOLATION_MS = 30_000;

export type Connection = "connecting" | "open" | "reconnecting";

export interface SimClock {
  simT: number;
  /** client epoch ms when simT was last observed */
  at: number;
  /** match ms per wall ms */
  rate: number;
}

export interface AgentRun {
  momentId: string;
  matchId?: string;
  kind?: string;
  stage: AgentData["stage"];
  simT: number;
  startedAt: number;
  ms?: number;
  trace?: string[];
  error?: string;
}

export interface HoldEntry extends HoldData {
  receivedAt: number;
  expiresAt: number;
  simT: number;
}

export type TimedCue = Cue & { sim_t: number };
export type AiredItem = AiredData & { sim_t: number; wall: number };
export type TickerItem = TickerData & { key: string; sim_t: number };
export type RundownItem = RundownData & { sim_t: number };
export type ScorePoint = ScoreData & { sim_t: number };
export type ResolvedHold = HoldResolvedData & { sim_t: number; at: number };

export interface GalleryState {
  connection: Connection;
  mode: Mode;
  runLabel: string | null;
  run: RunData | null;
  runWall: number;
  finished: boolean;
  clock: SimClock;
  fixtures: Record<string, Fixture>;
  fixtureOrder: string[];
  scores: Record<string, ScoreData>;
  scoreLog: Record<string, ScorePoint[]>;
  minutes: Record<string, { minute: number; sim_t: number }>;
  ticker: TickerItem[];
  moments: Record<string, MomentData & { sim_t: number }>;
  agents: Record<string, AgentRun>;
  agentOrder: string[];
  holds: Record<string, HoldEntry>;
  resolved: Record<string, ResolvedHold>;
  cues: Record<string, TimedCue>;
  cueOrder: string[];
  aired: AiredItem[];
  boards: Record<string, Story[]>;
  /** story ids cited by a cue that aired somewhere */
  airedStories: Record<string, true>;
  everSurfaced: Record<string, true>;
  table: TableData | null;
  prevTable: TableData | null;
  rundown: RundownItem | null;
  stats: ClockStats | null;
  /** slot → server wall time of the message currently held in that slot */
  seen: Record<string, number>;
  maxWall: number;
}

type Action =
  | { type: "batch"; msgs: Message[]; now: number }
  | { type: "hydrate"; state: StateResponse; now: number }
  | { type: "connection"; value: Connection };

function emptyRun(s?: GalleryState): GalleryState {
  return {
    connection: s?.connection ?? "connecting",
    mode: s?.mode ?? "idle",
    runLabel: s?.runLabel ?? null,
    run: null,
    runWall: 0,
    finished: false,
    clock: { simT: 0, at: 0, rate: 1 },
    fixtures: {},
    fixtureOrder: [],
    scores: {},
    scoreLog: {},
    minutes: {},
    ticker: [],
    moments: {},
    agents: {},
    agentOrder: [],
    holds: {},
    resolved: {},
    cues: {},
    cueOrder: [],
    aired: [],
    boards: {},
    airedStories: {},
    everSurfaced: {},
    table: null,
    prevTable: null,
    rundown: null,
    stats: null,
    seen: {},
    maxWall: s?.maxWall ?? 0,
  };
}

export const initialGallery = (): GalleryState => emptyRun();

/** Shallow-copies every container once so a batch can be applied with plain writes. */
function writable(s: GalleryState): GalleryState {
  return {
    ...s,
    fixtures: { ...s.fixtures },
    fixtureOrder: [...s.fixtureOrder],
    scores: { ...s.scores },
    scoreLog: { ...s.scoreLog },
    minutes: { ...s.minutes },
    ticker: [...s.ticker],
    moments: { ...s.moments },
    agents: { ...s.agents },
    agentOrder: [...s.agentOrder],
    holds: { ...s.holds },
    resolved: { ...s.resolved },
    cues: { ...s.cues },
    cueOrder: [...s.cueOrder],
    aired: [...s.aired],
    boards: { ...s.boards },
    airedStories: { ...s.airedStories },
    everSurfaced: { ...s.everSurfaced },
    seen: { ...s.seen },
  };
}

const bySimT = <T extends { sim_t: number }>(a: T, b: T) => a.sim_t - b.sim_t;

function newer(s: GalleryState, slot: string, wall: number): boolean {
  const prev = s.seen[slot];
  if (prev !== undefined && wall < prev) return false;
  s.seen[slot] = wall;
  return true;
}

function touchMinute(s: GalleryState, matchId: string, minute: number, simT: number) {
  const m = s.minutes[matchId];
  if (!m || simT >= m.sim_t) s.minutes[matchId] = { minute, sim_t: simT };
}

function setFixtures(s: GalleryState, fixtures: Fixture[] | undefined) {
  if (!fixtures?.length) return;
  s.fixtures = {};
  s.fixtureOrder = [];
  for (const f of fixtures) {
    s.fixtures[f.match_id] = f;
    s.fixtureOrder.push(f.match_id);
  }
}

function apply(input: GalleryState, msg: Message, now: number): GalleryState {
  let s = input;
  if (msg.kind === "hello") {
    s.mode = msg.data.mode;
    s.runLabel = msg.data.run;
    return s;
  }
  if (typeof msg.wall !== "number") return s;
  if (msg.kind !== "run" && s.runWall && msg.wall < s.runWall) return s; // from a previous run
  s.maxWall = Math.max(s.maxWall, msg.wall);

  if (msg.kind === "run") {
    const d = msg.data;
    if (d.status === "started") {
      if (msg.wall < s.runWall) return s;
      if (msg.wall > s.runWall) {
        s = writable(emptyRun(s));
        s.runWall = msg.wall;
        s.clock = { simT: 0, at: now, rate: d.speed && d.mode !== "replay" ? d.speed : 6 };
      }
      s.run = d;
      s.mode = d.mode ?? "live";
      if (s.mode === "live") s.runLabel = d.id;
      else if (!s.runLabel?.startsWith("replay")) s.runLabel = "replay";
      setFixtures(s, d.fixtures);
    } else if (msg.wall >= s.runWall) {
      s.finished = true;
      if (d.stats) s.stats = d.stats;
    }
    return s;
  }

  // the match clock
  if (msg.sim_t > s.clock.simT) {
    let rate = s.clock.rate;
    const elapsed = msg.wall - s.runWall;
    if (s.runWall && elapsed > 2) rate = Math.min(60, Math.max(0.25, msg.sim_t / (elapsed * 1000)));
    s.clock = { simT: msg.sim_t, at: now, rate };
  }

  switch (msg.kind) {
    case "score": {
      const d = msg.data;
      const log = [...(s.scoreLog[d.match_id] ?? [])];
      if (!log.some((p) => p.sim_t === msg.sim_t && p.score[0] === d.score[0] && p.score[1] === d.score[1])) {
        log.push({ ...d, sim_t: msg.sim_t });
        log.sort(bySimT);
        s.scoreLog[d.match_id] = log.slice(-CAP.scores);
      }
      if (newer(s, `score:${d.match_id}`, msg.wall)) s.scores[d.match_id] = d;
      touchMinute(s, d.match_id, d.minute, msg.sim_t);
      break;
    }
    case "ticker": {
      const d = msg.data;
      const key = `${d.match_id}:${msg.sim_t}:${d.type}:${d.player}:${d.outcome}`;
      if (!s.ticker.some((x) => x.key === key)) {
        s.ticker.push({ ...d, key, sim_t: msg.sim_t });
        s.ticker.sort(bySimT);
        if (s.ticker.length > CAP.ticker) s.ticker = s.ticker.slice(-CAP.ticker);
      }
      touchMinute(s, d.match_id, d.minute, msg.sim_t);
      break;
    }
    case "moment": {
      s.moments[msg.data.id] = { ...msg.data, sim_t: msg.sim_t };
      const ids = Object.keys(s.moments);
      if (ids.length > CAP.moments * 1.25) {
        const keep = ids.sort((a, b) => s.moments[a].sim_t - s.moments[b].sim_t).slice(-CAP.moments);
        s.moments = Object.fromEntries(keep.map((k) => [k, s.moments[k]]));
      }
      break;
    }
    case "agent": {
      const d = msg.data;
      const prev = s.agents[d.moment_id];
      if (prev && prev.stage !== "started" && d.stage === "started") break;
      s.agents[d.moment_id] = {
        momentId: d.moment_id,
        matchId: d.match_id ?? prev?.matchId,
        kind: d.kind ?? prev?.kind ?? s.moments[d.moment_id]?.kind,
        stage: d.stage,
        simT: prev?.simT ?? msg.sim_t,
        startedAt: prev?.startedAt ?? now,
        ms: d.ms,
        trace: d.trace,
        error: d.error,
      };
      if (!prev) {
        s.agentOrder.push(d.moment_id);
        s.agentOrder.sort((a, b) => s.agents[a].simT - s.agents[b].simT);
        if (s.agentOrder.length > CAP.agents) {
          for (const id of s.agentOrder.splice(0, s.agentOrder.length - CAP.agents)) delete s.agents[id];
        }
      }
      break;
    }
    case "hold": {
      const d = msg.data;
      if (s.resolved[d.id]) break;
      const lagMs = Math.max(0, s.maxWall - msg.wall) * 1000;
      s.holds[d.id] = {
        ...d,
        receivedAt: now,
        expiresAt: now + d.expires_in_s * 1000 - lagMs,
        simT: msg.sim_t,
      };
      break;
    }
    case "hold_resolved": {
      s.resolved[msg.data.id] = { ...msg.data, sim_t: msg.sim_t, at: now };
      delete s.holds[msg.data.id];
      break;
    }
    case "cue": {
      const d = msg.data;
      const isNew = !s.cues[d.id];
      s.cues[d.id] = { ...d, sim_t: msg.sim_t };
      if (isNew) {
        s.cueOrder.push(d.id);
        s.cueOrder.sort((a, b) => s.cues[a].sim_t - s.cues[b].sim_t);
        if (s.cueOrder.length > CAP.cues) {
          for (const id of s.cueOrder.splice(0, s.cueOrder.length - CAP.cues)) delete s.cues[id];
        }
      }
      if (Object.values(d.verdicts ?? {}).some((v) => v.verdict === "ON_AIR")) {
        for (const c of d.claims ?? []) for (const r of c.refs) s.airedStories[r] = true;
        for (const id of d.stories ?? []) s.airedStories[id] = true;
      }
      break;
    }
    case "aired": {
      const d = msg.data;
      if (!s.aired.some((a) => a.id === d.id)) {
        s.aired.push({ ...d, sim_t: msg.sim_t, wall: msg.wall });
        s.aired.sort(bySimT);
        if (s.aired.length > CAP.aired) s.aired = s.aired.slice(-CAP.aired);
      }
      break;
    }
    case "board": {
      const d = msg.data;
      if (newer(s, `board:${d.match_id}`, msg.wall)) s.boards[d.match_id] = d.stories;
      for (const st of d.stories) if (st.status === "surfaced") s.everSurfaced[st.id] = true;
      break;
    }
    case "table": {
      if (newer(s, "table", msg.wall)) {
        if (s.table) s.prevTable = s.table;
        s.table = msg.data;
      }
      break;
    }
    case "rundown": {
      if (newer(s, "rundown", msg.wall)) s.rundown = { ...msg.data, sim_t: msg.sim_t };
      break;
    }
    case "clock": {
      s.stats = msg.data.stats;
      break;
    }
  }
  return s;
}

export function galleryReducer(state: GalleryState, action: Action): GalleryState {
  switch (action.type) {
    case "connection":
      return state.connection === action.value ? state : { ...state, connection: action.value };
    case "batch": {
      let s = writable(state);
      for (const m of action.msgs) s = apply(s, m, action.now);
      return s;
    }
    case "hydrate": {
      const { state: st, now } = action;
      let s = writable(state);
      s.mode = st.mode;
      s.runLabel = st.run;
      const msgs = [...st.last].sort((a, b) => a.wall - b.wall);
      for (const m of msgs) s = apply(s, m, now);
      if (st.sim_t > s.clock.simT) s.clock = { ...s.clock, simT: st.sim_t, at: now };
      s.mode = st.mode === "idle" ? s.mode : st.mode;
      return s;
    }
  }
}

/** Current match time (ms), extrapolated from the last message at the estimated replay/live rate. */
export function simAt(clock: SimClock, now: number, finished = false): number {
  if (!clock.at) return clock.simT;
  if (finished) return clock.simT;
  return clock.simT + Math.min(Math.max(0, now - clock.at) * clock.rate, MAX_EXTRAPOLATION_MS);
}

function backoff(attempt: number) {
  return Math.min(10_000, 500 * 2 ** Math.min(attempt, 5));
}

/** The gallery's SSE client: hydrate from /api/state, then follow /api/stream with reconnect. */
export function useGalleryStream() {
  const [state, dispatch] = useReducer(galleryReducer, undefined, initialGallery);

  useEffect(() => {
    let es: EventSource | null = null;
    let closed = false;
    let attempt = 0;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let flushTimer: ReturnType<typeof setTimeout> | undefined;
    let raf = 0;
    const queue: Message[] = [];
    const ctrl = new AbortController();

    const flush = () => {
      raf = 0;
      flushTimer = undefined;
      if (!queue.length) return;
      dispatch({ type: "batch", msgs: queue.splice(0), now: Date.now() });
    };
    const enqueue = (m: Message) => {
      queue.push(m);
      if (raf || flushTimer) return;
      // rAF is paused in background tabs; fall back to a timer so the queue keeps draining.
      if (typeof document !== "undefined" && document.hidden) flushTimer = setTimeout(flush, 250);
      else raf = requestAnimationFrame(flush);
    };
    const hydrate = () => {
      api
        .state(ctrl.signal)
        .then((st) => {
          if (!closed) dispatch({ type: "hydrate", state: st, now: Date.now() });
        })
        .catch(() => undefined);
    };
    const connect = () => {
      es = new EventSource(`${API_BASE}/api/stream`);
      es.onopen = () => {
        attempt = 0;
        dispatch({ type: "connection", value: "open" });
      };
      es.addEventListener("hello", (ev) => {
        try {
          enqueue({ kind: "hello", sim_t: 0, wall: 0, data: JSON.parse((ev as MessageEvent).data) });
        } catch {
          /* ignore a malformed frame */
        }
      });
      for (const kind of KINDS) {
        es.addEventListener(kind, (ev) => {
          try {
            enqueue(JSON.parse((ev as MessageEvent).data) as Message);
          } catch {
            /* ignore a malformed frame */
          }
        });
      }
      es.onerror = () => {
        es?.close();
        es = null;
        if (closed) return;
        attempt += 1;
        dispatch({ type: "connection", value: "reconnecting" });
        retryTimer = setTimeout(() => {
          if (closed) return;
          hydrate();
          connect();
        }, backoff(attempt));
      };
    };

    hydrate();
    connect();
    return () => {
      closed = true;
      es?.close();
      clearTimeout(retryTimer);
      clearTimeout(flushTimer);
      cancelAnimationFrame(raf);
      ctrl.abort();
    };
  }, []);

  return state;
}

interface GalleryContextValue {
  state: GalleryState;
}

const GalleryContext = createContext<GalleryContextValue | null>(null);

export function GalleryProvider({ children }: { children: ReactNode }) {
  const state = useGalleryStream();
  const value = useMemo(() => ({ state }), [state]);
  return createElement(GalleryContext.Provider, { value }, children);
}

export function useGallery(): GalleryContextValue {
  const ctx = useContext(GalleryContext);
  if (!ctx) throw new Error("useGallery must be used inside <GalleryProvider>");
  return ctx;
}

/** Match time (ms) for rendering, re-evaluated every `intervalMs`. */
export function useSimNow(intervalMs = 1000): number {
  const { state } = useGallery();
  const now = useNow(intervalMs);
  return now ? simAt(state.clock, now, state.finished) : state.clock.simT;
}

/**
 * Match time for effects and loops: returns a stable getter that reads the latest clock,
 * monotonic within a run (a late message never moves the picture backwards).
 */
export function useSimClock(): () => number {
  const { state } = useGallery();
  const ref = useRef({ clock: state.clock, finished: state.finished, runWall: state.runWall });
  const last = useRef({ runWall: 0, t: 0 });
  useEffect(() => {
    ref.current = { clock: state.clock, finished: state.finished, runWall: state.runWall };
  }, [state.clock, state.finished, state.runWall]);
  return useCallback(() => {
    const { clock, finished, runWall } = ref.current;
    const t = simAt(clock, Date.now(), finished);
    const prev = last.current;
    if (prev.runWall === runWall && t < prev.t && prev.t - t < MAX_EXTRAPOLATION_MS) return prev.t;
    last.current = { runWall, t };
    return t;
  }, []);
}
