/** Selection only. Existing parlay.ts remains the sole parlay/Market math implementation. */
export type GeneratorPlayer = {
  player_id: string; game_id: string; td_estimate: number; game_status: string;
  injury_status: string; game_day_status?: string; roster_eligibility?: string;
};
export type GeneratorOptions = {
  legs: number; count: number; mode: "high-estimate" | "balanced" | "long-shot";
  maxExposure: number; crossGame: boolean; seed: string;
  games: readonly { game_id: string; kickoff_utc: string }[];
  generatedAt: string; now: number;
};
export type GeneratorResult = { combinations: string[][]; exposure: Record<string, number>; cap: number; eligible: number; warning: string | null };

export function seededRandom(seed: string): () => number {
  let state = 2166136261;
  for (const char of seed) state = Math.imul(state ^ char.charCodeAt(0), 16777619);
  return () => {
    state += 0x6d2b79f5;
    let value = Math.imul(state ^ (state >>> 15), 1 | state);
    value ^= value + Math.imul(value ^ (value >>> 7), 61 | value);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

export function generateParlays(rows: readonly GeneratorPlayer[], options: GeneratorOptions): GeneratorResult {
  const { legs, count, maxExposure, crossGame, mode, now } = options;
  if (!Number.isInteger(legs) || legs < 2 || legs > 5 || ![10, 20, 30].includes(count) ||
      !Number.isFinite(maxExposure) || maxExposure <= 0 || maxExposure > 1 ||
      !["high-estimate", "balanced", "long-shot"].includes(mode) || !Number.isFinite(now)) throw new Error("Invalid generator settings.");
  const generated = Date.parse(options.generatedAt);
  if (!Number.isFinite(generated) || generated > now) throw new Error("Prediction timestamp is invalid or in the future.");
  const cap = Math.floor(count * maxExposure);
  if (cap < 1) throw new Error("Exposure limit permits no appearances. Increase it.");
  const games = new Set(options.games.filter(g => {
    const remaining = Date.parse(g.kickoff_utc) - now;
    const limit = remaining <= 6 * 3600000 ? 1800000 : remaining <= 48 * 3600000 ? 6 * 3600000 : 24 * 3600000;
    return remaining > 600000 && now - generated < limit;
  }).map(g => g.game_id));
  const ids = new Set<string>();
  for (const row of rows) {
    if (ids.has(row.player_id)) throw new Error("Duplicate player identity in prediction pool.");
    ids.add(row.player_id);
  }
  const pool = rows.filter(p => games.has(p.game_id) && p.game_status === "Upcoming" &&
    !["Out", "IR", "Inactive"].includes(p.injury_status) && p.game_day_status !== "inactive" &&
    !["ineligible", "pending"].includes(p.roster_eligibility ?? "") && Number.isFinite(p.td_estimate) && p.td_estimate > 0 && p.td_estimate <= 100);
  if (pool.length < legs || pool.length * cap < legs * count || (crossGame && new Set(pool.map(p => p.game_id)).size < legs)) {
    throw new Error("Not enough fresh eligible players or games for this exposure limit. Adjust filters or settings.");
  }
  const rng = seededRandom(options.seed), exposure: Record<string, number> = {}, combinations: string[][] = [], seen = new Set<string>();
  const exponent = mode === "high-estimate" ? 2.5 : mode === "long-shot" ? .35 : 1;
  for (let attempt = 0; attempt < count * 500 && combinations.length < count; attempt++) {
    const picked: GeneratorPlayer[] = [];
    for (let leg = 0; leg < legs; leg++) {
      const available = pool.filter(p => (exposure[p.player_id] ?? 0) < cap && !picked.includes(p) &&
        (!crossGame || !picked.some(other => other.game_id === p.game_id)));
      const weights = available.map(p => Math.pow(p.td_estimate / 100, exponent) * Math.pow(1 - (exposure[p.player_id] ?? 0) / cap, 2));
      const total = weights.reduce((a, b) => a + b, 0);
      if (!(total > 0)) break;
      let draw = rng() * total, index = 0;
      while (index < weights.length - 1 && draw >= weights[index]) draw -= weights[index++];
      picked.push(available[index]);
    }
    if (picked.length !== legs) continue;
    const key = picked.map(p => p.player_id).sort().join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    combinations.push(picked.map(p => p.player_id));
    for (const p of picked) exposure[p.player_id] = (exposure[p.player_id] ?? 0) + 1;
  }
  if (combinations.length !== count) throw new Error("Cannot generate the full unique batch within these constraints. Widen the pool or adjust exposure; no partial batch is returned.");
  return { combinations, exposure, cap, eligible: pool.length, warning: null };
}
