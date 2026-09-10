import streamlit as st
import pandas as pd
from td_predictor_v5 import get_predictions, POSITIONS
from team_names import TEAM_NAMES

st.set_page_config(page_title="TD Likelihood Predictor", layout="wide")

st.title("🏈 TD Likelihood Predictor")
st.caption("Pure stats-based touchdown likelihood scoring — no odds, no market data.")

# --- Controls -----------------------------------------------------------
col1, col2 = st.columns(2)
with col1:
    season = st.number_input("Season", min_value=2020, max_value=2030, value=2026, step=1)
with col2:
    week = st.number_input("Week", min_value=1, max_value=18, value=1, step=1)

run = st.button("Run predictions", type="primary", use_container_width=True)

# --- Run ------------------------------------------------------------------
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

# --- Display ----------------------------------------------------------
if "scored" in st.session_state:
    scored = st.session_state["scored"]

    # Team filter is now a dropdown built from teams ACTUALLY in this
    # week's results, labeled by full name -- no more guessing whether
    # it's "LA", "LAR", or "RAMS". Fixes the empty-table bug.
    teams_present = sorted(scored["team"].dropna().unique().tolist())
    team_options = {f"{TEAM_NAMES.get(code, code)} ({code})": code for code in teams_present}

    team_labels = st.multiselect(
        "Filter to team(s) — leave blank to show everyone",
        options=sorted(team_options.keys()),
    )

    if team_labels:
        wanted = {team_options[label] for label in team_labels}
        view = scored[scored["team"].isin(wanted)].sort_values("td_score", ascending=False)
        st.subheader("Filtered: " + ", ".join(sorted(wanted)))
    else:
        view = scored
        st.subheader(f"Week {week}, {season} — Full board")

    pos_choice = st.multiselect("Position", sorted(POSITIONS), default=sorted(POSITIONS))
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

        st.caption("Est. TD% is an illustrative model transform, not a calibrated probability. "
                   "🆕 No history = rookie or player with zero games in the sample -- shown for "
                   "visibility, but the score reflects team/matchup context only, not personal usage.")

        csv = view.to_csv(index=False).encode("utf-8")
        st.download_button("Download CSV", csv, f"td_scores_{season}_week{week}.csv", "text/csv")
else:
    st.info("Set your season/week above and hit **Run predictions**.")