"use client";
import { useMemo, useState } from "react";
import styles from "../app/page.module.css";
import type { BoardRow } from "../lib/types";
import { formatPercent as fmtPct } from "../lib/format";
import { autoBuildParlay, parlayProbability, VOLATILITY_ORDER, type ParlayResult, type VolatilityBand } from "../lib/parlay";
import { PlayerPicker, ParlayView } from "./shared";
const errMessage = (e: unknown) => e instanceof Error ? e.message : String(e);

export default function ParlayTab({ rows }: { rows: BoardRow[] }) {
  const upcoming = useMemo(
    () => rows.filter((r) => r.game_status === "Upcoming").sort((a, b) => b.td_estimate - a.td_estimate),
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
          <h3>Build your selection <span className={styles.muted}>{picked.length} / 6 legs</span></h3>{upcoming.length === 0 && <p role="status" className={styles.notice}>No upcoming players are available for this snapshot.</p>}
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
