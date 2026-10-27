"use client";
import { useMemo, useState } from "react";
import styles from "../app/page.module.css";
import type { BoardRow, BoardMeta } from "../lib/types";
import { formatPercent as fmtPct } from "../lib/format";
import { TEAM_NAMES, POSITION_OPTIONS as POSITIONS } from "../lib/data";


const teamLabel = (code: string) => TEAM_NAMES[code] ? `${TEAM_NAMES[code]} (${code})` : code;

export default function RankingsTab({ rows, meta }: { rows: BoardRow[]; meta: BoardMeta }) {
  const [team, setTeam] = useState("ALL");
  const [positions, setPositions] = useState<Set<string>>(new Set<string>(POSITIONS));
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("probability");
  const [injury, setInjury] = useState("ALL");
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
          (injury === "ALL" || r.injury_status === injury) &&
          (!hideFinal || r.game_status === "Upcoming") &&
          (needle === "" || r.player.toLowerCase().includes(needle)),
      )
      .sort(
        (a, b) => {
          if (sort === "name") return a.player.localeCompare(b.player);
          if (sort === "ascending") return a.td_estimate - b.td_estimate;
          return b.td_estimate - a.td_estimate;
        },
      );
  }, [rows, team, positions, search, hideFinal, sort, injury]);

  const upcoming = useMemo(() => filtered.filter((r) => r.game_status === "Upcoming"), [filtered]);
  const top3 = upcoming.slice(0, 3);
  const maxEst = filtered.reduce((m, r) => Math.max(m, r.td_estimate), 1);
  const shown = filtered.slice(0, limit);
  const medals = ["01 / UPCOMING", "02 / UPCOMING", "03 / UPCOMING"];

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
          <div className={styles.field}><label htmlFor="rk-sort">Sort by</label><select id="rk-sort" className={styles.select} value={sort} onChange={e => setSort(e.target.value)}><option value="probability">TD estimate: high to low</option><option value="ascending">TD estimate: low to high</option><option value="name">Player name: A–Z</option></select></div>
          <div className={styles.field}><label htmlFor="rk-injury">Injury status</label><select id="rk-injury" className={styles.select} value={injury} onChange={e => setInjury(e.target.value)}>{["ALL", "Active", "Questionable", "Doubtful", "Out", "IR", "Unknown"].map(s => <option key={s} value={s}>{s === "ALL" ? "All statuses" : s}</option>)}</select></div>
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
            Upcoming games only
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
        <div className={styles.tableWrap} tabIndex={0} role="region" aria-label="Scrollable data table">
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
                <th>Injury</th>
                <th>Record timing</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r, i) => {
                const isFinal = r.game_status === "Final";
                const gameLabel = r.game_status === "In Progress" ? "🏈 In progress" :
                  r.game_status === "Upcoming" ? "Upcoming" : r.game_status === "Final" ? "✅ Final" : "Unknown";
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
                    <td>{gameLabel}</td>
                    <td>{isFinal ? (r.actual_scored_td === null ? "Outcome unavailable" : r.actual_scored_td ? "🎯 Scored TD" : "No TD") : "—"}</td>
                    <td
                      className={styles.numCell}
                      style={{ background: `rgba(52, 211, 153, ${alpha.toFixed(3)})`, fontWeight: 600 }}
                    >
                      {fmtPct(r.td_estimate)}
                    </td>
                    <td>{r.games === 0 ? "🆕 No history" : `${r.games} games`}</td>
                    <td>
                      {r.injury_status === "Active" ? "Active" : r.injury_status === "Unknown" ? (
                        <span className={styles.muted}>Unknown</span>
                      ) : <span className={styles.warnText}>{r.injury_status}</span>}
                    </td>
                    <td>{r.prediction_timing === "pregame_snapshot" ? "Pregame snapshot" :
                      r.prediction_timing === "historical_backfill" ? "Historical backfill" : "Timing unknown"}</td>
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
