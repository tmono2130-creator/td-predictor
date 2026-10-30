"""Versioned optional game projections. No publication writes; strict semantic contract."""
import hashlib
import json
import math
import re
from datetime import datetime,timezone,timedelta
from pathlib import Path
from data_schema import TEAM_CODES
from weekly_schedule import regular_games,kickoff,utc

NAME="game-predictor.json"
HASH="game_predictor_sha256"


def require(ok,message):
    if not ok:raise ValueError(message)


def build_artifact(team_games,schedule,season,week,cutoff,sources,model=None,generated_at=None):
    from game_projection import project_matchup,adjusted,model_fingerprint,VERSION
    cutoff=utc(cutoff);generated=utc(generated_at or datetime.now(timezone.utc))
    target=[g for g in regular_games(schedule,min_season=season,max_season=season) if g["week"]==week]
    require(target,"No scheduled matchup exists")
    require(cutoff<=generated and cutoff<min(kickoff(g) for g in target),"Invalid pregame cutoff")
    # A signed aggregate cannot silently omit completed historical games.
    prior=[g for g in regular_games(schedule,min_season=season-1,max_season=season) if g["complete"] and kickoff(g)<cutoff
           and (g["season"]<season or g["week"]<week)]
    for old in prior:
        rows=team_games[team_games.game_id.eq(old["game_id"])]
        require(len(rows)==2 and set(rows.team)=={old["home_team"],old["away_team"]},"Incomplete completed-game team statistics")
        require(all(utc(r.kickoff_utc)==kickoff(old) and r.season==old["season"] and r.week==old["week"] and r.opponent==(old["home_team"] if r.team==old["away_team"] else old["away_team"]) for r in rows.itertuples()),"Historical team/schedule identity mismatch")
    if model:require(utc(model["last_training_kickoff"])<cutoff and model["through_season"]<season,"Model trained on future/target season")
    mode="pregame_snapshot" if generated<min(kickoff(g) for g in target) and all(utc(v["as_of"])<=cutoff for v in sources.values()) else "retrospective_analysis"
    out={"meta":{"schema_version":1,"model_version":VERSION,"season":season,"week":week,"generated_at":generated.isoformat(),
        "data_cutoff":cutoff.isoformat(),"classification":mode,"sources":sources,"model":model,"model_sha256":model_fingerprint(model) if model else None,
        "primary_method":"baseline","warnings":["Offensive-drive PPP baseline excludes defensive/return points and safeties","No QB, injury, weather or sportsbook inputs","Adjusted model experimental; no calibrated win probabilities","Historical source revisions do not establish original pregame vintage"]},"games":{}}
    for g in target:
        projections=project_matchup(team_games,g,cutoff)
        methods={};warnings=[]
        if projections:
            for method in (["baseline","adjusted"] if model else ["baseline"]):
                scores={t:p["baseline"] if method=="baseline" else adjusted(p,model) for t,p in projections.items()}
                margin=scores[g["home_team"]]-scores[g["away_team"]]
                methods[method]={"scores":scores,"home_margin":margin,"total":sum(scores.values()),
                                 "favored":g["home_team"] if margin>0 else g["away_team"] if margin<0 else None,"win_probability":None}
        else:warnings=["Insufficient Data: fewer than four verified prior-week games per team"]
        out["games"][g["game_id"]]={"game_id":g["game_id"],"home_team":g["home_team"],"away_team":g["away_team"],"kickoff_utc":g["kickoff_utc"],
            "status":"available" if projections else "insufficient_data","teams":projections or {},"methods":methods,"warnings":warnings}
    validate_artifact(out,[{k:g[k] for k in ("game_id","home_team","away_team","kickoff_utc")} for g in target],season,week)
    return out


def validate_artifact(value,games,season,week,now=None,publishing=False):
    from game_projection import FEATURES,VERSION,model_fingerprint,adjusted
    require(isinstance(value,dict) and set(value)=={"meta","games"},"Invalid game projection structure")
    m=value["meta"]
    require(set(m)=={"schema_version","model_version","season","week","generated_at","data_cutoff","classification","sources","model","model_sha256","primary_method","warnings"},"Invalid game metadata fields")
    require(type(m["schema_version"]) is int and m["schema_version"]==1 and m["model_version"]==VERSION and type(m["season"]) is int and type(m["week"]) is int and (m["season"],m["week"])==(season,week),"Game projection version/week mismatch")
    cutoff,generated=utc(m["data_cutoff"]),utc(m["generated_at"])
    require(cutoff<=generated,"Invalid game source timing")
    require(m["classification"] in ("pregame_snapshot","retrospective_analysis") and m["primary_method"]=="baseline","Unsupported game classification/method")
    require(isinstance(m["warnings"],list) and all(isinstance(x,str) for x in m["warnings"]),"Missing game warnings")
    require(isinstance(m["sources"],dict) and set(m["sources"])=={"schedule","team_games"},"Missing game source provenance")
    for source in m["sources"].values():
        require(set(source)=={"as_of","sha256","origin"} and isinstance(source["sha256"],str) and len(source["sha256"])==64 and all(c in "0123456789abcdef" for c in source["sha256"]) and isinstance(source["origin"],str) and source["origin"].startswith("https://"),"Invalid game source fingerprint")
        if m["classification"]=="pregame_snapshot":require(utc(source["as_of"])<=cutoff,"Game source captured after cutoff")
        else:utc(source["as_of"])
    model=m["model"]
    if model:
        require(set(model)=={"version","features","through_season","last_training_kickoff","coefficients","intercept","residual_quantiles","training_games"} and model["version"]==VERSION and model["features"]==FEATURES and len(model["coefficients"])==5 and model_fingerprint(model)==m["model_sha256"],"Invalid adjusted model fingerprint")
        require(model["through_season"]<season and utc(model["last_training_kickoff"])<cutoff and model["training_games"]>=100,"Future or insufficient adjusted training")
    else:require(m["model_sha256"] is None,"Unexpected model hash")
    def numeric_tree(v):
        if isinstance(v,float):return math.isfinite(v)
        if isinstance(v,dict):return all(numeric_tree(x) for x in v.values())
        if isinstance(v,list):return all(numeric_tree(x) for x in v)
        return v is None or isinstance(v,(str,int,bool))
    require(numeric_tree(value),"Nonfinite projection data")
    expected={g["game_id"]:g for g in games}
    require(set(value["games"])==set(expected),"Game schedule coverage mismatch")
    for gid,g in value["games"].items():
        require(set(g)=={"game_id","home_team","away_team","kickoff_utc","status","teams","methods","warnings"},"Invalid game fields")
        schedule=expected[gid];teams={g["home_team"],g["away_team"]}
        require(len(teams)==2 and teams.issubset(TEAM_CODES) and all(g[k]==schedule[k] for k in ("game_id","home_team","away_team","kickoff_utc")),"Game schedule identity mismatch")
        require(cutoff<kickoff(g),"Post-kickoff game cutoff")
        if m["classification"]=="pregame_snapshot":require(generated<kickoff(g),"Post-kickoff game generation")
        if g["status"]=="insufficient_data":
            require(not g["teams"] and not g["methods"] and g["warnings"] and not publishing,"Incomplete game data cannot be published")
            continue
        require(g["status"]=="available" and set(g["teams"])==teams and set(g["methods"])==({"baseline","adjusted"} if model else {"baseline"}),"Missing game projection coverage")
        for team,p in g["teams"].items():
            own=p["summary"];other=g["teams"][next(t for t in teams if t!=team)]["summary"]
            require(set(p)=={"summary","opponent_defensive_ppp","expected_plays","expected_ppp","baseline","features"},"Invalid game input fields")
            require(set(own)=={"games","game_ids","last_kickoff_utc","offensive_points","offensive_plays","allowed_points","defensive_plays","offensive_ppp","defensive_ppp_allowed","plays_per_game","plays_faced_per_game","red_zone_drives_per_game"},"Invalid team summary")
            require(type(own["games"]) is int and 4<=own["games"]<=8 and len(set(own["game_ids"]))==len(own["game_ids"])==own["games"] and utc(own["last_kickoff_utc"])<cutoff,"Invalid historical sample")
            require(all(gid not in own["game_ids"] for gid in expected),"Target-game leakage")
            for sample_id in own["game_ids"]:
                match=re.fullmatch(r"(\d{4})_(\d{2})_([A-Z]+)_([A-Z]+)",sample_id)
                require(match and team in match.groups()[2:] and season-1<=int(match[1])<=season and 1<=int(match[2])<=18
                        and (int(match[1])<season or int(match[2])<week),"Future or wrong-team sample game")
            require(all(type(own[k]) in (int,float) and own[k]>=0 for k in ("offensive_points","allowed_points","offensive_plays","defensive_plays","red_zone_drives_per_game")) and own["offensive_plays"]>0 and own["defensive_plays"]>0,"Invalid team scoring evidence")
            pairs=[(own["offensive_ppp"],own["offensive_points"]/own["offensive_plays"]),(own["defensive_ppp_allowed"],own["allowed_points"]/own["defensive_plays"]),
                   (own["plays_per_game"],own["offensive_plays"]/own["games"]),(own["plays_faced_per_game"],own["defensive_plays"]/own["games"]),
                   (p["expected_plays"],(own["plays_per_game"]+other["plays_faced_per_game"])/2),
                   (p["opponent_defensive_ppp"],other["defensive_ppp_allowed"]),
                   (p["expected_ppp"],(own["offensive_ppp"]+other["defensive_ppp_allowed"])/2)]
            require(all(abs(a-b)<1e-9 for a,b in pairs) and abs(p["baseline"]-p["expected_ppp"]*p["expected_plays"])<1e-9,"PPP/pace calculation mismatch")
            require(len(p["features"])==5 and p["features"][:4]==[p["baseline"],own["offensive_ppp"],other["defensive_ppp_allowed"],p["expected_plays"]] and p["features"][4] in (0,1),"Adjusted input mismatch")
        for method,result in g["methods"].items():
            require(set(result)=={"scores","home_margin","total","favored","win_probability"} and result["win_probability"] is None and set(result["scores"])==teams,"Unsupported score/probability output")
            for t,p in g["teams"].items():
                score=p["baseline"] if method=="baseline" else adjusted(p,model)
                require(type(result["scores"][t]) in (int,float) and result["scores"][t]>=0 and abs(result["scores"][t]-score)<1e-9,"Projection formula changed")
            margin=result["scores"][g["home_team"]]-result["scores"][g["away_team"]]
            require(abs(result["home_margin"]-margin)<1e-9 and abs(result["total"]-sum(result["scores"].values()))<1e-9 and result["favored"]==(g["home_team"] if margin>0 else g["away_team"] if margin<0 else None),"Winner/margin/total mismatch")
    if publishing:
        require(m["classification"]=="pregame_snapshot","Historical game reconstructions cannot publish as forecasts")
        now=utc(now or datetime.now(timezone.utc));remaining=min(kickoff(g) for g in games)-now
        require(remaining>timedelta(minutes=10),"Game kickoff safety margin exhausted")
        limit=timedelta(minutes=30) if remaining<=timedelta(hours=6) else timedelta(hours=6) if remaining<=timedelta(hours=48) else timedelta(hours=24)
        require(all(timedelta(0)<=now-utc(t)<limit for t in [m["generated_at"],m["data_cutoff"],*[s["as_of"] for s in m["sources"].values()]]),"Stale game source data")
    return value


def validate_file(path,board,receipt,now=None,publishing=False):
    data=Path(path).read_bytes()
    require(hashlib.sha256(data).hexdigest()==receipt.get(HASH),"Game receipt hash mismatch")
    return validate_artifact(json.loads(data),board["meta"]["games"],board["meta"]["season"],board["meta"]["week"],now,publishing)
