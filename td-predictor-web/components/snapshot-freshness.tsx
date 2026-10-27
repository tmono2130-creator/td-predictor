"use client";
import { useSyncExternalStore } from "react";
import type { BoardMeta } from "../lib/types";
import { snapshotFreshness } from "../lib/format";
import styles from "../app/page.module.css";

const subscribe = (notify: () => void) => {
  const timer = window.setInterval(notify, 60_000);
  return () => window.clearInterval(timer);
};
const getMinute = () => Math.floor(Date.now() / 60_000) * 60_000;
const getServerMinute = () => 0;

export default function SnapshotFreshness({ meta }: { meta: BoardMeta }) {
  const now = useSyncExternalStore(subscribe, getMinute, getServerMinute);
  const classification = meta.snapshot_classification === "pregame_snapshot" ? "Pregame snapshot" :
    meta.snapshot_classification === "historical_backfill" ? "Historical backfill" :
    meta.snapshot_classification === "mixed_pregame_and_historical" ? "Mixed pregame / historical" : "Classification unavailable";
  const version = meta.model_version;
  return <>
    <span className={styles.pill} title={version ?? "No model version recorded"}>
      Version: {version ? `${version.split(":")[0]}:${version.split(":")[1]?.slice(0, 10) ?? "unknown"}` : "Not recorded"}
    </span>
    <span className={styles.pill}>{classification}</span>
    <span className={styles.pill} role="status" aria-label="Data freshness">
      {now ? snapshotFreshness(meta, now) : "Checking snapshot freshness…"}
    </span>
  </>;
}
