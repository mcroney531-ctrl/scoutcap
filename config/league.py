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

# Positional value multipliers — applied to the composite before pick mapping.
# Superflex-tuned: QBs carry a real premium because they can start in the SF slot.
# A value of 1.18 pushes a high-composite QB up roughly a full round vs. a flex player.
POSITION_VALUE = {"QB": 1.18, "RB": 1.0, "WR": 1.0, "TE": 0.95}

# Non-linear score → pick mapping (logistic curve).
# midpoint  = composite score that lands around the round-2/round-3 turn
# steepness = how sharply value changes near the midpoint
# The curve compresses the elite tier (90+ all cluster in round 1, a few picks apart)
# and flattens the late rounds (sub-50 composites bunch into rounds 3-4).
PICK_CURVE = {"midpoint": 68.0, "steepness": 0.10}
