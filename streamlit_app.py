import streamlit as st
import pandas as pd
from td_predictor_v5 import (
    get_predictions, POSITIONS, build_matchups, load_schedule,
    load_multi_season_stats, find_player_matches, player_vs_opponent_report,
    parlay_probability, auto_build_parlay,
)
from team_names import TEAM_NAMES

st.set_page_config(page_title="TD Likelihood Predictor", layout="wide")

st.title("🏈 TD Likelihood Predictor")
st.caption("Pure stats-based touchdown likelihood scoring — no odds, no market data.")

# --- Controls (shared by both tabs) --------------------------------------
col1, col2 = st.columns(2)
with col1:
    season = st.number_input("Season", min_value=2020, max_value=2030, value=2026, step=1)
with col2:
    week = st.number_input("Week", min_value=1, max_value=18, value=1, step=1)

run = st.button("Run predictions", type="primary", use_container_width=True)

if run:
    status_box = st.empty()

    def report(msg):
        status_box.info(msg)

    try:
        with st.spinner("Crunching numbers..."):
            scored, matchups = get_predictions(int(season), int(week), status_callback=report)
        status_box.empty()
        st.session_state["scored"] = scored
        st.session_state["matchups"] = matchups
    except Exception as e:
        status_box.empty()
        st.error(f"Something went wrong: {e}")

tab_rankings, tab_lookup, tab_parlay, tab_market = st.tabs(
    ["📊 Weekly Rankings", "🔎 Player Lookup", "🎯 Parlay Builder", "📈 Market Check"]
)

# ===========================================================================
# TAB 1 — Weekly rankings
# ===========================================================================
with tab_rankings:
    # Filters now render immediately, using the full 32-team list, instead
    # of waiting on a run to know which teams exist. Selecting a team that
    # isn't playing this week just returns an empty table once you do run.
    all_team_labels = sorted(f"{name} ({code})" for code, name in TEAM_NAMES.items())
    team_labels = st.multiselect(
        "Filter to team(s) — leave blank to show everyone",
        options=all_team_labels,
        key="rankings_team_filter",
    )
    pos_choice = st.multiselect(
        "Position", sorted(POSITIONS), default=sorted(POSITIONS), key="rankings_pos_filter"
    )

    if "scored" not in st.session_state:
        st.info("Hit **Run predictions** above to load this week's board.")
    else:
        scored = st.session_state["scored"]

        if team_labels:
            wanted = {label.split("(")[-1].rstrip(")") for label in team_labels}
            view = scored[scored["team"].isin(wanted)].sort_values("td_score", ascending=False)
            st.subheader("Filtered: " + ", ".join(sorted(wanted)))
        else:
            view = scored
            st.subheader(f"Week {week}, {season} — Full board")

        view = view[view["position"].isin(pos_choice)]

        if view.empty:
            st.warning("No players match this filter. Try a different team or position.")
        else:
            # Only upcoming games get featured in the callout cards/chart --
            # no point spotlighting someone whose game already happened.
            upcoming_view = view[view["game_status"] != "Final"]
            played_count = len(view) - len(upcoming_view)
            if played_count:
                st.caption(f"ℹ️ {played_count} player(s) from already-completed games this week "
                           f"are excluded from the highlights below, but still visible in the "
                           f"full table (sorted to the bottom, marked ✅ Final).")

            if upcoming_view.empty:
                st.info("All games matching this filter have already been played this week.")
            else:
                # Top-3 callout cards -- an at-a-glance headline instead of
                # having to scan the table for the top rows every time.
                top3 = upcoming_view.nlargest(3, "td_score").reset_index(drop=True)
                medal = ["🥇", "🥈", "🥉"]
                cols = st.columns(len(top3))
                for i, col in enumerate(cols):
                    row = top3.iloc[i]
                    with col:
                        st.metric(
                            f"{medal[i]} {row['player']}",
                            f"{row['td_estimate']:.1f}%",
                            f"{row['team']} vs {row['opponent']}",
                        )

                # Quick visual bar chart of the top 15 -- easier to eyeball
                # relative separation between players than scanning numbers.
                chart_data = upcoming_view.nlargest(15, "td_score").set_index("player")["td_score"]
                st.bar_chart(chart_data, horizontal=True)

            display_cols = ["player", "team", "position", "opponent", "game_status", "td_score", "td_estimate", "games", "injury_status"]
            display_df = view[display_cols].rename(columns={
                "player": "Player", "team": "Team", "position": "Pos",
                "opponent": "Opp", "game_status": "Game", "td_score": "Score", "td_estimate": "Est. TD%",
                "games": "Sample", "injury_status": "Status",
            }).reset_index(drop=True)
            display_df["Game"] = display_df["Game"].apply(
                lambda g: "✅ Final" if g == "Final" else "Upcoming"
            )
            display_df["Sample"] = display_df["Sample"].apply(
                lambda g: "🆕 No history" if g == 0 else f"{g} games"
            )
            display_df.index = display_df.index + 1

            st.dataframe(
                display_df.style
                .background_gradient(subset=["Score"], cmap="RdYlGn", vmin=0, vmax=100)
                .format({"Score": "{:.1f}", "Est. TD%": "{:.1f}%"}),
                use_container_width=True,
                height=min(600, 45 * (len(display_df) + 1)),
            )

            st.caption("Est. TD% is calibrated against real 2025-season outcomes (see backtest.py), "
                       "not a sportsbook probability. 🆕 No history = rookie or player with zero games "
                       "in the sample — shown for visibility, but the score reflects team/matchup "
                       "context only, not personal usage.")

            csv = view.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV", csv, f"td_scores_{season}_week{week}.csv", "text/csv")

# ===========================================================================
# TAB 2 — Player lookup: search a name, see history vs. this week's opponent
#
# Works independently of "Run predictions" above -- it only needs the
# schedule for the chosen season/week (a light lookup) to know each
# player's opponent, not the full model run.
# ===========================================================================
with tab_lookup:
    st.caption(
        "Team-level history only — free public data doesn't include which specific "
        "cornerback/safety covered a player on a given play. That data is either "
        "PFF-paywalled or comes from one-off beat-reporter charting."
    )

    lookback = st.slider("Seasons of history to search", min_value=1, max_value=6, value=4)
    query = st.text_input("Player name", placeholder="e.g. Jaxon Smith-Njigba")

    if query.strip():
        seasons_to_load = list(range(int(season) - lookback + 1, int(season) + 1))
        with st.spinner(f"Searching {seasons_to_load[0]}–{seasons_to_load[-1]}..."):
            history_stats = load_multi_season_stats(seasons_to_load)
            candidates = find_player_matches(history_stats, query)
            schedule = load_schedule(int(season))
            week_matchups = build_matchups(schedule, int(season), int(week))

        if candidates.empty:
            st.warning("No players matched that name in the loaded seasons.")
        else:
            choice = st.selectbox(
                "Select player" if len(candidates) > 1 else "Match",
                options=candidates["player_id"].tolist(),
                format_func=lambda pid: candidates.loc[
                    candidates["player_id"] == pid, "player_display_name"
                ].iloc[0],
            )

            chosen_name = candidates.loc[candidates["player_id"] == choice, "player_display_name"].iloc[0]

            # Prefer the fully-resolved current team from a completed model
            # run if one's available (handles offseason trades correctly);
            # otherwise fall back to their most recent team in the stats.
            team = None
            if "scored" in st.session_state:
                current_row = st.session_state["scored"][
                    st.session_state["scored"]["player_id"].astype(str) == str(choice)
                ]
                if not current_row.empty:
                    team = current_row["team"].iloc[0]

            if team is None:
                player_rows = history_stats[history_stats["player_id"].astype(str) == str(choice)]
                if not player_rows.empty and "team" in player_rows.columns:
                    team = player_rows.sort_values(["season", "week"])["team"].iloc[-1]

            opponent = week_matchups.get(team) if team else None

            st.subheader(
                f"{chosen_name} — {team or '?'} vs "
                f"{TEAM_NAMES.get(opponent, opponent) if opponent else '?'} "
                f"({opponent or 'unknown matchup'})"
            )

            if "scored" in st.session_state:
                current_row = st.session_state["scored"][
                    st.session_state["scored"]["player_id"].astype(str) == str(choice)
                ]
                if not current_row.empty:
                    m1, m2 = st.columns(2)
                    m1.metric("This week's TD Score", f"{current_row['td_score'].iloc[0]:.1f}")
                    m2.metric("Est. TD%", f"{current_row['td_estimate'].iloc[0]:.1f}%")
                else:
                    st.caption("This player isn't in this week's scored model run "
                               "(not on an active roster this week, or filtered out) — "
                               "showing history only, no current TD Score/Est. TD%.")
            else:
                st.caption("💡 Hit **Run predictions** above (in this same session/device) "
                           "to also see this week's TD Score and Est. TD% here. "
                           "Session data doesn't carry over between devices or browser tabs — "
                           "each one needs its own run.")

            if not opponent:
                st.info("Couldn't resolve this player's opponent for the selected week — "
                         "either they're not on an active roster for that week's games, "
                         "or the schedule hasn't been finalized yet.")
            else:
                report_data = player_vs_opponent_report(history_stats, choice, opponent)

                if report_data is None:
                    st.info("No stat history found for this player in the loaded seasons "
                             "(likely a rookie or very limited playing time).")
                else:
                    st.markdown(f"### History vs. {TEAM_NAMES.get(opponent, opponent)}")
                    vs_opp = report_data["vs_opponent_games"]
                    if vs_opp.empty:
                        st.info(f"No games found against {opponent} in the last {lookback} season(s).")
                    else:
                        vs_display = vs_opp[["season", "week", "targets", "carries", "receptions",
                                              "receiving_yards", "rushing_yards", "tds"]].rename(columns={
                            "season": "Season", "week": "Wk", "targets": "Tgt", "carries": "Car",
                            "receptions": "Rec", "receiving_yards": "Rec Yds", "rushing_yards": "Rush Yds",
                            "tds": "TD",
                        })
                        st.dataframe(vs_display, use_container_width=True, hide_index=True)
                        totals = vs_opp[["targets", "carries", "receptions", "receiving_yards",
                                          "rushing_yards", "tds"]].sum()
                        st.caption(f"Totals vs. {opponent}: {int(totals['targets'])} tgt, "
                                   f"{int(totals['carries'])} car, {int(totals['receptions'])} rec, "
                                   f"{int(totals['receiving_yards'])} rec yds, "
                                   f"{int(totals['rushing_yards'])} rush yds, {int(totals['tds'])} TD "
                                   f"across {len(vs_opp)} game(s).")

                    st.markdown("### Recent form (last 5 games, any opponent)")
                    recent = report_data["recent_games"]
                    recent_display = recent[["season", "week", "opponent_team", "targets", "carries",
                                              "receptions", "receiving_yards", "rushing_yards", "tds"]].rename(columns={
                        "season": "Season", "week": "Wk", "opponent_team": "Opp", "targets": "Tgt",
                        "carries": "Car", "receptions": "Rec", "receiving_yards": "Rec Yds",
                        "rushing_yards": "Rush Yds", "tds": "TD",
                    })
                    st.dataframe(recent_display, use_container_width=True, hide_index=True)

# ===========================================================================
# TAB 3 — Parlay Builder
#
# Two modes: check a parlay you already picked, or let the model suggest
# the highest-TRUE-PROBABILITY combination. Neither mode knows anything
# about payout odds -- see the caveats in td_predictor_v5.parlay_probability.
# ===========================================================================
with tab_parlay:
    st.warning(
        "**This gives a statistical probability, not betting advice.** It tells you how "
        "likely a parlay is to hit based on stats — it does NOT know the sportsbook's "
        "payout for that parlay, so it can't tell you if it's a good bet. A likely parlay "
        "at bad odds can still be a bad bet, and vice versa. You supply that judgment."
    )

    if "scored" not in st.session_state:
        st.info("Hit **Run predictions** above (Weekly Rankings tab) first — the parlay "
                 "builder uses that week's scored board.")
    else:
        scored = st.session_state["scored"]
        sub_manual, sub_auto = st.tabs(["Build your own", "Auto-build for me"])

        # --- Manual parlay check -----------------------------------------
        with sub_manual:
            options = scored[scored["game_status"] != "Final"].sort_values("td_score", ascending=False)
            label_map = {
                row["player_id"]: f"{row['player']} ({row['team']} vs {row['opponent']}) — {row['td_estimate']:.1f}%"
                for _, row in options.iterrows()
            }
            picks = st.multiselect(
                "Pick your legs (2-6 players)",
                options=list(label_map.keys()),
                format_func=lambda pid: label_map[pid],
                max_selections=6,
            )

            if len(picks) >= 2:
                try:
                    result = parlay_probability(scored, picks)
                    m1, m2 = st.columns(2)
                    m1.metric("Combined probability (all legs hit)",
                              f"{result['combined_probability_pct']:.2f}%")
                    m2.metric("Volatility", result["volatility"])
                    if result["same_team_warning"]:
                        st.warning("⚠️ Two or more legs share the same team. Red-zone "
                                   "chances within one game are a limited shared resource, "
                                   "so the real combined probability is likely a bit LOWER "
                                   "than the number above — this multiplication assumes "
                                   "independence, which doesn't fully hold for teammates.")
                    legs_df = pd.DataFrame(result["legs"]).rename(columns={
                        "player": "Player", "team": "Team", "opponent": "Opp",
                        "probability_pct": "Est. TD%",
                    })
                    st.dataframe(legs_df, use_container_width=True, hide_index=True)
                except ValueError as e:
                    st.error(str(e))
            elif len(picks) == 1:
                st.info("Pick at least one more leg to see a combined probability.")

        # --- Auto-build -----------------------------------------------------
        with sub_auto:
            n_legs = st.slider("Number of legs", min_value=2, max_value=6, value=3)
            one_per_team = st.checkbox(
                "Avoid same-team legs (recommended)", value=True,
                help="Keeps legs closer to statistically independent, so the combined "
                     "probability is more trustworthy. Uncheck to allow teammates, but "
                     "expect the combined number to be somewhat optimistic in that case."
            )

            if st.button("Suggest a parlay", use_container_width=True):
                try:
                    result = auto_build_parlay(scored, n_legs=n_legs, one_per_team=one_per_team)
                    m1, m2 = st.columns(2)
                    m1.metric("Combined probability (all legs hit)",
                              f"{result['combined_probability_pct']:.2f}%")
                    m2.metric("Volatility", result["volatility"])
                    if result["same_team_warning"]:
                        st.warning("⚠️ This suggestion includes same-team legs — see the "
                                   "note in 'Build your own' about why that overstates the "
                                   "combined probability somewhat.")
                    legs_df = pd.DataFrame(result["legs"]).rename(columns={
                        "player": "Player", "team": "Team", "opponent": "Opp",
                        "probability_pct": "Est. TD%",
                    })
                    st.dataframe(legs_df, use_container_width=True, hide_index=True)
                    st.caption("This is the highest TRUE PROBABILITY combination available "
                               "this week per the model — not necessarily the best-value bet.")
                except RuntimeError as e:
                    st.error(str(e))

# ===========================================================================
# TAB 4 — Market Check
#
# Pure read-only comparison. The "model" side is exactly the same
# td_estimate the honest model already produced -- nothing recomputed,
# nothing fed back into WEIGHTS or the model file. The "market" side is
# just odds-to-probability math on numbers YOU type in (no scraping, no
# API pull) -- you're the one supplying the market data, on purpose.
# ===========================================================================

def american_odds_to_implied_pct(odds_str):
    """
    Standard sportsbook odds -> implied probability conversion.
    +150 means bet $100 to win $150 (underdog); -150 means bet $150 to
    win $100 (favorite). This does NOT remove the sportsbook's vig, so
    it reflects "what the market is effectively pricing," not a pure
    objective probability.
    """
    s = odds_str.strip().replace("+", "")
    try:
        odds = float(s)
    except ValueError:
        return None
    if odds > 0:
        return 100.0 / (odds + 100.0) * 100.0
    else:
        return (-odds) / ((-odds) + 100.0) * 100.0


with tab_market:
    st.warning(
        "**No live odds are pulled automatically** — no free/legal source exists for that "
        "(see earlier discussion: sportsbook APIs aren't public, and scraping violates "
        "their terms). You type in the odds you're seeing yourself; this just does the "
        "implied-probability math and puts it next to your model's number."
    )

    if "scored" not in st.session_state:
        st.info("Hit **Run predictions** above (Weekly Rankings tab) first.")
    else:
        scored = st.session_state["scored"]

        if "market_comparisons" not in st.session_state:
            st.session_state["market_comparisons"] = []

        st.markdown("#### Add a player + the odds you're seeing")
        options = scored[scored["game_status"] != "Final"].sort_values("td_score", ascending=False)
        label_map = {
            row["player_id"]: f"{row['player']} ({row['team']} vs {row['opponent']}) — Model: {row['td_estimate']:.1f}%"
            for _, row in options.iterrows()
        }

        c1, c2, c3 = st.columns([3, 1, 1])
        with c1:
            picked_id = st.selectbox(
                "Player", options=list(label_map.keys()), format_func=lambda pid: label_map[pid]
            )
        with c2:
            odds_input = st.text_input("Anytime TD odds", placeholder="e.g. +150 or -120")
        with c3:
            st.write("")
            st.write("")
            add_clicked = st.button("Add", use_container_width=True)

        if add_clicked:
            implied = american_odds_to_implied_pct(odds_input) if odds_input else None
            if implied is None:
                st.error("Couldn't read those odds — use a format like +150 or -120.")
            else:
                row = scored[scored["player_id"] == picked_id].iloc[0]
                st.session_state["market_comparisons"].append({
                    "player": row["player"], "team": row["team"], "opponent": row["opponent"],
                    "model_pct": round(float(row["td_estimate"]), 1),
                    "market_odds": odds_input.strip(),
                    "market_implied_pct": round(implied, 1),
                    "gap_pct": round(float(row["td_estimate"]) - implied, 1),
                })

        if st.session_state["market_comparisons"]:
            comp_df = pd.DataFrame(st.session_state["market_comparisons"]).rename(columns={
                "player": "Player", "team": "Team", "opponent": "Opp",
                "model_pct": "Model Est. TD%", "market_odds": "Market Odds",
                "market_implied_pct": "Market Implied %", "gap_pct": "Model − Market",
            })
            st.dataframe(
                comp_df.style.background_gradient(subset=["Model − Market"], cmap="RdYlGn", vmin=-15, vmax=15),
                use_container_width=True, hide_index=True,
            )
            st.caption(
                "Positive 'Model − Market' = your stats-only model thinks this player is MORE "
                "likely to score than the market is pricing. Negative = the market's more "
                "bullish than your model. Neither side is automatically 'right' — this just "
                "shows you where they disagree so you can apply your own judgment."
            )
            if st.button("Clear comparisons"):
                st.session_state["market_comparisons"] = []
                st.rerun()
        else:
            st.info("Add a player above to start comparing.")