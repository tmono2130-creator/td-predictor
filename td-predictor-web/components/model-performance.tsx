"use client";
import { useEffect, useMemo, useState } from "react";
import { useJson } from "../lib/data";
import { decodeEvaluation, isEvaluationIndex, validateEvaluation, type Evaluation } from "../lib/performance";
import { DataTable } from "./shared";
import styles from "../app/page.module.css";

const value = (v: number | null | undefined, digits = 3) => v == null ? "Unavailable" : v.toFixed(digits);
export default function ModelPerformance({ season, week }: { season: number; week: number }) {
  const index = useJson<unknown>("/evaluations/index.json");
  const [choice, setChoice] = useState(`${season}:${week}`), [search, setSearch] = useState("");
  const entries = isEvaluationIndex(index.data) ? index.data.reports : [];
  const entry = entries.find(r => `${r.season}:${r.week}` === choice);
  const key = entry ? `${entry.path}:${entry.sha256}` : null;
  const [state, setState] = useState<{ key: string; data: unknown; error: string | null } | null>(null);
  useEffect(() => {
    if (!entry || !key) return;
    const abort = new AbortController();
    fetch(`/evaluations/${entry.path}`, { cache: "no-store", signal: abort.signal }).then(r => {
      if (!r.ok) throw new Error(`Evaluation HTTP ${r.status}`); return r.arrayBuffer();
    }).then(b => decodeEvaluation(b, entry.sha256)).then(data => { if (!abort.signal.aborted) setState({ key, data, error: null }); })
      .catch((e: unknown) => { if (!abort.signal.aborted) setState({ key, data: null, error: e instanceof Error ? e.message : String(e) }); });
    return () => abort.abort();
  }, [entry, key]);
  const active = state?.key === key ? state : null;
  const invalid = active?.data && entry ? validateEvaluation(active.data, entry.season, entry.week) ??
    ((active.data as Evaluation).evaluation_id !== entry.path.split("/")[0] ? "Evaluation identity differs from index." : null) : null;
  const report = active?.data && !invalid ? active.data as Evaluation : null;
  const players = useMemo(() => report?.players.filter(p => `${p.player} ${p.team} ${p.position}`.toLowerCase().includes(search.toLowerCase())) ?? [], [report, search]);
  return <section className={styles.panel} aria-label="Model performance">
    <h2>Model performance</h2>
    <p className={styles.caption}>Original frozen pregame estimates compared with verified outcomes. V5 estimates are not established calibrated probabilities. Ranking hit rates and probability-error metrics answer different questions.</p>
    {index.loading ? <p role="status">Loading reviewed evaluations…</p> : index.error ?
      <p role={index.error.includes("HTTP 404") ? "status" : "alert"} className={styles.notice}>{index.error.includes("HTTP 404") ? "No reviewed evaluations have been published. Original predictions remain unchanged." : `Evaluation index unavailable: ${index.error}`}</p> : !isEvaluationIndex(index.data) ?
      <p role="alert" className={styles.notice}>Evaluation index is invalid. No performance numbers are substituted.</p> : <>
      <div className={styles.field}><label htmlFor="evaluation-choice">Evaluation season and week</label><select id="evaluation-choice" className={styles.select} value={choice} onChange={e => { setChoice(e.target.value); setSearch(""); }}>
        {!entry && <option value={choice}>{choice.replace(":", " Week ")} · unavailable</option>}
        {entries.map(r => <option key={`${r.season}:${r.week}`} value={`${r.season}:${r.week}`}>{r.season} Week {r.week}</option>)}
      </select></div>
      {!entry && <p role="status" className={styles.notice}>No verified evaluation exists for this week. Historical data is never reconstructed as an original forecast.</p>}
      {entry && !active && <p role="status">Loading hash-verified performance…</p>}
      {(active?.error || invalid) && <p role="alert" className={`${styles.notice} ${styles.noticeError}`}>Evaluation unavailable: {active?.error ?? invalid}</p>}
    </>}
    {report && <>
      <p role="status" className={styles.notice}>{report.status === "partial" ? "Partial week" : "Verified final evaluation"}: {report.games_completed} completed · {report.games_pending} pending. Outcomes as of {new Date(report.evaluated_as_of).toLocaleString()}.</p>
      <p className={styles.caption}>Forecast generated {new Date(report.forecast_generated_at).toLocaleString()}. Evaluates original board SHA-256 {report.forecast_hashes["board.json"].slice(0, 16)}…; this may differ from the website’s selected prediction snapshot.</p>
      <DataTable rows={[{ Metric: "Winner accuracy", Value: report.game_metrics.winner_accuracy == null ? "Unavailable" : `${(report.game_metrics.winner_accuracy * 100).toFixed(1)}%` },
        { Metric: "Per-team score MAE", Value: value(report.game_metrics.team_score_mae) }, { Metric: "Total MAE", Value: value(report.game_metrics.total_mae) },
        { Metric: "Margin MAE", Value: value(report.game_metrics.margin_mae) }, { Metric: "TD Brier", Value: value(report.td_metrics.brier, 5) },
        { Metric: "TD log loss", Value: value(report.td_metrics.log_loss, 5) }, { Metric: "TD ROC AUC", Value: value(report.td_metrics.auc, 5) },
        { Metric: "Labelled player coverage", Value: `${report.td_metrics.n} / ${report.players.length}` }]}/>
      <h3>Predicted and actual scores</h3><DataTable rows={report.games.map(g => ({ Matchup: `${g.away_team} @ ${g.home_team}`, Status: g.status,
        "Projected away/home": g.prediction ? `${g.prediction.away.toFixed(2)} / ${g.prediction.home.toFixed(2)}` : "Unavailable",
        "Actual away/home": g.actual ? `${g.actual.away} / ${g.actual.home}` : "Pending" }))}/>
      <h3>Calibration diagnostics</h3><DataTable rows={report.td_metrics.calibration.map(b => ({ "Estimate band": `${b.lower_pct}–${b.upper_pct}%`, N: b.n, "Mean estimate %": b.mean_estimate_pct, "Observed TD %": b.observed_pct }))} emptyText="No verified labels available."/>
      <h3>Position diagnostics</h3><DataTable rows={Object.entries(report.position_metrics).map(([position, m]) => ({ Position: position, N: m.n, Brier: m.brier, "Log loss": m.log_loss, AUC: m.auc }))}/>
      <h3>Ranking hit rates</h3><DataTable rows={Object.entries(report.top_per_game ?? {}).map(([n, r]) => ({ "Top per game": Number(n), Selected: r.selected, Labelled: r.labelled, Hits: r.hits, "Hit rate %": r.hit_rate == null ? null : r.hit_rate * 100 }))} emptyText="Ranking diagnostics are unavailable for this evaluation."/>
      <h3>Error by original predicted margin</h3><DataTable rows={Object.entries(report.margin_bands ?? {}).map(([band, m]) => ({ Band: band, Games: m.n, "Winner accuracy %": m.winner_accuracy == null ? null : m.winner_accuracy * 100, "Score MAE": m.team_score_mae, "Total MAE": m.total_mae }))} emptyText="Margin-band diagnostics are unavailable."/>
      <h3>Frozen-input baseline comparison</h3><DataTable rows={[["PPP V1", report.game_metrics], ["Prior offensive points/game", report.baseline_metrics]].map(([label, metrics]) => { const m = metrics as Evaluation["game_metrics"]; return { Model: label as string, Games: m.n, "Winner accuracy %": m.winner_accuracy == null ? null : m.winner_accuracy * 100, "Score MAE": m.team_score_mae, "Total MAE": m.total_mae }; })}/>
      <p className={styles.caption}>The comparison uses each team’s historical offensive points/game already frozen before kickoff. It excludes defensive/return scoring and has no postgame fit.</p>
      <h3>Player outcomes</h3><label htmlFor="performance-search">Search evaluated players</label><input id="performance-search" className={styles.input} value={search} onChange={e => setSearch(e.target.value)}/>
      <DataTable rows={players.map(p => ({ Player: p.player, Team: p.team, Position: p.position, "V5 estimate %": p.estimate_pct, "Scored TD": p.actual_td == null ? "Unknown / pending" : p.actual_td ? "Yes" : "No", Evidence: p.outcome_reason }))}/>
      <h3>Coverage limitations</h3><ul>{report.limitations.map((text, i) => <li key={i}>{text}</li>)}</ul>
    </>}
  </section>;
}
