"""Explicit offline reconstruction/evaluation; never writes to served paths or existing datasets."""
import argparse
import gc
import json
import hashlib
from datetime import datetime,timezone
from pathlib import Path
import pandas as pd
import nflreadpy
from nflreadpy.config import update_config
from game_projection import PBP_COLUMNS,prepare_team_games,training_rows,fit_adjusted,evaluate,model_fingerprint
from weekly_schedule import retrieve_schedule
from publication_policy import REPOSITORY


def local_output(path):
    target=Path(path).resolve()
    if any(target.is_relative_to(REPOSITORY/root) for root in ("public","td-predictor-web/public","evaluation")):
        raise ValueError("Only a separate local analysis output directory is permitted")
    target.mkdir(parents=True,exist_ok=True)
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--output",required=True)
    args=parser.parse_args();root=local_output(args.output)
    update_config(cache_mode="off",timeout=90)
    schedule=retrieve_schedule();provenance={"schedule":{"retrieved_at_utc":datetime.now(timezone.utc).isoformat(),"sha256":hashlib.sha256(json.dumps(schedule,sort_keys=True,default=str).encode()).hexdigest()}}
    engine_hash=hashlib.sha256(Path(__file__).with_name("game_projection.py").read_bytes().replace(b"\r\n",b"\n")).hexdigest()
    frames=[]
    for year in range(2020,2026):
        file=root/f"team-games-{year}.csv"
        if file.exists():
            stamp=json.loads((root/f"source-{year}.json").read_text())
            if stamp.get("engine_sha256")!=engine_hash:raise ValueError("Cached scoring implementation differs; use a new analysis directory")
            if hashlib.sha256(file.read_bytes()).hexdigest()!=stamp["team_games_sha256"]:raise ValueError("Cached analysis input hash mismatch")
            provenance[str(year)]=stamp;frames.append(pd.read_csv(file));continue
        raw=nflreadpy.load_pbp(seasons=[year]);frame=raw.select(sorted(PBP_COLUMNS)).to_pandas();del raw;gc.collect()
        provenance[str(year)]={"engine_sha256":engine_hash,"retrieved_at_utc":datetime.now(timezone.utc).isoformat(),"sha256":hashlib.sha256(frame.to_json(orient="split").encode()).hexdigest(),"rows":len(frame)}
        frame.to_parquet(root/f"pbp-{year}.parquet",index=False)
        games=prepare_team_games([g for g in schedule if int(g["season"])==year],frame)
        games.to_csv(file,index=False)
        provenance[str(year)]["team_games_sha256"]=hashlib.sha256(file.read_bytes()).hexdigest()
        (root/f"source-{year}.json").write_text(json.dumps(provenance[str(year)],indent=2),encoding="utf-8")
        frames.append(games);del frame;gc.collect();print("Prepared real source season",year,flush=True)
    table=pd.concat(frames,ignore_index=True)
    records=training_rows(table,[g for g in schedule if 2020<=int(g["season"])<=2025])
    model=fit_adjusted(records,2022)
    validation=evaluate(records,model,2023)
    # Experimental gate uses validation only; a passing experiment cannot change release policy.
    improved=validation["adjusted"]["score_mae"]<validation["baseline"]["score_mae"] and validation["adjusted"]["margin_mae"]<validation["baseline"]["margin_mae"] and validation["adjusted"]["winner_accuracy"]>=validation["baseline"]["winner_accuracy"]
    report={"classification":"retrospective_event_time_reconstruction; original upstream pregame vintages unavailable",
            "train_through":2022,"validation_season":2023,"test_seasons":[2024,2025],"model_sha256":model_fingerprint(model),
            "primary_method":"baseline","experimental_gate_passed":improved,"selection_rule":"2023 score MAE and margin MAE improve, winner accuracy does not regress; conservative release gate; fixed alpha=100; no test tuning",
            "validation":validation,"tests":{str(y):evaluate(records,model,y) for y in (2024,2025)},"sources":provenance,
            "limitations":["Current revised feeds, not original captured vintages","REG only, last 8 prior-week games, at least 4 per team","No odds, injuries, QB or weather inputs","Baseline offensive-drive points omit defensive/return points and safeties; compared against actual final scores","Adjusted residual model learns aggregate scoring offsets; no calibrated win probabilities or prediction intervals","No held-out test tuning or future model retraining"]}
    for name,value in (("model.json",model),("evaluation.json",report)):
        path=root/name
        with path.open("x",encoding="utf-8") as out:json.dump(value,out,indent=2,allow_nan=False)
    print(json.dumps(report,indent=2))


if __name__=="__main__":main()
