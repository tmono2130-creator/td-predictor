"use client";
import { useMemo, useState } from "react";
import styles from "../app/page.module.css";
import type { BoardRow, TableRow } from "../lib/types";
import { formatPercent as fmtPct, formatParlayPercent as fmtParlay, cellText } from "../lib/format";
import { fairAmericanOdds, type ParlayResult } from "../lib/parlay";

export function DataTable({ rows, emptyText }: { rows: TableRow[]; emptyText?: string }) {
  if (rows.length === 0) return <p className={styles.muted}>{emptyText ?? "No data."}</p>;
  const cols = Object.keys(rows[0]);
  return (
    <div className={styles.tableWrap} tabIndex={0} role="region" aria-label="Scrollable data table">
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

export function PlayerPicker({
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
              <span><strong>{p.player}</strong> <small>{p.position}</small></span>
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

export function ParlayView({ result }: { result: ParlayResult }) {
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
