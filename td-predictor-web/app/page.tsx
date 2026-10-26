"use client";

/**
 * TD Likelihood — the website front end.
 *
 * This page does NOT run the model. The model lives in Python; export_json.py
 * runs it and writes two static files this page reads:
 *     /data/board.json        the ranked player board for the week
 *     /data/breakdowns.json   a scouting report for every game that week
 * Parlay math and the odds comparison run here in the browser, using the same
 * logic as the Python app (lib/parlay.ts is a tested port).
 */

import { useEffect, useMemo, useState } from "react";
import styles from "./page.module.css";
import {
  autoBuildParlay,
  fairAmericanOdds,
  impliedProbFromAmericanOdds,
  parlayProbability,
  VOLATILITY_ORDER,
  type BoardPlayer,
  type ParlayResult,
  type VolatilityBand,
} from "../lib/parlay";

/* ================================ types ================================ */

type FinalGame = { away_team: string; away_score: number; home_team: string; home_score: number };

type BoardMeta = {
  season: number;
  week: number;
  generated_at: string;
  model: "fitted" | "composite";
  final_games: FinalGame[];
};

// What the JSON can contain: several fields can be null.
type RawBoardRow = {
  player_id: string;
  player: string;
  team: string;
  position: string;
  opponent: string;
  td_score: number | null;
  td_estimate: number | null;
  games?: number | null;
  injury_status?: string | null;
  game_status: string;
  actual_scored_td?: boolean | null;
  is_home?: number | null;
};

type BoardFile = { meta: BoardMeta; rows: RawBoardRow[] };
type WeeklyFiles = { board: string; breakdowns: string | null; generated_at: string; model: "fitted" | "composite" };
type DataManifest = {
  schema_version: 1;
  supported_weeks: number[];
  seasons: Record<string, { weeks: Record<string, WeeklyFiles> }>;
};

// What the rest of the page works with: nulls already resolved.
type BoardRow = BoardPlayer & {
  position: string;
  games: number;
  injury_status: string;
  actual_scored_td: boolean;
  is_home: number | null;
};

type Cell = string | number | boolean | null;
type TableRow = Record<string, Cell>;

type Breakdown = {
  teams: [string, string];
  offense: TableRow[];
  defense: TableRow[];
  players: Record<string, Record<string, TableRow[]>>;
  injuries: Record<string, TableRow[]>;
  flags: string[];
  meta: { games_used: Record<string, number>; prior_season_games: Record<string, number>; lookback: number };
};

type BreakdownsFile = {
  meta: { season: number; week: number; lookback: number; generated_at: string };
  games: Record<string, Breakdown>;
  errors: Record<string, string>;
};

/* =============================== constants ============================== */

const POSITIONS = ["QB", "RB", "WR", "TE"] as const;
const GROUPS = ["RB", "WR", "TE", "QB"] as const;

const TEAM_NAMES: Record<string, string> = {
  ARI: "Arizona Cardinals", ATL: "Atlanta Falcons", BAL: "Baltimore Ravens", BUF: "Buffalo Bills",
  CAR: "Carolina Panthers", CHI: "Chicago Bears", CIN: "Cincinnati Bengals", CLE: "Cleveland Browns",
  DAL: "Dallas Cowboys", DEN: "Denver Broncos", DET: "Detroit Lions", GB: "Green Bay Packers",
  HOU: "Houston Texans", IND: "Indianapolis Colts", JAX: "Jacksonville Jaguars", KC: "Kansas City Chiefs",
  LA: "Los Angeles Rams", LAC: "Los Angeles Chargers", LV: "Las Vegas Raiders", MIA: "Miami Dolphins",
  MIN: "Minnesota Vikings", NE: "New England Patriots", NO: "New Orleans Saints", NYG: "New York Giants",
  NYJ: "New York Jets", PHI: "Philadelphia Eagles", PIT: "Pittsburgh Steelers", SEA: "Seattle Seahawks",
  SF: "San Francisco 49ers", TB: "Tampa Bay Buccaneers", TEN: "Tennessee Titans", WAS: "Washington Commanders",
};

const TABS = [
  { id: "rankings", label: "📊 Rankings" },
  { id: "parlay", label: "🎯 Parlay Builder" },
  { id: "market", label: "📈 Market Check" },
  { id: "breakdown", label: "🔬 Game Breakdown" },
] as const;
type TabId = (typeof TABS)[number]["id"];

/* =============================== helpers =============================== */

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function cellText(v: Cell | undefined): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100);
  if (typeof v === "boolean") return v ? "Yes" : "No";
  return v;
}

const fmtPct = (n: number, d = 1) => `${n.toFixed(d)}%`;
const fmtParlay = (n: number) => (n >= 1 ? `${n.toFixed(2)}%` : `${n.toFixed(3)}%`);
const teamLabel = (code: string) => (TEAM_NAMES[code] ? `${TEAM_NAMES[code]} (${code})` : code);

function normalizeBoard(file: BoardFile): BoardRow[] {
  return file.rows.map((r) => {
    const est = r.td_estimate ?? 0;
    return {
      player_id: r.player_id,
      player: r.player,
      team: r.team,
      position: r.position,
      opponent: r.opponent,
      td_estimate: est,
      td_score: r.td_score ?? est,
      game_status: r.game_status,
      games: r.games ?? 0,
      injury_status: r.injury_status ?? "Active",
      actual_scored_td: Boolean(r.actual_scored_td),
      is_home: r.is_home ?? null,
    };
  });
}

function useJson<T>(url: string | null) {
  const [state, setState] = useState<{ url: string | null; data: T | null; error: string | null }>(
    { url: null, data: null, error: null },
  );
  useEffect(() => {
    if (!url) return;
    let cancelled = false;
    fetch(url, { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`${url} returned HTTP ${r.status}`);
        return r.json() as Promise<T>;
      })
      .then((data) => {
        if (!cancelled) setState({ url, data, error: null });
      })
      .catch((e: unknown) => {
        if (!cancelled) setState({ url, data: null, error: errMessage(e) });
      });
    return () => { cancelled = true; };
  }, [url]);
  if (!url) return { data: null, error: null, loading: false };
  if (state.url !== url) return { data: null, error: null, loading: true };
  return { data: state.data, error: state.error, loading: false };
}

/* ============================ shared components ============================ */

function DataTable({ rows, emptyText }: { rows: TableRow[]; emptyText?: string }) {
  if (rows.length === 0) return <p className={styles.muted}>{emptyText ?? "No data."}</p>;
  const cols = Object.keys(rows[0]);
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {cols.map((c) => {
                const v = r[c];
                const flagged = c === "Status" && typeof v === "string" && v !== "Active";
                return (
                  <td key={c} className={typeof v === "number" ? styles.numCell : undefined}>
                    {flagged ? <span className={styles.warnText}>{v}</span> : cellText(v)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PlayerPicker({
  players,
  onPick,
  exclude,
  placeholder,
}: {
  players: BoardRow[];
  onPick: (p: BoardRow) => void;
  exclude?: Set<string>;
  placeholder: string;
}) {
  const [q, setQ] = useState("");
  const matches = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return players
      .filter(
        (p) =>
          !(exclude && exclude.has(p.player_id)) &&
          (needle === "" || p.player.toLowerCase().includes(needle) || p.team.toLowerCase().includes(needle)),
      )
      .slice(0, 40);
  }, [players, q, exclude]);

  return (
    <div className={styles.picker}>
      <input
        className={styles.input}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={placeholder}
        aria-label="Search players"
      />
      <div className={styles.pickList}>
        {matches.length === 0 ? (
          <div className={styles.pickEmpty}>No matching players.</div>
        ) : (
          matches.map((p) => (
            <button
              key={p.player_id}
              type="button"
              className={styles.pickItem}
              onClick={() => {
                onPick(p);
                setQ("");
              }}
            >
              <span>{p.player}</span>
              <span className={styles.muted}>
                {p.team} vs {p.opponent} · {fmtPct(p.td_estimate)}
              </span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}

function ParlayView({ result }: { result: ParlayResult }) {
  const fair = fairAmericanOdds(result.combinedPct);
  return (
    <div>
      <div className={styles.metrics}>
        <div className={styles.metric}>
          <div className={styles.metricLabel}>All legs hit</div>
          <div className={styles.metricValue}>{fmtParlay(result.combinedPct)}</div>
        </div>
        <div className={styles.metric}>
          <div className={styles.metricLabel}>Volatility</div>
          <div className={styles.metricValue}>{result.volatility}</div>
        </div>
        <div className={styles.metric}>
          <div className={styles.metricLabel}>Model fair price</div>
          <div className={styles.metricValue}>{fair ?? "—"}</div>
        </div>
      </div>
      {result.targetMissed && (
        <div className={styles.notice}>
          Couldn&apos;t find a combination in the exact range you asked for this week — showing the closest
          available instead.
        </div>
      )}
      {result.sameTeamWarning && (
        <div className={styles.notice}>
          ⚠️ Two or more legs share a team. Red-zone chances within one game are a limited shared resource, so the
          real combined probability is likely a bit LOWER than shown — multiplying assumes the legs are independent,
          which doesn&apos;t fully hold for teammates.
        </div>
      )}
      <DataTable
        rows={result.legs.map((l) => ({
          Player: l.player,
          Team: l.team,
          Opp: l.opponent,
          "Est. TD%": Math.round(l.probability_pct * 10) / 10,
        }))}
      />
      <p className={styles.caption}>
        &ldquo;Model fair price&rdquo; is the break-even price for the model&apos;s probability (no sportsbook margin). A
        book paying noticeably more than this is pricing the parlay lower than the model does — which only matters
        if you trust the model.
      </p>
    </div>
  );
}

/* ================================ Rankings ================================ */

function RankingsTab({ rows, meta }: { rows: BoardRow[]; meta: BoardMeta }) {
  const [team, setTeam] = useState("ALL");
  const [positions, setPositions] = useState<Set<string>>(new Set<string>(POSITIONS));
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(50);
  const [hideFinal, setHideFinal] = useState(false);

  const teams = useMemo(() => Array.from(new Set(rows.map((r) => r.team))).sort(), [rows]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return rows
      .filter(
        (r) =>
          (team === "ALL" || r.team === team) &&
          positions.has(r.position) &&
          (!hideFinal || r.game_status !== "Final") &&
          (needle === "" || r.player.toLowerCase().includes(needle)),
      )
      .sort(
        (a, b) =>
          (a.game_status === "Final" ? 1 : 0) - (b.game_status === "Final" ? 1 : 0) ||
          b.td_estimate - a.td_estimate,
      );
  }, [rows, team, positions, search, hideFinal]);

  const upcoming = useMemo(() => filtered.filter((r) => r.game_status !== "Final"), [filtered]);
  const top3 = upcoming.slice(0, 3);
  const maxEst = filtered.reduce((m, r) => Math.max(m, r.td_estimate), 1);
  const shown = filtered.slice(0, limit);
  const medals = ["🥇", "🥈", "🥉"];

  const togglePos = (p: string) =>
    setPositions((prev) => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      return next;
    });

  return (
    <div>
      {meta.final_games.length > 0 && (
        <details className={styles.details}>
          <summary>🏁 {meta.final_games.length} game(s) already final this week</summary>
          {meta.final_games.map((g) => (
            <p key={`${g.away_team}@${g.home_team}`}>
              <strong>
                {g.away_team} {g.away_score} — {g.home_team} {g.home_score}
              </strong>
            </p>
          ))}
        </details>
      )}

      <div className={styles.panel}>
        <div className={styles.controls}>
          <div className={styles.field}>
            <label htmlFor="rk-team">Team</label>
            <select id="rk-team" className={styles.select} value={team} onChange={(e) => setTeam(e.target.value)}>
              <option value="ALL">All teams</option>
              {teams.map((t) => (
                <option key={t} value={t}>
                  {teamLabel(t)}
                </option>
              ))}
            </select>
          </div>
          <div className={styles.field}>
            <label htmlFor="rk-search">Search player</label>
            <input
              id="rk-search"
              className={styles.input}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="e.g. Henry"
            />
          </div>
          <div className={styles.field} style={{ flex: "0 1 110px", minWidth: 100 }}>
            <label htmlFor="rk-limit">Rows</label>
            <select
              id="rk-limit"
              className={styles.select}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            >
              {[25, 50, 100, 250, 1000].map((n) => (
                <option key={n} value={n}>
                  {n === 1000 ? "All" : n}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className={styles.chips} role="group" aria-label="Positions">
          {POSITIONS.map((p) => (
            <button
              key={p}
              type="button"
              aria-pressed={positions.has(p)}
              className={`${styles.chip} ${positions.has(p) ? styles.chipActive : ""}`}
              onClick={() => togglePos(p)}
            >
              {p}
            </button>
          ))}
          <label className={styles.checkRow} style={{ marginLeft: 8 }}>
            <input type="checkbox" checked={hideFinal} onChange={(e) => setHideFinal(e.target.checked)} />
            Hide finished games
          </label>
        </div>
      </div>

      {top3.length > 0 && (
        <div className={styles.cards}>
          {top3.map((r, i) => (
            <div key={r.player_id} className={styles.card}>
              <div className={styles.cardRank}>{medals[i]}</div>
              <div className={styles.cardName}>{r.player}</div>
              <div className={styles.cardPct}>{fmtPct(r.td_estimate)}</div>
              <div className={styles.cardMeta}>
                {r.position} · {r.team} {r.is_home === 0 ? "@" : "vs"} {r.opponent}
              </div>
            </div>
          ))}
        </div>
      )}

      {filtered.length === 0 ? (
        <div className={`${styles.notice} ${styles.noticeInfo}`}>No players match these filters.</div>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Player</th>
                <th>Team</th>
                <th>Pos</th>
                <th>Opp</th>
                <th>Game</th>
                <th>Result</th>
                <th>Est. TD%</th>
                <th>Sample</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r, i) => {
                const isFinal = r.game_status === "Final";
                const alpha = Math.min(0.55, (r.td_estimate / maxEst) * 0.55);
                return (
                  <tr key={r.player_id} className={isFinal ? styles.dim : undefined}>
                    <td>
                      <span className={styles.muted}>{i + 1}.</span> {r.player}
                    </td>
                    <td>{r.team}</td>
                    <td>{r.position}</td>
                    <td>
                      {r.is_home === 0 ? "@" : r.is_home === 1 ? "vs" : ""} {r.opponent}
                    </td>
                    <td>{isFinal ? "✅ Final" : "Upcoming"}</td>
                    <td>{isFinal ? (r.actual_scored_td ? "🎯 Scored TD" : "No TD") : "—"}</td>
                    <td
                      className={styles.numCell}
                      style={{ background: `rgba(52, 211, 153, ${alpha.toFixed(3)})`, fontWeight: 600 }}
                    >
                      {fmtPct(r.td_estimate)}
                    </td>
                    <td>{r.games === 0 ? "🆕 No history" : `${r.games} games`}</td>
                    <td>
                      {r.injury_status === "Active" ? (
                        "Active"
                      ) : (
                        <span className={styles.warnText}>{r.injury_status}</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className={styles.caption}>
        Showing {shown.length} of {filtered.length}. Est. TD% is the model&apos;s probability that a player scores at
        least one rushing or receiving TD — calibrated against past seasons, not a sportsbook price. 🆕 = no game
        history, so the number reflects team/matchup context only. Injury status is the official report and does
        not reflect gameday inactives.
      </p>
    </div>
  );
}

/* ============================== Parlay Builder ============================== */

function ParlayTab({ rows }: { rows: BoardRow[] }) {
  const upcoming = useMemo(
    () => rows.filter((r) => r.game_status !== "Final").sort((a, b) => b.td_estimate - a.td_estimate),
    [rows],
  );
  const [mode, setMode] = useState<"manual" | "auto">("manual");

  // manual
  const [picked, setPicked] = useState<BoardRow[]>([]);
  const pickedIds = useMemo(() => new Set(picked.map((p) => p.player_id)), [picked]);
  const manual = useMemo(() => {
    if (picked.length < 2) return { result: null as ParlayResult | null, error: null as string | null };
    try {
      return { result: parlayProbability(rows, picked.map((p) => p.player_id)), error: null as string | null };
    } catch (e) {
      return { result: null as ParlayResult | null, error: errMessage(e) };
    }
  }, [rows, picked]);

  // auto
  const [nLegs, setNLegs] = useState(3);
  const [target, setTarget] = useState<VolatilityBand>("Moderate");
  const [onePerTeam, setOnePerTeam] = useState(true);
  const [auto, setAuto] = useState<ParlayResult | null>(null);
  const [autoError, setAutoError] = useState<string | null>(null);
  const [recent, setRecent] = useState<string[][]>([]);

  const suggest = () => {
    try {
      const r = autoBuildParlay(rows, { nLegs, onePerTeam, target, avoid: recent });
      setAuto(r);
      setAutoError(null);
      setRecent((prev) => [r.legs.map((l) => l.player_id), ...prev].slice(0, 3));
    } catch (e) {
      setAuto(null);
      setAutoError(errMessage(e));
    }
  };

  return (
    <div>
      <div className={styles.notice}>
        <strong>This is a probability, not betting advice.</strong> It tells you how likely a parlay is to hit based on
        stats — it does not know the payout, so it can&apos;t tell you whether it&apos;s a good bet. A likely parlay at a
        bad price is still a bad bet, and an unlikely one at a great price can be a good one.
      </div>

      <div className={styles.chips} style={{ marginBottom: 12 }} role="group" aria-label="Parlay mode">
        <button
          type="button"
          aria-pressed={mode === "manual"}
          className={`${styles.chip} ${mode === "manual" ? styles.chipActive : ""}`}
          onClick={() => setMode("manual")}
        >
          Build your own
        </button>
        <button
          type="button"
          aria-pressed={mode === "auto"}
          className={`${styles.chip} ${mode === "auto" ? styles.chipActive : ""}`}
          onClick={() => setMode("auto")}
        >
          Auto-build for me
        </button>
      </div>

      {mode === "manual" ? (
        <div className={styles.panel}>
          <h3>Pick 2–6 legs</h3>
          {picked.length > 0 && (
            <div className={styles.legChips}>
              {picked.map((p) => (
                <span key={p.player_id} className={styles.legChip}>
                  {p.player} <span className={styles.muted}>{fmtPct(p.td_estimate)}</span>
                  <button
                    type="button"
                    className={styles.legRemove}
                    aria-label={`Remove ${p.player}`}
                    onClick={() => setPicked((prev) => prev.filter((x) => x.player_id !== p.player_id))}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
          {picked.length < 6 ? (
            <PlayerPicker
              players={upcoming}
              exclude={pickedIds}
              placeholder="Search a player or team to add…"
              onPick={(p) => setPicked((prev) => (prev.length < 6 ? [...prev, p] : prev))}
            />
          ) : (
            <p className={styles.muted}>Six legs is the maximum — remove one to swap.</p>
          )}
          {picked.length === 1 && <p className={styles.caption}>Add at least one more leg to see a combined probability.</p>}
          {manual.error && <div className={`${styles.notice} ${styles.noticeError}`}>{manual.error}</div>}
          {manual.result && <ParlayView result={manual.result} />}
        </div>
      ) : (
        <div className={styles.panel}>
          <h3>Let the model suggest one</h3>
          <div className={styles.controls}>
            <div className={styles.field}>
              <label htmlFor="pl-legs">Legs: {nLegs}</label>
              <input
                id="pl-legs"
                className={styles.range}
                type="range"
                min={2}
                max={6}
                value={nLegs}
                onChange={(e) => setNLegs(Number(e.target.value))}
              />
            </div>
            <div className={styles.field}>
              <label htmlFor="pl-target">What are you looking for?</label>
              <select
                id="pl-target"
                className={styles.select}
                value={target}
                onChange={(e) => setTarget(e.target.value as VolatilityBand)}
              >
                {VOLATILITY_ORDER.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <label className={styles.checkRow} style={{ marginBottom: 12 }}>
            <input type="checkbox" checked={onePerTeam} onChange={(e) => setOnePerTeam(e.target.checked)} />
            Avoid same-team legs (recommended — keeps legs closer to independent)
          </label>
          <button type="button" className={`${styles.btn} ${styles.btnPrimary} ${styles.btnWide}`} onClick={suggest}>
            Suggest a parlay
          </button>
          <p className={styles.caption}>
            Bands are relative to what&apos;s achievable for this many legs this week: &ldquo;Most Likely&rdquo; is the
            safest quartile available, &ldquo;Extreme Long Shot&rdquo; the riskiest. More legs multiply the percentage
            down fast, so these are risk levels, not fixed probability cutoffs.
          </p>
          {autoError && <div className={`${styles.notice} ${styles.noticeError}`}>{autoError}</div>}
          {auto && <ParlayView result={auto} />}
        </div>
      )}
    </div>
  );
}

/* =============================== Market Check =============================== */

type StoredComparison = { player_id: string; odds: string };

function MarketTab({ rows, meta }: { rows: BoardRow[]; meta: BoardMeta }) {
  const upcoming = useMemo(
    () => rows.filter((r) => r.game_status !== "Final").sort((a, b) => b.td_estimate - a.td_estimate),
    [rows],
  );
  const byId = useMemo(() => new Map(rows.map((r) => [r.player_id, r] as const)), [rows]);

  const storageKey = `td-market:${meta.season}:${meta.week}`;
  const [items, setItems] = useState<StoredComparison[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [chosen, setChosen] = useState<BoardRow | null>(null);
  const [odds, setOdds] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Saved in this browser only, per week, so a refresh doesn't wipe your board.
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw) {
        const parsed: unknown = JSON.parse(raw);
        if (Array.isArray(parsed)) queueMicrotask(() => setItems(parsed as StoredComparison[]));
      }
    } catch {
      /* storage unavailable or corrupted — start empty */
    }
    queueMicrotask(() => setLoaded(true));
  }, [storageKey]);

  useEffect(() => {
    if (!loaded) return;
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(items));
    } catch {
      /* ignore */
    }
  }, [items, loaded, storageKey]);

  const add = () => {
    if (!chosen) {
      setError("Pick a player first.");
      return;
    }
    if (impliedProbFromAmericanOdds(odds) === null) {
      setError("Couldn't read those odds — use a format like +150 or -120.");
      return;
    }
    setError(null);
    setItems((prev) => [...prev.filter((x) => x.player_id !== chosen.player_id), { player_id: chosen.player_id, odds: odds.trim() }]);
    setChosen(null);
    setOdds("");
  };

  const table = items.flatMap((it) => {
    const p = byId.get(it.player_id);
    const implied = impliedProbFromAmericanOdds(it.odds);
    return p && implied !== null ? [{ p, odds: it.odds, implied, gap: p.td_estimate - implied }] : [];
  });

  return (
    <div>
      <div className={`${styles.notice} ${styles.noticeInfo}`}>
        No live odds are pulled automatically — there&apos;s no free, legal feed for that. You type in the price you&apos;re
        seeing; this does the implied-probability math and sets it next to the model&apos;s number.
      </div>

      <div className={styles.panel}>
        <h3>Add a player and the odds you&apos;re seeing</h3>
        {chosen ? (
          <div className={styles.legChips}>
            <span className={styles.legChip}>
              {chosen.player} <span className={styles.muted}>model {fmtPct(chosen.td_estimate)}</span>
              <button type="button" className={styles.legRemove} aria-label="Clear player" onClick={() => setChosen(null)}>
                ×
              </button>
            </span>
          </div>
        ) : (
          <PlayerPicker players={upcoming} placeholder="Search a player or team…" onPick={setChosen} />
        )}
        <div className={styles.controls} style={{ marginTop: 12 }}>
          <div className={styles.field}>
            <label htmlFor="mk-odds">Anytime TD odds</label>
            <input
              id="mk-odds"
              className={styles.input}
              value={odds}
              onChange={(e) => setOdds(e.target.value)}
              placeholder="+150 or -120"
              inputMode="text"
              autoComplete="off"
            />
          </div>
          <button type="button" className={`${styles.btn} ${styles.btnPrimary}`} onClick={add}>
            Add
          </button>
        </div>
        {error && <div className={`${styles.notice} ${styles.noticeError}`}>{error}</div>}
      </div>

      {table.length === 0 ? (
        <p className={styles.muted}>Add a player above to start comparing.</p>
      ) : (
        <div>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Player</th>
                  <th>Model</th>
                  <th>Model fair price</th>
                  <th>Market odds</th>
                  <th>Market implied</th>
                  <th>Model − Market</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {table.map(({ p, odds: o, implied, gap }) => (
                  <tr key={p.player_id}>
                    <td>
                      {p.player} <span className={styles.muted}>{p.team} vs {p.opponent}</span>
                    </td>
                    <td className={styles.numCell}>{fmtPct(p.td_estimate)}</td>
                    <td className={styles.numCell}>{fairAmericanOdds(p.td_estimate) ?? "—"}</td>
                    <td className={styles.numCell}>{o}</td>
                    <td className={styles.numCell}>{fmtPct(implied)}</td>
                    <td className={`${styles.numCell} ${gap >= 0 ? styles.good : styles.bad}`} style={{ fontWeight: 600 }}>
                      {gap >= 0 ? "+" : ""}
                      {gap.toFixed(1)} pts
                    </td>
                    <td>
                      <button
                        type="button"
                        className={`${styles.btn} ${styles.btnSmall}`}
                        aria-label={`Remove ${p.player}`}
                        onClick={() => setItems((prev) => prev.filter((x) => x.player_id !== p.player_id))}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button type="button" className={styles.btn} onClick={() => setItems([])}>
            Clear all
          </button>
          <p className={styles.caption}>
            Positive = the stats model thinks the player is MORE likely to score than the price implies; negative = the
            market is more bullish than the model. Neither side is automatically right — this shows where they
            disagree so you can apply your own judgment. A book&apos;s implied probability includes its built-in margin
            (the &ldquo;vig&rdquo;), so it&apos;s a price, not a pure probability. Your list is saved in this browser only.
          </p>
        </div>
      )}
    </div>
  );
}

/* ============================== Game Breakdown ============================== */

function BreakdownTab({ boardMeta, dataUrl }: { boardMeta: BoardMeta; dataUrl: string | null }) {
  const { data, error, loading } = useJson<BreakdownsFile>(dataUrl);
  const keys = useMemo(() => (data ? Object.keys(data.games) : []), [data]);
  const [selected, setSelected] = useState("");
  const [side, setSide] = useState(0);

  if (!dataUrl) {
    return <div className={`${styles.notice} ${styles.noticeInfo}`}>No game breakdown export is available for this season and week.</div>;
  }
  if (loading) return <p className={styles.muted}>Loading breakdowns…</p>;
  if (error || !data) {
    return (
      <div className={`${styles.notice} ${styles.noticeError}`}>
        Couldn&apos;t load /data/breakdowns.json ({error ?? "no data"}). Run export_json.py without --skip-breakdowns and
        copy the output into public/data.
      </div>
    );
  }
  if (keys.length === 0) {
    return <div className={`${styles.notice} ${styles.noticeInfo}`}>No game breakdowns were generated for this week.</div>;
  }

  const active = keys.includes(selected) ? selected : keys[0];
  const bd = data.games[active];
  const [away, home] = bd.teams;
  const team = side === 0 ? away : home;
  const stale = data.meta.week !== boardMeta.week || data.meta.season !== boardMeta.season;
  const errorKeys = Object.keys(data.errors);

  return (
    <div>
      <p className={styles.caption} style={{ marginTop: 0 }}>
        A scouting report built from play-by-play. It is separate from the model — it never changes a ranking or
        probability. Use it to see the usage and scoring patterns behind a matchup and make your own call.
      </p>
      {stale && (
        <div className={styles.notice}>
          These breakdowns are for week {data.meta.week}, {data.meta.season}, but the board is week {boardMeta.week},{" "}
          {boardMeta.season}. Re-run export_json.py to refresh both.
        </div>
      )}
      {errorKeys.length > 0 && (
        <div className={`${styles.notice} ${styles.noticeInfo}`}>Couldn&apos;t build: {errorKeys.join(", ")}.</div>
      )}

      <div className={styles.controls}>
        <div className={styles.field}>
          <label htmlFor="bd-game">Game</label>
          <select
            id="bd-game"
            className={styles.select}
            value={active}
            onChange={(e) => {
              setSelected(e.target.value);
              setSide(0);
            }}
          >
            {keys.map((k) => {
              const [a, h] = k.split("@");
              return (
                <option key={k} value={k}>
                  {a} @ {h}
                </option>
              );
            })}
          </select>
        </div>
      </div>

      <h2 className={styles.sectionTitle} style={{ marginTop: 6 }}>
        {away} @ {home}
      </h2>
      <p className={styles.caption} style={{ marginTop: 0 }}>
        Window: each team&apos;s last {bd.meta.lookback} regular-season games before this week ({away}:{" "}
        {bd.meta.games_used[away]} games, {bd.meta.prior_season_games[away]} from last season · {home}:{" "}
        {bd.meta.games_used[home]} games, {bd.meta.prior_season_games[home]} from last season). Samples are small —
        read the counts, not just the percentages.
      </p>

      <h3 className={styles.sectionTitle}>📌 Stats that stand out</h3>
      {bd.flags.length > 0 ? (
        <ul className={styles.flagList}>
          {bd.flags.map((f, i) => (
            <li key={i}>{f}</li>
          ))}
        </ul>
      ) : (
        <p className={styles.muted}>Nothing crossed the automatic thresholds for this game.</p>
      )}
      <p className={styles.caption}>
        Flags use fixed thresholds and minimum sample sizes. They&apos;re prompts for your own judgment, not model output.
      </p>

      <h3 className={styles.sectionTitle}>Team scoring profile</h3>
      <p className={styles.muted}>Offense — how they score</p>
      <DataTable rows={bd.offense} />
      <p className={styles.muted}>Defense — what they allow</p>
      <DataTable rows={bd.defense} />

      <h3 className={styles.sectionTitle}>Players by position group</h3>
      <div className={styles.chips} role="group" aria-label="Team" style={{ marginBottom: 8 }}>
        {[away, home].map((t, i) => (
          <button
            key={t}
            type="button"
            aria-pressed={side === i}
            className={`${styles.chip} ${side === i ? styles.chipActive : ""}`}
            onClick={() => setSide(i)}
          >
            {t}
          </button>
        ))}
      </div>
      {GROUPS.map((g) => {
        const groupRows = bd.players[team]?.[g] ?? [];
        return groupRows.length > 0 ? (
          <div key={g}>
            <p className={styles.muted}>
              <strong>{g}</strong>
            </p>
            <DataTable rows={groupRows} />
          </div>
        ) : null;
      })}
      {(bd.injuries[team]?.length ?? 0) > 0 && (
        <div>
          <p className={styles.muted}>
            <strong>🩹 Injury impact — usage tied to flagged players</strong>
          </p>
          <DataTable rows={bd.injuries[team]} />
        </div>
      )}
      <p className={styles.caption}>
        RZ = inside the opponent&apos;s 20 · GL = inside the 5 · RZ share is carries for RB/QB and targets for WR/TE · 1st TD
        counts the game&apos;s first rushing/receiving TD over the last two seasons (defensive and special-teams TDs
        ignored) · Status is the official injury report, not gameday inactives.
      </p>
    </div>
  );
}

/* ================================== Page ================================== */

function boardValidationError(value: BoardFile | null, season: number, week: number): string | null {
  if (!value || typeof value !== "object" || !value.meta || !Array.isArray(value.rows)) {
    return "The selected board file does not match the required meta/rows schema.";
  }
  const meta = value.meta;
  if (meta.season !== season || meta.week !== week) {
    return `The selected file contains ${meta.season} week ${meta.week}, not ${season} week ${week}.`;
  }
  if (!Number.isFinite(Date.parse(meta.generated_at)) || !["fitted", "composite"].includes(meta.model) || !Array.isArray(meta.final_games)) {
    return "The selected board metadata is invalid.";
  }
  const seen = new Set<string>();
  const teams = new Set(Object.keys(TEAM_NAMES));
  for (const [index, row] of value.rows.entries()) {
    if (!row || typeof row !== "object") return `Board row ${index + 1} is invalid.`;
    for (const field of ["player_id", "player", "position", "game_status"] as const) {
      if (typeof row[field] !== "string" || !row[field].trim()) return `Board row ${index + 1} is missing ${field}.`;
    }
    if (seen.has(row.player_id)) return `The board contains duplicate player ID ${row.player_id}.`;
    seen.add(row.player_id);
    if (!teams.has(row.team) || !teams.has(row.opponent)) return `Board row ${index + 1} has an invalid team code.`;
    for (const field of ["td_score", "td_estimate"] as const) {
      if (typeof row[field] !== "number" || !Number.isFinite(row[field]) || row[field] < 0 || row[field] > 100) {
        return `Board row ${index + 1} has an invalid ${field}; expected a number from 0 to 100.`;
      }
    }
  }
  return null;
}

function WeeklyDashboard({ manifest }: { manifest: DataManifest }) {
  const seasonOptions = Object.keys(manifest.seasons).map(Number).filter(Number.isFinite).sort((a, b) => b - a);
  const [selectedSeason, setSelectedSeason] = useState(String(seasonOptions[0] ?? ""));
  const season = seasonOptions.includes(Number(selectedSeason)) ? Number(selectedSeason) : (seasonOptions[0] ?? 0);
  const selectedSeasonData = manifest.seasons[String(season)];
  const generatedWeeks = Object.keys(selectedSeasonData?.weeks ?? {}).map(Number).filter(Number.isFinite).sort((a, b) => a - b);
  const [selectedWeek, setSelectedWeek] = useState(String(generatedWeeks.at(-1) ?? manifest.supported_weeks[0] ?? 1));
  const week = Number(selectedWeek || generatedWeeks.at(-1) || manifest.supported_weeks[0] || 1);
  const entry = selectedSeasonData?.weeks[String(week)];
  const boardUrl = entry?.board ? `/data/${entry.board}` : null;
  const breakdownsUrl = entry?.breakdowns ? `/data/${entry.breakdowns}` : null;
  const { data, error, loading } = useJson<BoardFile>(boardUrl);
  const [tab, setTab] = useState<TabId>("rankings");
  const validationError = boardValidationError(data, season, week);
  const boardError = error ?? validationError;
  const rows = data && !boardError ? normalizeBoard(data) : [];
  const supported = manifest.supported_weeks.includes(week);

  return (
    <div className={styles.app}>
      <div className={styles.shell}>
        <header className={styles.header}>
          <h1>🏈 TD Likelihood</h1>
          <p className={styles.subtitle}>Stats-only touchdown probabilities. No odds, no public opinion feed into the model.</p>
          <div className={styles.metaRow}>
            <label className={styles.pill}>Season{" "}
              <select className={styles.select} aria-label="Season" value={String(season)} onChange={(e) => {
                const nextSeason = Number(e.target.value);
                const nextWeeks = Object.keys(manifest.seasons[String(nextSeason)]?.weeks ?? {}).map(Number).sort((a, b) => a - b);
                setSelectedSeason(e.target.value);
                setSelectedWeek(String(nextWeeks.at(-1) ?? manifest.supported_weeks[0] ?? 1));
              }}>
                {seasonOptions.map((year) => <option key={year} value={year}>{year}</option>)}
              </select>
            </label>
            <label className={styles.pill}>Week{" "}
              <select className={styles.select} aria-label="Week" value={String(week)} onChange={(e) => setSelectedWeek(e.target.value)}>
                {manifest.supported_weeks.map((n) => <option key={n} value={n}>Week {n}{selectedSeasonData?.weeks[String(n)] ? "" : " · not generated"}</option>)}
              </select>
            </label>
            {data && !boardError && <>
              <span className={`${styles.pill} ${styles.pillAccent}`}>Week {data.meta.week} · {data.meta.season}</span>
              <span className={styles.pill}>Model: {data.meta.model === "fitted" ? "fitted (logistic regression)" : "hand-weighted composite"}</span>
              <span className={styles.pill}>Updated {new Date(data.meta.generated_at).toLocaleString()}</span>
            </>}
          </div>
        </header>

        <div className={styles.tabs} role="tablist" aria-label="Sections">
          {TABS.map((t) => (
            <button key={t.id} type="button" role="tab" aria-selected={tab === t.id}
              className={`${styles.tab} ${tab === t.id ? styles.tabActive : ""}`} onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </div>

        {loading && <p className={styles.muted}>Loading {season} week {week}…</p>}
        {!loading && !boardUrl && <div className={`${styles.notice} ${supported ? styles.noticeInfo : styles.noticeError}`}>
          {supported ? `Predictions for ${season} week ${week} have not been generated yet. Run export_json.py for this week.` : `Week ${week} is outside the supported regular-season range.`}
        </div>}
        {!loading && boardUrl && boardError && <div className={`${styles.notice} ${styles.noticeError}`}>
          Couldn&apos;t load valid predictions for {season} week {week}: {boardError}. Re-run export_json.py and check its validation output.
        </div>}

        {data && !boardError && <>
          <div hidden={tab !== "rankings"}><RankingsTab rows={rows} meta={data.meta} /></div>
          <div hidden={tab !== "parlay"}><ParlayTab rows={rows} /></div>
          <div hidden={tab !== "market"}><MarketTab rows={rows} meta={data.meta} /></div>
          <div hidden={tab !== "breakdown"}><BreakdownTab boardMeta={data.meta} dataUrl={breakdownsUrl} /></div>
        </>}
        <footer className={styles.footer}>
          Data: nflverse (via nflreadpy). Est. TD% is a model&apos;s estimate from past play — not a guarantee and not a sportsbook price. For entertainment and analysis only; not betting advice. If gambling stops being fun, help is available at{" "}
          <a href="https://www.ncpgambling.org" target="_blank" rel="noopener noreferrer">ncpgambling.org</a>.
        </footer>
      </div>
    </div>
  );
}

export default function Home() {
  const { data, error, loading } = useJson<DataManifest>("/data/manifest.json");
  if (loading) return <main className={styles.app}><p className={styles.muted}>Loading available prediction weeks…</p></main>;
  if (error || !data || data.schema_version !== 1 || !Array.isArray(data.supported_weeks) || !data.seasons || typeof data.seasons !== "object") {
    return <main className={styles.app}><div className={`${styles.notice} ${styles.noticeError}`}>
      Prediction week index is unavailable or invalid ({error ?? "manifest schema mismatch"}). Run export_json.py successfully to publish validated weekly data.
    </div></main>;
  }
  return <WeeklyDashboard manifest={data} />;
}
