"""Hardcoded league settings — one specific league, not a generalized product.
Roster positions verified against Sleeper API 2026-07-04.
"""

# The rookie class Scout is built around: the Sleeper board (years_exp == 0),
# the ESPN draft lookups, the Mock Draft's pick season and every "<year> rookie
# class" label read this one value.
#
# Rollover is deliberately manual. Change DRAFT_CLASS_YEAR only when the whole
# Scout experience is intentionally moving to the next rookie class and its
# Sleeper and ESPN data sources support that class consistently. Never derive it
# from the calendar: in late 2026 the Sleeper rookie board is still the 2026
# class, so a date-based switch to 2027 would split the app across two classes.
# (The "most recent completed college season" used for college stats is a
# different, deliberately calendar-based clock; see agents/production_agent.py.)
DRAFT_CLASS_YEAR = 2026

LEAGUE = {
    "rounds": 4,
    "picks_per_round": 12,
    "total_picks": 48,
    "scoring": "half-PPR",
    "roster_spots": {
        "QB": 1,
        "RB": 2,
        "WR": 3,
        "TE": 1,
        "FLEX": 1,   # RB/WR/TE
        "SF": 1,     # SUPER_FLEX (QB/RB/WR/TE)
        "K": 1,
        "BN": 14,
        "TAXI": 4,
        "IR": 4,
    },
}



def validate_league_shape(league: dict) -> None:
    """The Mock Draft board, pick labels and score -> pick mapping all assume
    total_picks == rounds * picks_per_round. Fail loudly if that stops being true."""
    rounds, per_round, total = league["rounds"], league["picks_per_round"], league["total_picks"]
    if rounds < 1 or per_round < 1 or total != rounds * per_round:
        raise ValueError(
            f"Invalid league shape: total_picks={total} must equal rounds={rounds} x "
            f"picks_per_round={per_round} (both at least 1)."
        )


validate_league_shape(LEAGUE)

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
