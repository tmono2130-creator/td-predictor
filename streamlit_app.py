import streamlit as st
import pandas as pd
from td_predictor_v5 import (
    get_predictions, POSITIONS, build_matchups, load_schedule,
    load_multi_season_stats, find_player_matches, player_vs_opponent_report,
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

tab_rankings, tab_lookup = st.tabs(["📊 Weekly Rankings", "🔎 Player Lookup"])

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
            display_cols = ["player", "team", "position", "opponent", "td_score", "td_estimate", "games", "injury_status"]
            display_df = view[display_cols].rename(columns={
                "player": "Player", "team": "Team", "position": "Pos",
                "opponent": "Opp", "td_score": "Score", "td_estimate": "Est. TD%",
                "games": "Sample", "injury_status": "Status",
            }).reset_index(drop=True)
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