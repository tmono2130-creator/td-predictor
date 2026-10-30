"use client";
import { useMemo, useState } from "react";
import styles from "../app/page.module.css";
import type { BoardMeta, BoardRow, BreakdownsFile } from "../lib/types";

import { TEAM_NAMES, POSITION_GROUPS as GROUPS, useJson, breakdownValidationError } from "../lib/data";

import { DataTable } from "./shared";
import MatchupIntelligence, { type IntelligenceView } from "./matchup-intelligence";

export default function BreakdownTab({ boardMeta, rows, dataUrl, intelligenceUrl, intelligenceHash }: { boardMeta: BoardMeta; rows: BoardRow[]; dataUrl: string | null; intelligenceUrl:string|null; intelligenceHash:string|null }) {
  const { data, error, loading } = useJson<BreakdownsFile>(dataUrl);
  const validation = data ? breakdownValidationError(data, boardMeta) : null;
  const keys = useMemo(() => (data && !validation ? Object.keys(data.games) : []), [data, validation]);
  const [selected, setSelected] = useState("");
  const [side, setSide] = useState(0);
  const [view,setView] = useState<"breakdown"|IntelligenceView>("breakdown");

  if (!dataUrl) {
    return <div className={`${styles.notice} ${styles.noticeInfo}`}>No game breakdown export is available for this season and week.</div>;
  }
  if (loading) return <p className={styles.muted}>Loading breakdowns…</p>;
  if (error || !data || validation) {
    return (
      <div className={`${styles.notice} ${styles.noticeError}`}>
        Game breakdown is unavailable ({error ?? validation ?? "no data"}). Try another generated week or reload the page.
      </div>
    );
  }
  if (data.meta.week !== boardMeta.week || data.meta.season !== boardMeta.season) {
    return <div className={`${styles.notice} ${styles.noticeError}`}>
      The breakdown file is for {data.meta.season} week {data.meta.week}, but the selected board is {boardMeta.season} week {boardMeta.week}. It was not displayed.
    </div>;
  }
  const scheduledPairs = new Set(boardMeta.games.map((g) => `${g.away_team}@${g.home_team}`));
  const mismatchedGame = keys.find((key) => {
    const bd = data.games[key];
    return !scheduledPairs.has(key) || !bd || bd.teams.join("@") !== key;
  });
  if (mismatchedGame) {
    return <div className={`${styles.notice} ${styles.noticeError}`}>
      Breakdown game {mismatchedGame} does not match the selected week&apos;s schedule. It was not displayed.
    </div>;
  }
  if (keys.length === 0) {
    return <div className={`${styles.notice} ${styles.noticeInfo}`}>No game breakdowns were generated for this week.</div>;
  }

  const active = keys.includes(selected) ? selected : keys[0];
  const bd = data.games[active];
  const [away, home] = bd.teams;
  const team = side === 0 ? away : home;
  const errorKeys = Object.keys(data.errors);

  return (
    <div>
      <p className={styles.caption} style={{ marginTop: 0 }}>
        A scouting report built from play-by-play. It is separate from the model — it never changes a ranking or
        probability. Use it to see the usage and scoring patterns behind a matchup and make your own call.
      </p>
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

      <div className={styles.matchupHero}><div><span className={styles.eyebrow}>AWAY</span><strong>{away}</strong><small>{TEAM_NAMES[away]}</small></div><span className={styles.muted}>VS</span><div><span className={styles.eyebrow}>HOME</span><strong>{home}</strong><small>{TEAM_NAMES[home]}</small></div></div>
      <div className={styles.chips} role="group" aria-label="Game Breakdown sections">{([["breakdown","TD Breakdown"],["offense","Offensive Identity"],["defense","Defensive Vulnerabilities"],["recommendations","TD Recommendations"]] as const).map(([id,label])=><button key={id} aria-pressed={view===id} className={`${styles.chip} ${view===id?styles.chipActive:""}`} onClick={()=>setView(id)}>{label}</button>)}</div>
      {view!=="breakdown"&&<MatchupIntelligence view={view} url={intelligenceUrl} hash={intelligenceHash} board={boardMeta} rows={rows} gameId={boardMeta.games.find(g=>g.away_team===away&&g.home_team===home)!.game_id} team={team} onTeamChange={t=>setSide(t===away?0:1)}/>}
      <div hidden={view!=="breakdown"}>
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

      <h3 className={styles.sectionTitle}>Matchup touchdown rankings</h3>
      <DataTable rows={rows.filter(r => (r.team === away && r.opponent === home) || (r.team === home && r.opponent === away)).sort((a,b) => b.td_estimate - a.td_estimate).slice(0,10).map((r,i) => ({Rank:i+1, Player:r.player, Team:r.team, Pos:r.position, "TD score":r.td_score, "TD probability %":r.td_estimate, Status:r.injury_status}))} />
      <p className={styles.caption}>Top 10 published estimates for this matchup. Injury status does not establish game-day activation.</p>
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
    </div>
  );
}
