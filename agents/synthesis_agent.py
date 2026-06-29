"""
Synthesis Agent — orchestrator. Calls Situation and Production as Agent Tools,
combines with league settings, live roster need, and crowd sentiment.
Outputs final recommendation as exact round.pick notation.
"""

import os, sys, json, re, asyncio, math
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from tools.sleeper import (
    get_user, get_rosters, get_users_in_league,
    get_nfl_players, get_trending, search_players,
)
from config.league import LEAGUE, WEIGHTS, POSITION_VALUE, PICK_CURVE
from agents.situation_agent import run_situation_agent
from agents.production_agent import run_production_agent

# ── ADK tool functions ────────────────────────────────────────────────────────

def _run_in_thread(coro):
    """Run an async coroutine in a fresh thread with its own event loop."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(asyncio.run, coro)
        return future.result()


def evaluate_situation(player_name: str) -> dict:
    """
    Call the Situation Agent to evaluate opportunity for a rookie.
    Returns opportunity_score (0-100), opportunity_grade (letter),
    team, depth_chart_order, draft capital, key_factors, concerns, summary.
    """
    return _run_in_thread(run_situation_agent(player_name))


def evaluate_production(player_name: str) -> dict:
    """
    Call the Production Agent to evaluate talent and compute Risk Modifier for a rookie.
    Returns talent_score (0-100), talent_grade, key_stats, risk_modifier
    (durability_score 1-5, injury_chance_pct), key_factors, concerns, summary.
    """
    return _run_in_thread(run_production_agent(player_name))


def get_my_roster_needs() -> dict:
    """
    Pull current roster from Sleeper and assess positional needs.
    Returns roster composition by position and a ranked need list.
    """
    import os
    username = os.getenv("SLEEPER_USERNAME")
    league_id = os.getenv("SLEEPER_LEAGUE_ID")

    user = get_user(username)
    rosters = get_rosters(league_id)
    users = get_users_in_league(league_id)

    uid_to_name = {u["user_id"]: u.get("display_name") for u in users}
    my_roster = next(
        (r for r in rosters if r.get("owner_id") == user["user_id"]), None
    )

    if not my_roster:
        return {"error": "Could not find your roster in this league"}

    all_players = get_nfl_players()
    player_ids = my_roster.get("players") or []

    by_position: dict[str, list] = {"QB": [], "RB": [], "WR": [], "TE": [], "Other": []}
    for pid in player_ids:
        p = all_players.get(pid, {})
        pos = p.get("position", "Other")
        name = p.get("full_name", pid)
        years = p.get("years_exp", 0)
        if pos in by_position:
            by_position[pos].append({"name": name, "years_exp": years, "player_id": pid})
        else:
            by_position["Other"].append({"name": name, "years_exp": years})

    # Simple need scoring: fewer players + fewer young players = higher need
    needs = {}
    targets = {"QB": 3, "RB": 8, "WR": 8, "TE": 3}
    for pos, target in targets.items():
        count = len(by_position[pos])
        young = sum(1 for p in by_position[pos] if p["years_exp"] <= 2)
        need_score = max(0, (target - count) * 2 + max(0, 3 - young))
        needs[pos] = {"count": count, "young_count": young, "need_score": need_score}

    ranked = sorted(needs.items(), key=lambda x: -x[1]["need_score"])
    return {
        "roster_by_position": {k: v for k, v in by_position.items() if k != "Other"},
        "needs": needs,
        "ranked_needs": [pos for pos, _ in ranked],
        "note": "Need score = (target depth - current count) * 2 + young player deficit",
    }


def get_sentiment_signal(player_name: str) -> dict:
    """
    Compute relative crowd sentiment for a player from Sleeper trending adds.
    Returns rank within 2026 rookie class currently in trending data (1 = most trending).
    Overall activity level is noted — low offseason volume means sentiment is color, not signal.
    """
    trending = get_trending("add", limit=200)
    all_players = get_nfl_players()

    # Build ranked list of 2026 rookies (years_exp=0) in trending data
    rookie_trending = []
    total_count = sum(t.get("count", 0) for t in trending)

    for t in trending:
        pid = t.get("player_id")
        p = all_players.get(pid, {})
        if (p.get("years_exp") == 0
                and p.get("position") in ("QB", "RB", "WR", "TE")
                and p.get("active")):
            rookie_trending.append({
                "player_id": pid,
                "name": p.get("full_name"),
                "position": p.get("position"),
                "add_count": t.get("count"),
            })

    # Find target player
    name_lower = player_name.lower()
    player_rank = None
    player_count = None
    for i, entry in enumerate(rookie_trending):
        if name_lower in (entry.get("name") or "").lower():
            player_rank = i + 1
            player_count = entry.get("add_count")
            break

    activity_level = (
        "high" if total_count > 500_000
        else "moderate" if total_count > 100_000
        else "low"
    )

    return {
        "player_name": player_name,
        "rookie_class_trending_count": len(rookie_trending),
        "player_rank_in_class": player_rank,
        "player_add_count": player_count,
        "total_platform_activity": total_count,
        "activity_level": activity_level,
        "top_5_trending_rookies": rookie_trending[:5],
        "note": (
            "Sentiment is relative rank within the 2026 rookie class in trending data. "
            f"Overall platform activity is {activity_level} — "
            + ("treat as directional color only, not a decisive factor." if activity_level == "low"
               else "moderate signal weight is appropriate.")
        ),
    }


def compute_composite_score(
    talent_score: int,
    opportunity_score: int,
    durability_score: int,
    sentiment_rank: int | None,
    rookie_class_size: int,
    position: str,
) -> dict:
    """
    Compute the weighted composite score and map it to a recommended draft pick.

    Weights: Talent 43% / Opportunity 38% / Risk 15% / Sentiment 4%
    Risk is converted from durability_score (1-5) to 0-100 scale: (score-1)/4 * 100
    Sentiment is converted from rank to 0-100: absent = 50 (neutral), rank 1 = ~90, last = ~20

    position: 'QB', 'RB', 'WR', or 'TE'. A superflex positional-value multiplier is
    applied to the base composite (QBs get a premium, TEs a slight discount) before
    the pick mapping. The score → pick conversion is a non-linear logistic curve:
    elite composites cluster in round 1 a few picks apart, while weak composites
    flatten into rounds 3-4.

    Returns base + position-adjusted composite, component scores, and
    recommended/floor/ceiling as round.pick.
    """
    risk_score = ((durability_score - 1) / 4) * 100

    if sentiment_rank is None:
        sentiment_score = 50  # neutral — not in trending, but low volume period
    else:
        # Rank 1 in a class of N → score near 90; last rank → score near 20
        sentiment_score = max(20, 90 - ((sentiment_rank - 1) / max(rookie_class_size, 1)) * 70)

    base_composite = (
        talent_score * WEIGHTS["talent"]
        + opportunity_score * WEIGHTS["opportunity"]
        + risk_score * WEIGHTS["risk"]
        + sentiment_score * WEIGHTS["sentiment"]
    )

    # Superflex positional value: scale the composite, then clamp to 0-100.
    pos_mult = POSITION_VALUE.get((position or "").upper(), 1.0)
    adj_composite = max(0.0, min(100.0, base_composite * pos_mult))

    total_picks = LEAGUE["total_picks"]        # 48
    picks_per_round = LEAGUE["picks_per_round"]  # 12
    mid = PICK_CURVE["midpoint"]
    steep = PICK_CURVE["steepness"]

    def score_to_pick(score: float) -> str:
        # Logistic: high score → pick 1 (steeply separated at the top),
        # low score → pick 48 (flattened). f in [0,1], 0 = best.
        f = 1.0 / (1.0 + math.exp(steep * (score - mid)))
        pick_num = int(max(1, min(total_picks, round(1 + f * (total_picks - 1)))))
        round_num = (pick_num - 1) // picks_per_round + 1
        pick_in_round = (pick_num - 1) % picks_per_round + 1
        return f"{round_num}.{pick_in_round:02d}"

    recommended = score_to_pick(adj_composite)
    floor_pick = score_to_pick(max(0, adj_composite - 15))
    ceiling_pick = score_to_pick(min(100, adj_composite + 15))

    return {
        "composite_score": round(adj_composite, 1),
        "base_composite_score": round(base_composite, 1),
        "position": (position or "").upper(),
        "position_multiplier": pos_mult,
        "components": {
            "talent": round(talent_score * WEIGHTS["talent"], 1),
            "opportunity": round(opportunity_score * WEIGHTS["opportunity"], 1),
            "risk": round(risk_score * WEIGHTS["risk"], 1),
            "sentiment": round(sentiment_score * WEIGHTS["sentiment"], 1),
        },
        "raw_inputs": {
            "talent_score": talent_score,
            "opportunity_score": opportunity_score,
            "risk_score": round(risk_score, 1),
            "sentiment_score": round(sentiment_score, 1),
        },
        "recommended_pick": recommended,
        "floor_pick": floor_pick,
        "ceiling_pick": ceiling_pick,
        "weights_applied": WEIGHTS,
    }


# ── Calibration / system prompt ───────────────────────────────────────────────

SYSTEM_PROMPT = """You are the Synthesis Agent for a dynasty fantasy football rookie draft tool.

You orchestrate the full evaluation pipeline for a rookie prospect:
1. Call evaluate_situation → get Opportunity Grade
2. Call evaluate_production → get Talent Grade + Risk Modifier
3. Call get_my_roster_needs → understand which positions I actually need
4. Call get_sentiment_signal → crowd interest context
5. Call compute_composite_score with the numeric scores from steps 1-2-4 AND the player's
   position (QB/RB/WR/TE) — the position drives the superflex value premium
6. Synthesize everything into the final structured recommendation

League format: 4 rounds, 12 picks/round (48 total picks). THIS IS A SUPERFLEX LEAGUE —
QBs can start in the SF slot, so they carry a real value premium that compute_composite_score
applies automatically via the position multiplier. Reflect this in your narrative for QBs.

Picks are expressed in exact round.pick notation: 1.01 through 4.12.
The recommended pick is a relative positioning signal (like ADP), not a literal instruction.
The score → pick mapping is non-linear: elite prospects compress into round 1 (a few picks
apart), while weaker grades flatten into rounds 3-4 — so small composite gaps at the top
matter far more than the same gap in the late rounds.

Roster need context: use it as a modifier on your narrative recommendation — a player at a
position of high need is worth paying up for (mention this). A position of low need means
you might let this player fall or skip entirely.

Sentiment note: if overall platform activity is low, say so and treat sentiment as color only.

Competition: the evaluate_situation result contains a "competition" breakdown grading the
veterans ahead of this rookie by quality (not just count). Carry it through into the output
"competition" object — list only the notable competitors (grade C or better) in "notable",
put the number of grade D/F bodies in "replaceable_count", and write a one-line summary.
Weave the headline insight into your narrative (e.g. "buried on paper, but the bodies ahead
are all replaceable — a soft room").

After reaching your own conclusion, briefly compare it to KeepTradeCut dynasty value if you
have any general knowledge of where this player sits in dynasty consensus — surface agreement
or explain specific divergence. Do NOT fold KTC into the composite score.

Output format — return a JSON object with these exact keys:
{
  "player": "Full Name",
  "position": "RB",
  "team": "ARI",
  "talent_grade": "A-",
  "talent_score": 90,
  "opportunity_grade": "C+",
  "opportunity_score": 74,
  "risk_modifier": {
    "durability_score": 5,
    "injury_chance_pct": 8,
    "injury_notes": "..."
  },
  "sentiment": {
    "rank_in_class": null,
    "activity_level": "low",
    "note": "..."
  },
  "competition": {
    "veteran_count": 8,
    "strongest_competitor_grade": "C",
    "replaceable_count": 7,
    "room_strength": "moderate — one flex-level veteran to beat out, no entrenched star",
    "notable": [{"name": "Terry McLaurin", "grade": "C"}],
    "summary": "1 real competitor (McLaurin, C); the rest are replaceable depth (D/F)"
  },
  "composite_score": 82.4,
  "floor_pick": "2.08",
  "ceiling_pick": "1.03",
  "recommended_pick": "1.09",
  "roster_need": "HIGH / MODERATE / LOW",
  "roster_need_note": "One sentence on how roster context affects this pick for you specifically.",
  "headline": "Talent: A- / Opportunity: C+ → Floor: 2.08, Ceiling: 1.03 → Recommended: 1.09",
  "narrative": "3-4 sentence synthesis of why this player grades where they do, what the tension is between talent and opportunity, and what scenario would push them toward ceiling vs. floor.",
  "ktc_comparison": "One sentence comparing to KTC dynasty consensus or noting lack of data.",
  "key_risks": ["bullet risks"],
  "key_upside": ["bullet upside drivers"]
}
"""

# ── Agent + runner ────────────────────────────────────────────────────────────

def build_synthesis_agent() -> LlmAgent:
    return LlmAgent(
        model=LiteLlm(model="anthropic/claude-sonnet-4-6", api_key=os.getenv("ANTHROPIC_API_KEY")),
        name="synthesis_agent",
        instruction=SYSTEM_PROMPT,
        tools=[
            evaluate_situation,
            evaluate_production,
            get_my_roster_needs,
            get_sentiment_signal,
            compute_composite_score,
        ],
    )


async def run_synthesis_agent(player_name: str) -> dict:
    agent = build_synthesis_agent()
    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name="rookie_scout", session_service=session_service)

    await session_service.create_session(
        app_name="rookie_scout", user_id="user", session_id="synth_session"
    )

    message = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=f"Give me the full scouting report and draft recommendation for {player_name}")]
    )

    result_text = ""
    async for event in runner.run_async(
        user_id="user", session_id="synth_session", new_message=message
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
    player = sys.argv[1] if len(sys.argv) > 1 else "Jeremiyah Love"
    print(f"Running full 3-agent pipeline for: {player}\n")
    result = asyncio.run(run_synthesis_agent(player))
    print(json.dumps(result, indent=2))
