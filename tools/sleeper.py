"""Scout Sleeper facade over shared dynasty_core.sleeper.

Provider/network behavior lives in dynasty_core. This module keeps Scout's
existing public names as aliases so callers don't churn, plus Scout-specific
player-search policy (search_players).
"""

from dynasty_core.sleeper import (
    get_user,
    get_leagues,
    get_league_rosters as get_rosters,
    get_league_users as get_users_in_league,
    get_all_players as get_nfl_players,
    get_player,
    get_trending,
)

__all__ = [
    "get_user",
    "get_leagues",
    "get_rosters",
    "get_users_in_league",
    "get_nfl_players",
    "get_player",
    "get_trending",
    "search_players",
]


def search_players(name: str) -> list[dict]:
    """Scout-specific name search over the shared cached player catalog:
    case-insensitive substring match on full_name, QB/RB/WR/TE only."""
    all_players = get_nfl_players()
    name_lower = name.lower()
    return [
        {"player_id": pid, **p}
        for pid, p in all_players.items()
        if name_lower in (p.get("full_name") or "").lower()
        and p.get("position") in ("QB", "RB", "WR", "TE")
    ]
