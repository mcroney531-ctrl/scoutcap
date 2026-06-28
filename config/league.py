"""Hardcoded league settings — one specific league, not a generalized product."""

LEAGUE = {
    "rounds": 4,
    "picks_per_round": 12,
    "total_picks": 48,
    "scoring": "PPR",
    "roster_spots": {
        "QB": 1,
        "RB": 2,
        "WR": 2,
        "TE": 1,
        "FLEX": 2,   # RB/WR/TE
        "SF": 1,     # Superflex (QB/RB/WR/TE) — update if not superflex
        "BN": 20,
    },
    "notes": "Update SF to False and remove if not a superflex league.",
}

# Composite weighting — locked, uniform across all positions
WEIGHTS = {
    "talent": 0.43,
    "opportunity": 0.38,
    "risk": 0.15,
    "sentiment": 0.04,
}

# Roster need priority order — positions where depth is thinnest matter most
# This is computed live from Sleeper, but positional value tiebreaker is here
POSITION_VALUE = {"QB": 1.15, "RB": 1.0, "WR": 1.0, "TE": 0.95}
