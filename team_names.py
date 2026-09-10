TEAM_NAMES = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs", "LA": "Los Angeles Rams", "LAC": "Los Angeles Chargers",
    "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings",
    "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
}

# Common alternate spellings/nicknames people might type, mapped to the
# real nflverse code. "LAR"/"RAMS" -> "LA" is exactly the bug this fixes.
TEAM_ALIASES = {
    "LAR": "LA", "RAMS": "LA", "LOS ANGELES RAMS": "LA",
    "PATRIOTS": "NE", "NEW ENGLAND": "NE",
    "SEAHAWKS": "SEA", "NINERS": "SF", "49ERS": "SF",
    "JAGS": "JAX", "JAGUARS": "JAX",
    "WASHINGTON": "WAS", "COMMANDERS": "WAS",
    "GIANTS": "NYG", "JETS": "NYJ",
    "CHARGERS": "LAC", "RAIDERS": "LV",
    "PACKERS": "GB", "BUCS": "TB", "BUCCANEERS": "TB",
}


def resolve_team_code(raw: str) -> str | None:
    """Turn free-typed text into a real nflverse team code, or None if unrecognized."""
    key = raw.strip().upper()
    if key in TEAM_NAMES:
        return key
    if key in TEAM_ALIASES:
        return TEAM_ALIASES[key]
    return None