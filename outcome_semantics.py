"""Outcome evidence is separate from forecast scores. Never infer unknown negatives."""
import math
import numpy as np
import pandas as pd


def touchdown_count(value):
    if isinstance(value, (bool, np.bool_, type(pd.NA))) or value is None:
        raise ValueError('Missing or malformed touchdown count')
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        raise ValueError('Missing or malformed touchdown count') from None
    if not math.isfinite(numeric) or numeric < 0 or not numeric.is_integer():
        raise ValueError('Missing or malformed touchdown count')
    return int(numeric)


def forecast_outcomes(rows, evidence=None):
    """Only explicit, complete, verified player/game evidence can label a final row.

    Existing score annotations are deliberately ignored: legacy False is not
    evidence. The compatibility exporter does not retrieve or invent outcomes.
    """
    result = pd.Series([None] * len(rows), index=rows.index, dtype=object)
    if evidence is None or evidence.empty:
        return result
    required = {'player_id', 'game_id', 'actual_td_count', 'outcome_verified', 'game_complete'}
    if not required.issubset(evidence.columns):
        raise ValueError('Outcome evidence lacks verification fields')
    if evidence.duplicated(['player_id', 'game_id']).any():
        raise ValueError('Ambiguous player/game outcome evidence')
    verified = {}
    for row in evidence.itertuples(index=False):
        if row.outcome_verified is True and row.game_complete is True:
            verified[(str(row.player_id), str(row.game_id))] = touchdown_count(row.actual_td_count) > 0
    for index, row in rows.iterrows():
        if row.get('game_status') == 'Final':
            result.at[index] = verified.get((str(row['player_id']), str(row['game_id'])))
    return result
