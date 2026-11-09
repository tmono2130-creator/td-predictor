"use client";
import { useMemo, useState, useSyncExternalStore } from "react";
import type { BoardMeta, BoardRow } from "../lib/types";
import { generateParlays, type GeneratorOptions, type GeneratorResult } from "../lib/parlay-generator";
import { parlayProbability } from "../lib/parlay";
import { formatParlayPercent } from "../lib/format";
import { subscribeClock, clockSnapshot, serverClockSnapshot } from "../lib/clock";
import { DataTable } from "./shared";
import styles from "../app/page.module.css";

export default function DiversifiedParlays({ rows, meta }: { rows: BoardRow[]; meta: BoardMeta }) {
  const now = useSyncExternalStore(subscribeClock, clockSnapshot, serverClockSnapshot);
  const [legs, setLegs] = useState(3), [count, setCount] = useState(10), [exposure, setExposure] = useState(30);
  const [mode, setMode] = useState<GeneratorOptions["mode"]>("balanced"), [game, setGame] = useState("all"), [window, setWindow] = useState("all");
  const [seed, setSeed] = useState("nfl-pm"), [crossGame, setCrossGame] = useState(true);
  const [output, setOutput] = useState<{ result: GeneratorResult; settings: GeneratorOptions; key: string } | null>(null), [error, setError] = useState<string | null>(null);
  const snapshotKey = useMemo(() => meta.generated_at + JSON.stringify({ games: meta.games, players: rows.map(r => [r.player_id, r.game_id, r.team, r.opponent, r.game_status, r.td_estimate, r.injury_status, r.game_day_status, r.roster_eligibility]) }), [meta.generated_at, meta.games, rows]);
  const games = useMemo(() => meta.games.filter(g => {
    if (game !== "all" && g.game_id !== game) return false;
    const hour = Number(new Intl.DateTimeFormat("en-US", { hour: "numeric", hourCycle: "h23", timeZone: "America/New_York" }).format(new Date(g.kickoff_utc)));
    return window === "all" || (window === "early" ? hour < 16 : window === "late" ? hour >= 16 && hour < 19 : hour >= 19);
  }), [meta.games, game, window]);
  const run = () => {
    try {
      if (!now || meta.snapshot_classification !== "pregame_snapshot") throw new Error("A verified fresh pregame snapshot is required.");
      const settings: GeneratorOptions = { legs, count, mode, maxExposure: exposure / 100, crossGame, seed, games, generatedAt: meta.generated_at, now };
      setOutput({ result: generateParlays(rows, settings), settings, key: snapshotKey }); setError(null);
    } catch (e) { setOutput(null); setError(e instanceof Error ? e.message : String(e)); }
  };
  const usedIds = new Set(output?.result.combinations.flat() ?? []);
  const usedGames = output?.settings.games.filter(g => rows.some(r => r.game_id === g.game_id && usedIds.has(r.player_id))) ?? [];
  const visible = output && output.key === snapshotKey && now && usedGames.length > 0 && usedGames.every(g => Date.parse(g.kickoff_utc) - now > 600000) &&
    now - Date.parse(meta.generated_at) < (Math.min(...usedGames.map(g => Date.parse(g.kickoff_utc))) - now <= 6 * 3600000 ? 1800000 :
      Math.min(...usedGames.map(g => Date.parse(g.kickoff_utc))) - now <= 48 * 3600000 ? 6 * 3600000 : 24 * 3600000);
  const combinationRows = useMemo(() => output?.key === snapshotKey ? output.result.combinations.map((ids, i) => {
    const result = parlayProbability(rows, ids);
    return { Combination: i + 1, Players: result.legs.map(l => `${l.player} (${l.team})`).join(" · "), "Independence estimate": formatParlayPercent(result.combinedPct) };
  }) : [], [output, rows, snapshotKey]);
  return <section className={styles.panel} aria-label="Diversified parlay generator">
    <h3>Diversified combinations</h3>
    <p className={styles.caption}>Uses unchanged V5 estimates. High-estimate concentrates weight on stronger estimates; long-shot spreads selection further down the pool. Unknown injuries remain unverified. Confirmed Out, IR, inactive and ineligible players are excluded.</p>
    <div className={styles.controls}>
      <div className={styles.field}><label htmlFor="batch-legs">Combination legs</label><select id="batch-legs" className={styles.select} value={legs} onChange={e => setLegs(Number(e.target.value))}>{[2,3,4,5].map(n => <option key={n}>{n}</option>)}</select></div>
      <div className={styles.field}><label htmlFor="batch-count">Number of combinations</label><select id="batch-count" className={styles.select} value={count} onChange={e => setCount(Number(e.target.value))}>{[10,20,30].map(n => <option key={n}>{n}</option>)}</select></div>
      <div className={styles.field}><label htmlFor="batch-mode">Selection mode</label><select id="batch-mode" className={styles.select} value={mode} onChange={e => setMode(e.target.value as GeneratorOptions["mode"])}><option value="high-estimate">High-estimate</option><option value="balanced">Balanced</option><option value="long-shot">Long-shot</option></select></div>
      <div className={styles.field}><label htmlFor="batch-exposure">Maximum player exposure (%)</label><input id="batch-exposure" className={styles.input} type="number" min={1} max={100} value={exposure} onChange={e => setExposure(Number(e.target.value))}/></div>
      <div className={styles.field}><label htmlFor="batch-game">Combination game</label><select id="batch-game" className={styles.select} value={game} onChange={e => setGame(e.target.value)}><option value="all">All games</option>{meta.games.map(g => <option key={g.game_id} value={g.game_id}>{g.away_team} @ {g.home_team}</option>)}</select></div>
      <div className={styles.field}><label htmlFor="batch-window">Kickoff window (Eastern)</label><select id="batch-window" className={styles.select} value={window} onChange={e => setWindow(e.target.value)}><option value="all">All windows</option><option value="early">Before 4 PM</option><option value="late">4–7 PM</option><option value="night">7 PM onward</option></select></div>
      <div className={styles.field}><label htmlFor="batch-seed">Reproducible seed</label><input id="batch-seed" className={styles.input} value={seed} onChange={e => setSeed(e.target.value)}/></div>
    </div>
    <label className={styles.checkRow}><input type="checkbox" checked={crossGame} onChange={e => setCrossGame(e.target.checked)}/>One leg per game</label>
    <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={run}>Generate combinations</button>{" "}
    <button className={styles.btn} onClick={() => setSeed(String(crypto.getRandomValues(new Uint32Array(1))[0]))}>Shuffle seed</button>
    {error && <p role="alert" className={`${styles.notice} ${styles.noticeError}`}>{error}</p>}
    {output && !visible && <p role="status" className={styles.notice}>Combinations unavailable: snapshot freshness or kickoff margin has expired. Generate again using fresh predictions.</p>}
    {output && visible && <>
      <p role="status">Generated {output.result.combinations.length} of {output.settings.count}. Maximum {output.result.cap} appearances per player; {output.result.eligible} eligible players.</p>
      <p className={styles.caption}>Seed: {output.settings.seed} · {output.settings.mode} · {output.settings.legs} legs</p>
      {output.result.warning && <p className={styles.notice}>{output.result.warning}</p>}
      <DataTable rows={combinationRows}/>
      <DataTable rows={Object.entries(output.result.exposure).sort((a,b) => b[1]-a[1]).map(([id, n]) => ({ Player: rows.find(r => r.player_id === id)?.player ?? id, Appearances: n }))}/>
    </>}
    <p className={styles.caption}>Combined estimates multiply existing V5 estimates under an independence approximation. They are not validated joint probabilities, sportsbook odds or expected value.</p>
  </section>;
}
