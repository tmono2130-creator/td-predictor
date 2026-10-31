import type { WeeklyFiles } from "./types";

// A corrected current-week release may be newer than an older future-week export.
export function latestGeneratedWeek(weeks: Record<string, WeeklyFiles> | undefined, fallback = 1): number {
  const available = Object.entries(weeks ?? {})
    .filter(([week, entry]) => Number.isInteger(Number(week)) && Number(week) >= 1 && Number(week) <= 18 && Number.isFinite(Date.parse(entry.generated_at)))
    .sort(([a, first], [b, second]) => Date.parse(second.generated_at) - Date.parse(first.generated_at) || Number(b) - Number(a));
  return available.length ? Number(available[0][0]) : fallback;
}
