"""
Scout's Mock Draft follows the league's real draft order.

Sleeper is authoritative: Dynasty Daddies' 2026 rookie draft (and 2023-2025)
is LINEAR, 4 rounds x 12 teams, while Scout assumed snake and so mirrored
every even round (slot 1 was shown 2.12 / 4.12 instead of 2.01 / 4.01).

Draft type and slot assignments are separate evidence:
  - the type comes from the one draft matching DRAFT_CLASS_YEAR and the
    configured rounds x teams (a season can also hold a 26-round snake
    startup draft, as 2023 does); only linear and plain snake are supported,
    anything else (auction, third-round reversal) is reported, never
    approximated;
  - slots come from that draft's draft_order (or slot_to_roster_id) and are
    used only if they cover every roster exactly once.
Either can be verified while the other is unknown. The pick-number functions
take the order explicitly; there is no default to fall back on.

Trade ownership (_load_pick_arsenal) is order-independent and unchanged.
"""
import ast
import os
import pathlib
import unittest
from unittest import mock

os.environ.setdefault("ANTHROPIC_API_KEY", "x")

import config.league as league

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_PATH = ROOT / "app.py"
HELPERS = ("_overall_pick", "_user_picks_for_slot", "_arsenal_to_picks_set", "_resolve_user_picks",
           "_arsenal_loaded", "_clamp_slot", "_default_acquired_slot", "_select_draft",
           "_draft_order_type", "_verified_slots", "_slot_status", "_load_draft_meta")
SUPPORTED = ("linear", "snake")


def app_helpers(extra=None):
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in HELPERS]
    ns = {"LEAGUE": league.LEAGUE, "DRAFT_CLASS_YEAR": league.DRAFT_CLASS_YEAR, "os": os,
          "SUPPORTED_DRAFT_ORDERS": SUPPORTED, **(extra or {})}
    exec(compile(ast.Module(body=fns, type_ignores=[]), str(APP_PATH), "exec"), ns)
    missing = set(HELPERS) - set(ns)
    if missing:
        raise AssertionError(f"app.py is missing {sorted(missing)}")
    return ns


def _draft(season="2026", type_="linear", rounds=4, teams=12, reversal=0, status="complete",
           draft_order=None, slot_to_roster_id=None):
    return {"draft_id": f"d{season}{rounds}", "season": season, "type": type_, "status": status,
            "settings": {"rounds": rounds, "teams": teams, "reversal_round": reversal},
            "draft_order": draft_order, "slot_to_roster_id": slot_to_roster_id}


ROSTERS = [{"roster_id": r, "owner_id": f"u{r}"} for r in range(1, 13)]
# Real-looking order: roster r's owner drafts from slot (13 - r).
DRAFT_ORDER = {f"u{r}": 13 - r for r in range(1, 13)}


class PickNumbersTest(unittest.TestCase):
    def setUp(self):
        self.h = app_helpers()

    def test_linear_keeps_every_slot_in_place(self):
        self.assertEqual(self.h["_user_picks_for_slot"](1, "linear"), [1, 13, 25, 37])
        self.assertEqual(self.h["_user_picks_for_slot"](12, "linear"), [12, 24, 36, 48])
        self.assertEqual(self.h["_user_picks_for_slot"](5, "linear", rounds=3, teams=10), [5, 15, 25])

    def test_snake_regression_is_preserved_explicitly(self):
        self.assertEqual(self.h["_user_picks_for_slot"](1, "snake"), [1, 24, 25, 48])
        self.assertEqual(self.h["_user_picks_for_slot"](12, "snake"), [12, 13, 36, 37])
        self.assertEqual(self.h["_user_picks_for_slot"](3, "snake", rounds=3, teams=10), [3, 18, 23])

    def test_no_order_or_unsupported_order_is_an_error(self):
        for order in (None, "", "auction", "snake_3rr", "Linear"):
            with self.subTest(order=order):
                with self.assertRaises(ValueError):
                    self.h["_overall_pick"](2, 1, order)
                with self.assertRaises(ValueError):
                    self.h["_user_picks_for_slot"](1, order)
                with self.assertRaises(ValueError):
                    self.h["_arsenal_to_picks_set"]([{"round": 1, "orig_rid": 1, "source": "own"}], 1, {}, order)

    def test_traded_picks_across_rounds_follow_the_order(self):
        arsenal = [
            {"round": 1, "orig_rid": 1, "source": "own"},
            {"round": 2, "orig_rid": 9, "source": "acquired"},
            {"round": 3, "orig_rid": 1, "source": "own"},
            {"round": 4, "orig_rid": 3, "source": "acquired"},
        ]
        slots = {"2_9": 9, "4_3": 3}
        to_set = self.h["_arsenal_to_picks_set"]
        self.assertEqual(to_set(arsenal, 5, slots, "linear"), {5, 21, 29, 39})
        self.assertEqual(to_set(arsenal, 5, slots, "snake"), {5, 16, 29, 46})

    def test_resolve_user_picks_threads_the_order(self):
        resolve = self.h["_resolve_user_picks"]
        self.assertEqual(resolve(None, 1, {}, "linear"), {1, 13, 25, 37})
        self.assertEqual(resolve(None, 1, {}, "snake"), {1, 24, 25, 48})
        loaded = {"my_rid": 1, "picks": [{"round": 2, "orig_rid": 1, "source": "own"}]}
        self.assertEqual(resolve(loaded, 1, {}, "linear"), {13})
        self.assertEqual(resolve({"my_rid": 1, "picks": []}, 1, {}, "linear"), set())


class DraftSelectionTest(unittest.TestCase):
    def setUp(self):
        self.h = app_helpers()

    def test_selects_the_rookie_draft_not_a_startup_draft_in_the_same_season(self):
        startup = _draft(season="2026", type_="snake", rounds=26, reversal=3)
        rookie = _draft(season="2026")
        draft, problem = self.h["_select_draft"]([startup, rookie], 2026)
        self.assertIs(draft, rookie)
        self.assertIsNone(problem)

    def test_no_matching_draft_or_more_than_one_is_a_problem_not_a_guess(self):
        cases = {
            "none at all": [],
            "other season only": [_draft(season="2025")],
            "wrong geometry": [_draft(rounds=5), _draft(teams=10)],
            "two matches": [_draft(), _draft(type_="snake")],
        }
        for label, drafts in cases.items():
            with self.subTest(label):
                draft, problem = self.h["_select_draft"](drafts, 2026)
                self.assertIsNone(draft)
                self.assertTrue(problem)

    def test_order_type(self):
        order_type = self.h["_draft_order_type"]
        self.assertEqual(order_type(_draft(type_="linear")), ("linear", None))
        self.assertEqual(order_type(_draft(type_="snake")), ("snake", None))
        for d in (_draft(type_="snake", reversal=3), _draft(type_="auction"), _draft(type_="mystery"),
                  {"type": None, "settings": {}}):
            with self.subTest(d.get("type")):
                order, problem = order_type(d)
                self.assertIsNone(order)
                self.assertTrue(problem)

    def test_reversal_problem_names_the_variant(self):
        _, problem = self.h["_draft_order_type"](_draft(type_="snake", reversal=3))
        self.assertIn("reversal", problem.lower())


class VerifiedSlotsTest(unittest.TestCase):
    def setUp(self):
        self.h = app_helpers()

    def test_draft_order_maps_each_roster_to_its_slot(self):
        slots = self.h["_verified_slots"](_draft(draft_order=DRAFT_ORDER), ROSTERS)
        self.assertEqual(slots, {r: 13 - r for r in range(1, 13)})

    def test_slot_to_roster_id_is_used_when_present(self):
        s2r = {str(s): 13 - s for s in range(1, 13)}
        slots = self.h["_verified_slots"](_draft(slot_to_roster_id=s2r), ROSTERS)
        self.assertEqual(slots, {r: 13 - r for r in range(1, 13)})

    def test_incomplete_or_inconsistent_order_is_not_verified(self):
        missing = dict(DRAFT_ORDER); missing.pop("u4")
        dup = dict(DRAFT_ORDER); dup["u4"] = dup["u5"]
        out_of_range = dict(DRAFT_ORDER); out_of_range["u4"] = 13
        for label, order in (("none", None), ("empty", {}), ("missing roster", missing),
                             ("duplicate slot", dup), ("slot out of range", out_of_range)):
            with self.subTest(label):
                self.assertIsNone(self.h["_verified_slots"](_draft(draft_order=order), ROSTERS))

    def test_slot_status(self):
        status = self.h["_slot_status"]
        self.assertEqual(status(4, 4), "verified")
        self.assertEqual(status(6, 4), "override")
        self.assertEqual(status(6, None), "assumed")


class LoadDraftMetaTest(unittest.TestCase):
    USER = {"user_id": "u1", "display_name": "Me"}

    def _load(self, drafts, env=None, rosters=ROSTERS, user=None):
        calls = {
            "get_league_drafts": mock.Mock(return_value=drafts),
            "get_rosters": mock.Mock(return_value=rosters),
            "get_user": mock.Mock(return_value=user if user is not None else self.USER),
        }
        h = app_helpers(calls)
        env = {"SLEEPER_USERNAME": "me", "SLEEPER_LEAGUE_ID": "L1"} if env is None else env
        clean = {k: v for k, v in os.environ.items() if k not in ("SLEEPER_USERNAME", "SLEEPER_LEAGUE_ID")}
        with mock.patch.dict(os.environ, {**clean, **env}, clear=True):
            return h["_load_draft_meta"](), calls

    def test_type_and_slots_verified(self):
        meta, calls = self._load([_draft(draft_order=DRAFT_ORDER)])
        self.assertEqual(meta["order"], "linear")
        self.assertIsNone(meta["order_problem"])
        self.assertEqual(meta["draft_status"], "complete")
        self.assertEqual(meta["slots"], {r: 13 - r for r in range(1, 13)})
        self.assertEqual(meta["my_rid"], 1)
        calls["get_league_drafts"].assert_called_once_with("L1")

    def test_type_verified_while_slots_are_unknown(self):
        meta, _ = self._load([_draft(status="pre_draft", draft_order=None)])
        self.assertEqual(meta["order"], "linear")
        self.assertIsNone(meta["slots"])
        self.assertTrue(meta["slots_problem"])

    def test_unsupported_type_is_reported_and_never_becomes_linear_or_snake(self):
        meta, _ = self._load([_draft(type_="snake", reversal=3, draft_order=DRAFT_ORDER)])
        self.assertIsNone(meta["order"])
        self.assertTrue(meta["order_unsupported"])
        self.assertIn("reversal", meta["order_problem"].lower())

    def test_no_draft_for_the_season_is_unknown_not_unsupported(self):
        meta, _ = self._load([_draft(season="2025")])
        self.assertIsNone(meta["order"])
        self.assertFalse(meta["order_unsupported"])
        self.assertTrue(meta["order_problem"])
        self.assertIsNone(meta["slots"])

    def test_missing_league_id_makes_no_calls(self):
        meta, calls = self._load([_draft()], env={"SLEEPER_USERNAME": "me"})
        self.assertIsNone(meta["order"])
        self.assertTrue(meta["order_problem"])
        for call in calls.values():
            call.assert_not_called()

    def test_unknown_user_keeps_verified_type_and_slots_without_an_own_roster(self):
        meta, _ = self._load([_draft(draft_order=DRAFT_ORDER)], user={})
        self.assertEqual(meta["order"], "linear")
        self.assertIsNotNone(meta["slots"])
        self.assertIsNone(meta["my_rid"])


if __name__ == "__main__":
    unittest.main()
