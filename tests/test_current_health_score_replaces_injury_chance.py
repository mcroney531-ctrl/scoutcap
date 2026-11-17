"""
Regression test for the second injury-signal correctness fix: Scout's
Production and Synthesis agents used to ask the model for a fabricated
injury_chance_pct (a numeric injury probability with no data source or
predictive model behind it) alongside a durability_score that no longer
meant anything once historical injury data was removed (see
test_production_agent_no_false_injury_history.py for that first fix).

The fix renames durability_score -> current_health_score (a current-status/
availability signal only, scored from current Sleeper injury/practice
status) and removes injury_chance_pct entirely, with no percentage
replacement. compute_composite_score's existing 1-5 -> 0-100 conversion and
the 15% risk weight are unchanged -- only the semantics of what feeds that
conversion changed.

Run with:
    python -m unittest discover -s tests -v
"""
import os
import unittest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-for-import-only")
os.environ.setdefault("GOOGLE_API_KEY", "test-key-for-import-only")

import agents.production_agent as production_agent
import agents.synthesis_agent as synthesis_agent
from config.league import WEIGHTS


class InjuryChancePctIsGoneTest(unittest.TestCase):
    """injury_chance_pct must not appear anywhere in active Scout prompts,
    output schemas, or UI source."""

    def test_production_agent_prompt_has_no_injury_chance_pct(self):
        self.assertNotIn("injury_chance_pct", production_agent.SYSTEM_PROMPT)

    def test_production_agent_calibration_has_no_injury_chance_pct(self):
        self.assertNotIn("injury_chance_pct", production_agent.TALENT_CALIBRATION)

    def test_synthesis_agent_prompt_has_no_injury_chance_pct(self):
        self.assertNotIn("injury_chance_pct", synthesis_agent.SYSTEM_PROMPT)

    def test_production_agent_prompt_bans_numeric_injury_probability(self):
        collapsed = " ".join(production_agent.SYSTEM_PROMPT.lower().split())
        self.assertIn("never output a numeric injury probability", collapsed)

    def test_calibration_no_longer_contains_probability_percentages(self):
        # The old calibration tiers read like "Questionable -> 10-20% injury
        # chance" and "IR/PUP -> 35-50%". Those percentage ranges must be gone.
        for stale_pct in ("10-20%", "20-35%", "35-50%", "<10%"):
            self.assertNotIn(stale_pct, production_agent.TALENT_CALIBRATION)

    def test_app_source_has_no_injury_chance_pct(self):
        app_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")
        with open(app_path, encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("injury_chance_pct", source)
        self.assertNotIn("Injury chance", source)


class DurabilityScoreIsGoneFromActiveScoringTest(unittest.TestCase):
    """durability_score must not appear in active Scout scoring paths
    (Production prompt/schema, Synthesis prompt/schema/function signature, UI)."""

    def test_production_agent_prompt_has_no_durability_score(self):
        self.assertNotIn("durability_score", production_agent.SYSTEM_PROMPT)

    def test_synthesis_agent_prompt_has_no_durability_score(self):
        self.assertNotIn("durability_score", synthesis_agent.SYSTEM_PROMPT)

    def test_compute_composite_score_signature_has_no_durability_score(self):
        import inspect
        params = list(inspect.signature(synthesis_agent.compute_composite_score).parameters)
        self.assertNotIn("durability_score", params)

    def test_app_source_has_no_durability_score(self):
        app_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")
        with open(app_path, encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("durability_score", source)
        self.assertNotIn("Durability", source)

    def test_app_source_has_no_historical_injury_record_claim(self):
        app_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")
        with open(app_path, encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("historical injury record", source.lower())


class CurrentHealthScorePresentInContractsTest(unittest.TestCase):
    """current_health_score must be present in both Production and
    Synthesis contracts (prompts, output schema, function signature)."""

    def test_production_agent_prompt_uses_current_health_score(self):
        self.assertIn("current_health_score", production_agent.SYSTEM_PROMPT)

    def test_production_agent_calibration_describes_current_health_score(self):
        collapsed = " ".join(production_agent.TALENT_CALIBRATION.lower().split())
        self.assertIn("current health score", collapsed)
        self.assertIn("not a forecast of future injury probability", collapsed)
        self.assertIn("not a historical durability assessment", collapsed)

    def test_synthesis_agent_prompt_uses_current_health_score(self):
        self.assertIn("current_health_score", synthesis_agent.SYSTEM_PROMPT)

    def test_synthesis_agent_evaluate_production_doc_mentions_current_health_score(self):
        doc = synthesis_agent.evaluate_production.__doc__ or ""
        self.assertIn("current_health_score", doc)

    def test_compute_composite_score_signature_has_current_health_score(self):
        import inspect
        params = list(inspect.signature(synthesis_agent.compute_composite_score).parameters)
        self.assertIn("current_health_score", params)

    def test_app_source_uses_current_health_score(self):
        app_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")
        with open(app_path, encoding="utf-8") as f:
            source = f.read()
        self.assertIn("current_health_score", source)
        self.assertIn("Current health", source)


class ComputeCompositeScoreConversionUnchangedTest(unittest.TestCase):
    """The deterministic 1-5 -> 0-100 conversion and the 15% risk weight
    that consumes current_health_score must be unchanged -- only the
    semantics of the input, not the math."""

    def test_risk_weight_is_still_15_percent(self):
        self.assertEqual(WEIGHTS["risk"], 0.15)

    def test_health_score_of_1_converts_to_risk_component_of_0(self):
        # sentiment_rank=None -> neutral 50; isolate the risk component by
        # zeroing talent/opportunity and reading back the composite math.
        result = synthesis_agent.compute_composite_score(
            talent_score=0,
            opportunity_score=0,
            current_health_score=1,
            sentiment_rank=None,
            rookie_class_size=10,
            position="WR",
        )
        risk_contribution = result["raw_inputs"]["risk_score"]
        self.assertEqual(risk_contribution, 0)

    def test_health_score_of_5_converts_to_risk_component_of_100(self):
        result = synthesis_agent.compute_composite_score(
            talent_score=0,
            opportunity_score=0,
            current_health_score=5,
            sentiment_rank=None,
            rookie_class_size=10,
            position="WR",
        )
        risk_contribution = result["raw_inputs"]["risk_score"]
        self.assertEqual(risk_contribution, 100)


class CurrentSleeperFieldsAreOnlyHealthEvidenceTest(unittest.TestCase):
    """lookup_player_info's live Sleeper injury/practice fields remain the
    only health evidence the Production Agent is told to use."""

    def test_lookup_player_info_is_the_only_health_tool(self):
        agent = production_agent.build_production_agent()
        tool_names = [t.__name__ for t in agent.tools]
        self.assertIn("lookup_player_info", tool_names)
        self.assertNotIn("get_injury_history", tool_names)
        self.assertNotIn("get_nfl_injuries", tool_names)

    def test_prompt_scores_health_from_current_sleeper_status_only(self):
        collapsed = " ".join(production_agent.SYSTEM_PROMPT.lower().split())
        self.assertIn("score the current health score from current sleeper", collapsed)


if __name__ == "__main__":
    unittest.main()
