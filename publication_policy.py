"""Shared live-data boundary and freshness policy; no network or write operations."""
import re
import subprocess
from datetime import timedelta
from pathlib import Path
from weekly_schedule import kickoff, utc

REPOSITORY = Path(__file__).resolve().parent
LIVE_ROOTS = (REPOSITORY / 'td-predictor-web/public/data', REPOSITORY / 'public/data')


def is_live_path(path):
    resolved = Path(path).resolve()
    return any(resolved.is_relative_to(root.resolve()) for root in LIVE_ROOTS)


def require_review_checkout(path, historical=False):
    if not is_live_path(path):
        return
    if Path(path).resolve() != LIVE_ROOTS[0].resolve() or historical:
        raise ValueError('Live data requires the reviewed pregame publication pipeline')
    branch = subprocess.check_output(['git', '-C', str(REPOSITORY), 'branch', '--show-current']).decode().strip()
    if not re.fullmatch(r'nfl-pm/publication/[0-9]+-[0-9]+', branch):
        raise ValueError('Live manifest staging requires a reviewed publication review branch')


def fresh(board, receipt, now):
    now = utc(now)
    remaining = min(kickoff(g) for g in board['meta']['games']) - now
    if remaining <= timedelta(minutes=10):
        raise ValueError('Kickoff safety margin exhausted')
    limit = (timedelta(minutes=30) if remaining <= timedelta(hours=6) else
             timedelta(hours=6) if remaining <= timedelta(hours=48) else timedelta(hours=24))
    for timestamp in (board['meta']['generated_at'], receipt['source_cutoff_utc']):
        age = now - utc(timestamp)
        if age < timedelta(0) or age >= limit:
            raise ValueError('Stale predictions or source cutoff; regenerate')
