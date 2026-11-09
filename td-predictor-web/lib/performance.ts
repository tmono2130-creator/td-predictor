export type EvaluationIndex = { schema_version: 1; reports: { season: number; week: number; path: string; sha256: string }[] };
export type ScoreMetrics = { n: number; winner_accuracy: number | null; team_score_mae: number | null; total_mae: number | null; margin_mae: number | null };
export type TdMetrics = { n: number; positives: number; brier: number | null; log_loss: number | null; auc: number | null; calibration: { lower_pct: number; upper_pct: number; n: number; mean_estimate_pct: number; observed_pct: number }[] };
export type Evaluation = {
  schema_version: 1; evaluation_id: string; engine_sha256: string; outcome_sources: Record<string, unknown>; season: number; week: number; status: "partial" | "complete";
  evaluated_as_of: string; forecast_generated_at: string; forecast_hashes: Record<string, string>;
  games_completed: number; games_pending: number; game_metrics: ScoreMetrics; baseline_metrics: ScoreMetrics;
  td_metrics: TdMetrics; position_metrics: Record<string, TdMetrics>; missing_labels: Record<string, number>;
  top_per_game?: Record<string, { selected: number; labelled: number; hits: number; hit_rate: number | null }>;
  margin_bands?: Record<string, ScoreMetrics>;
  limitations: string[];
  games: { game_id: string; away_team: string; home_team: string; kickoff_utc: string; status: "final" | "pending";
    prediction: { away: number; home: number } | null; prior_offensive_mean?: { away: number; home: number } | null; actual: { away: number; home: number } | null }[];
  players: { game_id: string; player_id: string; player: string; team: string; position: string; estimate_pct: number;
    actual_td: boolean | null; outcome_reason: string }[];
};
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const integer = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v >= 0;
const number = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v >= 0;
const timestamp = (v: unknown): v is string => typeof v === "string" && Number.isFinite(Date.parse(v));
const hash = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);

export function isEvaluationIndex(value: unknown): value is EvaluationIndex {
  if (!record(value) || value.schema_version !== 1 || !Array.isArray(value.reports)) return false;
  const seen = new Set<string>();
  return value.reports.every(r => {
    if (!record(r) || !integer(r.season) || r.season < 2002 || !integer(r.week) || r.week < 1 || r.week > 18 ||
      typeof r.path !== "string" || !/^[a-f0-9]{24}\/evaluation\.json$/.test(r.path) || !hash(r.sha256)) return false;
    const key = `${r.season}:${r.week}`;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  });
}

// Structural provenance checks are not independent verification of the source bytes.
// decodeEvaluation separately binds bytes to a reviewed index SHA-256. Arithmetic
// checks below bind reported metrics to observations, not observations to reality.
function validOutcomeSources(value: unknown, season: number, asOf: string): boolean {
  if (!record(value) || value.kind !== "live_capture" || !timestamp(value.started_at_utc) ||
    !timestamp(value.source_cutoff_utc) || Date.parse(value.source_cutoff_utc) !== Date.parse(asOf) ||
    Date.parse(value.started_at_utc) > Date.parse(asOf) || typeof value.git_revision !== "string" ||
    !/^[a-f0-9]{40}$/.test(value.git_revision) || !record(value.code_sha256) ||
    !Object.keys(value.code_sha256).length || !Object.values(value.code_sha256).every(hash) ||
    !record(value.dependencies) || !Object.keys(value.dependencies).length ||
    !Object.values(value.dependencies).every(v => typeof v === "string" && v.length > 0) || !record(value.sources)) return false;
  const sources = value.sources;
  return ["schedule", `stats_${season}`, `pbp_${season}`].every(key => {
    const r = sources[key];
    if (!record(r) || r.available !== true || !hash(r.sha256) || !integer(r.bytes) || r.bytes < 1 ||
      typeof r.path !== "string" || r.path !== key + (key === "schedule" ? ".csv" : ".parquet") ||
      typeof r.url !== "string" || !r.url.startsWith("https://") ||
      !timestamp(r.started_at_utc) || !timestamp(r.retrieved_at_utc) ||
      Date.parse(r.started_at_utc) < Date.parse(value.started_at_utc as string) ||
      Date.parse(r.started_at_utc) > Date.parse(r.retrieved_at_utc) || Date.parse(r.retrieved_at_utc) > Date.parse(asOf)) return false;
    return r.provider_modified_utc === null || (timestamp(r.provider_modified_utc) && Date.parse(r.provider_modified_utc) <= Date.parse(r.retrieved_at_utc));
  });
}

const sameArithmetic = (actual: unknown, expected: unknown): boolean => {
  if (typeof expected === "number") return typeof actual === "number" && Number.isFinite(actual) && Math.abs(actual - expected) <= 1e-9 * Math.max(1, Math.abs(expected));
  if (expected === null) return actual === null;
  if (Array.isArray(expected)) return Array.isArray(actual) && actual.length === expected.length && expected.every((v, i) => sameArithmetic(actual[i], v));
  return record(expected) && record(actual) && Object.entries(expected).every(([k, v]) => sameArithmetic(actual[k], v));
};
function tdArithmetic(players: Evaluation["players"]): TdMetrics {
  const rows = players.filter(p => p.actual_td !== null), n = rows.length, positives = rows.filter(p => p.actual_td).length;
  if (!n) return { n, positives, brier: null, log_loss: null, auc: null, calibration: [] };
  let brier = 0, loss = 0, wins = 0, negativesBefore = 0;
  const sorted = [...rows].sort((a, b) => a.estimate_pct - b.estimate_pct);
  for (let i = 0; i < sorted.length;) {
    let end = i + 1; while (end < sorted.length && sorted[end].estimate_pct === sorted[i].estimate_pct) end++;
    const group = sorted.slice(i, end), pos = group.filter(p => p.actual_td).length, neg = group.length - pos;
    wins += pos * (negativesBefore + neg / 2); negativesBefore += neg; i = end;
  }
  for (const row of rows) {
    const p = row.estimate_pct / 100, y = Number(row.actual_td), clipped = Math.min(1 - 1e-15, Math.max(1e-15, p));
    brier += (p - y) ** 2; loss -= y * Math.log(clipped) + (1 - y) * Math.log(1 - clipped);
  }
  const calibration: TdMetrics["calibration"] = [];
  for (let lower = 0; lower < 100; lower += 10) {
    const bin = rows.filter(r => r.estimate_pct >= lower && (lower === 90 ? r.estimate_pct <= 100 : r.estimate_pct < lower + 10));
    if (bin.length) calibration.push({ lower_pct: lower, upper_pct: lower + 10, n: bin.length,
      mean_estimate_pct: bin.reduce((sum, r) => sum + r.estimate_pct, 0) / bin.length,
      observed_pct: 100 * bin.filter(r => r.actual_td).length / bin.length });
  }
  return { n, positives, brier: brier / n, log_loss: loss / n, auc: positives && positives < n ? wins / (positives * (n - positives)) : null, calibration };
}
function scoreArithmetic(games: Evaluation["games"], baseline = false): ScoreMetrics {
  let n = 0, correct = 0, scores = 0, totals = 0, margins = 0;
  for (const g of games) {
    const p = baseline ? g.prior_offensive_mean : g.prediction, a = g.actual;
    if (g.status !== "final" || !p || !a) continue;
    n++; correct += Number(Math.sign(p.home - p.away) === Math.sign(a.home - a.away));
    scores += Math.abs(p.away - a.away) + Math.abs(p.home - a.home);
    totals += Math.abs(p.home + p.away - a.home - a.away); margins += Math.abs(p.home - p.away - a.home + a.away);
  }
  return { n, winner_accuracy: n ? correct / n : null, team_score_mae: n ? scores / (2 * n) : null,
    total_mae: n ? totals / n : null, margin_mae: n ? margins / n : null };
}
function consistentArithmetic(report: Evaluation): boolean {
  if (!sameArithmetic(report.td_metrics, tdArithmetic(report.players)) ||
      !sameArithmetic(report.game_metrics, scoreArithmetic(report.games)) || !sameArithmetic(report.baseline_metrics, scoreArithmetic(report.games, true))) return false;
  const positions = ["QB", "RB", "WR", "TE"];
  if (Object.keys(report.position_metrics).length !== positions.length || !positions.every(pos => sameArithmetic(report.position_metrics[pos], tdArithmetic(report.players.filter(p => (p.position === "FB" ? "RB" : p.position) === pos))))) return false;
  const missing: Record<string, number> = {};
  for (const p of report.players) if (p.actual_td === null) missing[p.outcome_reason] = (missing[p.outcome_reason] ?? 0) + 1;
  if (Object.keys(missing).length !== Object.keys(report.missing_labels).length || !sameArithmetic(report.missing_labels, missing)) return false;
  if (report.top_per_game) for (const [key, value] of Object.entries(report.top_per_game)) {
    const n = Number(key); if (![5, 10, 20, 30].includes(n)) return false;
    const selected = report.games.filter(g => g.status === "final").flatMap(g => report.players.filter(p => p.game_id === g.game_id)
      .sort((a, b) => b.estimate_pct - a.estimate_pct || (a.player_id < b.player_id ? -1 : a.player_id > b.player_id ? 1 : 0)).slice(0, n));
    const labelled = selected.filter(p => p.actual_td !== null), hits = labelled.filter(p => p.actual_td).length;
    if (!sameArithmetic(value, { selected: selected.length, labelled: labelled.length, hits, hit_rate: labelled.length ? hits / labelled.length : null })) return false;
  }
  if (report.margin_bands) for (const [key, value] of Object.entries(report.margin_bands)) {
    const bounds = { under_3: [0, 3], "3_to_under_7": [3, 7], "7_plus": [7, Infinity] }[key];
    if (!bounds || !sameArithmetic(value, scoreArithmetic(report.games.filter(g => g.prediction && Math.abs(g.prediction.home - g.prediction.away) >= bounds[0] && Math.abs(g.prediction.home - g.prediction.away) < bounds[1])))) return false;
  }
  return true;
}

export function validateEvaluation(value: unknown, season: number, week: number, now = Date.now()): string | null {
  if (!record(value) || value.schema_version !== 1 || !integer(season) || season < 2002 || !integer(week) || week < 1 || week > 18 || value.season !== season || value.week !== week ||
    !hash(value.engine_sha256) ||
    typeof value.evaluation_id !== "string" || !/^[a-f0-9]{24}$/.test(value.evaluation_id) ||
    !timestamp(value.evaluated_as_of) || !timestamp(value.forecast_generated_at) || !Number.isFinite(now) || Date.parse(value.evaluated_as_of) > now || Date.parse(value.evaluated_as_of) < Date.parse(value.forecast_generated_at) ||
    !["partial", "complete"].includes(String(value.status)) || !record(value.forecast_hashes) ||
    !hash(value.forecast_hashes["board.json"]) || !hash(value.forecast_hashes["receipt.json"]) ||
    !Object.values(value.forecast_hashes).every(hash) || !Array.isArray(value.games) || !value.games.length || !Array.isArray(value.players) ||
    !Array.isArray(value.limitations) || !value.limitations.every(v => typeof v === "string")) return "Invalid evaluation metadata or provenance.";
  if (!validOutcomeSources(value.outcome_sources, season, value.evaluated_as_of as string)) return "Missing or invalid outcome source provenance.";
  const games = new Map<string, Record<string, unknown>>();
  for (const g of value.games) {
    if (!record(g) || typeof g.game_id !== "string" || !/^\d{4}_\d{2}_[A-Z]+_[A-Z]+$/.test(g.game_id) ||
      games.has(g.game_id) || g.game_id !== `${season}_${String(week).padStart(2, "0")}_${g.away_team}_${g.home_team}` ||
      g.away_team === g.home_team || !timestamp(g.kickoff_utc) || Date.parse(value.forecast_generated_at) >= Date.parse(g.kickoff_utc) ||
      !["pending", "final"].includes(String(g.status))) return "Invalid evaluated game identity or pregame timing.";
    const score = (v: unknown) => record(v) && number(v.away) && number(v.home);
    if ((g.prior_offensive_mean !== undefined && g.prior_offensive_mean !== null && !score(g.prior_offensive_mean)) || (g.prediction !== null && !score(g.prediction))) return "Invalid projected scores.";
    if (g.status === "pending" ? g.actual !== null : !score(g.actual) || !integer((g.actual as Record<string, unknown>).away) || !integer((g.actual as Record<string, unknown>).home) || Date.parse(g.kickoff_utc) >= Date.parse(value.evaluated_as_of)) return "Unverified or premature final outcome.";
    games.set(g.game_id, g);
  }
  const completed = value.games.filter(g => g.status === "final").length;
  if (value.games_completed !== completed || value.games_pending !== games.size - completed ||
    value.status !== (completed === games.size ? "complete" : "partial")) return "Evaluation completion counts disagree.";
  const seen = new Set<string>(); let labelled = 0, positives = 0;
  for (const p of value.players) {
    if (!record(p) || typeof p.game_id !== "string" || typeof p.player_id !== "string" || !/^00-\d{7}$/.test(p.player_id) ||
      typeof p.player !== "string" || !p.player || !["QB", "RB", "FB", "WR", "TE"].includes(String(p.position)) || !number(p.estimate_pct) || p.estimate_pct > 100 ||
      !(p.actual_td === null || typeof p.actual_td === "boolean") || typeof p.outcome_reason !== "string") return "Invalid player outcome or estimate.";
    const g = games.get(p.game_id), key = `${p.game_id}:${p.player_id}`;
    if (!g || ![g.away_team, g.home_team].includes(p.team) || seen.has(key) || (g.status === "pending" && p.actual_td !== null)) return "Player outcome identity conflicts with game state.";
    seen.add(key);
    if (p.actual_td !== null) { labelled++; if (p.actual_td) positives++; }
  }
  const td = (v: unknown) => record(v) && integer(v.n) && integer(v.positives) && v.positives <= v.n &&
    [v.brier, v.log_loss, v.auc].every(n => n === null || number(n)) && (v.auc === null || Number(v.auc) <= 1) &&
    (v.brier === null || Number(v.brier) <= 1) && Array.isArray(v.calibration) && v.calibration.every(b => record(b) &&
      number(b.lower_pct) && number(b.upper_pct) && b.lower_pct < b.upper_pct && b.upper_pct <= 100 && integer(b.n) && b.n > 0 &&
      number(b.mean_estimate_pct) && b.mean_estimate_pct <= 100 && number(b.observed_pct) && b.observed_pct <= 100);
  const score = (v: unknown) => record(v) && integer(v.n) && [v.winner_accuracy, v.team_score_mae, v.total_mae, v.margin_mae].every(n => n === null || number(n)) &&
    (v.winner_accuracy === null || Number(v.winner_accuracy) <= 1);
  if (!td(value.td_metrics) || !record(value.td_metrics) || value.td_metrics.n !== labelled || value.td_metrics.positives !== positives ||
    !record(value.position_metrics) || !Object.values(value.position_metrics).every(td) || !score(value.game_metrics) || !score(value.baseline_metrics) ||
    !record(value.missing_labels) || !Object.values(value.missing_labels).every(integer)) return "Invalid evaluation metrics or labelled coverage.";
  if (value.top_per_game !== undefined && (!record(value.top_per_game) || !Object.values(value.top_per_game).every(r => record(r) &&
    integer(r.selected) && integer(r.labelled) && integer(r.hits) && r.hits <= r.labelled && r.labelled <= r.selected &&
    (r.labelled === 0 ? r.hit_rate === null : number(r.hit_rate) && Math.abs(r.hit_rate - r.hits / r.labelled) < 1e-9)))) return "Invalid ranking coverage.";
  if (value.margin_bands !== undefined && (!record(value.margin_bands) || !Object.values(value.margin_bands).every(score))) return "Invalid margin bands.";
  if (!consistentArithmetic(value as unknown as Evaluation)) return "Evaluation metrics disagree with reported observations.";
  return null;
}

export async function decodeEvaluation(bytes: ArrayBuffer, pin: string): Promise<unknown> {
  if (!hash(pin)) throw new Error("Invalid evaluation hash pin.");
  const actual = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(v => v.toString(16).padStart(2, "0")).join("");
  if (actual !== pin) throw new Error("Evaluation hash mismatch.");
  return JSON.parse(new TextDecoder().decode(bytes));
}
