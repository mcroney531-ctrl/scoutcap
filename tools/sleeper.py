import httpx

BASE = "https://api.sleeper.app/v1"


def get_user(username: str) -> dict:
    r = httpx.get(f"{BASE}/user/{username}")
    r.raise_for_status()
    return r.json()


def get_leagues(user_id: str, season: str = "2025") -> list:
    r = httpx.get(f"{BASE}/user/{user_id}/leagues/nfl/{season}")
    r.raise_for_status()
    return r.json()


def get_rosters(league_id: str) -> list:
    r = httpx.get(f"{BASE}/league/{league_id}/rosters")
    r.raise_for_status()
    return r.json()


def get_users_in_league(league_id: str) -> list:
    r = httpx.get(f"{BASE}/league/{league_id}/users")
    r.raise_for_status()
    return r.json()


def get_nfl_players() -> dict:
    """Full player map — large (~5MB). Cache locally after first fetch."""
    r = httpx.get(f"{BASE}/players/nfl", timeout=30)
    r.raise_for_status()
    return r.json()


def get_player(player_id: str) -> dict | None:
    """Look up a single player by Sleeper player_id."""
    r = httpx.get(f"{BASE}/players/nfl/{player_id}")
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def search_players(name: str) -> list[dict]:
    """Search all NFL players by name (full player map — cache externally)."""
    all_players = get_nfl_players()
    name_lower = name.lower()
    return [
        {"player_id": pid, **p}
        for pid, p in all_players.items()
        if name_lower in (p.get("full_name") or "").lower()
        and p.get("position") in ("QB", "RB", "WR", "TE")
    ]


def get_trending(type: str = "add", sport: str = "nfl", limit: int = 25) -> list:
    r = httpx.get(f"{BASE}/players/{sport}/trending/{type}", params={"limit": limit})
    r.raise_for_status()
    return r.json()
