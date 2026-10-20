"use client";

import { useMemo, useState } from "react";

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
  recentTDs: number;
  opportunities: number;
  matchup: string;
};

const demoPlayers: Player[] = [
  {
    name: "Josh Allen",
    team: "BUF",
    opponent: "KC",
    position: "QB",
    score: 94.8,
    probability: 62.4,
    recentTDs: 4,
    opportunities: 12,
    matchup: "Favorable",
  },
  {
    name: "Saquon Barkley",
    team: "PHI",
    opponent: "DAL",
    position: "RB",
    score: 92.1,
    probability: 58.7,
    recentTDs: 3,
    opportunities: 21,
    matchup: "Favorable",
  },
  {
    name: "Jahmyr Gibbs",
    team: "DET",
    opponent: "BUF",
    position: "RB",
    score: 90.5,
    probability: 55.2,
    recentTDs: 3,
    opportunities: 18,
    matchup: "Favorable",
  },
  {
    name: "Ja'Marr Chase",
    team: "CIN",
    opponent: "BAL",
    position: "WR",
    score: 88.9,
    probability: 49.6,
    recentTDs: 2,
    opportunities: 11,
    matchup: "Neutral",
  },
  {
    name: "Lamar Jackson",
    team: "BAL",
    opponent: "CIN",
    position: "QB",
    score: 87.6,
    probability: 47.8,
    recentTDs: 3,
    opportunities: 10,
    matchup: "Neutral",
  },
  {
    name: "Derrick Henry",
    team: "BAL",
    opponent: "CIN",
    position: "RB",
    score: 86.2,
    probability: 45.9,
    recentTDs: 3,
    opportunities: 17,
    matchup: "Neutral",
  },
  {
    name: "Amon-Ra St. Brown",
    team: "DET",
    opponent: "BUF",
    position: "WR",
    score: 84.7,
    probability: 42.3,
    recentTDs: 2,
    opportunities: 10,
    matchup: "Neutral",
  },
  {
    name: "Travis Kelce",
    team: "KC",
    opponent: "BUF",
    position: "TE",
    score: 81.3,
    probability: 36.8,
    recentTDs: 1,
    opportunities: 8,
    matchup: "Difficult",
  },
];

const positionOptions: PositionFilter[] = ["ALL", "QB", "RB", "WR", "TE"];

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
  switch (position) {
    case "QB":
      return "bg-purple-500/15 text-purple-300 border-purple-500/20";
    case "RB":
      return "bg-emerald-500/15 text-emerald-300 border-emerald-500/20";
    case "WR":
      return "bg-sky-500/15 text-sky-300 border-sky-500/20";
    case "TE":
      return "bg-amber-500/15 text-amber-300 border-amber-500/20";
    default:
      return "bg-zinc-500/15 text-zinc-300 border-zinc-500/20";
  }
}

function getProbabilityStyle(probability: number) {
  if (probability >= 50) {
    return "text-emerald-300";
  }

  if (probability >= 35) {
    return "text-lime-300";
  }

  if (probability >= 20) {
    return "text-amber-300";
  }

  return "text-zinc-300";
}

export default function Home() {
  const [position, setPosition] = useState<PositionFilter>("ALL");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<SortOption>("probability");
  const [selectedWeek, setSelectedWeek] = useState("Week 1");

  const players = useMemo(() => {
    const normalizedSearch = search.toLowerCase().trim();

    return demoPlayers
      .filter((player) => {
        const matchesPosition =
          position === "ALL" || player.position === position;

        const searchableText =
          player.name + " " + player.team + " " + player.opponent;

        const matchesSearch = searchableText
          .toLowerCase()
          .includes(normalizedSearch);

        return matchesPosition && matchesSearch;
      })
      .sort((a, b) => {
        if (sortBy === "probability") {
          return b.probability - a.probability;
        }

        return b.score - a.score;
      });
  }, [position, search, sortBy]);

  const averageProbability =
    players.length > 0
      ? players.reduce((total, player) => total + player.probability, 0) /
        players.length
      : 0;

  const topPlayer = players.length > 0 ? players[0] : null;

  const highProbabilityCount = players.filter(
    (player) => player.probability >= 40,
  ).length;

  return (
    <main className="min-h-screen bg-[#090b0a] text-white">
      <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8 lg:px-10">
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
              Analyze player touchdown potential using opportunity, scoring
              trends, matchup information, and team environment.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3">
              <p className="text-xs text-zinc-500">Season</p>
              <p className="mt-1 font-semibold">2026 NFL</p>
            </div>

            <label className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3">
              <span className="block text-xs text-zinc-500">Select week</span>

              <select
                value={selectedWeek}
                onChange={(event) => setSelectedWeek(event.target.value)}
                className="mt-1 bg-transparent text-sm font-semibold text-white outline-none"
              >
                {Array.from({ length: 18 }, (_, index) => index + 1).map(
                  (week) => (
                    <option
                      key={week}
                      value={"Week " + week}
                      className="bg-zinc-900"
                    >
                      Week {week}
                    </option>
                  ),
                )}
              </select>
            </label>
          </div>
        </header>

        <section className="mt-8 rounded-2xl border border-amber-400/20 bg-amber-400/[0.06] p-4">
          <div className="flex gap-3">
            <div className="mt-0.5 text-amber-300">ⓘ</div>

            <div>
              <p className="text-sm font-semibold text-amber-200">
                Frontend preview — sample data
              </p>

              <p className="mt-1 text-sm leading-6 text-zinc-400">
                These numbers are placeholders to test the website interface.
                They are not live predictions or verified 2026 statistics.
                The next step is connecting your existing Python prediction
                model.
              </p>
            </div>
          </div>
        </section>

        <section className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <SummaryCard
            label="Players displayed"
            value={String(players.length)}
            detail="Based on your current filters"
          />

          <SummaryCard
            label="Average TD probability"
            value={averageProbability.toFixed(1) + "%"}
            detail="Across sample players"
          />

          <SummaryCard
            label="Highest-rated player"
            value={topPlayer ? topPlayer.name : "No results"}
            detail={
              topPlayer
                ? topPlayer.team + " vs. " + topPlayer.opponent
                : "Try another search"
            }
          />

          <SummaryCard
            label="40%+ TD probability"
            value={String(highProbabilityCount)}
            detail="Sample players at or above 40%"
          />
        </section>

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
                Compare projected touchdown probabilities across positions.
              </p>
            </div>

            <div className="text-sm text-zinc-500">
              Showing {players.length} players
            </div>
          </div>

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
                <option value="probability">Sort: TD probability</option>
                <option value="score">Sort: Predictor score</option>
              </select>
            </div>
          </div>

          <div className="mt-4 overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02]">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[850px] text-left text-sm">
                <thead className="border-b border-white/10 bg-white/[0.03] text-xs uppercase tracking-wider text-zinc-500">
                  <tr>
                    <th className="px-5 py-4 font-medium">Rank / Player</th>
                    <th className="px-5 py-4 font-medium">Position</th>
                    <th className="px-5 py-4 font-medium">Matchup</th>
                    <th className="px-5 py-4 font-medium">TD probability</th>
                    <th className="px-5 py-4 font-medium">Model score</th>
                    <th className="px-5 py-4 font-medium">Recent TDs</th>
                    <th className="px-5 py-4 font-medium">Opportunities</th>
                  </tr>
                </thead>

                <tbody className="divide-y divide-white/[0.07]">
                  {players.map((player, index) => (
                    <tr
                      key={player.name}
                      className="transition hover:bg-white/[0.035]"
                    >
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

                      <td className="px-5 py-5">
                        <div className="font-medium text-zinc-200">
                          {player.team} vs. {player.opponent}
                        </div>

                        <div className="mt-1 text-xs text-zinc-500">
                          {player.matchup} matchup
                        </div>
                      </td>

                      <td className="px-5 py-5">
                        <div
                          className={
                            "text-lg font-bold " +
                            getProbabilityStyle(player.probability)
                          }
                        >
                          {player.probability.toFixed(1) + "%"}
                        </div>

                        <div className="mt-2 h-1.5 w-28 overflow-hidden rounded-full bg-white/10">
                          <div
                            className="h-full rounded-full bg-emerald-400"
                            style={{
                              width: Math.min(
                                100,
                                Math.max(0, player.probability),
                              ) + "%",
                            }}
                          />
                        </div>
                      </td>

                      <td className="px-5 py-5">
                        <span className="font-semibold text-zinc-200">
                          {player.score.toFixed(1)}
                        </span>
                        <span className="text-zinc-600"> / 100</span>
                      </td>

                      <td className="px-5 py-5 text-zinc-300">
                        {player.recentTDs}
                      </td>

                      <td className="px-5 py-5 text-zinc-300">
                        {player.opportunities}
                      </td>
                    </tr>
                  ))}

                  {players.length === 0 && (
                    <tr>
                      <td
                        colSpan={7}
                        className="px-5 py-12 text-center text-zinc-500"
                      >
                        No players match your search. Try another player,
                        team, or position.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <p className="mt-4 text-xs leading-5 text-zinc-600">
            TD Likelihood Predictor is being developed. Sample probabilities
            are for interface testing only and should not be used for betting
            or real-world predictions.
          </p>
        </section>

        <footer className="mt-12 flex flex-col justify-between gap-3 border-t border-white/10 pt-6 text-xs text-zinc-600 sm:flex-row">
          <p>TD Likelihood Predictor · 2026 Season</p>
          <p>Built for football analytics</p>
        </footer>
      </div>
    </main>
  );
}