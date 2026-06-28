import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed

NFL_BASE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
CFB_BASE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"

# Module-level cache: built once per process, reused across all lookups
_draft_roster_cache: dict | None = None


def _get(url: str, **params) -> dict:
    r = httpx.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _resolve_draft_athlete(url: str) -> dict | None:
    """Resolve a single draft athlete ref to a summary dict."""
    try:
        a = _get(url)
        athlete_id = url.split("/athletes/")[1].split("?")[0]

        pick_ref = (a.get("pick") or {}).get("$ref")
        round_num = pick_num = overall = None
        if pick_ref:
            try:
                pd = _get(pick_ref)
                round_num = pd.get("round")
                pick_num = pd.get("pick")
                overall = pd.get("overall")
            except Exception:
                pass

        attrs = {x["name"]: x.get("value") for x in (a.get("attributes") or [])}
        athlete_ref = (a.get("athlete") or {}).get("$ref", "")

        return {
            "espn_id": athlete_id,
            "name": (a.get("displayName") or "").strip(),
            "position": (a.get("position") or {}).get("abbreviation"),
            "draft_round": round_num,
            "draft_pick": pick_num,
            "draft_overall": overall,
            "espn_grade": attrs.get("grade"),
            "espn_overall_rank": attrs.get("overall"),
            "espn_position_rank": attrs.get("rank"),
            "athlete_ref": athlete_ref,
        }
    except Exception:
        return None


def _build_draft_roster(season: int = 2026) -> dict:
    """
    Fetch all draft athletes for a season in parallel and return a
    name-keyed index: {lower_name: prospect_dict}.
    Called once per process; result cached in module-level variable.
    """
    # Collect all athlete refs
    refs = []
    page, limit = 1, 100
    while True:
        data = _get(f"{NFL_BASE}/seasons/{season}/draft/athletes", limit=limit, page=page)
        refs.extend(item["$ref"] for item in data.get("items", []))
        if page * limit >= data.get("count", 0):
            break
        page += 1

    # Resolve in parallel — 20 workers keeps ESPN happy
    index: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(_resolve_draft_athlete, url): url for url in refs}
        for future in as_completed(futures):
            result = future.result()
            if result and result.get("name"):
                index[result["name"].lower()] = result

    return index


def _get_draft_roster(season: int = 2026) -> dict:
    global _draft_roster_cache
    if _draft_roster_cache is None:
        _draft_roster_cache = _build_draft_roster(season)
    return _draft_roster_cache


def search_draft_prospects(name: str, season: int = 2026) -> list[dict]:
    """
    Search draft prospects by name. Fast: uses cached parallel-built roster index.
    Returns list of matches sorted by closeness of name match.
    """
    roster = _get_draft_roster(season)
    name_lower = name.lower()
    matches = [v for k, v in roster.items() if name_lower in k]
    matches.sort(key=lambda p: (
        0 if p["name"].lower() == name_lower else
        1 if p["name"].lower().startswith(name_lower) else 2
    ))
    return matches


def get_espn_athlete_id(draft_athlete_id: str, season: int = 2026) -> str | None:
    """
    Resolve a draft athlete ID to the base ESPN athlete (college-football) ID.
    First checks the roster cache for speed, falls back to live fetch.
    """
    roster = _get_draft_roster(season)
    for prospect in roster.values():
        if prospect.get("espn_id") == draft_athlete_id:
            athlete_ref = prospect.get("athlete_ref", "")
            if athlete_ref:
                try:
                    ra = _get(athlete_ref)
                    return ra.get("id")
                except Exception:
                    pass

    # Fallback: live fetch
    r = httpx.get(f"{NFL_BASE}/seasons/{season}/draft/athletes/{draft_athlete_id}", timeout=15)
    if r.status_code != 200:
        return None
    athlete_ref = (r.json().get("athlete") or {}).get("$ref")
    if not athlete_ref:
        return None
    ra = httpx.get(athlete_ref, timeout=15)
    return ra.json().get("id") if ra.status_code == 200 else None


def get_draft_prospect(espn_athlete_id: str, season: int = 2026) -> dict:
    """Return draft capital + basic info for a prospect by draft athlete ID."""
    roster = _get_draft_roster(season)
    for prospect in roster.values():
        if prospect.get("espn_id") == espn_athlete_id:
            return prospect
    return {"error": f"Draft athlete {espn_athlete_id} not found"}


def get_college_stats(espn_athlete_id: str, season: int | None = None) -> dict:
    """
    Fetch college production stats for an athlete.
    season=None returns career totals; season=2024 returns that year's regular season.
    """
    if season:
        url = f"{CFB_BASE}/seasons/{season}/types/2/athletes/{espn_athlete_id}/statistics/0"
    else:
        url = f"{CFB_BASE}/athletes/{espn_athlete_id}/statistics/0"

    r = httpx.get(url, timeout=15)
    if r.status_code == 404:
        return {"error": f"No college stats found for ESPN athlete {espn_athlete_id}"}
    r.raise_for_status()
    data = r.json()

    result: dict = {"espn_id": espn_athlete_id, "season": season or "career"}
    for cat in data.get("splits", {}).get("categories", []):
        abbr = cat.get("abbreviation", "").lower()
        if abbr not in ("rush", "rec", "gen", "s"):
            continue
        for stat in cat.get("stats", []):
            key = f"{abbr}_{stat.get('abbreviation', '').lower()}"
            result[key] = stat.get("displayValue")

    return result


def get_nfl_injuries(espn_athlete_id: str) -> dict:
    """Fetch historical injury records for an athlete from ESPN."""
    r = httpx.get(f"{NFL_BASE}/athletes/{espn_athlete_id}/injuries", timeout=15)
    if r.status_code == 404:
        return {"espn_id": espn_athlete_id, "injuries": [], "note": "No injury history found"}
    r.raise_for_status()
    data = r.json()
    injuries = []
    for item in data.get("items", []):
        injuries.append({
            "date": item.get("date"),
            "type": item.get("type", {}).get("text"),
            "detail": item.get("details", {}).get("detail"),
            "side": item.get("details", {}).get("side"),
            "return_date": item.get("details", {}).get("returnDate"),
        })
    return {"espn_id": espn_athlete_id, "injuries": injuries}


def get_nfl_team(team_ref: str) -> dict:
    """Resolve an NFL team ref to name/abbreviation."""
    data = _get(team_ref)
    return {
        "id": data.get("id"),
        "name": data.get("displayName"),
        "abbreviation": data.get("abbreviation"),
        "location": data.get("location"),
    }
