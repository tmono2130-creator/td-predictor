import type { BoardMeta, BoardRow, PredictionTiming, TableCell } from "./types";

export const formatPercent = (value: number, digits = 1) => value.toFixed(digits) + "%";
export const formatParlayPercent = (value: number) => value >= 1 ? value.toFixed(2) + "%" : value.toFixed(3) + "%";
export const teamName = (team: string) => team;
export const matchupLabel = (row: Pick<BoardRow, "team" | "opponent" | "is_home">) =>
  (row.is_home === 0 ? "@" : row.is_home === 1 ? "vs" : "·") + " " + row.opponent;
export function formatTimestamp(value: string) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "Time unavailable";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}
export const timingLabel = (timing: PredictionTiming) =>
  timing === "pregame_snapshot" ? "Pregame snapshot" :
  timing === "historical_backfill" ? "Historical backfill" : "Timing unknown";
export function cellText(value: TableCell | undefined): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return value;
}

// A snapshot's freshness is separate from its authenticity classification.
export function snapshotFreshness(meta: BoardMeta, now: number): string {
  const generated = Date.parse(meta.generated_at);
  if (!Number.isFinite(generated)) return "Freshness unavailable";
  if (generated > now + 60_000) return "Generation timestamp is in the future";
  if (meta.snapshot_classification === "historical_backfill") return "Retrospective record";
  const remaining = meta.games.map(g => Date.parse(g.kickoff_utc) - now).filter(ms => ms > 0);
  if (!remaining.length) return "Archived snapshot · games have started";
  const next = Math.min(...remaining);
  const limit = next <= 6 * 3_600_000 ? 3_600_000 : next <= 48 * 3_600_000 ? 6 * 3_600_000 : 24 * 3_600_000;
  return now - generated > limit ? "Refresh due · viewing saved snapshot" : "Within refresh window";
}
