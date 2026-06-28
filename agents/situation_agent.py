"""
Situation Agent — evaluates opportunity only, independent of talent.

Inputs:  player name
Outputs: structured opportunity assessment with Opportunity Grade (0-100 → letter)
"""

import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from tools.sleeper import search_players, get_nfl_players, get_trending
from tools.espn import search_draft_prospects

# ── ADK tool functions ────────────────────────────────────────────────────────

def lookup_player_opportunity(player_name: str) -> dict:
    """
    Look up a rookie's opportunity signals from Sleeper:
    - depth_chart_order (1 = starter, higher = deeper backup)
    - depth_chart_position (e.g. LWR, RB1)
    - team, status, injury_status
    Returns the best match for the given name.
    """
    matches = search_players(player_name)
    if not matches:
        return {"error": f"No player found matching '{player_name}'"}

    # Prefer year-0 rookies (2026 class), then most relevant by search_rank
    rookies = [p for p in matches if p.get("years_exp") == 0]
    pool = rookies if rookies else matches
    pool.sort(key=lambda p: p.get("search_rank") or 9999999)
    p = pool[0]

    return {
        "player_id": p.get("player_id"),
        "full_name": p.get("full_name"),
        "position": p.get("position"),
        "team": p.get("team"),
        "depth_chart_order": p.get("depth_chart_order"),
        "depth_chart_position": p.get("depth_chart_position"),
        "status": p.get("status"),
        "injury_status": p.get("injury_status"),
        "years_exp": p.get("years_exp"),
    }


def lookup_draft_capital(player_name: str) -> dict:
    """
    Look up a rookie's NFL draft capital from ESPN:
    - draft_round, draft_pick, draft_overall
    - espn_grade, espn_overall_rank, espn_position_rank
    Returns best name match from the 2026 draft class.
    """
    results = search_draft_prospects(player_name, season=2026)
    if not results:
        return {"error": f"No ESPN draft prospect found matching '{player_name}'"}
    return results[0]


def get_position_depth(team: str, position: str) -> dict:
    """
    Return all players at a given position on a given team, ordered by depth_chart_order.
    Useful for assessing how crowded the depth chart is.
    team: NFL team abbreviation (e.g. 'ARI', 'TEN')
    position: 'QB', 'RB', 'WR', or 'TE'
    """
    all_players = get_nfl_players()
    depth = [
        {
            "name": p.get("full_name"),
            "depth_chart_order": p.get("depth_chart_order"),
            "depth_chart_position": p.get("depth_chart_position"),
            "years_exp": p.get("years_exp"),
            "status": p.get("status"),
        }
        for p in all_players.values()
        if p.get("team") == team
        and p.get("position") == position
        and p.get("depth_chart_order") is not None
    ]
    depth.sort(key=lambda x: x["depth_chart_order"] or 99)
    return {"team": team, "position": position, "depth_chart": depth}


def get_trending_sentiment(limit: int = 50) -> dict:
    """
    Return trending add data from Sleeper for the current draft class context.
    Used by Synthesis — exposed here so Situation can optionally note it.
    """
    trending = get_trending("add", limit=limit)
    all_players = get_nfl_players()
    result = []
    for t in trending:
        pid = t.get("player_id")
        p = all_players.get(pid, {})
        if p.get("position") in ("QB", "RB", "WR", "TE"):
            result.append({
                "player_id": pid,
                "name": p.get("full_name"),
                "position": p.get("position"),
                "team": p.get("team"),
                "add_count": t.get("count"),
            })
    return {"trending_adds": result, "note": "Counts reflect raw platform activity — interpret relative to each other, not as absolute thresholds."}


# ── Calibration anchors (baked into system prompt) ────────────────────────────

OPPORTUNITY_CALIBRATION = """
Opportunity Grade calibration anchors (0-100):
- 95-100 (A+): Day-1 starter on a contending team with no competition, elite scheme fit, multi-year window
- 85-94  (A/A-): Clear starter, minimal competition, good scheme, good team
- 75-84  (B+/B): Likely starter but meaningful competition OR suboptimal scheme/team
- 65-74  (B-/C+): Legitimate role but sharing touches or unclear depth chart
- 50-64  (C/C-): Backup with a path, or starter on a very run-heavy/pass-light team
- 35-49  (D+/D): Deep backup or blocked by established veteran
- 0-34   (D-/F): No clear path to meaningful touches this season

Letter grade conversion:
97-100→A+, 93-96→A, 90-92→A-, 87-89→B+, 83-86→B, 80-82→B-,
77-79→C+, 73-76→C, 70-72→C-, 67-69→D+, 63-66→D, 60-62→D-, <60→F
"""

SYSTEM_PROMPT = f"""You are the Situation Agent for a dynasty fantasy football rookie draft tool.

Your job: evaluate a rookie's OPPORTUNITY only — completely independent of how talented they are.
Do not factor in college production, athleticism, or draft pedigree in your grade.
Focus entirely on: landing spot quality, depth chart position, scheme fit, team context, and competition for snaps.

{OPPORTUNITY_CALIBRATION}

Tools available:
- lookup_player_opportunity: Get Sleeper depth chart data for the player
- lookup_draft_capital: Get ESPN draft round/pick and scout grades
- get_position_depth: See the full depth chart at their position on their team
- get_trending_sentiment: Optional — Sleeper trending adds for context

Steps:
1. Call lookup_player_opportunity to get depth chart and team
2. Call lookup_draft_capital to get draft round/pick
3. Call get_position_depth to assess depth chart crowding
4. Synthesize into an Opportunity Grade (numeric 0-100, then letter)

Output format — always return a JSON object with these exact keys:
{{
  "player": "Full Name",
  "position": "WR",
  "team": "TEN",
  "draft_round": 1,
  "draft_pick": 8,
  "depth_chart_order": 1,
  "opportunity_score": 82,
  "opportunity_grade": "B",
  "key_factors": ["WR1 on depth chart", "pass-heavy offense", "crowded room — 2 other WRs drafted"],
  "concerns": ["offensive line uncertainty may limit explosive plays"],
  "summary": "Two-sentence plain-English summary of opportunity outlook."
}}
"""

# ── Agent + runner setup ──────────────────────────────────────────────────────

def build_situation_agent() -> LlmAgent:
    return LlmAgent(
        model=LiteLlm(model="anthropic/claude-sonnet-4-6", api_key=os.getenv("ANTHROPIC_API_KEY")),
        name="situation_agent",
        instruction=SYSTEM_PROMPT,
        tools=[
            lookup_player_opportunity,
            lookup_draft_capital,
            get_position_depth,
            get_trending_sentiment,
        ],
    )


async def run_situation_agent(player_name: str) -> dict:
    """Run the Situation Agent for a given player. Returns parsed JSON output."""
    agent = build_situation_agent()
    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name="rookie_scout", session_service=session_service)

    session = await session_service.create_session(
        app_name="rookie_scout", user_id="user", session_id="sit_session"
    )

    message = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=f"Evaluate the opportunity for {player_name}")]
    )

    result_text = ""
    async for event in runner.run_async(
        user_id="user", session_id="sit_session", new_message=message
    ):
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if part.text:
                    result_text += part.text

    # Parse JSON from response
    import re
    json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group())
    return {"raw_output": result_text}


# ── CLI test entry point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    player = sys.argv[1] if len(sys.argv) > 1 else "Jeremiyah Love"
    print(f"Running Situation Agent for: {player}\n")
    result = asyncio.run(run_situation_agent(player))
    print(json.dumps(result, indent=2))
