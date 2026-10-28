"""Week-aware eligibility and identity resolution, independent of scoring/injuries."""
import re
import math
import numbers
from collections import Counter
import pandas as pd
from data_schema import TEAM_CODES

SKILL_POSITIONS = {'QB', 'RB', 'FB', 'WR', 'TE'}
NON_SKILL_POSITIONS = {'C','G','T','OL','OG','OT','LS','DE','DT','DL','NT','LB','ILB','OLB','MLB',
                       'DB','CB','S','FS','SS','SAF','EDGE','K','P'}
EXCLUDED_STATUSES = {'CUT', 'RET', 'RES', 'DEV'}
STABLE_IDS = ('pfr_id', 'espn_id', 'sleeper_id', 'sportradar_id')
GSIS = re.compile(r'00-\d{7}\Z')


class EligibilityError(ValueError):
    def __init__(self, audit):
        self.audit = audit
        pending = [r for r in audit['decisions'] if r['decision'] == 'pending']
        examples = ', '.join(f"{r['player_id'] or r['name']}: {r['reason']}" for r in pending[:8])
        super().__init__(f'Unresolved roster eligibility ({len(pending)} pending): {examples}')


def text(value):
    return '' if value is None or pd.isna(value) else str(value).strip()


def stable_text(value):
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        return str(int(value)) if math.isfinite(value) and float(value).is_integer() else ''
    return text(value)


def select_weekly(frame, season, week):
    if frame.empty:
        return frame.copy()
    if not {'season', 'week'}.issubset(frame.columns):
        raise ValueError('Weekly roster requires explicit season and week')
    selected = frame[pd.to_numeric(frame.season, errors='raise').eq(season) &
                     pd.to_numeric(frame.week, errors='raise').eq(week)].copy()
    if 'game_type' in selected:
        selected = selected[selected.game_type.astype(str).str.strip().str.upper().eq('REG')]
    return selected


def identity_index(known):
    result = {'ids':set(known.gsis_id.dropna().map(text)), 'stable':{}}
    for field in STABLE_IDS:
        mapping = {}
        if field in known:
            for external, gsis in zip(known[field], known.gsis_id):
                key, value = stable_text(external), text(gsis)
                if key and value:
                    mapping.setdefault(key, set()).add(value)
        result['stable'][field] = mapping
    return result


def identity(row, index):
    supplied = {text(row.get(c)) for c in ('player_id','gsis_id') if text(row.get(c))}
    nfl_id = text(row.get('nfl_id'))
    if GSIS.fullmatch(nfl_id):
        supplied.add(nfl_id)
    if len(supplied) > 1:
        return None, 'conflicting-authoritative-ids'
    player_id = next(iter(supplied), '')
    matched = []
    for field in STABLE_IDS:
        value = stable_text(row.get(field))
        if value:
            matches = index['stable'][field].get(value, set())
            if len(matches) > 1:
                return None, 'ambiguous-stable-id'
            if matches:
                matched.append(next(iter(matches)))
    if len(set(matched)) > 1:
        return None, 'conflicting-stable-ids'
    if player_id:
        if not GSIS.fullmatch(player_id):
            return None, 'invalid-player-identifiers'
        if matched and matched[0] != player_id:
            return None, 'authoritative-id-conflicts-with-crosswalk'
        if player_id in index['ids']:
            return player_id, 'authoritative-gsis'
        return None, 'authoritative-id-not-in-crosswalk'
    # Two independent stable identifiers must agree. Names are never matched.
    if len(matched) >= 2 and GSIS.fullmatch(matched[0]):
        return matched[0], 'corroborated-stable-ids'
    return None, 'unresolved-player-identifiers'


def resolve_roster(weekly, live, known, season, week, teams=None, historical=False):
    if type(season) is not int or season < 2002 or type(week) is not int or week not in range(1,19):
        raise ValueError('Invalid eligibility season/week')
    selected = select_weekly(weekly, season, week)
    scope = 'target-week roster'
    if selected.empty:
        if historical:
            raise ValueError('Historical eligibility requires a week-specific roster')
        if 'season' not in live:
            raise ValueError('Live roster requires an explicit season')
        selected = live[pd.to_numeric(live.season, errors='raise').eq(season)].copy()
        if teams is not None and 'team' in selected:
            selected = selected[selected.team.map(text).str.upper().isin(teams)].copy()
        if 'game_type' in selected:
            selected = selected[selected.game_type.astype(str).str.strip().str.upper().eq('REG')]
        if 'week' in selected and pd.to_numeric(selected.week, errors='raise').gt(week).any():
            raise ValueError('Live roster is from a later week; cannot reconstruct earlier eligibility')
        scope = 'live season roster retrieved before kickoff; target weekly roster unavailable'
    if not {'team','position','status'}.issubset(selected.columns):
        raise ValueError('Roster requires team, position and status')
    if 'gsis_id' not in known:
        raise ValueError('Player crosswalk requires authoritative GSIS identifiers')
    selected['team'] = selected.team.map(text).str.upper()
    requested = set(teams) if teams is not None else set(selected.team)
    if not requested or not requested.issubset(TEAM_CODES):
        raise ValueError('Invalid scheduled roster teams')
    # Scope before identity checks: unrelated teams can never block this slate.
    selected = selected[selected.team.isin(requested)].copy()
    index = identity_index(known)
    audit = {'policy_version':'week-aware-v1','season':season,'week':week,'scope':scope,
             'scheduled_teams':sorted(requested),'decisions':[], 'counts':{}}
    included = []
    for _, row in selected.iterrows():
        status, position = text(row.get('status')).upper(), text(row.get('position')).upper()
        decision = {'player_id':text(row.get('gsis_id')) or text(row.get('player_id')),
                    'name':text(row.get('full_name')) or text(row.get('model_player_name')),
                    'team':row['team'],'position':position,'roster_status':status,
                    'record_season':season, 'record_week':text(row.get('week')),
                    'decision':'pending','reason':'unknown-roster-status'}
        if status in EXCLUDED_STATUSES:
            decision.update(decision='exclude',reason='explicit-non-active-membership')
        elif position in NON_SKILL_POSITIONS:
            decision.update(decision='exclude',reason='non-skill-position')
        elif position not in SKILL_POSITIONS:
            decision['reason']='unresolved-position'
        elif status == 'ACT':
            player_id, method = identity(row, index)
            if player_id is None:
                decision['reason']=method
            elif not decision['name']:
                decision['reason']='missing-player-name'
            else:
                decision.update(player_id=player_id,decision='include',reason='verified-active-membership',identity_method=method)
                included.append({'player_id':player_id,'model_player_name':decision['name'],
                                 'team':row['team'],'position':position})
        elif status == 'INA':
            decision['reason']='inactive-status-needs-game-specific-resolution'
        audit['decisions'].append(decision)
    counts = Counter(r['player_id'] for r in included)
    for decision in audit['decisions']:
        if decision['decision']=='include' and counts[decision['player_id']]>1:
            decision.update(decision='pending',reason='duplicate-or-ambiguous-player-assignment')
    covered = {r['team'] for r in included}
    for team in sorted(requested-covered):
        if not any(r['team']==team and r['decision']=='pending' for r in audit['decisions']):
            audit['decisions'].append({'player_id':'','name':'','team':team,'position':'','roster_status':'',
                                       'decision':'pending','reason':'missing-team-player-coverage'})
    audit['counts']={key:sum(r['decision']==key for r in audit['decisions']) for key in ('include','exclude','pending')}
    if audit['counts']['pending']:
        raise EligibilityError(audit)
    return pd.DataFrame(included, columns=['player_id','model_player_name','team','position']), audit
