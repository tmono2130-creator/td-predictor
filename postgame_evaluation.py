"""Evaluate immutable forecasts against separately captured outcomes; never forecast or publish."""
import argparse
import csv
import json
import math
import subprocess
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from data_schema import validate_board, validate_breakdowns
from game_projection_artifact import validate_artifact
from outcome_semantics import touchdown_count as strict_touchdown_count
from roster_eligibility import GSIS
from weekly_capture import Capture, encode, load_capture, local_root, schedule_rows, sha, source_url, verified_schedule
from weekly_schedule import SCHEDULE_URL, kickoff, regular_games, utc


def touchdown_count(value):
    try:
        return strict_touchdown_count(value)
    except ValueError:
        return None


def metrics(rows):
    """Raw V5 estimate diagnostics; no calibration fit and no weight changes."""
    labelled = [r for r in rows if r['actual_td'] is not None]
    if not labelled:
        return {'n': 0, 'positives': 0, 'brier': None, 'log_loss': None, 'auc': None, 'calibration': []}
    p = np.array([r['estimate_pct'] / 100 for r in labelled], dtype=float)
    y = np.array([int(r['actual_td']) for r in labelled])
    if not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError('Invalid original V5 estimate')
    bounded = np.clip(p, 1e-15, 1 - 1e-15)  # Log loss only, never Brier or displayed estimates.
    bins = []
    for lower in range(0, 100, 10):
        mask = (p >= lower / 100) & ((p < (lower + 10) / 100) if lower < 90 else (p <= 1))
        if mask.any():
            bins.append({'lower_pct': lower, 'upper_pct': lower + 10, 'n': int(mask.sum()),
                         'mean_estimate_pct': float(p[mask].mean() * 100), 'observed_pct': float(y[mask].mean() * 100)})
    return {'n': len(y), 'positives': int(y.sum()), 'brier': float(((p - y) ** 2).mean()),
            'log_loss': float(-(y * np.log(bounded) + (1 - y) * np.log(1 - bounded)).mean()),
            'auc': float(roc_auc_score(y, p)) if len(set(y)) == 2 else None, 'calibration': bins}


def load_forecast(folder):
    folder = Path(folder)
    receipt = json.loads((folder / 'receipt.json').read_bytes())
    pins = {'board.json': receipt['board_sha256'], 'breakdowns.json': receipt['breakdowns_sha256']}
    for name, key in [('game-predictor.json', 'game_predictor_sha256'), ('matchup-intelligence.json', 'matchup_intelligence_sha256')]:
        if key in receipt:
            pins[name] = receipt[key]
    for name, pin in pins.items():
        if sha((folder / name).read_bytes()) != pin:
            raise ValueError('Frozen prediction hash mismatch: ' + name)
    envelope = receipt.get('input_capture', {})
    capture = envelope.get('manifest', {})
    if envelope.get('manifest_sha256') != sha(encode(capture)) or capture.get('kind') != 'live_capture':
        raise ValueError('Missing authentic captured forecast provenance')
    revision = capture['git_revision']
    if len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):
        raise ValueError('Invalid original revision')
    # Validate original source at its actual Git revision, not against today's code.
    for name, pin in capture['code_sha256'].items():
        if sha(subprocess.check_output(['git', 'show', f'{revision}:{name}'])) != pin:
            raise ValueError('Original source fingerprint mismatch: ' + name)
    board = json.loads((folder / 'board.json').read_bytes())
    meta = board['meta']
    if meta.get('snapshot_classification') != 'pregame_snapshot':
        raise ValueError('Evaluation requires original pregame predictions')
    validate_board(board, meta['season'], meta['week'])
    validate_breakdowns(json.loads((folder / 'breakdowns.json').read_bytes()), meta['season'], meta['week'], meta['games'])
    cutoff, generated = utc(receipt['source_cutoff_utc']), utc(meta['generated_at'])
    if cutoff != utc(capture['source_cutoff_utc']) or not utc(capture['started_at_utc']) <= cutoff <= generated:
        raise ValueError('Original cutoff disagrees with capture')
    for record in capture['sources'].values():
        if utc(record['retrieved_at_utc']) > cutoff:
            raise ValueError('Forecast source was retrieved after cutoff')
    if any(generated >= kickoff(g) for g in meta['games']):
        raise ValueError('Post-kickoff prediction cannot be evaluated as pregame')
    gp = json.loads((folder / 'game-predictor.json').read_bytes()) if 'game-predictor.json' in pins else None
    if gp:
        validate_artifact(gp, meta['games'], meta['season'], meta['week'])
        if utc(gp['meta']['data_cutoff']) != cutoff or gp['meta']['classification'] != 'pregame_snapshot':
            raise ValueError('Game predictor provenance disagrees with core')
    mi = json.loads((folder / 'matchup-intelligence.json').read_bytes()) if 'matchup-intelligence.json' in pins else None
    if mi:
        from matchup_schema import validate_intelligence
        validate_intelligence(mi, board)
    pins['receipt.json'] = sha((folder / 'receipt.json').read_bytes())
    return board, gp, mi, receipt, pins


def score_summary(games, field='prediction'):
    ready = [g for g in games if g['status'] == 'final' and g[field] is not None]
    if not ready:
        return {'n': 0, 'winner_accuracy': None, 'team_score_mae': None, 'total_mae': None, 'margin_mae': None}
    errors, totals, margins, correct = [], [], [], []
    for g in ready:
        p, a = g[field], g['actual']
        errors += [abs(p['away'] - a['away']), abs(p['home'] - a['home'])]
        totals.append(abs(p['away'] + p['home'] - a['away'] - a['home']))
        margins.append(abs((p['home'] - p['away']) - (a['home'] - a['away'])))
        correct.append(np.sign(p['home'] - p['away']) == np.sign(a['home'] - a['away']))
    return {'n': len(ready), 'winner_accuracy': float(np.mean(correct)), 'team_score_mae': float(np.mean(errors)),
            'total_mae': float(np.mean(totals)), 'margin_mae': float(np.mean(margins))}


def evaluate(board, gp, mi, receipt, pins, records, pbp, stats, as_of):
    """Postgame-only labels. Pending/missing evidence never turns into a negative."""
    meta = board['meta']
    records = verified_schedule(records, {meta['season']: pbp}, as_of)
    schedule = {g['game_id']: g for g in regular_games(records, min_season=meta['season'], max_season=meta['season'])}
    stats = stats[(pd.to_numeric(stats.season, errors='raise') == meta['season']) &
                  (pd.to_numeric(stats.week, errors='raise') == meta['week'])].copy()
    if 'season_type' in stats:
        stats = stats[stats.season_type.eq('REG')]
    if stats.duplicated(['game_id', 'player_id']).any():
        raise ValueError('Duplicate outcome player/game identities')
    if pbp.duplicated(['game_id', 'play_id']).any():
        raise ValueError('Duplicate outcome play identities')
    indexed = {(r.game_id, r.player_id): r._asdict() for r in stats.itertuples(index=False)}
    games, evidence = [], {}
    for original in meta['games']:
        gid = original['game_id']
        current = schedule.get(gid)
        if not current or any(current[k] != original[k] for k in ['home_team', 'away_team']) or kickoff(current) != kickoff(original):
            raise ValueError('Outcome schedule identity differs from original forecast: ' + gid)
        final = current['complete'] and kickoff(current) < utc(as_of)
        p = gp['games'][gid] if gp else None
        prediction = {'away': p['methods']['baseline']['scores'][original['away_team']],
                      'home': p['methods']['baseline']['scores'][original['home_team']]} if p and p['status'] == 'available' else None
        baseline = {side: p['teams'][original[side + '_team']]['summary']['offensive_points'] /
                    p['teams'][original[side + '_team']]['summary']['games'] for side in ['away', 'home']} if prediction else None
        games.append({**{k: original[k] for k in ['game_id', 'away_team', 'home_team', 'kickoff_utc']},
                      'status': 'final' if final else 'pending', 'prediction': prediction, 'prior_offensive_mean': baseline,
                      'actual': {'away': int(current['away_score']), 'home': int(current['home_score'])} if final else None})
        plays = pbp[pbp.game_id.eq(gid)]
        touchdowns, offensive = Counter(), Counter()
        complete_scorers = final and not plays.empty
        for row in plays.to_dict('records'):
            flag = touchdown_count(row.get('touchdown'))
            if flag is None:
                # Administrative events often omit this field. They are not TD evidence.
                play_type = row.get('play_type')
                if isinstance(play_type, str) and play_type != 'no_play':
                    complete_scorers = False
                if pd.notna(row.get('td_player_id')) or pd.notna(row.get('td_team')):
                    complete_scorers = False
                continue
            if flag not in [0, 1]:
                complete_scorers = False
            if flag != 1 or touchdown_count(row.get('two_point_attempt')) == 1:
                continue
            scorer, team = row.get('td_player_id'), row.get('td_team')
            if not isinstance(scorer, str) or not GSIS.fullmatch(scorer) or team not in [original['away_team'], original['home_team']]:
                complete_scorers = False
                continue
            touchdowns[(scorer, team)] += 1
            if touchdown_count(row.get('return_touchdown')) == 0 and (
                    touchdown_count(row.get('rush_touchdown')) == 1 or touchdown_count(row.get('pass_touchdown')) == 1):
                offensive[(scorer, team)] += 1
        evidence[gid] = (final, complete_scorers, touchdowns, offensive)
    players = []
    for row in board['rows']:
        gid, pid, team = row['game_id'], row['player_id'], row['team']
        final, complete, scored, offensive = evidence[gid]
        s = indexed.get((gid, pid))
        actual, reason, participated = None, 'pending_game', False
        if final:
            reason = 'missing_player_stat_evidence'
            if s is not None:
                if s['team'] != team:
                    reason = 'player_team_conflict'
                else:
                    rush, receiving = touchdown_count(s.get('rushing_tds')), touchdown_count(s.get('receiving_tds'))
                    participated = any((touchdown_count(s.get(k)) or 0) > 0 for k in ['attempts', 'carries', 'targets'])
                    if rush is None or receiving is None:
                        reason = 'malformed_or_missing_touchdown_evidence'
                    elif rush + receiving != offensive[(pid, team)]:
                        reason = 'stats_pbp_touchdown_conflict'
                    elif complete:
                        actual, reason = scored[(pid, team)] > 0, 'verified_stats_and_complete_pbp'
                    else:
                        reason = 'incomplete_game_scorer_evidence'
            elif scored[(pid, team)] > 0:
                actual, reason, participated = True, 'verified_pbp_scorer_without_stats', True
        players.append({'game_id': gid, 'player_id': pid, 'player': row['player'], 'team': team,
                        'position': row['position'], 'estimate_pct': row['td_estimate'], 'ranking_score': row['td_score'],
                        'actual_td': actual, 'outcome_reason': reason, 'participation_verified': participated})
    top = {}
    for n in [5, 10, 20, 30]:
        selected = []
        for g in games:
            if g['status'] == 'final':
                selected += sorted([p for p in players if p['game_id'] == g['game_id']], key=lambda p: (-p['estimate_pct'], p['player_id']))[:n]
        labelled = [p for p in selected if p['actual_td'] is not None]
        top[str(n)] = {'selected': len(selected), 'labelled': len(labelled), 'hits': sum(p['actual_td'] for p in labelled),
                       'hit_rate': sum(p['actual_td'] for p in labelled) / len(labelled) if labelled else None}
    margin_bands = {}
    for label, low, high in [('under_3', 0, 3), ('3_to_under_7', 3, 7), ('7_plus', 7, math.inf)]:
        margin_bands[label] = score_summary([g for g in games if g['prediction'] and
                                             low <= abs(g['prediction']['home'] - g['prediction']['away']) < high])
    return {'schema_version': 1, 'season': meta['season'], 'week': meta['week'],
            'status': 'complete' if all(g['status'] == 'final' for g in games) else 'partial', 'evaluated_as_of': utc(as_of).isoformat(),
            'forecast_generated_at': meta['generated_at'], 'forecast_hashes': pins,
            'games_completed': sum(g['status'] == 'final' for g in games), 'games_pending': sum(g['status'] == 'pending' for g in games),
            'game_metrics': score_summary(games), 'baseline_metrics': score_summary(games, 'prior_offensive_mean'),
            'baseline_definition': 'Prior offensive points/game from frozen PPP inputs; excludes return/defensive scoring; no postgame fit',
            'margin_bands': margin_bands, 'td_metrics': metrics(players),
            'participation_metrics': metrics([p for p in players if p['participation_verified']]),
            'position_metrics': {pos: metrics([p for p in players if ('RB' if p['position'] == 'FB' else p['position']) == pos]) for pos in ['QB', 'RB', 'WR', 'TE']},
            'top_per_game': top, 'missing_labels': dict(Counter(p['outcome_reason'] for p in players if p['actual_td'] is None)),
            'quality': {'injury_coverage': receipt['source_metadata'].get('injury_coverage'),
                        'matchup_designations': dict(Counter(p['advantage'] for g in mi['games'].values() for p in g['recommendations'])) if mi else {},
                        'matchup_insufficiency_reasons': dict(Counter(e for g in mi['games'].values() for p in g['recommendations'] if p['advantage'] == 'Insufficient Data' for e in p['explanation'])) if mi else {}},
            'limitations': ['Raw V5 estimates are not established calibrated probabilities; no model fitting performed',
                            'TD labels are credited scorer events (including returns), never passing TDs for the passer',
                            'Missing stats/evidence remain unknown; metrics are conditional on labelled coverage, not sportsbook settlement',
                            'Original pregame raw inputs are not retained; frozen artifacts and their capture receipt are preserved',
                            'Only original pregame information is used for forecasts; outcome captures are postgame evaluation evidence'],
            'games': games, 'players': players}


def write_report(report, output, source_manifest):
    output = local_root(output)
    if output.is_relative_to(Path(__file__).parent/'evaluation'):
        raise ValueError('Existing historical evaluation datasets are immutable')
    identity = {'engine': sha(Path(__file__).read_bytes()), 'forecasts': report['forecast_hashes'],
                'games': report['games'], 'players': report['players']}
    run_id = sha(encode(identity))[:24]
    folder = output / run_id
    report = {**report, 'evaluation_id': run_id, 'engine_sha256': identity['engine'], 'outcome_sources': source_manifest}
    import jsonschema
    schema = json.loads((Path(__file__).parent/'schemas/evaluation.schema.json').read_bytes())
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(report)
    states = {g['game_id']: g for g in report['games']}
    if len(states) != len(report['games']) or any(p['game_id'] not in states or
            (states[p['game_id']]['status'] == 'pending' and p['actual_td'] is not None) for p in report['players']):
        raise ValueError('Evaluation labels conflict with game state')
    completed = sum(g['status'] == 'final' for g in report['games'])
    if (report['games_completed'], report['games_pending'], report['status']) != (
            completed, len(states)-completed, 'complete' if completed == len(states) else 'partial'):
        raise ValueError('Evaluation completion state conflicts')
    if report['td_metrics'] != metrics(report['players']) or report['game_metrics'] != score_summary(report['games']):
        raise ValueError('Evaluation metrics conflict with observations')
    if folder.exists():
        prior_bytes = (folder / 'evaluation.json').read_bytes()
        index = json.loads((folder/'index-proposal.json').read_bytes())
        if index['reports'] != [{'season': report['season'], 'week': report['week'],
                                 'path': f'{run_id}/evaluation.json', 'sha256': sha(prior_bytes)}]:
            raise ValueError('Existing evaluation hash binding conflicts; refusing overwrite')
        prior = json.loads(prior_bytes)
        if prior['evaluation_id'] != run_id or any(prior[k] != report[k] for k in ['games', 'players', 'forecast_hashes', 'engine_sha256']):
            raise ValueError('Existing evaluation conflicts; refusing overwrite')
        return folder
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'evaluation.json').write_bytes(encode(report))
    pin = sha((folder / 'evaluation.json').read_bytes())
    index = {'schema_version': 1, 'reports': [{'season': report['season'], 'week': report['week'],
              'path': f'{run_id}/evaluation.json', 'sha256': pin}]}
    (folder / 'index-proposal.json').write_bytes(encode(index))
    summary = [f"# {report['season']} Week {report['week']} immutable evaluation", '',
               f"Status: {report['status']}; {report['games_completed']} completed, {report['games_pending']} pending.",
               f"Original generation: {report['forecast_generated_at']}. Outcomes captured: {report['evaluated_as_of']}.",
               '', 'Game metrics: '+json.dumps(report['game_metrics']), 'Frozen prior-mean baseline: '+json.dumps(report['baseline_metrics']),
               'TD estimate metrics: '+json.dumps(report['td_metrics']), 'Coverage/missing: '+json.dumps(report['missing_labels']),
               '', '## Limitations', *['- '+x for x in report['limitations']]]
    game_rows = []
    summary += ['', '## Game results', '', '| Game | Status | Predicted A/H | Actual A/H | Predicted home margin | Actual home margin | Predicted total | Actual total |', '|---|---|---|---|---:|---:|---:|---:|']
    for game in report['games']:
        p, a = game['prediction'], game['actual']
        row = {'game_id': game['game_id'], 'status': game['status'],
               'predicted_away': p['away'] if p else None, 'predicted_home': p['home'] if p else None,
               'actual_away': a['away'] if a else None, 'actual_home': a['home'] if a else None,
               'predicted_margin_home': p['home']-p['away'] if p else None, 'actual_margin_home': a['home']-a['away'] if a else None,
               'predicted_total': sum(p.values()) if p else None, 'actual_total': sum(a.values()) if a else None}
        game_rows.append(row)
        summary.append(f"| {game['away_team']} @ {game['home_team']} | {game['status']} | {p['away']:.2f}/{p['home']:.2f} | "
                       f"{str(a['away'])+'/'+str(a['home']) if a else 'Pending'} | {row['predicted_margin_home']:.2f} | "
                       f"{row['actual_margin_home']} | {row['predicted_total']:.2f} | {row['actual_total']} |" if p else f"| {game['game_id']} | {game['status']} | Unavailable | | | | | |")
    summary += ['', '## Calibration bins', json.dumps(report['td_metrics']['calibration'], indent=2),
                '', '## Position diagnostics', json.dumps(report['position_metrics'], indent=2),
                '', '## Ranking hit rates (original top slots; unknown labels excluded explicitly)', json.dumps(report['top_per_game'], indent=2),
                '', '## Performance by original predicted margin', json.dumps(report['margin_bands'], indent=2)]
    (folder / 'report.md').write_text('\n'.join(summary)+'\n', encoding='utf-8')
    for name, rows in [('games.csv', game_rows), ('players.csv', report['players'])]:
        if rows:
            with (folder/name).open('x', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    return folder


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--capture', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--capture-latest', action='store_true')
    args = parser.parse_args(argv)
    board, gp, mi, receipt, pins = load_forecast(args.snapshot)
    season = board['meta']['season']
    if args.capture_latest:
        capture = Capture(args.capture)
        capture.fetch('schedule', SCHEDULE_URL)
        for source in ['stats', 'pbp']:
            capture.fetch(f'{source}_{season}', source_url(source, season))
        capture.freeze()
    capture = load_capture(args.capture)
    root = Path(args.capture)
    report = evaluate(board, gp, mi, receipt, pins, schedule_rows((root / 'schedule.csv').read_bytes()),
                      pd.read_parquet(root / f'pbp_{season}.parquet'), pd.read_parquet(root / f'stats_{season}.parquet'),
                      capture['source_cutoff_utc'])
    folder = write_report(report, args.output, capture)
    print(json.dumps({'output': str(folder), 'status': report['status'], 'game_metrics': report['game_metrics'],
                      'td_metrics': report['td_metrics'], 'missing_labels': report['missing_labels']}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
