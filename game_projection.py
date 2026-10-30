"""Offline team projections, independent of V5. Event-time historical reconstruction."""
import hashlib
import json
import numpy as np
import pandas as pd
from weekly_schedule import regular_games, kickoff, utc

VERSION = "game-ppp-v1"
FEATURES = ["baseline", "own_ppp", "opponent_ppp_allowed", "expected_plays", "home"]
PBP_COLUMNS = {"game_id", "play_id", "posteam", "defteam", "play_type", "two_point_attempt", "touchdown",
               "td_team", "return_touchdown", "extra_point_result", "two_point_conv_result", "field_goal_result",
               "yardline_100", "drive", "extra_point_attempt", "field_goal_attempt", "desc"}


def prepare_team_games(schedule, pbp):
    """Offensive drive points: rush/pass TDs, their PAT/2pt, and made FGs.

    Return/defensive TDs and their conversions and safeties are excluded.
    Plays: run/pass including sacks/scrambles, excluding kneels/spikes/no-play/2pt.
    """
    if not PBP_COLUMNS.issubset(pbp):
        raise ValueError("Missing play-by-play scoring evidence")
    if pbp.duplicated(["game_id", "play_id"]).any():
        raise ValueError("Duplicate play identity")
    games = [g for g in regular_games(schedule, min_season=2020) if g["complete"]]
    results = []
    groups = {gid:q.sort_values("play_id") for gid,q in pbp.groupby("game_id")}
    for game in games:
        if game["game_id"] not in groups:
            raise ValueError("Missing completed-game play coverage: "+game["game_id"])
        q=groups[game["game_id"]]
        teams={game["home_team"],game["away_team"]}
        if any(r.posteam not in teams or r.defteam not in teams or r.posteam==r.defteam for r in q[q.play_type.isin(["run","pass"])].itertuples()):
            raise ValueError("Play/schedule team mismatch")
        scores={t:0. for t in teams};conversion_team=None
        for r in q.itertuples():
            # Some feeds retain extra_point as play_type on explicitly nullified tries.
            # A source's explicit No Play is not an observed failed kick.
            if r.play_type in ("extra_point", "field_goal") and isinstance(r.desc, str) and "No Play" in r.desc:
                continue
            if r.play_type == "field_goal":
                if r.field_goal_attempt != 1 or r.field_goal_result not in ("made", "missed", "blocked"):
                    raise ValueError("Missing verified field-goal outcome")
            if r.play_type == "extra_point":
                if r.extra_point_attempt == 0 and r.two_point_attempt == 0 and pd.isna(r.extra_point_result):
                    continue
                if r.extra_point_attempt != 1 or r.extra_point_result not in ("good", "failed", "blocked"):
                    raise ValueError("Missing verified extra-point outcome")
            if r.two_point_attempt == 1 and r.two_point_conv_result not in ("success", "failure"):
                raise ValueError("Missing verified two-point outcome")
            if r.play_type in ("run","pass") and r.two_point_attempt==0:
                if r.touchdown not in (0,1) or r.return_touchdown not in (0,1):
                    raise ValueError("Missing touchdown evidence")
                if r.touchdown==1:
                    if r.td_team not in teams:raise ValueError("Missing touchdown team evidence")
                    conversion_team=r.posteam if r.td_team==r.posteam and r.return_touchdown==0 else None
                    if conversion_team:scores[conversion_team]+=6
            elif r.touchdown==1:
                conversion_team=None
            if r.extra_point_result=="good" and conversion_team:
                scores[conversion_team]+=1;conversion_team=None
            if r.two_point_conv_result=="success" and conversion_team:
                scores[conversion_team]+=2;conversion_team=None
            if r.play_type=="kickoff":conversion_team=None
            if r.field_goal_result=="made":
                if r.posteam not in teams:raise ValueError("Field goal team missing")
                scores[r.posteam]+=3;conversion_team=None
        for team,opponent,side in ((game["home_team"],game["away_team"],"home"),(game["away_team"],game["home_team"],"away")):
            plays=q[q.posteam.eq(team)&q.play_type.isin(["run","pass"])&q.two_point_attempt.eq(0)]
            faced=q[q.posteam.eq(opponent)&q.play_type.isin(["run","pass"])&q.two_point_attempt.eq(0)]
            if plays.empty or faced.empty:raise ValueError("Missing team play coverage")
            if not all(v in (0,1) for v in q.loc[q.play_type.isin(["run","pass"]),"two_point_attempt"]):raise ValueError("Missing conversion flags")
            final=float(game[side+"_score"])
            if scores[team]>final:raise ValueError("Offensive points exceed final score")
            drives=plays.dropna(subset=["drive"]).groupby("drive").yardline_100.min()
            results.append(dict(game_id=game["game_id"],season=game["season"],week=game["week"],kickoff_utc=game["kickoff_utc"],
                team=team,opponent=opponent,plays=len(plays),faced=len(faced),off_points=scores[team],allowed_points=scores[opponent],
                final_points=final,rz_drives=int(drives.le(20).sum()),drives=len(drives),home=int(side=="home"),neutral=game.get("location")=="Neutral"))
    return pd.DataFrame(results)


def team_summary(history, team):
    rows=history[history.team.eq(team)].sort_values("kickoff_utc").tail(8)
    if len(rows)<4:return None
    return {"games":len(rows),"game_ids":rows.game_id.tolist(),"last_kickoff_utc":rows.kickoff_utc.max(),
            "offensive_points":float(rows.off_points.sum()),"offensive_plays":int(rows.plays.sum()),
            "allowed_points":float(rows.allowed_points.sum()),"defensive_plays":int(rows.faced.sum()),
            "offensive_ppp":float(rows.off_points.sum()/rows.plays.sum()),
            "defensive_ppp_allowed":float(rows.allowed_points.sum()/rows.faced.sum()),
            "plays_per_game":float(rows.plays.mean()),"plays_faced_per_game":float(rows.faced.mean()),
            "red_zone_drives_per_game":float(rows.rz_drives.mean())}


def project_matchup(team_games, game, cutoff):
    cutoff=utc(cutoff)
    if cutoff>=kickoff(game):raise ValueError("Pregame cutoff must precede kickoff")
    # Prior weeks only: excludes unfinished same-week games and early-release final scores.
    history=team_games[(pd.to_datetime(team_games.kickoff_utc,utc=True)<cutoff)&
                       ((team_games.season<game["season"])|((team_games.season==game["season"])&(team_games.week<game["week"])))]
    history=history[history.season.ge(game["season"]-1)]
    summaries={t:team_summary(history,t) for t in (game["away_team"],game["home_team"])}
    if any(s is None for s in summaries.values()):return None
    result={}
    for team,opponent in ((game["away_team"],game["home_team"]),(game["home_team"],game["away_team"])):
        own,other=summaries[team],summaries[opponent]
        pace=(own["plays_per_game"]+other["plays_faced_per_game"])/2
        ppp=(own["offensive_ppp"]+other["defensive_ppp_allowed"])/2
        baseline=ppp*pace
        home=int(team==game["home_team"] and game.get("location")!="Neutral")
        result[team]={"summary":own,"opponent_defensive_ppp":other["defensive_ppp_allowed"],"expected_plays":pace,
                      "expected_ppp":ppp,"baseline":baseline,"features":[baseline,own["offensive_ppp"],other["defensive_ppp_allowed"],pace,home]}
    return result


def training_rows(team_games, schedule):
    records=[]
    for game in regular_games(schedule, min_season=2020):
        if not game["complete"]:continue
        prediction=project_matchup(team_games,game,kickoff(game)-pd.Timedelta(seconds=1))
        actual=team_games[team_games.game_id.eq(game["game_id"])]
        if prediction is None or len(actual)!=2:continue
        for team,p in prediction.items():
            records.append({"game_id":game["game_id"],"season":game["season"],"week":game["week"],"team":team,
                "home":team==game["home_team"],"kickoff_utc":game["kickoff_utc"],"baseline":p["baseline"],"features":p["features"],
                "actual":float(actual[actual.team.eq(team)].final_points.iloc[0])})
    return records


def fit_adjusted(records, through_season):
    # Fixed ridge penalty; no tuning on held-out seasons. Scaling fits training rows only.
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge
    training=[r for r in records if r["season"]<=through_season]
    if len({r["game_id"] for r in training})<100:raise ValueError("Insufficient independent training games")
    x=np.array([r["features"] for r in training]);y=np.array([r["actual"]-r["baseline"] for r in training])
    model=make_pipeline(StandardScaler(),Ridge(alpha=100.))
    model.fit(x,y)
    scaler,ridge=model.steps[0][1],model.steps[1][1]
    coefficients=(ridge.coef_/scaler.scale_).tolist();intercept=float(ridge.intercept_-np.dot(ridge.coef_/scaler.scale_,scaler.mean_))
    residuals=[r["actual"]-max(0,r["baseline"]+intercept+sum(a*b for a,b in zip(coefficients,r["features"]))) for r in training]
    return {"version":VERSION,"features":FEATURES,"through_season":through_season,"last_training_kickoff":max(r["kickoff_utc"] for r in training),
            "coefficients":coefficients,"intercept":intercept,"residual_quantiles":np.quantile(residuals,[.1,.5,.9]).tolist(),
            "training_games":len(training)//2}


def adjusted(projection, model):
    return max(0.,projection["baseline"]+model["intercept"]+sum(a*b for a,b in zip(projection["features"],model["coefficients"])))


def evaluate(records, model, season):
    rows=[r for r in records if r["season"]==season]
    if season<=model["through_season"]:raise ValueError("Train/test seasons overlap")
    metrics={}
    for method in ("baseline","adjusted"):
        predicted={};errors=[]
        for r in rows:
            value=r["baseline"] if method=="baseline" else adjusted(r,model)
            errors.append(value-r["actual"]);predicted.setdefault(r["game_id"],{})[r["home"]]=(value,r["actual"])
        margins=[];totals=[];wins=[]
        for pair in predicted.values():
            if set(pair)!={True,False}:raise ValueError("Incomplete evaluation game")
            (h,ha),(a,aa)=pair[True],pair[False]
            margins.append((h-a)-(ha-aa));totals.append((h+a)-(ha+aa))
            # Actual ties reported separately; they are not binary wins/losses.
            if ha!=aa:wins.append(int(np.sign(h-a)==np.sign(ha-aa)))
        metrics[method]={"games":len(predicted),"team_scores":len(errors),"score_mae":float(np.mean(np.abs(errors))),"score_rmse":float(np.sqrt(np.mean(np.square(errors)))),
                         "margin_mae":float(np.mean(np.abs(margins))),"total_mae":float(np.mean(np.abs(totals))),"winner_accuracy":float(np.mean(wins)),"winner_games":len(wins)}
    return metrics


def model_fingerprint(model):
    return hashlib.sha256(json.dumps(model,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
