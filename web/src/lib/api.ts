import type { FrameResponse, LedgerResponse, LiveStartResponse, StateResponse } from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_TALKBACK_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

/** Where the backend will serve the OGraf renderer page for a territory output. */
export const OGRAF_RENDERER = (output: string) =>
  `${API_BASE}/ograf/renderer/index.html?renderer=${encodeURIComponent(output)}`;

/** Set NEXT_PUBLIC_OGRAF=1 (or add ?ograf=1 to the URL) to show the OGraf renderer instead of the web overlay. */
export const OGRAF_DEFAULT = process.env.NEXT_PUBLIC_OGRAF === "1";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(0, "The gallery service is not reachable.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const api = {
  state: (signal?: AbortSignal) => request<StateResponse>("/api/state", { signal }),
  frame: (matchId: string, t: number, signal?: AbortSignal) =>
    request<FrameResponse>(`/api/frames/${encodeURIComponent(matchId)}?t=${Math.max(100, Math.round(t))}`, {
      signal,
    }),
  goLive: (speed?: number) =>
    request<LiveStartResponse>("/api/live", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(speed ? { speed } : {}),
    }),
  holds: () => request<{ holds: { moment_id: string; match_id: string; holds: unknown[] }[] }>("/api/holds"),
  decide: (momentId: string, decisions: Record<string, "approve" | "reject">) =>
    request<{ ok: boolean }>(`/api/holds/${encodeURIComponent(momentId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decisions }),
    }),
  ledger: (cueId: string, signal?: AbortSignal) =>
    request<LedgerResponse>(`/api/ledger/${encodeURIComponent(cueId)}`, { signal }),
};
