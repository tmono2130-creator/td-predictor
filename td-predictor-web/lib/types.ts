import type { BoardPlayer, ParlayResult } from "./parlay";

export type PredictionTiming = "pregame_snapshot" | "historical_backfill" | "unknown";
export type GameStatus = "Upcoming" | "In Progress" | "Final" | "Unknown";
export type InjuryStatus = "Active" | "Questionable" | "Doubtful" | "Out" | "IR" | "Unknown";

export type FinalGame = {
  away_team: string;
  away_score: number;
  home_team: string;
  home_score: number;
};

export type ScheduledGame = {
  game_id: string;
  away_team: string;
  home_team: string;
  kickoff_utc: string;
  prediction_timing: PredictionTiming;
  snapshot_classification?: string;
};

export type BoardMeta = {
  season: number;
  week: number;
  generated_at: string;
  model: "fitted" | "composite";
  model_version?: string;
  snapshot_classification?: string;
  probability_semantics?: string;
  source_versions?: Record<string, string>;
  final_games: FinalGame[];
  games: ScheduledGame[];
  injury_report: { source: string; week_available: boolean; unknown_is_not_active: true };
};

export type RawBoardRow = {
  player_id: string;
  game_id: string;
  player: string;
  team: string;
  position: string;
  opponent: string;
  td_score: number | null;
  td_estimate: number | null;
  games?: number | null;
  injury_status: string;
  game_status: string;
  prediction_timing: PredictionTiming;
  actual_scored_td?: boolean | null;
  is_home?: number | null;
};

export type BoardFile = { meta: BoardMeta; rows: RawBoardRow[] };
export type WeeklyFiles = {
  game_predictor?: string;
  game_predictor_sha256?: string;
  board: string;
  breakdowns: string | null;
  generated_at: string;
  model: "fitted" | "composite";
};
export type DataManifest = {
  schema_version: 1;
  supported_weeks: number[];
  seasons: Record<string, { weeks: Record<string, WeeklyFiles> }>;
};

export type BoardRow = BoardPlayer & {
  game_id: string;
  position: string;
  games: number;
  injury_status: InjuryStatus;
  prediction_timing: PredictionTiming;
  actual_scored_td: boolean | null;
  is_home: number | null;
};

export type TableCell = string | number | boolean | null;
export type TableRow = Record<string, TableCell>;

export type Breakdown = {
  teams: [string, string];
  offense: TableRow[];
  defense: TableRow[];
  players: Record<string, Record<string, TableRow[]>>;
  injuries: Record<string, TableRow[]>;
  flags: string[];
  meta: {
    games_used: Record<string, number>;
    prior_season_games: Record<string, number>;
    lookback: number;
  };
};

export type BreakdownsFile = {
  meta: { season: number; week: number; lookback: number; generated_at: string };
  games: Record<string, Breakdown>;
  errors: Record<string, string>;
};

export type SectionId = "dashboard" | "rankings" | "parlay" | "market" | "breakdown" | "game";
export type StoredComparison = { player_id: string; odds: string };
export type { ParlayResult };
