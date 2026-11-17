"""
D3: Mock Draft league geometry has one source, config/league.py LEAGUE.

Before D3, app.py re-encoded 4 rounds x 12 teams x 48 picks in its helper
defaults, board loops, slot selectors, pin bound, completion checks and
status text, and defaulted acquired picks to slot 6. The helpers now read
LEAGUE. Run against a made-up 3 x 10 shape they behave accordingly, which
shows nothing is still hard-coded. (Scout stays a single-league product;
the alternate shape exists only in these tests.)

The draft ORDER is passed explicitly (test_draft_order.py covers it): the
league's real rookie drafts are linear, and the snake expectations below are
kept as explicit snake regressions.

app.py is a Streamlit script, so its helpers are compiled out of its own
source and run with the config they resolve at call time.
"""
import ast
import os
import pathlib
import re
import unittest

os.environ.setdefault("ANTHROPIC_API_KEY", "x")

import config.league as league

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_PATH = ROOT / "app.py"
HELPERS = ("_pick_label", "_overall_pick", "_user_picks_for_slot", "_default_acquired_slot", "_clamp_slot",
           "_board_pick_rows", "_draft_complete", "_arsenal_loaded", "_resolve_user_picks",
           "_arsenal_to_picks_set")
ALT = {"rounds": 3, "picks_per_round": 10, "total_picks": 30}


def app_helpers(league_shape: dict) -> dict:
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in HELPERS]
    ns = {"LEAGUE": league_shape, "SUPPORTED_DRAFT_ORDERS": ("linear", "snake")}
    exec(compile(ast.Module(body=fns, type_ignores=[]), str(APP_PATH), "exec"), ns)
    return ns


class LeagueConfigTest(unittest.TestCase):
    def test_production_shape_is_pinned(self):
        self.assertEqual((league.LEAGUE["rounds"], league.LEAGUE["picks_per_round"],
                          league.LEAGUE["total_picks"]), (4, 12, 48))

    def test_shape_invariant_holds_and_fails_loudly(self):
        league.validate_league_shape(league.LEAGUE)
        for bad in ({"rounds": 4, "picks_per_round": 12, "total_picks": 47},
                    {"rounds": 0, "picks_per_round": 12, "total_picks": 0}):
            with self.subTest(bad), self.assertRaises(ValueError):
                league.validate_league_shape(bad)


class ProductionGeometryUnchangedTest(unittest.TestCase):
    def setUp(self):
        self.h = app_helpers(league.LEAGUE)

    def test_pick_labels(self):
        self.assertEqual([self.h["_pick_label"](n) for n in (1, 12, 13, 48)], ["1.01", "1.12", "2.01", "4.12"])

    def test_natural_snake_picks(self):
        self.assertEqual(self.h["_user_picks_for_slot"](1, "snake"), [1, 24, 25, 48])
        self.assertEqual(self.h["_user_picks_for_slot"](12, "snake"), [12, 13, 36, 37])

    def test_natural_linear_picks(self):
        self.assertEqual(self.h["_user_picks_for_slot"](1, "linear"), [1, 13, 25, 37])
        self.assertEqual(self.h["_user_picks_for_slot"](12, "linear"), [12, 24, 36, 48])

    def test_acquired_default_is_still_slot_6(self):
        self.assertEqual(self.h["_default_acquired_slot"](), 6)
        picks = self.h["_arsenal_to_picks_set"](
            [{"round": 1, "orig_rid": 7, "source": "acquired"}], my_slot=1, acquired_slots={}, order="linear")
        self.assertEqual(picks, {6})

    def test_board_is_4_by_12(self):
        rows = self.h["_board_pick_rows"]()
        self.assertEqual([len(r) for r in rows], [12] * 4)
        self.assertEqual((rows[0][0], rows[-1][-1]), (1, 48))

    def test_completion(self):
        self.assertFalse(self.h["_draft_complete"](48))
        self.assertTrue(self.h["_draft_complete"](49))


class AlternateGeometryTest(unittest.TestCase):
    """Same helpers, a 3 x 10 league: nothing may still assume 4 x 12."""

    def setUp(self):
        self.h = app_helpers(ALT)

    def test_pick_labels(self):
        self.assertEqual([self.h["_pick_label"](n) for n in (10, 11, 30)], ["1.10", "2.01", "3.10"])

    def test_natural_snake_picks(self):
        self.assertEqual(self.h["_user_picks_for_slot"](3, "snake"), [3, 18, 23])
        self.assertEqual(self.h["_user_picks_for_slot"](3, "linear"), [3, 13, 23])

    def test_acquired_conversion_and_default(self):
        self.assertEqual(self.h["_default_acquired_slot"](), 5)
        arsenal = [{"round": 2, "orig_rid": 7, "source": "acquired"},
                   {"round": 3, "orig_rid": 1, "source": "own"}]
        self.assertEqual(self.h["_arsenal_to_picks_set"](arsenal, my_slot=2, acquired_slots={}, order="snake"), {16, 22})
        self.assertEqual(self.h["_arsenal_to_picks_set"](arsenal, my_slot=2, acquired_slots={}, order="linear"), {15, 22})

    def test_slot_clamping(self):
        clamp = self.h["_clamp_slot"]
        self.assertEqual((clamp(15), clamp(0), clamp(4), clamp("junk")), (10, 1, 4, 5))
        arsenal = [{"round": 1, "orig_rid": 7, "source": "acquired"}]
        self.assertEqual(self.h["_arsenal_to_picks_set"](arsenal, 1, {"1_7": 12}, "linear"), {10})

    def test_board_and_completion(self):
        rows = self.h["_board_pick_rows"]()
        self.assertEqual([len(r) for r in rows], [10] * 3)
        self.assertEqual(rows[-1], list(range(21, 31)))
        self.assertFalse(self.h["_draft_complete"](30))
        self.assertTrue(self.h["_draft_complete"](31))


class UserPickResolutionTest(unittest.TestCase):
    """not loaded -> natural picks; loaded -> exactly its picks, even none."""

    def setUp(self):
        self.resolve = app_helpers(league.LEAGUE)["_resolve_user_picks"]

    def test_not_loaded_uses_natural_picks(self):
        self.assertEqual(self.resolve(None, 1, {}, "snake"), {1, 24, 25, 48})

    def test_failed_load_is_not_loaded(self):
        self.assertEqual(self.resolve({"error": "x"}, 1, {}, "snake"), {1, 24, 25, 48})

    def test_loaded_with_picks_uses_them(self):
        arsenal = {"my_rid": 1, "picks": [{"round": 1, "orig_rid": 1, "source": "own"}]}
        self.assertEqual(self.resolve(arsenal, 3, {}, "linear"), {3})

    def test_loaded_with_zero_picks_stays_zero(self):
        self.assertEqual(self.resolve({"my_rid": 1, "picks": []}, 1, {}, "linear"), set())


class NoHardcodedGeometryInAppTest(unittest.TestCase):
    PATTERNS = [r"range\(1, 5\)", r"range\(1, 13\)", r"range\(4\)", r"teams: int = 12", r"rounds: int = 4",
                r"/48\b", r"> 48\b", r"<= 48\b", r", 48, ", r"\.get\(key, 6\)", r"round_idx \* 12"]

    def test_no_magic_league_numbers(self):
        src = APP_PATH.read_text(encoding="utf-8")
        for pattern in self.PATTERNS:
            with self.subTest(pattern):
                self.assertIsNone(re.search(pattern, src))


class SynthesisPromptGeometryTest(unittest.TestCase):
    def test_prompt_reads_league_geometry(self):
        import agents.synthesis_agent as synthesis
        prod = synthesis.build_system_prompt(league.LEAGUE)
        self.assertIn("4 rounds, 12 picks/round (48 total picks)", prod)
        self.assertIn("1.01 through 4.12", prod)
        self.assertIn("flatten into rounds 3-4", prod)
        self.assertEqual(synthesis.SYSTEM_PROMPT, prod)
        alt = synthesis.build_system_prompt(ALT)
        self.assertIn("3 rounds, 10 picks/round (30 total picks)", alt)
        self.assertIn("1.01 through 3.10", alt)
        self.assertIn("flatten into rounds 2-3", alt)
        self.assertNotIn("<<", alt)

    def test_score_to_pick_math_unchanged_for_production(self):
        import agents.synthesis_agent as synthesis
        # (recommended, floor, ceiling) as computed at base commit a2cd79f.
        cases = {(95, 90, 5, None, 20, "QB"): ("1.03", "1.04", "1.03"),
                 (80, 75, 4, 3, 20, "WR"): ("2.02", "2.08", "1.09"),
                 (60, 55, 3, None, 20, "RB"): ("4.01", "4.05", "3.07"),
                 (35, 30, 2, 15, 20, "TE"): ("4.11", "4.11", "4.10")}
        for (talent, opp, health, sent, size, pos), expected in cases.items():
            with self.subTest(pos=pos):
                out = synthesis.compute_composite_score(talent, opp, health, sent, size, pos)
                self.assertEqual((out["recommended_pick"], out["floor_pick"], out["ceiling_pick"]), expected)


if __name__ == "__main__":
    unittest.main()
