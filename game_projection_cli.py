"""Explicit local Game Predictor artifact creation; never a publication command."""
import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path
from datetime import datetime,timezone
import pandas as pd
from game_projection_artifact import build_artifact,validate_file,NAME,HASH
from publication_policy import REPOSITORY,is_live_path


def local(path):
    path=Path(path).resolve()
    if is_live_path(path) or any(path.is_relative_to(REPOSITORY/p) for p in ("public","td-predictor-web/public")):
        raise ValueError("Served data paths are forbidden; reviewed publication only")
    return path


def attach(candidate,artifact,now=None):
    from weekly_storage import validate_candidate,digest
    candidate=local(candidate);board,_,receipt=validate_candidate(candidate,now)
    if HASH in receipt:raise ValueError("Existing game evidence is immutable")
    raw=Path(artifact).read_bytes();receipt[HASH]=hashlib.sha256(raw).hexdigest()
    validate_file(artifact,board,receipt,now,publishing=True)
    before=digest(candidate/'receipt.json');temporary=candidate/('.receipt-'+uuid.uuid4().hex)
    try:
        with temporary.open('x',encoding='utf-8') as stream:
            json.dump(receipt,stream,allow_nan=False,separators=(',',':'));stream.flush();os.fsync(stream.fileno())
        with (candidate/NAME).open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        if digest(candidate/'receipt.json')!=before:raise ValueError('Concurrent candidate receipt change; inspect and rebuild')
        os.replace(temporary,candidate/'receipt.json')
    finally:temporary.unlink(missing_ok=True)
    validate_candidate(candidate,now)
    return receipt[HASH]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('team-games','schedule','sources','season','week','cutoff','output'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--model')
    args=parser.parse_args();output=local(args.output)
    sources=json.loads(Path(args.sources).read_text(encoding='utf-8'))
    for key,path in (('schedule',args.schedule),('team_games',args.team_games)):
        if sources[key]['sha256']!=hashlib.sha256(Path(path).read_bytes()).hexdigest():raise ValueError('Input capture hash mismatch: '+key)
    value=build_artifact(pd.read_csv(args.team_games),json.loads(Path(args.schedule).read_text()),int(args.season),int(args.week),args.cutoff,
                         sources,json.loads(Path(args.model).read_text()) if args.model else None)
    folder=output/str(args.season)/('week-'+str(args.week))/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:12])
    folder.mkdir(parents=True,exist_ok=False)
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    with (folder/NAME).open('xb') as stream:stream.write(raw)
    print(json.dumps({'path':str(folder/NAME),'sha256':hashlib.sha256(raw).hexdigest(),'published':False,'classification':value['meta']['classification']}))


if __name__=='__main__':main()
