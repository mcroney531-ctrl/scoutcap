"""
Production Agent — evaluates talent only, independent of situation.
Also computes the Risk Modifier (durability score 1-5 + injury % chance)
folded in as an internal input to the Talent Grade.

Inputs:  player name
Outputs: structured talent assessment + risk modifier
"""

import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from tools.sleeper import search_players
from tools.espn import search_draft_prospects, get_college_stats, get_nfl_injuries, get_espn_athlete_id

# ── ADK tool functions ────────────────────────────────────────────────────────

def lookup_player_info(player_name: str) -> dict:
    """
    Look up a rookie's basic profile and current injury/practice status from Sleeper.
    Returns name, position, team, status, injury_status, injury_start_date,
    practice_participation, college, age.
    """
    matches = search_players(player_name)
    if not matches:
        return {"error": f"No player found matching '{player_name}'"}

    rookies = [p for p in matches if p.get("years_exp") == 0]
    pool = rookies if rookies else matches
    pool.sort(key=lambda p: p.get("search_rank") or 9999999)
    p = pool[0]

    return {
        "player_id": p.get("player_id"),
        "full_name": p.get("full_name"),
        "position": p.get("position"),
        "team": p.get("team"),
        "college": p.get("college"),
        "age": p.get("age"),
        "years_exp": p.get("years_exp"),
        "status": p.get("status"),
        "injury_status": p.get("injury_status"),
        "injury_start_date": p.get("injury_start_date"),
        "practice_participation": p.get("practice_participation"),
    }


def lookup_draft_prospect_info(player_name: str) -> dict:
    """
    Look up a rookie's ESPN draft profile: draft round/pick, ESPN scout grade,
    ESPN overall rank, ESPN position rank, weight, height, position.
    Also returns the ESPN athlete ID needed for college stats and injury lookups.
    """
    results = search_draft_prospects(player_name, season=2026)
    if not results:
        return {"error": f"No ESPN draft prospect found matching '{player_name}'"}
    prospect = results[0]

    # Resolve the ESPN athlete (college-football) ID for stat/injury lookups
    draft_id = prospect.get("espn_id")
    athlete_id = get_espn_athlete_id(draft_id) if draft_id else None
    prospect["espn_athlete_id"] = athlete_id
    return prospect


def get_career_college_stats(espn_athlete_id: str) -> dict:
    """
    Fetch career college production stats (rushing, receiving, scoring) for an athlete.
    espn_athlete_id: the ESPN athlete ID (not the draft ID), e.g. '4870808'.
    """
    return get_college_stats(espn_athlete_id, season=None)


def get_recent_college_stats(espn_athlete_id: str, season: int = 2024) -> dict:
    """
    Fetch single-season college production stats for an athlete.
    espn_athlete_id: the ESPN athlete ID (not the draft ID).
    season: e.g. 2024 for their final college season.
    """
    return get_college_stats(espn_athlete_id, season=season)


def get_injury_history(espn_athlete_id: str) -> dict:
    """
    Fetch historical injury records for an athlete from ESPN.
    espn_athlete_id: the ESPN athlete ID.
    Returns a list of past injuries with type, detail, and dates.
    """
    return get_nfl_injuries(espn_athlete_id)


# ── Calibration anchors ───────────────────────────────────────────────────────

TALENT_CALIBRATION = """
Talent Grade calibration anchors (0-100) — evaluate production and athleticism ONLY, ignore landing spot:
- 95-100 (A+): Historically elite college producer, multi-year dominant, elite measurables, top-5 pick talent
- 85-94  (A/A-): Top-tier producer, dominant final season, clear Day-1 first-round talent
- 75-84  (B+/B): Strong producer, above-average measurables, mid-first to early-second talent
- 65-74  (B-/C+): Solid producer with clear tools, developmental upside, Day-2 talent
- 50-64  (C/C-): Inconsistent production or limited sample, raw athleticism, Day-3 range
- 35-49  (D+/D): Thin production, scheme-dependent stats, limited athleticism indicators
- 0-34   (D-/F): Minimal production evidence, major athletic question marks

Letter grade conversion:
97-100→A+, 93-96→A, 90-92→A-, 87-89→B+, 83-86→B, 80-82→B-,
77-79→C+, 73-76→C, 70-72→C-, 67-69→D+, 63-66→D, 60-62→D-, <60→F

Risk Modifier — durability score 1-5 (5 = most durable) and injury chance %:
- 5 / <10%: No injury history, full practice participation, no known concerns
- 4 / 10-20%: Minor injury history (e.g. single soft-tissue issue), fully healthy now
- 3 / 20-35%: Moderate history (1-2 significant injuries) or current minor limitation
- 2 / 35-50%: Recurrent injuries or a significant structural injury (ACL, shoulder labrum)
- 1 / >50%: Multiple structural injuries or chronic durability concerns
"""

SYSTEM_PROMPT = f"""You are the Production Agent for a dynasty fantasy football rookie draft tool.

Your job: evaluate a rookie's TALENT only — completely independent of their landing spot or opportunity.
Focus on: college production volume and efficiency, athletic profile (size/speed/draft grade),
positional value, and durability (Risk Modifier).

{TALENT_CALIBRATION}

Tools available:
- lookup_player_info: Basic profile + live injury/practice status from Sleeper
- lookup_draft_prospect_info: ESPN draft grade, round/pick, ESPN athlete ID
- get_career_college_stats: Career college production totals
- get_recent_college_stats: Final season college stats (default 2024)
- get_injury_history: Historical injury record from ESPN

Steps:
1. Call lookup_player_info for basic profile and live injury status
2. Call lookup_draft_prospect_info for draft grade and ESPN athlete ID
3. Call get_career_college_stats and get_recent_college_stats using the espn_athlete_id
4. Call get_injury_history using the espn_athlete_id
5. Compute Risk Modifier from injury history + current status
6. Synthesize all into a Talent Grade

Key stats to weight for skill positions:
- RB: rushing yards/game, yards per carry, TD rate, receiving involvement, workload durability
- WR: receiving yards/game, yards per reception, TD rate, target share context, route running indicators
- QB: completion %, yards/attempt, TD/INT ratio, rushing contribution
- TE: receiving yards, TD rate, inline vs. move TE profile

Output format — always return a JSON object with these exact keys:
{{
  "player": "Full Name",
  "position": "RB",
  "college": "Notre Dame",
  "espn_athlete_id": "4870808",
  "draft_round": 1,
  "draft_pick": 3,
  "espn_grade": 94.0,
  "key_stats": {{
    "career_rush_yards": "2882",
    "career_rush_tds": "XX",
    "final_season_rush_yards": "949",
    "final_season_ypc": "7.1",
    "final_season_games": "12",
    "final_season_rec": "22",
    "final_season_rec_yards": "206"
  }},
  "risk_modifier": {{
    "durability_score": 4,
    "injury_chance_pct": 15,
    "injury_notes": "Brief description of any relevant injury history"
  }},
  "talent_score": 88,
  "talent_grade": "B+",
  "key_factors": ["bullet points on what drives the grade"],
  "concerns": ["any talent/production concerns"],
  "summary": "Two-sentence plain-English summary of talent outlook."
}}
"""

# ── Agent + runner ────────────────────────────────────────────────────────────

def build_production_agent() -> LlmAgent:
    return LlmAgent(
        model=LiteLlm(model="anthropic/claude-sonnet-4-6"),
        name="production_agent",
        instruction=SYSTEM_PROMPT,
        tools=[
            lookup_player_info,
            lookup_draft_prospect_info,
            get_career_college_stats,
            get_recent_college_stats,
            get_injury_history,
        ],
    )


async def run_production_agent(player_name: str) -> dict:
    """Run the Production Agent for a given player. Returns parsed JSON output."""
    agent = build_production_agent()
    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name="rookie_scout", session_service=session_service)

    session = await session_service.create_session(
        app_name="rookie_scout", user_id="user", session_id="prod_session"
    )

    message = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=f"Evaluate the talent and production for {player_name}")]
    )

    result_text = ""
    async for event in runner.run_async(
        user_id="user", session_id="prod_session", new_message=message
    ):
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if part.text:
                    result_text += part.text

    json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group())
    return {"raw_output": result_text}


if __name__ == "__main__":
    import asyncio
    player = sys.argv[1] if len(sys.argv) > 1 else "Jeremiyah Love"
    print(f"Running Production Agent for: {player}\n")
    result = asyncio.run(run_production_agent(player))
    print(json.dumps(result, indent=2))
