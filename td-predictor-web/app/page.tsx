"use client";
import Link from "next/link";
import { Activity, useState } from "react";
import styles from "./page.module.css";
import { useJson, isManifest, boardValidationError, normalizeBoard } from "../lib/data";
import type { DataManifest, BoardFile, SectionId, BoardRow } from "../lib/types";
import RankingsTab from "../components/rankings";
import ParlayTab from "../components/parlay-builder";
import MarketTab from "../components/market-check";
import BreakdownTab from "../components/game-breakdown";
import GamePredictor from "../components/game-predictor";
import Overview from "../components/overview";
import SnapshotFreshness from "../components/snapshot-freshness";
const TABS: { id: SectionId; label: string; accessible: string }[] = [
 { id: "dashboard", label: "Dashboard", accessible: "Dashboard" },
 { id: "rankings", label: "TD Rankings", accessible: "Player Rankings" },
 { id: "parlay", label: "Parlay Builder", accessible: "Parlay Builder" },
 { id: "market", label: "Market Check", accessible: "Market Check" },
 { id: "game", label: "Game Predictor", accessible: "Game Predictor" },
 { id: "breakdown", label: "Game Breakdown", accessible: "Game Breakdown" },
];
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
  const [tab, setTab] = useState<SectionId>("dashboard");
  const validationError = boardValidationError(data, season, week);
  const boardError = error ?? validationError;
  const rows = data && !boardError ? normalizeBoard(data) : [];
  const snapshot = `${season}:${week}`;
  const [selection, setSelection] = useState<{ snapshot: string; ids: string[] }>({ snapshot: "", ids: [] });
  const selectedIds = selection.snapshot === snapshot ? selection.ids : [];
  const updateSelection = (ids: string[]) => setSelection({ snapshot, ids });
  const addToParlay = (player: BoardRow) => {
    if (player.game_status !== "Upcoming" || selectedIds.includes(player.player_id) || selectedIds.length >= 6) return;
    updateSelection([...selectedIds, player.player_id]);
  };
  const supported = manifest.supported_weeks.includes(week);

  return (
    <div className={styles.app}>
      <a href="#main-content" className={styles.skipLink}>Skip to content</a>
      <aside className={styles.sidebar}>
        <Link className={styles.brand} href="/">NFL<span>PM</span><small>TOUCHDOWN ANALYTICS</small></Link>
        <span className={styles.navLabel}>WORKSPACE</span>
        <nav aria-label="Main navigation">{TABS.map((t,i) => <button key={t.id} type="button" aria-label={t.accessible} aria-current={tab === t.id ? "page" : undefined} className={`${styles.navItem} ${tab === t.id ? styles.navActive : ""}`} onClick={() => setTab(t.id)}><svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d={["M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z","M4 5h16M4 12h16M4 19h16M8 3v18","M4 7h16v14H4zM8 7V5a4 4 0 018 0v2M8 13h8M12 9v8","M3 17l6-6 4 3 8-10M15 4h6v6","M3 12h18M12 3v18M4 4l16 16","M4 4h16v16H4zM4 10h16M10 4v16"][i]} /></svg><span>{t.label}</span>{t.id === "parlay" && selectedIds.length > 0 ? <small className={styles.navCount}>{selectedIds.length}</small> : null}</button>)}</nav>
        <div className={styles.sidebarNote}><span className={styles.liveDot} /> PUBLISHED SNAPSHOTS<p>Independent estimates.<br/>Your weekly football perspective.</p><span className={styles.sidebarSeason}>{season} SEASON · WEEK {week}</span></div>
      </aside>
      <main id="main-content" className={styles.shell}>
        <header className={styles.header}>
          <div className={styles.eyebrow}>NFL / TOUCHDOWN ANALYTICS</div><h1>{TABS.find(t => t.id === tab)?.label}</h1>
          <p className={styles.subtitle}>Explore the slate, compare probabilities and understand every matchup.</p>
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
              <SnapshotFreshness meta={data.meta} />
              <span className={styles.pill}>
                {data.meta.injury_report.week_available ? "Weekly injury report available" : "Weekly injury report unavailable"}
              </span>
            </>}
          </div>
        </header>

        {loading && <div role="status" className={styles.loading}><span className={styles.spinner} />Loading {season} week {week}…</div>}
        {!loading && !boardUrl && <div className={`${styles.notice} ${supported ? styles.noticeInfo : styles.noticeError}`}>
          {supported ? `Predictions for ${season} week ${week} have not been generated yet. Choose a generated week to explore available predictions.` : `Week ${week} is outside the supported regular-season range.`}
        </div>}
        {!loading && boardUrl && boardError && <div role="alert" className={`${styles.notice} ${styles.noticeError}`}>
          Couldn&apos;t load valid predictions for {season} week {week}: {boardError}. Try another generated week or reload the page.
        </div>}

        {data && !boardError && !loading && <>
          <div className={styles.snapshotBar}><span className={styles.liveDot} /> GENERATED SNAPSHOT <span>{data.meta.games.length} matchups · {rows.length} players</span></div>
          {tab === "dashboard" && <Overview rows={rows} meta={data.meta} onNavigate={setTab} />}
          <Activity mode={tab === "rankings" ? "visible" : "hidden"}><RankingsTab key={`${season}:${week}`} rows={rows} meta={data.meta} onAdd={addToParlay} selectedIds={selectedIds} /></Activity>
          <Activity mode={tab === "parlay" ? "visible" : "hidden"}><ParlayTab key={`${season}:${week}`} rows={rows} selectedIds={selectedIds} onSelectionChange={updateSelection} /></Activity>
          <Activity mode={tab === "market" ? "visible" : "hidden"}><MarketTab key={`${season}:${week}`} rows={rows} meta={data.meta} /></Activity>
          <Activity mode={tab === "game" ? "visible" : "hidden"}><GamePredictor key={`${season}:${week}`} season={season} week={week} games={data.meta.games} url={entry?.game_predictor?`/data/${entry.game_predictor}`:null} pin={entry?.game_predictor_sha256??null}/></Activity>
          <Activity mode={tab === "breakdown" ? "visible" : "hidden"}><BreakdownTab key={`${season}:${week}`} boardMeta={data.meta} rows={rows} dataUrl={breakdownsUrl} /></Activity>
        </>}
        <footer className={styles.footer}>
          Data: nflverse (via nflreadpy). Est. TD% is a model&apos;s estimate from past play — not a guarantee and not a sportsbook price. For entertainment and analysis only; not betting advice. If gambling stops being fun, help is available at{" "}
          <a href="https://www.ncpgambling.org" target="_blank" rel="noopener noreferrer">ncpgambling.org</a>.
        </footer>
      </main>
    </div>
  );
}

export default function Home() {
  const { data, error, loading } = useJson<DataManifest>("/data/manifest.json");
  if (loading) return <main className={styles.app}><div role="status" className={styles.loading}><span className={styles.spinner} />Loading available prediction weeks…</div></main>;
  if (error || !isManifest(data)) {
    return <main className={styles.app}><div role="alert" className={`${styles.notice} ${styles.noticeError}`}>
      Prediction week index is unavailable or invalid ({error ?? "manifest schema mismatch"}). Reload the page to retry, or check the published data index.
    </div></main>;
  }
  return <WeeklyDashboard manifest={data} />;
}
