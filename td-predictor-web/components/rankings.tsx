"use client";
import { useMemo, useState } from "react";
import styles from "../app/page.module.css";
import type { BoardRow, BoardMeta } from "../lib/types";
import { formatPercent as fmtPct } from "../lib/format";
import { TEAM_NAMES, POSITION_OPTIONS as POSITIONS } from "../lib/data";


const teamLabel = (code: string) => TEAM_NAMES[code] ? `${TEAM_NAMES[code]} (${code})` : code;

export default function RankingsTab({ rows, meta, onAdd, selectedIds }: { rows: BoardRow[]; meta: BoardMeta; onAdd: (player: BoardRow) => void; selectedIds: string[] }) {
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
          const ascending = sort.endsWith("-asc");
          const key = sort.replace(/-asc$/, "");
          const value = (r: BoardRow) => key === "score" ? r.td_score : key === "team" ? r.team : key === "position" ? r.position : key === "opponent" ? r.opponent : key === "status" ? r.injury_status : key === "player" ? r.player : r.td_estimate;
          const av = value(a), bv = value(b);
          const result = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv));
          return (ascending ? result : -result) || a.player.localeCompare(b.player);
        },
      );
  }, [rows, team, positions, search, hideFinal, sort, injury]);

  const upcoming = useMemo(() => filtered.filter((r) => r.game_status === "Upcoming"), [filtered]);
  const top3 = upcoming.slice(0, 3);
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
          <div className={styles.field}><label htmlFor="rk-sort">Sort by</label><select id="rk-sort" className={styles.select} value={sort} onChange={e => setSort(e.target.value)}><option value="probability">TD estimate: high to low</option><option value="ascending">TD estimate: low to high</option><option value="name">Player name: A–Z</option>{!["probability","ascending","name"].includes(sort) && <option value={sort}>Table column: {sort}</option>}</select></div>
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
            <caption>PLAYER TD RANKINGS · WEEK {meta.week} · CLICK A COLUMN TO SORT / A PLAYER FOR DETAILS</caption>
            <thead><tr><th scope="col">Rank</th>{([["player","Player"],["team","Team"],["position","Pos"],["opponent","Opp"],["score","TD score"],["probability","TD probability"],["status","Status"]] as const).map(([key,label]) => {
              const active = sort === key || sort === `${key}-asc` || (key === "probability" && sort === "ascending") || (key === "player" && sort === "name");
              const ascending = sort.endsWith("-asc") || sort === "ascending" || sort === "name";
              return <th key={key} scope="col" aria-sort={active ? ascending ? "ascending" : "descending" : "none"}><button className={styles.sortButton} onClick={() => setSort(active && !ascending ? `${key}-asc` : key)}>{label}{active ? ascending ? " ▲" : " ▼" : ""}</button></th>;
            })}<th scope="col">Game</th><th scope="col">Parlay</th></tr></thead>
            <tbody>{shown.map((r,i) => <tr key={r.player_id} className={i < 3 && sort === "probability" ? styles.topRank : undefined}>
              <td>{i+1}</td><td><details className={styles.playerDetails}><summary>{r.player}</summary><p>Sample: {r.games === 0 ? "No history — team/matchup context only" : `${r.games} games`}<br/>Record: {r.prediction_timing === "pregame_snapshot" ? "Pregame snapshot" : r.prediction_timing === "historical_backfill" ? "Historical backfill" : "Timing unknown"}<br/>Outcome: {r.game_status === "Final" && r.actual_scored_td !== null ? r.actual_scored_td ? "Scored TD" : "No TD" : "Outcome unavailable"}<br/>Injury: {r.injury_status} (not game-day activation)</p></details></td>
              <td>{r.team}</td><td>{r.position}</td><td>{r.is_home === 0 ? "@" : r.is_home === 1 ? "vs" : ""} {r.opponent}</td><td className={styles.numCell}>{r.td_score.toFixed(1)}</td><td className={`${styles.numCell} ${styles.statAccent}`}>{fmtPct(r.td_estimate)}<span className={styles.probabilityTrack} aria-hidden="true"><span style={{width:`${r.td_estimate}%`}} /></span></td><td className={r.injury_status !== "Active" && r.injury_status !== "Unknown" ? styles.warnText : undefined}>{r.injury_status}</td><td>{r.game_status}</td><td><button className={`${styles.btn} ${styles.btnSmall}`} aria-label={`Add ${r.player} to parlay`} disabled={r.game_status !== "Upcoming" || selectedIds.includes(r.player_id) || selectedIds.length >= 6} onClick={() => onAdd(r)}>{selectedIds.includes(r.player_id) ? "Selected" : r.game_status !== "Upcoming" ? "Unavailable" : "+ Add"}</button></td>
            </tr>)}</tbody>
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
