export type EvaluationIndex = { schema_version: 1; reports: { season: number; week: number; path: string; sha256: string }[] };
export type ScoreMetrics = { n: number; winner_accuracy: number | null; team_score_mae: number | null; total_mae: number | null; margin_mae: number | null };
export type TdMetrics = { n: number; positives: number; brier: number | null; log_loss: number | null; auc: number | null; calibration: { lower_pct: number; upper_pct: number; n: number; mean_estimate_pct: number; observed_pct: number }[] };
export type Evaluation = {
  schema_version: 1; evaluation_id: string; season: number; week: number; status: "partial" | "complete";
  evaluated_as_of: string; forecast_generated_at: string; forecast_hashes: Record<string, string>;
  games_completed: number; games_pending: number; game_metrics: ScoreMetrics; baseline_metrics: ScoreMetrics;
  td_metrics: TdMetrics; position_metrics: Record<string, TdMetrics>; missing_labels: Record<string, number>;
  top_per_game?: Record<string, { selected: number; labelled: number; hits: number; hit_rate: number | null }>;
  margin_bands?: Record<string, ScoreMetrics>;
  limitations: string[];
  games: { game_id: string; away_team: string; home_team: string; kickoff_utc: string; status: "final" | "pending";
    prediction: { away: number; home: number } | null; actual: { away: number; home: number } | null }[];
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

export function validateEvaluation(value: unknown, season: number, week: number, now = Date.now()): string | null {
  if (!record(value) || value.schema_version !== 1 || value.season !== season || value.week !== week ||
    typeof value.evaluation_id !== "string" || !/^[a-f0-9]{24}$/.test(value.evaluation_id) ||
    !timestamp(value.evaluated_as_of) || !timestamp(value.forecast_generated_at) || !Number.isFinite(now) || Date.parse(value.evaluated_as_of) > now || Date.parse(value.evaluated_as_of) < Date.parse(value.forecast_generated_at) ||
    !["partial", "complete"].includes(String(value.status)) || !record(value.forecast_hashes) ||
    !hash(value.forecast_hashes["board.json"]) || !hash(value.forecast_hashes["receipt.json"]) ||
    !Object.values(value.forecast_hashes).every(hash) || !Array.isArray(value.games) || !value.games.length || !Array.isArray(value.players) ||
    !Array.isArray(value.limitations) || !value.limitations.every(v => typeof v === "string")) return "Invalid evaluation metadata or provenance.";
  const games = new Map<string, Record<string, unknown>>();
  for (const g of value.games) {
    if (!record(g) || typeof g.game_id !== "string" || !/^\d{4}_\d{2}_[A-Z]+_[A-Z]+$/.test(g.game_id) ||
      games.has(g.game_id) || g.game_id !== `${season}_${String(week).padStart(2, "0")}_${g.away_team}_${g.home_team}` ||
      g.away_team === g.home_team || !timestamp(g.kickoff_utc) || Date.parse(value.forecast_generated_at) >= Date.parse(g.kickoff_utc) ||
      !["pending", "final"].includes(String(g.status))) return "Invalid evaluated game identity or pregame timing.";
    const score = (v: unknown) => record(v) && number(v.away) && number(v.home);
    if (g.prediction !== null && !score(g.prediction)) return "Invalid projected scores.";
    if (g.status === "pending" ? g.actual !== null : !score(g.actual) || !integer((g.actual as Record<string, unknown>).away) || !integer((g.actual as Record<string, unknown>).home) || Date.parse(g.kickoff_utc) >= Date.parse(value.evaluated_as_of)) return "Unverified or premature final outcome.";
    games.set(g.game_id, g);
  }
  const completed = value.games.filter(g => g.status === "final").length;
  if (value.games_completed !== completed || value.games_pending !== games.size - completed ||
    value.status !== (completed === games.size ? "complete" : "partial")) return "Evaluation completion counts disagree.";
  const seen = new Set<string>(); let labelled = 0, positives = 0;
  for (const p of value.players) {
    if (!record(p) || typeof p.game_id !== "string" || typeof p.player_id !== "string" || !/^00-\d{7}$/.test(p.player_id) ||
      typeof p.player !== "string" || !p.player || typeof p.position !== "string" || !number(p.estimate_pct) || p.estimate_pct > 100 ||
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
  return null;
}

export async function decodeEvaluation(bytes: ArrayBuffer, pin: string): Promise<unknown> {
  if (!hash(pin)) throw new Error("Invalid evaluation hash pin.");
  const actual = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(v => v.toString(16).padStart(2, "0")).join("");
  if (actual !== pin) throw new Error("Evaluation hash mismatch.");
  return JSON.parse(new TextDecoder().decode(bytes));
}
