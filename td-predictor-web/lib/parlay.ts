/**
 * Parlay + market math, ported from td_predictor_v5.py so the website behaves
 * exactly like the Python app. Pure functions, no React, no I/O.
 *
 * Everything here answers "how likely is this, statistically?" It knows nothing
 * about payouts, so it cannot tell you whether a parlay is a good BET.
 */

export type BoardPlayer = {
  player_id: string;
  player: string;
  team: string;
  opponent: string;
  td_score: number;
  td_estimate: number;
  game_status: string; // "Upcoming" | "Final"
};

export const VOLATILITY_ORDER = ["Most Likely", "Moderate", "Long Shot", "Extreme Long Shot"] as const;
export type VolatilityBand = (typeof VOLATILITY_ORDER)[number];

export const VOLATILITY_EMOJI: Record<VolatilityBand, string> = {
  "Most Likely": "🟢 Most Likely",
  Moderate: "🟡 Moderate",
  "Long Shot": "🟠 Long Shot",
  "Extreme Long Shot": "🔴 Extreme Long Shot",
};

export type Cutoffs = { q75: number; q50: number; q25: number };

export type Leg = {
  player_id: string;
  player: string;
  team: string;
  opponent: string;
  probability_pct: number;
};

export type ParlayResult = {
  legs: Leg[];
  combinedPct: number;
  volatility: string;
  sameTeamWarning: boolean;
  targetMissed: boolean;
};

type Combo = { value: number; picks: string[] };

/** Linear-interpolated quantile; matches pandas Series.quantile (default). */
export function quantile(sortedAsc: number[], q: number): number {
  const n = sortedAsc.length;
  if (n === 0) return NaN;
  const pos = q * (n - 1);
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sortedAsc[lo] + (sortedAsc[hi] - sortedAsc[lo]) * (pos - lo);
}

/** Players still available to parlay (games not final), best first. */
export function eligiblePool(board: BoardPlayer[]): BoardPlayer[] {
  return board
    .filter((p) => p.game_status !== "Final")
    .slice()
    .sort((a, b) => (b.td_score ?? 0) - (a.td_score ?? 0));
}

function rawCombinedPct(estimateById: Map<string, number>, ids: string[]): number {
  let product = 1;
  let found = 0;
  for (const id of ids) {
    const est = estimateById.get(id);
    if (est === undefined) continue;
    product *= est / 100;
    found += 1;
  }
  return found === 0 ? 0 : product * 100;
}

/**
 * A representative best-to-worst spread of achievable N-leg combos (start the
 * greedy pick at each rank in turn). Not every possible combination - that is
 * combinatorially huge - but a fair sample of the realistic range.
 */
function combosByOffset(pool: BoardPlayer[], nLegs: number, onePerTeam: boolean): Combo[] {
  const estimateById = new Map<string, number>();
  for (const p of pool) if (!estimateById.has(p.player_id)) estimateById.set(p.player_id, p.td_estimate);

  const combos: Combo[] = [];
  const maxOffset = Math.max(0, pool.length - nLegs);
  for (let offset = 0; offset <= maxOffset; offset++) {
    const picks: string[] = [];
    const usedTeams = new Set<string>();
    for (let i = offset; i < pool.length; i++) {
      const r = pool[i];
      if (onePerTeam && usedTeams.has(r.team)) continue;
      picks.push(r.player_id);
      usedTeams.add(r.team);
      if (picks.length === nLegs) break;
    }
    if (picks.length === nLegs) combos.push({ value: rawCombinedPct(estimateById, picks), picks });
  }
  return combos;
}

/**
 * Quartile cutoffs of what is actually achievable THIS WEEK for this leg count.
 * Relative on purpose: multiplying legs shrinks probability fast, so fixed
 * thresholds made "Most Likely" unreachable for any 3+ leg parlay.
 */
export function getVolatilityCutoffs(board: BoardPlayer[], nLegs: number, onePerTeam = true): Cutoffs | null {
  const combos = combosByOffset(eligiblePool(board), nLegs, onePerTeam);
  if (combos.length === 0) return null;
  const values = combos.map((c) => c.value).sort((a, b) => a - b);
  return { q75: quantile(values, 0.75), q50: quantile(values, 0.5), q25: quantile(values, 0.25) };
}

function bandOf(value: number, c: Cutoffs): VolatilityBand {
  if (value >= c.q75) return "Most Likely";
  if (value >= c.q50) return "Moderate";
  if (value >= c.q25) return "Long Shot";
  return "Extreme Long Shot";
}

export function volatilityLabel(combinedPct: number, cutoffs: Cutoffs | null): string {
  if (cutoffs === null) {
    // Fallback only when no reference range exists.
    if (combinedPct >= 15) return VOLATILITY_EMOJI["Most Likely"];
    if (combinedPct >= 5) return VOLATILITY_EMOJI.Moderate;
    if (combinedPct >= 1) return VOLATILITY_EMOJI["Long Shot"];
    return VOLATILITY_EMOJI["Extreme Long Shot"];
  }
  return VOLATILITY_EMOJI[bandOf(combinedPct, cutoffs)];
}

/**
 * Combined probability that ALL legs score, multiplying each player's own
 * estimate. That assumes independence - roughly fine across different games,
 * NOT fine for teammates (red-zone chances are a shared, limited resource),
 * which is why sameTeamWarning exists.
 *
 * Pass `cutoffs` to reuse ones you already computed; leave undefined to compute.
 */
export function parlayProbability(
  board: BoardPlayer[],
  playerIds: string[],
  cutoffs?: Cutoffs | null,
): ParlayResult {
  const wanted = new Set(playerIds);
  const seen = new Set<string>();
  const rows: BoardPlayer[] = [];
  for (const p of board) {
    if (wanted.has(p.player_id) && !seen.has(p.player_id)) {
      rows.push(p);
      seen.add(p.player_id);
    }
  }
  const missing = [...wanted].filter((id) => !seen.has(id));
  if (missing.length > 0) throw new Error(`Could not find these player(s) on this week's board: ${missing.join(", ")}`);

  let combined = 1;
  const legs: Leg[] = rows.map((r) => {
    combined *= r.td_estimate / 100;
    return {
      player_id: r.player_id,
      player: r.player,
      team: r.team,
      opponent: r.opponent,
      probability_pct: r.td_estimate,
    };
  });
  const combinedPct = combined * 100;
  const resolved = cutoffs === undefined ? getVolatilityCutoffs(board, wanted.size) : cutoffs;
  const teams = rows.map((r) => r.team);

  return {
    legs,
    combinedPct,
    volatility: volatilityLabel(combinedPct, resolved),
    sameTeamWarning: new Set(teams).size !== teams.length,
    targetMissed: false,
  };
}

export type AutoBuildOptions = {
  nLegs: number;
  onePerTeam: boolean;
  target: VolatilityBand;
  /** Recently shown combinations (player_id lists) to avoid repeating. */
  avoid?: string[][];
  /** Injectable for tests; defaults to Math.random. */
  rng?: () => number;
};

/**
 * Picks randomly among ALL combinations that land in the requested band, and
 * skips recently shown ones when an alternative exists. If the band is empty
 * (only possible with a tiny pool) it says so via targetMissed instead of
 * pretending it hit the target.
 */
export function autoBuildParlay(board: BoardPlayer[], opts: AutoBuildOptions): ParlayResult {
  const { nLegs, onePerTeam, target, avoid = [], rng = Math.random } = opts;
  if (!(VOLATILITY_ORDER as readonly string[]).includes(target)) {
    throw new Error(`Unknown volatility target: ${target}`);
  }

  const pool = eligiblePool(board);
  const combos = combosByOffset(pool, nLegs, onePerTeam);
  if (combos.length === 0) throw new Error("Not enough eligible players this week to build a parlay of this size.");

  const values = combos.map((c) => c.value).sort((a, b) => a - b);
  const cutoffs: Cutoffs = { q75: quantile(values, 0.75), q50: quantile(values, 0.5), q25: quantile(values, 0.25) };

  let matches = combos.filter((c) => bandOf(c.value, cutoffs) === target).map((c) => c.picks);
  let targetMissed = false;
  if (matches.length === 0) {
    targetMissed = true;
    matches = combos.map((c) => c.picks);
  }

  if (avoid.length > 0) {
    const avoidKeys = new Set(avoid.map((s) => [...s].sort().join("|")));
    const fresh = matches.filter((m) => !avoidKeys.has([...m].sort().join("|")));
    if (fresh.length > 0) matches = fresh;
  }

  const chosen = matches[Math.min(matches.length - 1, Math.floor(rng() * matches.length))];
  const result = parlayProbability(board, chosen, cutoffs);
  result.targetMissed = targetMissed;
  return result;
}

/**
 * American odds -> the probability the price implies (vig NOT removed).
 * "+150" -> 40%, "-150" -> 60%. Returns null for anything unreadable.
 */
export function impliedProbFromAmericanOdds(input: string): number | null {
  const cleaned = input.trim().replace(/^\+/, "");
  if (cleaned === "") return null;
  const odds = Number(cleaned);
  if (!Number.isFinite(odds) || odds === 0) return null;
  return odds > 0 ? (100 / (odds + 100)) * 100 : (-odds / (-odds + 100)) * 100;
}

/**
 * A probability expressed as the American-odds price that would be break-even
 * for it (no vig). 25% -> "+300", 75% -> "-300". Compare against a book's
 * price: a better payout than this means the book is paying more than the
 * model thinks the outcome is worth (if you trust the model).
 */
export function fairAmericanOdds(pct: number): string | null {
  const p = pct / 100;
  if (!Number.isFinite(p) || p <= 0 || p >= 1) return null;
  return p <= 0.5 ? `+${Math.round(((1 - p) / p) * 100)}` : `-${Math.round((p / (1 - p)) * 100)}`; // even money is +100
}