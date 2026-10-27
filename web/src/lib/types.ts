// Payloads of the Talkback gallery service (src/talkback/service/app.py, gallery/runner.py).

export type Mode = "replay" | "live" | "idle";
export type Territory = "uk" | "es" | "mena" | "kids" | "br";
/** A program output: the international clean feed, or one territory's cleared feed. */
export type Output = "world" | Territory;
export type Verdict = "ON_AIR" | "HOLD_FOR_PRODUCER" | "KILLED";
export type Audience = "analyst" | "casual" | "presenter" | "recap";
export type TemplateId =
  | "stat_card"
  | "story_card"
  | "lower_third"
  | "counterfactual_card"
  | "table_swing"
  | "player_tag";
export type StoryStatus = "latent" | "live" | "surfaced" | "resolved";
export type Scalar = string | number | boolean | null;

export interface Envelope<K extends string = string, D = unknown> {
  kind: K;
  sim_t: number;
  wall: number;
  data: D;
}

export interface Fixture {
  match_id: string;
  home: string;
  away: string;
  home_name: string;
  away_name: string;
}

export interface RunData {
  id: string;
  status: "started" | "finished" | "generating" | "failed";
  speed?: number;
  fixtures?: Fixture[];
  mode?: Mode;
  recorded?: number;
  stats?: ClockStats;
}

export interface ScoreData {
  match_id: string;
  home: string;
  away: string;
  home_short: string;
  away_short: string;
  score: [number, number];
  minute: number;
  period: number;
  reds: [number, number];
  finished: boolean;
}

export interface TickerData {
  match_id: string;
  type: "goal" | "card" | "shot" | "substitution" | "period_end" | string;
  team: string | null;
  player: string;
  minute: number;
  outcome: string;
  xg: number | null;
}

export interface MomentData {
  id: string;
  match_id: string;
  t: number;
  kind: string;
  subject: string | null;
  salience: number;
  rationale: string;
  ranked_by: string;
  event_ids?: string[];
  detail?: Record<string, Scalar>;
}

export interface AgentData {
  moment_id: string;
  match_id?: string;
  stage: "started" | "done" | "error";
  kind?: string;
  ms?: number;
  trace?: string[];
  error?: string;
}

export interface HoldCue {
  cue_id: string;
  text: string;
  territories: Territory[];
  reasons: string[];
}

export interface HoldData {
  id: string;
  match_id: string;
  holds: HoldCue[];
  expires_in_s: number;
}

export interface HoldResolvedData {
  id: string;
  decision: Record<string, string>;
}

export interface Claim {
  span: string;
  kind: "numeric" | "comparative" | "causal" | "storyline" | "descriptive" | string;
  subject: string | null;
  refs: string[];
  value: number | null;
  strength: number;
}

export interface TerritoryVerdict {
  territory: string;
  verdict: Verdict;
  reasons: string[];
  text: string;
}

export interface Experiment {
  id: string;
  moment_id?: string;
  metric: string;
  baseline: number;
  counterfactual: number;
  effect: number;
  ci95: [number, number];
  n: number;
  seed?: number;
  intervention: Record<string, Scalar> & { describe?: string };
}

export interface Fact {
  id: string;
  match_id?: string | null;
  metric: string;
  subject: string;
  value: number;
  unit: string;
  window: [number, number];
  sample_size: number;
  evidence: string[];
  computed_at?: number;
}

export interface Cue {
  id: string;
  match_id: string;
  moment_id: string | null;
  audience: Audience | string;
  text: string;
  lang: string;
  claims: Claim[];
  template: TemplateId | string;
  data: Record<string, Scalar>;
  valid_state_hash?: string;
  max_age_ms?: number;
  created_t?: number;
  universal_reasons: string[];
  verdicts: Record<string, TerritoryVerdict>;
  moment_kind?: string;
  moment_t?: number;
  latency_ms?: number;
  status?: Record<string, string>;
  timings?: Record<string, number>;
  stories?: string[];
  experiments?: Experiment[];
  lab_conclusion?: string;
  evidence?: Fact[];
}

export interface AiredData {
  id: string;
  cue_id: string;
  match_id: string;
  territory: Territory;
  text: string;
  template: TemplateId | string;
  data: Record<string, Scalar>;
  audience: Audience | string;
  delay_ms: number;
}

export interface Story {
  id: string;
  kind: string;
  subjects: string[];
  fixture_id?: string;
  summary: string;
  facts: Record<string, Scalar>;
  trigger?: string;
  status: StoryStatus;
}

export interface BoardData {
  match_id: string;
  stories: Story[];
}

export interface TableRow {
  club_id: string;
  position: number;
  points: number;
  title: number;
  top4: number;
  relegation: number;
}

export interface Swing {
  club_id: string;
  metric: "title" | "top4" | "relegation" | string;
  before: number;
  after: number;
  caused_by: string;
}

export interface TableData {
  rows: TableRow[];
  swings: Swing[];
}

export interface RundownData {
  channel: string;
  match_id: string;
  from_t: number;
  reason: string;
  moment_ids: string[];
}

export interface ClockStats {
  moments: number;
  workflows: number;
  cues: number;
  aired: number;
  held: number;
  killed: number;
  stale: number;
}

export interface ClockData {
  stats: ClockStats;
  holds: string[];
}

export interface HelloData {
  mode: Mode;
  run: string | null;
}

export type Message =
  | Envelope<"hello", HelloData>
  | Envelope<"run", RunData>
  | Envelope<"score", ScoreData>
  | Envelope<"ticker", TickerData>
  | Envelope<"moment", MomentData>
  | Envelope<"agent", AgentData>
  | Envelope<"hold", HoldData>
  | Envelope<"hold_resolved", HoldResolvedData>
  | Envelope<"cue", Cue>
  | Envelope<"aired", AiredData>
  | Envelope<"board", BoardData>
  | Envelope<"table", TableData>
  | Envelope<"rundown", RundownData>
  | Envelope<"clock", ClockData>;

export type MessageKind = Message["kind"];

export interface StateResponse {
  mode: Mode;
  run: string | null;
  sim_t: number;
  last: Message[];
}

export interface FrameResponse {
  match_id: string;
  t: number;
  ball: [number, number, number];
  ids: string[];
  pos: [number, number][];
}

export interface LedgerEvent {
  id: string;
  match_id: string;
  seq: number;
  t: number;
  period: number;
  type: string;
  team_id: string | null;
  player_id: string | null;
  other_player_id?: string | null;
  x: number | null;
  y: number | null;
  end_x?: number | null;
  end_y?: number | null;
  outcome: string;
  qualifiers: Record<string, Scalar>;
}

export interface LedgerResponse {
  cue: Cue;
  events: Record<string, LedgerEvent>;
}

export interface LiveStartResponse {
  run: string;
  mode: Mode;
}
