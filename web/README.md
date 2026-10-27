# Talkback web

The web front end for the Talkback gallery: a landing page, the console, a fan view and the proof page. It reads everything from the gallery service (`src/talkback/service/app.py`).

## Run it

Start the service from the repo root. With no live run, it replays the latest recorded matchday on a loop:

```sh
TALKBACK_RUN_DIR=runs/md-2026 TALKBACK_REPLAY_SPEED=6 uv run uvicorn talkback.service.app:app --port 8000
```

Then start the web app:

```sh
cd web
npm install
npm run dev          # http://localhost:3000
```

The service address comes from `NEXT_PUBLIC_API_BASE` (default `http://127.0.0.1:8000`). It is read at build time, so set it before `npm run build`.

```sh
npm run build        # standalone output in .next/standalone
npm run lint
npm run typecheck
```

## Pages

| Route | What it is |
|---|---|
| `/` | The claim, live air from the Director's match, how it works, the crew |
| `/gallery` | The console: ten-match wall, program monitor with territory outputs, Director rundown, story board with Story Recall, clearance matrix, producer queue, agents, live table, claim ledger |
| `/fan` | Territory and language, casual or analyst, favourite club; the feed cleared for that territory (Arabic right to left, two minutes behind) |
| `/proof` | The evaluation scorecard, read from `public/eval/summary.json` |

`public/eval/summary.json` holds **sample values** and is marked `"provisional": true`; the page says so on every number until the eval harness writes the real file.

## How it is put together

- `src/lib/stream.ts`: the one SSE client. It hydrates from `/api/state`, follows `/api/stream`, reconnects with backoff, and folds every message into one reducer. The service replays the latest message per key on connect, so the reducer is idempotent and order-tolerant; a newer `run: started` (a replay loop or a live kick-off) resets the state.
- `src/lib/types.ts`: the message payloads.
- `src/lib/frames.ts`: polls `/api/frames/{match}` (5 Hz for the program monitor, 1 Hz for the wall) at the extrapolated match time; delayed outputs poll behind it.
- `src/components/`: `broadcast/` (program monitor, graphics overlay, aired feed), `console/` (the console panels), `ledger/` (claim ledger drawer, Lab chart), `fan/`, `proof/`, `landing/`, `site/`.
- `src/data/world.json`: club names, colours and squad numbers from the fictional league. Regenerate with `node scripts/sync-world.mjs ../runs/md-2026/world.json`.

### Theme

Every colour, font role, radius, space and duration is a custom property in `src/styles/theme.css`; the pitch canvas reads the same properties. The faces are loaded in `src/styles/fonts.ts`. Re-theming means editing those two files. (The favicon in `src/app/icon.svg` carries its own two colours.)

### OGraf

The program monitor draws a web overlay for the latest aired graphic (stat card, story card, lower third, counterfactual card, table swing, player tag). To use the service's OGraf renderer instead, set `NEXT_PUBLIC_OGRAF=1` or add `?ograf=1` to the URL: the monitor then loads `/ograf/renderer/index.html?renderer=<output>` from the service as a transparent layer over the pitch (`ProgramMonitor`, `renderer` prop).
