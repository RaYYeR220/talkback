// Copies the club colours and squad numbers the UI needs out of a run's world.json.
// Usage: node scripts/sync-world.mjs ../runs/md-2026/world.json
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const src = process.argv[2];
if (!src) {
  console.error("usage: node scripts/sync-world.mjs <path/to/world.json>");
  process.exit(1);
}
const world = JSON.parse(readFileSync(src, "utf8"));
const clubs = {};
const players = {};
for (const c of world.league.clubs) {
  clubs[c.id] = { name: c.name, short: c.short, city: c.city, primary: c.primary, secondary: c.secondary };
  for (const p of c.squad) players[p.id] = [p.short_name, p.shirt, p.position];
}
const out = { league: world.league.name, season: world.league.season, clubs, players };
const dest = fileURLToPath(new URL("../src/data/world.json", import.meta.url));
writeFileSync(dest, JSON.stringify(out) + "\n");
console.log(`wrote ${Object.keys(clubs).length} clubs, ${Object.keys(players).length} players`);
