import { useEffect, useState } from "react";
import type { BoardFile, BoardMeta, BoardRow, DataManifest, RawBoardRow } from "./types";

export const TEAM_NAMES: Record<string, string> = {
  ARI: "Arizona Cardinals", ATL: "Atlanta Falcons", BAL: "Baltimore Ravens", BUF: "Buffalo Bills",
  CAR: "Carolina Panthers", CHI: "Chicago Bears", CIN: "Cincinnati Bengals", CLE: "Cleveland Browns",
  DAL: "Dallas Cowboys", DEN: "Denver Broncos", DET: "Detroit Lions", GB: "Green Bay Packers",
  HOU: "Houston Texans", IND: "Indianapolis Colts", JAX: "Jacksonville Jaguars", KC: "Kansas City Chiefs",
  LA: "Los Angeles Rams", LAC: "Los Angeles Chargers", LV: "Las Vegas Raiders", MIA: "Miami Dolphins",
  MIN: "Minnesota Vikings", NE: "New England Patriots", NO: "New Orleans Saints", NYG: "New York Giants",
  NYJ: "New York Jets", PHI: "Philadelphia Eagles", PIT: "Pittsburgh Steelers", SEA: "Seattle Seahawks",
  SF: "San Francisco 49ers", TB: "Tampa Bay Buccaneers", TEN: "Tennessee Titans", WAS: "Washington Commanders",
};
export const NFL_TEAMS = new Set(Object.keys(TEAM_NAMES));
export const POSITION_OPTIONS = ["QB", "RB", "FB", "WR", "TE"] as const;
export const POSITION_GROUPS = ["RB", "WR", "TE", "QB"] as const;

export function useJson<T>(url: string | null) {
  const [state, setState] = useState<{ url: string | null; data: T | null; error: string | null }>({
    url: null, data: null, error: null,
  });
  useEffect(() => {
    if (!url) {
      return;
    }
    let cancelled = false;
    fetch(url, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error("Request failed with HTTP " + response.status);
        return response.json() as Promise<T>;
      })
      .then((data) => { if (!cancelled) setState({ url, data, error: null }); })
      .catch((error: unknown) => {
        if (!cancelled) setState({ url, data: null, error: error instanceof Error ? error.message : String(error) });
      });
    return () => { cancelled = true; };
  }, [url]);
  if (!url) return { data: null, error: null, loading: false };
  if (state.url !== url) return { data: null, error: null, loading: true };
  return { data: state.data, error: state.error, loading: false };
}

const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const safePath = (v: unknown): v is string => typeof v === "string" && /^[a-zA-Z0-9_-]+(?:\/[a-zA-Z0-9_.-]+)*\.json$/.test(v) && !v.split("/").some(s => s === "." || s === "..");
export function isManifest(value: unknown): value is DataManifest {
  if (!record(value) || value.schema_version !== 1 || !Array.isArray(value.supported_weeks) ||
      !value.supported_weeks.length || !value.supported_weeks.every(w => Number.isInteger(w) && w >= 1 && w <= 18) ||
      new Set(value.supported_weeks).size !== value.supported_weeks.length || !record(value.seasons) || !Object.keys(value.seasons).length) return false;
  return Object.entries(value.seasons).every(([season, entry]) => /^\d{4}$/.test(season) && record(entry) && record(entry.weeks) &&
    Object.entries(entry.weeks).every(([week, file]) => value.supported_weeks instanceof Array && value.supported_weeks.includes(Number(week)) &&
      record(file) && safePath(file.board) && (file.breakdowns === null || safePath(file.breakdowns)) &&
      typeof file.generated_at === "string" && Number.isFinite(Date.parse(file.generated_at)) && ["fitted", "composite"].includes(String(file.model))));
}

export function normalizeBoard(file: BoardFile): BoardRow[] {
  return file.rows.map((row: RawBoardRow) => {
    const estimate = row.td_estimate ?? 0;
    return {
      player_id: row.player_id,
      game_id: row.game_id,
      player: row.player,
      team: row.team,
      position: row.position,
      opponent: row.opponent,
      td_estimate: estimate,
      td_score: row.td_score ?? estimate,
      game_status: row.game_status,
      games: row.games ?? 0,
      injury_status: row.injury_status === "Active" || row.injury_status === "Questionable" ||
        row.injury_status === "Doubtful" || row.injury_status === "Out" || row.injury_status === "IR"
        ? row.injury_status : "Unknown",
      prediction_timing: row.prediction_timing,
      actual_scored_td: row.actual_scored_td ?? null,
      is_home: row.is_home ?? null,
    };
  });
}

export function boardValidationError(value: BoardFile | null, season: number, week: number): string | null {
  if (!value || typeof value !== "object" || !value.meta || !Array.isArray(value.rows)) {
    return "This board does not match the expected weekly data format.";
  }
  const meta: BoardMeta = value.meta;
  if (meta.season !== season || meta.week !== week) {
    return "This file contains " + meta.season + " week " + meta.week + ", not " + season + " week " + week + ".";
  }
  if (!Number.isFinite(Date.parse(meta.generated_at)) || !["fitted", "composite"].includes(meta.model) ||
      !Array.isArray(meta.final_games) || !Array.isArray(meta.games) || meta.games.length === 0 ||
      !meta.injury_report || meta.injury_report.unknown_is_not_active !== true) {
    return "Weekly board metadata is invalid.";
  }
  if (typeof meta.injury_report.source !== "string" || typeof meta.injury_report.week_available !== "boolean" ||
      !meta.final_games.every(g => g && NFL_TEAMS.has(g.away_team) && NFL_TEAMS.has(g.home_team) && g.away_team !== g.home_team &&
        Number.isInteger(g.away_score) && g.away_score >= 0 && Number.isInteger(g.home_score) && g.home_score >= 0)) return "Invalid injury or final-game metadata.";
  const gameById = new Map<string, (typeof meta.games)[number]>();
  const scheduledTeams = new Set<string>();
  for (const game of meta.games) {
    if (!game || typeof game.game_id !== "string" || !game.game_id ||
        !NFL_TEAMS.has(game.home_team) || !NFL_TEAMS.has(game.away_team) ||
        game.home_team === game.away_team || !Number.isFinite(Date.parse(game.kickoff_utc)) ||
        !["pregame_snapshot", "historical_backfill", "unknown"].includes(game.prediction_timing)) {
      return "A scheduled game in this board is invalid.";
    }
    if (gameById.has(game.game_id) || scheduledTeams.has(game.home_team) || scheduledTeams.has(game.away_team)) {
      return "The schedule contains a duplicate game or team.";
    }
    gameById.set(game.game_id, game);
    scheduledTeams.add(game.home_team);
    scheduledTeams.add(game.away_team);
  }
  if (value.rows.length === 0) return "This board contains no player predictions.";
  const seen = new Set<string>();
  for (const row of value.rows) {
    if (!row || ![row.player_id, row.game_id, row.player, row.position].every(v => typeof v === "string" && v.trim())) {
      return "A player row is missing its identity fields.";
    }
    if ((row.games != null && (!Number.isInteger(row.games) || row.games < 0)) ||
        (row.is_home != null && row.is_home !== 0 && row.is_home !== 1) ||
        (row.actual_scored_td != null && typeof row.actual_scored_td !== "boolean")) return "A player row contains invalid history or outcome fields.";
    if (seen.has(row.player_id)) return "The board contains duplicate player IDs.";
    seen.add(row.player_id);
    const game = gameById.get(row.game_id);
    if (!game || !NFL_TEAMS.has(row.team) || !NFL_TEAMS.has(row.opponent) ||
        ![game.home_team, game.away_team].includes(row.team) ||
        ![game.home_team, game.away_team].includes(row.opponent) || row.team === row.opponent) {
      return "A player’s team and matchup do not match the selected week’s schedule.";
    }
    if (!["Active", "Questionable", "Doubtful", "Out", "IR", "Unknown"].includes(row.injury_status) ||
        !["Upcoming", "In Progress", "Final", "Unknown"].includes(row.game_status) ||
        !["pregame_snapshot", "historical_backfill", "unknown"].includes(row.prediction_timing) ||
        row.prediction_timing !== game.prediction_timing) {
      return "A player row contains an invalid status or timing value.";
    }
    for (const probability of [row.td_score, row.td_estimate]) {
      if (typeof probability !== "number" || !Number.isFinite(probability) || probability < 0 || probability > 100) {
        return "A player row contains an invalid score or estimate.";
      }
    }
  }
  return null;
}

export function breakdownValidationError(value: unknown, board: BoardMeta): string | null {
  if (!record(value) || !record(value.meta) || value.meta.season !== board.season || value.meta.week !== board.week ||
      !record(value.games) || !record(value.errors) || !Object.values(value.errors).every(e => typeof e === "string")) return "The breakdown does not match the selected weekly snapshot.";
  const pairs = new Set(board.games.map(g => `${g.away_team}@${g.home_team}`));
  const table = (v: unknown) => Array.isArray(v) && v.every(r => record(r) && Object.values(r).every(c => c === null || typeof c === "string" || typeof c === "boolean" || (typeof c === "number" && Number.isFinite(c))));
  for (const [key, game] of Object.entries(value.games)) {
    if (!pairs.has(key) || !record(game) || !Array.isArray(game.teams) || game.teams.join("@") !== key ||
        !table(game.offense) || !table(game.defense) || !record(game.players) || !record(game.injuries) ||
        !Array.isArray(game.flags) || !game.flags.every(f => typeof f === "string") || !record(game.meta) ||
        !record(game.meta.games_used) || !record(game.meta.prior_season_games) || !Number.isInteger(game.meta.lookback) ||
        !game.teams.every(t => typeof t === "string" && record(game.meta) && record(game.meta.games_used) && record(game.meta.prior_season_games) &&
          Number.isInteger(game.meta.games_used[t]) && Number(game.meta.games_used[t]) >= 0 && Number.isInteger(game.meta.prior_season_games[t]) && Number(game.meta.prior_season_games[t]) >= 0) ||
        !Object.values(game.players).every(groups => record(groups) && Object.values(groups).every(table)) ||
        !Object.values(game.injuries).every(table)) return "The matchup breakdown contains invalid data.";
  }
  return null;
}
