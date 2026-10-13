"use client";

import { useEffect, useMemo, useState } from "react";

type Position = "QB" | "RB" | "WR" | "TE";
type PositionFilter = "ALL" | Position;
type SortOption = "probability" | "score";

type Player = {
  name: string;
  team: string;
  opponent: string;
  position: Position;
  score: number;
  probability: number;
  seasonTDs: number;
  opportunities: number;
  matchup: string;
  gameStatus: string;
};

type ApiPlayer = {
  player?: string | null;
  position?: string | null;
  team?: string | null;
  opponent?: string | null;
  td_score?: number | null;
  td_estimate?: number | null;
  season_tds?: number | null;
  opportunities_pg?: number | null;
  matchup_score?: number | null;
  game_status?: string | null;
};

type ApiResponse = {
  season: number;
  week: number;
  count: number;
  players: ApiPlayer[];
  notice?: string;
};

const API_URL =
  process.env.NEXT_PUBLIC_TD_API_URL || "http://127.0.0.1:8000";

const positionOptions: PositionFilter[] = [
  "ALL",
  "QB",
  "RB",
  "WR",
  "TE",
];

function SummaryCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-5">
      <p className="text-sm text-zinc-400">{label}</p>

      <p className="mt-2 text-3xl font-semibold tracking-tight text-white">
        {value}
      </p>

      <p className="mt-2 text-xs text-zinc-500">{detail}</p>
    </div>
  );
}

function getPositionStyle(position: Position) {
  const styles: Record<Position, string> = {
    QB: "border-purple-400/30 bg-purple-400/10 text-purple-300",
    RB: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
    WR: "border-sky-400/30 bg-sky-400/10 text-sky-300",
    TE: "border-amber-400/30 bg-amber-400/10 text-amber-300",
  };

  return styles[position];
}

function getProbabilityStyle(probability: number) {
  if (probability >= 40) {
    return "text-emerald-300";
  }

  if (probability >= 25) {
    return "text-amber-300";
  }

  return "text-zinc-300";
}

function getMatchupLabel(score: number | null | undefined) {
  if (score === null || score === undefined) {
    return "Unavailable";
  }

  if (score >= 70) {
    return "Favorable";
  }

  if (score >= 40) {
    return "Neutral";
  }

  return "Difficult";
}

export default function Home() {
  const [position, setPosition] = useState<PositionFilter>("ALL");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<SortOption>("probability");
  const [selectedWeek, setSelectedWeek] = useState("Week 1");

  const [apiPlayers, setApiPlayers] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState("");
  const [apiNotice, setApiNotice] = useState(
    "TD estimates are model estimates, not guaranteed outcomes.",
  );

  useEffect(() => {
    const controller = new AbortController();

    async function loadPredictions() {
      setLoading(true);
      setApiError("");

      try {
        const week = Number(selectedWeek.replace("Week ", ""));

        const response = await fetch(
          `${API_URL}/api/predictions?season=2026&week=${week}&top=100`,
          {
            signal: controller.signal,
            cache: "no-store",
          },
        );

        if (!response.ok) {
          const errorData = await response.json().catch(() => null);

          throw new Error(
            errorData?.detail ||
              `The prediction API returned error ${response.status}.`,
          );
        }

        const data: ApiResponse = await response.json();

        const mappedPlayers: Player[] = (data.players || [])
          .filter(
            (player) =>
              player.player &&
              player.team &&
              ["QB", "RB", "WR", "TE"].includes(
                player.position || "",
              ) &&
              typeof player.td_score === "number",
          )
          .map((player) => ({
            name: player.player as string,
            team: player.team as string,
            opponent: player.opponent || "N/A",
            position: player.position as Position,
            score: player.td_score as number,
            probability: player.td_estimate ?? 0,
            seasonTDs: player.season_tds ?? 0,
            opportunities: player.opportunities_pg ?? 0,
            matchup: getMatchupLabel(player.matchup_score),
            gameStatus: player.game_status || "Unknown",
          }));

        setApiPlayers(mappedPlayers);

        setApiNotice(
          data.notice ||
            "TD estimates are model estimates, not guaranteed outcomes.",
        );
      } catch (error) {
        if (
          error instanceof Error &&
          error.name === "AbortError"
        ) {
          return;
        }

        setApiError(
          error instanceof Error
            ? error.message
            : "Unable to load predictions.",
        );

        setApiPlayers([]);
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }

    loadPredictions();

    return () => controller.abort();
  }, [selectedWeek]);

  const players = useMemo(() => {
    const normalizedSearch = search.toLowerCase().trim();

    return apiPlayers
      .filter((player) => {
        const matchesPosition =
          position === "ALL" || player.position === position;

        const searchableText =
          `${player.name} ${player.team} ${player.opponent}`.toLowerCase();

        const matchesSearch =
          searchableText.includes(normalizedSearch);

        return matchesPosition && matchesSearch;
      })
      .sort((a, b) => {
        if (sortBy === "probability") {
          return b.probability - a.probability;
        }

        return b.score - a.score;
      });
  }, [apiPlayers, position, search, sortBy]);

  const averageEstimate =
    players.length > 0
      ? players.reduce(
          (total, player) => total + player.probability,
          0,
        ) / players.length
      : 0;

  const topPlayer = players.length > 0 ? players[0] : null;

  const highEstimateCount = players.filter(
    (player) => player.probability >= 40,
  ).length;

  return (
    <main className="min-h-screen bg-[#090b0a] text-white">
      <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8 lg:px-10">
        {/* Header */}
        <header className="flex flex-col justify-between gap-5 border-b border-white/10 pb-8 md:flex-row md:items-center">
          <div>
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-400 text-lg font-black text-black">
                TD
              </div>

              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.25em] text-emerald-400">
                  Football Analytics
                </p>

                <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">
                  TD Likelihood Predictor
                </h1>
              </div>
            </div>

            <p className="mt-4 max-w-2xl text-sm leading-6 text-zinc-400">
              Analyze player touchdown potential using opportunity,
              scoring trends, matchup information, and team environment.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3">
              <p className="text-xs text-zinc-500">Season</p>
              <p className="mt-1 font-semibold">2026 NFL</p>
            </div>

            <label className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3">
              <span className="block text-xs text-zinc-500">
                Select week
              </span>

              <select
                value={selectedWeek}
                onChange={(event) =>
                  setSelectedWeek(event.target.value)
                }
                className="mt-1 bg-transparent text-sm font-semibold text-white outline-none"
              >
                {Array.from(
                  { length: 18 },
                  (_, index) => index + 1,
                ).map((week) => (
                  <option
                    key={week}
                    value={`Week ${week}`}
                    className="bg-zinc-900"
                  >
                    Week {week}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </header>

        {/* API status */}
        <section className="mt-8 rounded-2xl border border-white/10 bg-white/[0.03] p-4">
          <div className="flex items-start gap-3">
            <div
              className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${
                loading
                  ? "animate-pulse bg-amber-400"
                  : apiError
                    ? "bg-red-400"
                    : "bg-emerald-400"
              }`}
            />

            <div className="min-w-0">
              <p className="text-sm font-semibold text-white">
                {loading
                  ? "Loading predictions..."
                  : apiError
                    ? "Prediction API unavailable"
                    : "Connected to prediction API"}
              </p>

              <p className="mt-1 text-sm leading-6 text-zinc-400">
                {loading
                  ? `Retrieving 2026 ${selectedWeek} player rankings from your Python model.`
                  : apiError
                    ? apiError
                    : `${apiNotice} Data is supplied by your existing Python prediction engine.`}
              </p>

              {apiError && (
                <button
                  onClick={() => {
                    setSelectedWeek((current) => current);
                  }}
                  className="mt-3 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-zinc-300 transition hover:bg-white/[0.06]"
                >
                  Check connection
                </button>
              )}
            </div>
          </div>
        </section>

        {/* Summary cards */}
        <section className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <SummaryCard
            label="Players displayed"
            value={String(players.length)}
            detail="Based on your current filters"
          />

          <SummaryCard
            label="Average TD estimate"
            value={`${averageEstimate.toFixed(1)}%`}
            detail="Average of the displayed model estimates"
          />

          <SummaryCard
            label="Highest-rated player"
            value={topPlayer ? topPlayer.name : loading ? "Loading..." : "No results"}
            detail={
              topPlayer
                ? `${topPlayer.team} vs. ${topPlayer.opponent}`
                : "Try another week or search"
            }
          />

          <SummaryCard
            label="40%+ TD estimate"
            value={String(highEstimateCount)}
            detail="Model estimates at or above 40%"
          />
        </section>

        {/* Rankings */}
        <section className="mt-10">
          <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-emerald-400">
                Prediction board
              </p>

              <h2 className="mt-2 text-2xl font-bold tracking-tight">
                Player rankings
              </h2>

              <p className="mt-2 text-sm text-zinc-400">
                Compare model-generated touchdown estimates across
                quarterbacks, running backs, wide receivers, and tight ends.
              </p>
            </div>

            <div className="text-sm text-zinc-500">
              Showing {players.length} players
            </div>
          </div>

          {/* Filters */}
          <div className="mt-6 flex flex-col gap-4 rounded-2xl border border-white/10 bg-white/[0.03] p-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap gap-2">
              {positionOptions.map((option) => {
                const isActive = position === option;

                return (
                  <button
                    key={option}
                    onClick={() => setPosition(option)}
                    className={
                      "rounded-lg px-4 py-2 text-sm font-semibold transition " +
                      (isActive
                        ? "bg-emerald-400 text-black"
                        : "border border-white/10 bg-white/[0.03] text-zinc-400 hover:bg-white/[0.08] hover:text-white")
                    }
                  >
                    {option === "ALL" ? "All Players" : option}
                  </button>
                );
              })}
            </div>

            <div className="flex flex-col gap-3 sm:flex-row">
              <input
                type="text"
                placeholder="Search player or team..."
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="min-w-0 rounded-lg border border-white/10 bg-black/30 px-4 py-2.5 text-sm text-white outline-none placeholder:text-zinc-600 focus:border-emerald-400/50 sm:w-64"
              />

              <select
                value={sortBy}
                onChange={(event) =>
                  setSortBy(event.target.value as SortOption)
                }
                className="rounded-lg border border-white/10 bg-[#111412] px-4 py-2.5 text-sm text-white outline-none"
              >
                <option value="probability">
                  Sort: TD estimate
                </option>

                <option value="score">
                  Sort: Predictor score
                </option>
              </select>
            </div>
          </div>

          {/* Player table */}
          <div className="mt-4 overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02]">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[950px] text-left text-sm">
                <thead className="border-b border-white/10 bg-white/[0.03] text-xs uppercase tracking-wider text-zinc-500">
                  <tr>
                    <th className="px-5 py-4 font-medium">
                      Rank / Player
                    </th>

                    <th className="px-5 py-4 font-medium">
                      Position
                    </th>

                    <th className="px-5 py-4 font-medium">
                      Matchup
                    </th>

                    <th className="px-5 py-4 font-medium">
                      TD estimate
                    </th>

                    <th className="px-5 py-4 font-medium">
                      Model score
                    </th>

                    <th className="px-5 py-4 font-medium">
                      Season TDs
                    </th>

                    <th className="px-5 py-4 font-medium">
                      Opportunities / game
                    </th>
                  </tr>
                </thead>

                <tbody className="divide-y divide-white/[0.07]">
                  {players.map((player, index) => (
                    <tr
                      key={`${player.name}-${player.team}`}
                      className="transition hover:bg-white/[0.035]"
                    >
                      {/* Player */}
                      <td className="px-5 py-5">
                        <div className="flex items-center gap-3">
                          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-xs font-bold text-zinc-400">
                            {String(index + 1).padStart(2, "0")}
                          </div>

                          <div>
                            <p className="font-semibold text-white">
                              {player.name}
                            </p>

                            <p className="mt-1 text-xs text-zinc-500">
                              {player.team}
                            </p>
                          </div>
                        </div>
                      </td>

                      {/* Position */}
                      <td className="px-5 py-5">
                        <span
                          className={
                            "rounded-md border px-2.5 py-1 text-xs font-semibold " +
                            getPositionStyle(player.position)
                          }
                        >
                          {player.position}
                        </span>
                      </td>

                      {/* Matchup */}
                      <td className="px-5 py-5">
                        <div className="font-medium text-zinc-200">
                          {player.team} vs. {player.opponent}
                        </div>

                        <div className="mt-1 text-xs text-zinc-500">
                          {player.matchup} matchup
                        </div>

                        {player.gameStatus !== "Unknown" && (
                          <div className="mt-1 text-xs text-zinc-600">
                            {player.gameStatus}
                          </div>
                        )}
                      </td>

                      {/* TD estimate */}
                      <td className="px-5 py-5">
                        <div
                          className={
                            "text-lg font-bold " +
                            getProbabilityStyle(player.probability)
                          }
                        >
                          {player.probability.toFixed(1)}%
                        </div>

                        <div className="mt-2 h-1.5 w-28 overflow-hidden rounded-full bg-white/10">
                          <div
                            className="h-full rounded-full bg-emerald-400"
                            style={{
                              width:
                                Math.min(
                                  100,
                                  Math.max(0, player.probability),
                                ) + "%",
                            }}
                          />
                        </div>
                      </td>

                      {/* Model score */}
                      <td className="px-5 py-5">
                        <span className="font-semibold text-zinc-200">
                          {player.score.toFixed(1)}
                        </span>

                        <span className="text-zinc-600"> / 100</span>
                      </td>

                      {/* Season TDs */}
                      <td className="px-5 py-5 text-zinc-300">
                        {player.seasonTDs}
                      </td>

                      {/* Opportunities per game */}
                      <td className="px-5 py-5 text-zinc-300">
                        {player.opportunities.toFixed(1)}
                      </td>
                    </tr>
                  ))}

                  {!loading && players.length === 0 && (
                    <tr>
                      <td
                        colSpan={7}
                        className="px-5 py-12 text-center text-zinc-500"
                      >
                        {apiError
                          ? "Predictions could not be loaded. Check that your Python API is running."
                          : "No players match your search. Try another player, team, or position."}
                      </td>
                    </tr>
                  )}

                  {loading && (
                    <tr>
                      <td
                        colSpan={7}
                        className="px-5 py-12 text-center text-zinc-400"
                      >
                        Loading player rankings from your prediction model...
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <p className="mt-4 text-xs leading-5 text-zinc-600">
            TD estimates are generated by your existing prediction model.
            They are not guaranteed outcomes or necessarily calibrated
            probabilities. Historical results and completed games may be
            included depending on the selected week and the data available
            to the model.
          </p>
        </section>

        {/* Footer */}
        <footer className="mt-12 flex flex-col justify-between gap-3 border-t border-white/10 pt-6 text-xs text-zinc-600 sm:flex-row">
          <p>TD Likelihood Predictor · 2026 Season</p>

          <p>Built for football analytics</p>
        </footer>
      </div>
    </main>
  );
}