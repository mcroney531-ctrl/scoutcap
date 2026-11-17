"""
Regression test for the confirmed production bug: agents/production_agent.py's
get_injury_history tool delegated to tools.espn.get_nfl_injuries(), whose
endpoint (NFL_BASE/athletes/{id}/injuries) was confirmed live to return 404
for every real ESPN athlete id tested -- including two players Sleeper
currently marks "Out" with real, populated entries on the working team-feed
path. get_nfl_injuries() catches that 404 and returns a well-formed
{"injuries": [], "note": "No injury history found"}, so the agent could not
tell "the provider call failed" from "this player has a clean record."

There's a second problem independent of whether that endpoint ever starts
working: it's an active-NFL status endpoint, not a college durability
record, so even a working response would have been the wrong kind of
evidence for a rookie's Risk Modifier.

The fix removes the tool and the historical-injury claim from the prompt
entirely, leaving current Sleeper injury/practice status (already surfaced
by lookup_player_info) as the only health signal, with an explicit
instruction not to infer a clean history from the absence of one.

This is the first test file in this repo -- run with:
    python -m unittest discover -s tests -v
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-for-import-only")
os.environ.setdefault("GOOGLE_API_KEY", "test-key-for-import-only")

import agents.production_agent as production_agent


class InjuryHistoryToolIsGoneTest(unittest.TestCase):
    def test_build_production_agent_has_no_injury_history_tool(self):
        agent = production_agent.build_production_agent()
        tool_names = [t.__name__ for t in agent.tools]
        self.assertNotIn("get_injury_history", tool_names)

    def test_module_no_longer_defines_get_injury_history(self):
        self.assertFalse(hasattr(production_agent, "get_injury_history"))

    def test_module_no_longer_imports_get_nfl_injuries(self):
        self.assertFalse(hasattr(production_agent, "get_nfl_injuries"))


class SystemPromptNoLongerClaimsEspnInjuryHistoryTest(unittest.TestCase):
    def test_prompt_does_not_reference_the_removed_tool(self):
        self.assertNotIn("get_injury_history", production_agent.SYSTEM_PROMPT)

    def test_prompt_does_not_claim_espn_injury_history_is_available(self):
        # The old prompt described get_injury_history as "Historical injury
        # record from ESPN" -- that specific claim must be gone.
        self.assertNotIn("Historical injury record from ESPN", production_agent.SYSTEM_PROMPT)

    def test_prompt_explicitly_states_historical_data_is_unavailable(self):
        # Normalize whitespace: the source wraps long lines for readability,
        # which must not defeat a substring check on the wrapped phrase.
        collapsed = " ".join(production_agent.SYSTEM_PROMPT.lower().split())
        self.assertIn("historical injury data is not available", collapsed)
        self.assertIn("do not infer", collapsed)

    def test_risk_modifier_calibration_is_scored_from_current_status_only(self):
        collapsed = " ".join(production_agent.TALENT_CALIBRATION.lower().split())
        self.assertIn("current sleeper injury/practice status", collapsed)
        # The old calibration scored durability by counting a known injury
        # history ("minor injury history", "moderate history (1-2 significant
        # injuries)", etc.) -- that framing must be gone, even though the new
        # disclaimer legitimately still says the phrase "no injury history"
        # once, as part of instructing the model not to infer it.
        for stale_phrase in (
            "minor injury history",
            "moderate history",
            "recurrent injuries",
            "multiple structural injuries or chronic durability concerns",
        ):
            self.assertNotIn(stale_phrase, collapsed)


class LookupPlayerInfoStillExposesCurrentStatusTest(unittest.TestCase):
    def test_current_injury_and_practice_fields_still_present(self):
        fake_matches = [{
            "player_id": "12345",
            "full_name": "Test Rookie",
            "position": "WR",
            "team": "KC",
            "college": "Test State",
            "age": 22,
            "years_exp": 0,
            "status": "Active",
            "injury_status": "Questionable",
            "injury_start_date": "2026-09-01",
            "practice_participation": "Limited",
            "search_rank": 1,
        }]
        with mock.patch.object(production_agent, "search_players", return_value=fake_matches):
            result = production_agent.lookup_player_info("Test Rookie")

        self.assertEqual(result["injury_status"], "Questionable")
        self.assertEqual(result["practice_participation"], "Limited")
        self.assertEqual(result["injury_start_date"], "2026-09-01")


class FullAgentStackStillImportsAndBuildsTest(unittest.TestCase):
    """Minimum bar from the fix instructions: the whole Scout agent stack
    still imports and the production agent still builds with its
    declarations intact, given this repo has no broader test suite yet."""

    def test_full_agent_stack_imports(self):
        import agents.situation_agent  # noqa: F401
        import agents.synthesis_agent  # noqa: F401
        import mcp_server  # noqa: F401

    def test_production_agent_builds_with_remaining_tools_intact(self):
        agent = production_agent.build_production_agent()
        tool_names = sorted(t.__name__ for t in agent.tools)
        self.assertEqual(
            tool_names,
            sorted([
                "lookup_player_info",
                "lookup_draft_prospect_info",
                "get_career_college_stats",
                "get_recent_college_stats",
            ]),
        )

    def test_mcp_server_no_longer_exposes_injury_history_tool(self):
        import mcp_server
        self.assertFalse(hasattr(mcp_server, "injury_history"))
        self.assertFalse(hasattr(mcp_server, "get_injury_history"))


if __name__ == "__main__":
    unittest.main()
