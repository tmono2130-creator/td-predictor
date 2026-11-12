"""Read-only weekly source diagnostics. Does not score, infer health, or override eligibility."""
import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from roster_eligibility import EligibilityError, resolve_roster, select_weekly
from weekly_capture import load_capture, local_root, schedule_rows, source_url
from weekly_schedule import kickoff, plan_week, regular_games, utc


def diagnose(board, receipt, weekly, known, injuries, schedule, cutoff, target_week=None):
    season, week = board['meta']['season'], target_week or board['meta']['week']
    games = [g for g in regular_games(schedule, min_season=season, max_season=season) if g['week'] == week]
    teams = {g[key] for g in games for key in ['away_team', 'home_team']}
    target = select_weekly(weekly, season, week)
    issues, eligible, pending = [], [], []
    if target.empty:
        issues.append({'kind': 'target_week_roster_unavailable', 'blocking': True})
        counts = None
    else:
        try:
            eligible, audit = resolve_roster(weekly, pd.DataFrame(), known, season, week, teams)
            counts = audit['counts']
        except EligibilityError as exc:
            counts = exc.audit['counts']
            pending = [r for r in exc.audit['decisions'] if r['decision'] == 'pending']
            issues.append({'kind': 'pending_roster_eligibility', 'blocking': True})
    if target_week is None:
        membership = set(zip(target.gsis_id, target.team)) if not target.empty else set()
        seen = set()
        by_id = {g['game_id']: g for g in games}
        for row in board['rows']:
            key = (row['player_id'], row['game_id'])
            if key in seen:
                issues.append({'kind': 'duplicate_prediction_identity', 'player_id': row['player_id'], 'blocking': True})
            seen.add(key)
            game = by_id.get(row['game_id'])
            if not game or (row['team'], row['opponent']) not in [(game['away_team'], game['home_team']), (game['home_team'], game['away_team'])]:
                issues.append({'kind': 'prediction_matchup_identity', 'player_id': row['player_id'], 'blocking': True})
            if membership and (row['player_id'], row['team']) not in membership:
                issues.append({'kind': 'target_week_membership_disagreement', 'player_id': row['player_id'], 'team': row['team'], 'blocking': True})
    reports = injuries
    for name, value in [('season', season), ('week', week)]:
        if name in reports:
            reports = reports[pd.to_numeric(reports[name], errors='coerce').eq(value)]
        else:
            reports = reports.iloc[:0]
    # Practice participation, no game designation, and absent rows are not verified Active.
    statuses = Counter(str(v) for v in reports.get('report_status', pd.Series(dtype=str)).fillna('Unknown'))
    prior_incomplete = [g['game_id'] for g in regular_games(schedule, min_season=season, max_season=season)
                        if g['week'] < week and kickoff(g) < utc(cutoff) and not g['complete']]
    if prior_incomplete:
        issues.append({'kind': 'prior_final_evidence_missing', 'games': prior_incomplete, 'blocking': True})
    plan = plan_week(schedule, now=cutoff, season=season, week=week)
    membership = set(zip(target.gsis_id, target.team)) if not target.empty else set()
    quarterbacks = [{'game_id': g['game_id'], 'team': g[f'{side}_team'], 'provider_gsis_id': g.get(f'{side}_qb_id'),
                     'provider_name': g.get(f'{side}_qb_name'),
                     'target_roster_match': (g.get(f'{side}_qb_id'), g[f'{side}_team']) in membership,
                     'starting_status': 'unverified_provider_annotation'} for g in games for side in ['away', 'home']]
    return {'season': season, 'week': week, 'as_of': utc(cutoff).isoformat(), 'scheduled_games': len(games),
            'earliest_kickoff': min((g['kickoff_utc'] for g in games), default=None), 'upcoming_games': len(plan.get('games', [])),
            'target_week_roster_rows': len(target), 'roster_counts': counts, 'pending': pending,
            'injury_source_rows': len(reports), 'injury_report_status_values': dict(statuses),
            'quarterback_annotations': quarterbacks,
            'original_forecast_injury_coverage': receipt.get('source_metadata', {}).get('injury_coverage'),
            'issues': issues, 'ready_for_candidate': plan['status'] == 'ready' and not any(i['blocking'] for i in issues),
            'limitations': ['Roster membership, injury designation and game-day activation are separate',
                            'Unknown/blank injuries are not Active; practice participation is not clearance',
                            'Schedule QB fields are provider annotations, not verified starting-QB availability',
                            'Current source records cannot rewrite or prove the vintage of frozen pregame forecasts',
                            'These diagnostics never change the published cohort or scoring formulas']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target-week', type=int)
    args = parser.parse_args(argv)
    from weekly_capture import verified_schedule
    capture = load_capture(args.capture)
    season = json.loads((args.snapshot/'board.json').read_bytes())['meta']['season']
    def read(name, optional=False):
        record = capture['sources'].get(f'{name}_{season}')
        if optional and (not record or not record.get('available')):
            return pd.DataFrame()
        if not record or not record.get('available'):
            raise ValueError('Required diagnostic source unavailable: ' + name)
        return pd.read_parquet(args.capture/record['path'])
    records = verified_schedule(schedule_rows((args.capture/'schedule.csv').read_bytes()), {season: read('pbp')}, capture['source_cutoff_utc'])
    injury_record = capture['sources'].get(f'injuries_{season}', {})
    report = diagnose(json.loads((args.snapshot/'board.json').read_bytes()), json.loads((args.snapshot/'receipt.json').read_bytes()),
                      read('weekly_rosters', optional=True), read('players'), read('injuries') if injury_record.get('available') else pd.DataFrame(),
                      records, capture['source_cutoff_utc'], args.target_week)
    report['source_origins'] = {kind: source_url(kind, season) for kind in ['weekly_rosters', 'players', 'injuries']}
    report['source_availability'] = {key: {name: record.get(name) for name in ['available', 'reason', 'retrieved_at_utc', 'provider_modified_utc']}
                                     for key, record in capture['sources'].items()}
    output = local_root(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(json.dumps(report, indent=2).encode())
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
