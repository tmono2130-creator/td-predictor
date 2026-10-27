import type { BoardRow, PredictionTiming, TableCell } from "./types";

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
