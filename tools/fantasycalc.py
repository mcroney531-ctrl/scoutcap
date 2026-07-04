"""
FantasyCalc value lookups — used to grade the QUALITY of veteran competition,
not just count bodies on a depth chart.

FantasyCalc publishes current dynasty + redraft values via a free, no-auth API.
We map by Sleeper player_id (the same IDs the rest of the app uses).

Key idea: three replaceable veterans ahead of a rookie (all grade D/F) is a SOFT
depth chart and a plus for the rookie; a single grade A/B vet is a real block.
"""

import httpx
from collections import defaultdict
from config.dynasty_config import LEAGUE as _LEAGUE_CFG

_VALUES_URL = "https://api.fantasycalc.com/values/current"

# League-matched params sourced from dynasty_config.py — single source of truth.
_PARAMS = {
    "isDynasty": "true",
    "numQbs": _LEAGUE_CFG["num_qbs"],
    "numTeams": _LEAGUE_CFG["num_teams"],
    "ppr": _LEAGUE_CFG["ppr"],
}

# Grade tiers by rank within position. Near-term competition is ranked by
# redraft value (who actually eats snaps now); dynasty value is kept for context.
# 12-team superflex calibration.
GRADE_TIERS = {
    "QB": [(12, "A"), (20, "B"), (28, "C"), (36, "D")],
    "RB": [(12, "A"), (24, "B"), (36, "C"), (48, "D")],
    "WR": [(12, "A"), (24, "B"), (36, "C"), (54, "D")],
    "TE": [(6, "A"), (12, "B"), (18, "C"), (24, "D")],
}

_cache: dict | None = None


def _load() -> dict:
    """Fetch + index FantasyCalc values once. Returns {sleeper_id: record}.

    Each record carries dynasty/redraft value, dynasty position rank, and a
    computed redraft position rank (derived from the live data so it survives
    any rescaling on FantasyCalc's side).
    """
    global _cache
    if _cache is not None:
        return _cache

    try:
        data = httpx.get(_VALUES_URL, params=_PARAMS, timeout=30).json()
    except Exception:
        _cache = {}
        return _cache

    by_sleeper: dict[str, dict] = {}
    pos_players: dict[str, list] = defaultdict(list)

    for d in data:
        p = d.get("player", {})
        sid = p.get("sleeperId")
        if not sid:
            continue
        rec = {
            "name": p.get("name"),
            "position": p.get("position"),
            "team": p.get("maybeTeam"),
            "age": p.get("maybeAge"),
            "years_exp": p.get("maybeYoe"),
            "dynasty_value": d.get("value") or 0,
            "redraft_value": d.get("redraftValue") or 0,
            "dynasty_pos_rank": d.get("positionRank"),
            "redraft_pos_rank": None,  # filled below
        }
        by_sleeper[sid] = rec
        pos_players[p.get("position")].append(sid)

    # Compute redraft position ranks from the live data
    for pos, sids in pos_players.items():
        sids.sort(key=lambda s: by_sleeper[s]["redraft_value"], reverse=True)
        for i, sid in enumerate(sids):
            by_sleeper[sid]["redraft_pos_rank"] = i + 1

    _cache = by_sleeper
    return _cache


def value_grade(position: str, redraft_pos_rank: int | None) -> str:
    """Letter grade for a competitor from their redraft rank within position."""
    if redraft_pos_rank is None:
        return "F"
    for thresh, grade in GRADE_TIERS.get(position, []):
        if redraft_pos_rank <= thresh:
            return grade
    return "F"


def get_player_value(sleeper_id) -> dict | None:
    """Return the FantasyCalc record for a Sleeper player_id, or None if absent.

    Absent = outside the dynasty-relevant pool (~460 players) = replaceable.
    """
    return _load().get(str(sleeper_id))
