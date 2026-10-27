"use client";
import Link from "next/link";
import { Activity, useState } from "react";
import styles from "./page.module.css";
import { useJson, isManifest, boardValidationError, normalizeBoard } from "../lib/data";
import type { DataManifest, BoardFile, SectionId } from "../lib/types";
import RankingsTab from "../components/rankings";
import ParlayTab from "../components/parlay-builder";
import MarketTab from "../components/market-check";
import BreakdownTab from "../components/game-breakdown";
import Overview from "../components/overview";
import SnapshotFreshness from "../components/snapshot-freshness";
const TABS: { id: SectionId; label: string; icon: string }[] = [
 { id: "dashboard", label: "Dashboard", icon: "◈" }, { id: "rankings", label: "Player Rankings", icon: "≡" },
 { id: "parlay", label: "Parlay Builder", icon: "⊕" }, { id: "breakdown", label: "Game Breakdown", icon: "▥" }, { id: "market", label: "Market Check", icon: "↗" },
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
  const supported = manifest.supported_weeks.includes(week);

  return (
    <div className={styles.app}>
      <a href="#main-content" className={styles.skipLink}>Skip to content</a>
      <aside className={styles.sidebar}><Link className={styles.brand} href="/">NFL<span>PM</span><small>TOUCHDOWN INTELLIGENCE</small></Link><span className={styles.navLabel}>WORKSPACE</span><nav aria-label="Main navigation">{TABS.map(t => <button key={t.id} type="button" aria-current={tab === t.id ? "page" : undefined} className={`${styles.navItem} ${tab === t.id ? styles.navActive : ""}`} onClick={() => setTab(t.id)}><span aria-hidden="true">{t.icon}</span>{t.label}</button>)}</nav><div className={styles.sidebarNote}><span className={styles.liveDot} /> SNAPSHOT ANALYTICS<p>Independent model estimates.<br />A clearer view of every matchup.</p></div></aside>
      <main id="main-content" className={styles.shell}>
        <header className={styles.header}>
          <div className={styles.eyebrow}>NFL / ANALYTICS WORKSPACE</div><h1>{TABS.find(t => t.id === tab)?.label}</h1>
          <p className={styles.subtitle}>Explore the slate. Understand the probabilities. Build your perspective.</p>
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
          <Activity mode={tab === "rankings" ? "visible" : "hidden"}><RankingsTab key={`${season}:${week}`} rows={rows} meta={data.meta} /></Activity>
          <Activity mode={tab === "parlay" ? "visible" : "hidden"}><ParlayTab key={`${season}:${week}`} rows={rows} /></Activity>
          <Activity mode={tab === "market" ? "visible" : "hidden"}><MarketTab key={`${season}:${week}`} rows={rows} meta={data.meta} /></Activity>
          <Activity mode={tab === "breakdown" ? "visible" : "hidden"}><BreakdownTab key={`${season}:${week}`} boardMeta={data.meta} dataUrl={breakdownsUrl} /></Activity>
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
