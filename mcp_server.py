"""
Rookie Scout — MCP server.

Exposes the dynasty rookie scouting capabilities over the Model Context Protocol so
any MCP client (Claude Desktop, etc.) can use them. Two layers:

  • Granular data tools  — search prospects, opportunity, draft capital, veteran
    competition quality, dynasty value, college production, injury history.
  • High-level pipeline  — scout_rookie() runs the full 3-agent evaluation and
    returns the structured draft recommendation.

Run (stdio transport):
    python mcp_server.py

Claude Desktop config (claude_desktop_config.json):
    {
      "mcpServers": {
        "rookie-scout": {
          "command": "D:\\\\venvs\\\\kaggleproj312\\\\Scripts\\\\python.exe",
          "args": ["C:\\\\Users\\\\myfit\\\\OneDrive\\\\Documents\\\\KaggleProj\\\\mcp_server.py"]
        }
      }
    }
"""

import os, sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from mcp.server.fastmcp import FastMCP

# Reuse the existing tool layer — no logic duplicated.
from tools.sleeper import search_players, get_trending, get_nfl_players
from tools.espn import search_draft_prospects
from tools.fantasycalc import get_player_value, value_grade
from agents.situation_agent import (
    lookup_player_opportunity,
    lookup_draft_capital,
    assess_veteran_competition,
)
from agents.production_agent import (
    lookup_draft_prospect_info,
    get_career_college_stats,
    get_injury_history,
)
from agents.synthesis_agent import run_synthesis_agent

mcp = FastMCP("rookie-scout")


def _best_match(name: str) -> dict | None:
    """Pick the most relevant Sleeper player for a name (rookies first)."""
    matches = search_players(name)
    if not matches:
        return None
    rookies = [p for p in matches if p.get("years_exp") == 0]
    pool = rookies if rookies else matches
    pool.sort(key=lambda p: p.get("search_rank") or 9999999)
    return pool[0]


# ── Granular data tools ───────────────────────────────────────────────────────

@mcp.tool()
def search_prospects(name: str) -> list:
    """Search the 2026 NFL draft class (ESPN) by name. Returns matching prospects
    with draft capital, ESPN scout grade, and ESPN ranks."""
    return search_draft_prospects(name, season=2026)


@mcp.tool()
def player_opportunity(name: str) -> dict:
    """Sleeper opportunity signals for a rookie: team, depth chart order/position,
    status, and injury status."""
    return lookup_player_opportunity(name)


@mcp.tool()
def draft_capital(name: str) -> dict:
    """NFL draft capital for a rookie from ESPN: round, pick, scout grade,
    overall and positional ranks."""
    return lookup_draft_capital(name)


@mcp.tool()
def veteran_competition(team: str, position: str) -> dict:
    """Grade the QUALITY of veteran competition at a team+position (FantasyCalc).
    Distinguishes a soft room of replaceable D/F vets from an entrenched A/B starter.
    team: NFL abbreviation (e.g. 'WAS'); position: QB/RB/WR/TE."""
    return assess_veteran_competition(team, position)


@mcp.tool()
def dynasty_value(name: str) -> dict:
    """Dynasty + redraft value for any player (rookie or veteran) from FantasyCalc,
    with a positional grade. 12-team superflex PPR settings."""
    p = _best_match(name)
    if not p:
        return {"error": f"No player found matching '{name}'"}
    v = get_player_value(p.get("player_id"))
    if not v:
        return {
            "name": p.get("full_name"),
            "position": p.get("position"),
            "found_in_fantasycalc": False,
            "note": "Outside FantasyCalc's dynasty-relevant pool (~460 players) — replaceable.",
        }
    return {
        "name": p.get("full_name"),
        "position": p.get("position"),
        "found_in_fantasycalc": True,
        "grade": value_grade(p.get("position"), v.get("redraft_pos_rank")),
        **v,
    }


@mcp.tool()
def college_production(name: str) -> dict:
    """Career college production stats for a draft prospect (ESPN)."""
    prospect = lookup_draft_prospect_info(name)
    aid = prospect.get("espn_athlete_id")
    if not aid:
        return {"error": f"Could not resolve ESPN athlete ID for '{name}'", "prospect": prospect}
    return get_career_college_stats(aid)


@mcp.tool()
def injury_history(name: str) -> dict:
    """Historical injury records for a draft prospect (ESPN)."""
    prospect = lookup_draft_prospect_info(name)
    aid = prospect.get("espn_athlete_id")
    if not aid:
        return {"error": f"Could not resolve ESPN athlete ID for '{name}'", "prospect": prospect}
    return get_injury_history(aid)


@mcp.tool()
def trending_adds(limit: int = 25) -> dict:
    """Current Sleeper trending-add activity (raw crowd interest signal)."""
    trending = get_trending("add", limit=limit)
    players = get_nfl_players()
    out = []
    for t in trending:
        p = players.get(t.get("player_id"), {})
        if p.get("position") in ("QB", "RB", "WR", "TE"):
            out.append({
                "name": p.get("full_name"),
                "position": p.get("position"),
                "team": p.get("team"),
                "add_count": t.get("count"),
            })
    return {"trending_adds": out}


# ── High-level pipeline tool ──────────────────────────────────────────────────

@mcp.tool()
async def scout_rookie(player_name: str) -> dict:
    """Run the full 3-agent scouting pipeline (Situation + Production + Synthesis)
    and return the structured dynasty draft recommendation: talent/opportunity
    grades, risk modifier, veteran competition, composite score, and the
    recommended/floor/ceiling pick in round.pick notation."""
    return await run_synthesis_agent(player_name)


if __name__ == "__main__":
    mcp.run()
