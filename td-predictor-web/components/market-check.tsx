"use client";
import { useEffect, useMemo, useState } from "react";
import styles from "../app/page.module.css";
import type { BoardRow, BoardMeta, StoredComparison } from "../lib/types";
import { formatPercent as fmtPct } from "../lib/format";
import { fairAmericanOdds, impliedProbFromAmericanOdds } from "../lib/parlay";
import { PlayerPicker } from "./shared";

export default function MarketTab({ rows, meta }: { rows: BoardRow[]; meta: BoardMeta }) {
  const upcoming = useMemo(
    () => rows.filter((r) => r.game_status === "Upcoming").sort((a, b) => b.td_estimate - a.td_estimate),
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
        if (Array.isArray(parsed)) { const valid = parsed.filter((item): item is StoredComparison => !!item && typeof item === "object" && typeof item.player_id === "string" && typeof item.odds === "string" && impliedProbFromAmericanOdds(item.odds) !== null); queueMicrotask(() => setItems(valid)); }
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
        Enter the American odds you see in the market to compare their implied probability with the model estimate. Prices are entered manually and are not a live feed.
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
          <div className={styles.tableWrap} tabIndex={0} role="region" aria-label="Scrollable data table">
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
