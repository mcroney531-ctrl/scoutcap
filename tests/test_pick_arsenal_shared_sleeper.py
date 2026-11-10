"""
app.py::_load_pick_arsenal: shared Sleeper primitives (Stage 2C-4), the
configured draft class and configured rounds (D1/D3), and explicit
configuration failures.

Kept from Stage 2C-4:
- app -> tools.sleeper facade -> dynasty_core, with no direct Sleeper HTTP
  from app.py;
- a provider non-2xx raises at the provider boundary, and is never turned
  into a fake empty pick list;
- own/acquired classification, from_team naming, (round, orig_rid) sorting,
  the returned shape, and {"error": "Could not find your roster"}.

Changed by D1/D3 (these were previously pinned as "2026 season policy" and a
"4-round ownership algorithm"):
- the season defaults to config DRAFT_CLASS_YEAR;
- ownership covers config LEAGUE["rounds"];
- local/config problems return a clear {"error": ...} before ownership math.
  That covers a missing username or league id, an unknown user, no rosters, a
  roster count that differs from picks_per_round, and a traded pick in a round
  the config doesn't have.
- A successful load can hold zero picks.

app.py can't be imported directly (it's a Streamlit script), so the real
_load_pick_arsenal is compiled out of app.py's own source and run with the
names it resolves at call time. No live Sleeper calls.
"""
import ast
import os
import pathlib
import unittest
from unittest import mock

import httpx

import config.league as league
import dynasty_core.sleeper as core
import tools.sleeper as facade

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_PATH = ROOT / "app.py"
BASE = core.BASE_URL
YEAR = league.DRAFT_CLASS_YEAR
TEAMS = league.LEAGUE["picks_per_round"]

USER = {"user_id": "u1", "display_name": "Me"}
ROSTERS = [{"roster_id": i, "owner_id": f"u{i}"} for i in range(1, TEAMS + 1)]
USERS = [{"user_id": "u1", "display_name": "Me"}, {"user_id": "u2", "display_name": "Team Two"},
         {"user_id": "u3", "display_name": "Team Three"}] + [
    {"user_id": f"u{i}", "display_name": f"Team {i}"} for i in range(4, TEAMS + 1)]
TRADED = [
    {"season": str(YEAR), "round": 1, "roster_id": 2, "owner_id": 1},      # acquired Team Two's 1st
    {"season": str(YEAR), "round": 2, "roster_id": 1, "owner_id": 3},      # traded away my 2nd
    {"season": str(YEAR + 1), "round": 1, "roster_id": 3, "owner_id": 1},  # a different season
]


def _load_pick_arsenal_from_app(namespace: dict):
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_load_pick_arsenal")
    ns = {"os": os, "LEAGUE": league.LEAGUE, "DRAFT_CLASS_YEAR": YEAR, **namespace}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(APP_PATH), "exec"), ns)
    return ns["_load_pick_arsenal"]


def _env(**overrides):
    env = {"SLEEPER_USERNAME": "me", "SLEEPER_LEAGUE_ID": "L1", **overrides}
    return mock.patch.dict(os.environ, env)


def _no_direct_http():
    # Any request that doesn't go through a mocked shared primitive fails loudly.
    return mock.patch.object(httpx, "get", side_effect=AssertionError("direct Sleeper HTTP from app.py"))


class ArsenalUsesSharedPrimitivesTest(unittest.TestCase):
    def _run(self, *args, env=None, extra_ns=None, **overrides):
        prims = {
            "get_user": mock.Mock(return_value=USER),
            "get_rosters": mock.Mock(return_value=ROSTERS),
            "get_users_in_league": mock.Mock(return_value=USERS),
            "get_traded_picks": mock.Mock(return_value=TRADED),
        }
        prims.update(overrides)
        fn = _load_pick_arsenal_from_app({**prims, **(extra_ns or {})})
        with _env(**(env or {})), _no_direct_http():
            return fn(*args), prims

    def test_calls_each_shared_primitive_once_with_expected_args(self):
        _, prims = self._run()
        prims["get_user"].assert_called_once_with("me")
        prims["get_rosters"].assert_called_once_with("L1")
        prims["get_users_in_league"].assert_called_once_with("L1")
        prims["get_traded_picks"].assert_called_once_with("L1")

    def test_configured_class_ownership_shape_and_sort(self):
        result, _ = self._run()
        self.assertEqual(result, {"my_rid": 1, "picks": [
            {"round": 1, "orig_rid": 1, "source": "own", "from_team": "Me"},
            {"round": 1, "orig_rid": 2, "source": "acquired", "from_team": "Team Two"},
            {"round": 3, "orig_rid": 1, "source": "own", "from_team": "Me"},
            {"round": 4, "orig_rid": 1, "source": "own", "from_team": "Me"},
        ]})

    def test_requested_season_filters_traded_picks(self):
        result, _ = self._run(YEAR + 1)
        self.assertEqual([(p["round"], p["orig_rid"], p["source"]) for p in result["picks"]],
                         [(1, 1, "own"), (1, 3, "acquired"), (2, 1, "own"), (3, 1, "own"), (4, 1, "own")])

    def test_default_season_is_the_configured_draft_class(self):
        tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_load_pick_arsenal")
        self.assertIsNone(ast.literal_eval(fn.args.defaults[0]))
        # A different configured year is honored with no argument.
        traded = [{"season": "2031", "round": 1, "roster_id": 2, "owner_id": 1}]
        result, _ = self._run(get_traded_picks=mock.Mock(return_value=traded), extra_ns={"DRAFT_CLASS_YEAR": 2031})
        self.assertIn((1, 2, "acquired"), [(p["round"], p["orig_rid"], p["source"]) for p in result["picks"]])

    def test_ownership_covers_the_configured_rounds(self):
        three_rounds = {"rounds": 3, "picks_per_round": TEAMS, "total_picks": 3 * TEAMS}
        result, _ = self._run(get_traded_picks=mock.Mock(return_value=[]), extra_ns={"LEAGUE": three_rounds})
        self.assertEqual([p["round"] for p in result["picks"]], [1, 2, 3])

    def test_successful_zero_pick_arsenal(self):
        all_traded = [{"season": str(YEAR), "round": r, "roster_id": 1, "owner_id": 5} for r in range(1, 5)]
        result, _ = self._run(get_traded_picks=mock.Mock(return_value=all_traded))
        self.assertEqual(result, {"my_rid": 1, "picks": []})

    def test_missing_username_or_league_id(self):
        for env in ({"SLEEPER_USERNAME": ""}, {"SLEEPER_LEAGUE_ID": ""}):
            with self.subTest(env):
                result, prims = self._run(env=env)
                self.assertIn("SLEEPER_USERNAME and SLEEPER_LEAGUE_ID", result["error"])
                prims["get_user"].assert_not_called()

    def test_unknown_user(self):
        for user in (None, {}, {"display_name": "x"}):
            with self.subTest(user=user):
                result, prims = self._run(get_user=mock.Mock(return_value=user))
                self.assertIn("Sleeper user", result["error"])
                prims["get_rosters"].assert_not_called()

    def test_no_rosters(self):
        result, _ = self._run(get_rosters=mock.Mock(return_value=[]))
        self.assertIn("No rosters", result["error"])

    def test_missing_roster_returns_same_error_dict(self):
        result, _ = self._run(get_user=mock.Mock(return_value={"user_id": "nobody"}))
        self.assertEqual(result, {"error": "Could not find your roster"})

    def test_roster_count_must_match_picks_per_round(self):
        result, _ = self._run(get_rosters=mock.Mock(return_value=ROSTERS[:10]))
        self.assertIn("10 rosters", result["error"])
        self.assertIn(f"{TEAMS} picks per round", result["error"])

    def test_out_of_range_traded_round_is_an_error_not_dropped(self):
        traded = TRADED + [{"season": str(YEAR), "round": 5, "roster_id": 4, "owner_id": 1}]
        result, _ = self._run(get_traded_picks=mock.Mock(return_value=traded))
        self.assertIn("round-5", result["error"])

    def test_out_of_range_round_in_another_season_is_ignored(self):
        traded = TRADED + [{"season": str(YEAR + 1), "round": 5, "roster_id": 4, "owner_id": 1}]
        result, _ = self._run(get_traded_picks=mock.Mock(return_value=traded))
        self.assertEqual(len(result["picks"]), 4)

    def test_shared_primitive_error_propagates(self):
        err = httpx.HTTPStatusError("boom", request=mock.Mock(), response=mock.Mock(status_code=503))
        with self.assertRaises(httpx.HTTPStatusError):
            self._run(get_traded_picks=mock.Mock(side_effect=err))


class ArsenalEndToEndThroughFacadeTest(unittest.TestCase):
    """app -> tools.sleeper facade -> dynasty_core.sleeper -> HTTP. The fake
    accepts only the four shared URLs AND only requests issued from
    dynasty_core/sleeper.py, so a direct call from app.py fails even though
    it would hit the same URL."""

    ALLOWED = {
        f"{BASE}/user/me": USER,
        f"{BASE}/league/L1/rosters": ROSTERS,
        f"{BASE}/league/L1/users": USERS,
        f"{BASE}/league/L1/traded_picks": TRADED,
    }

    def _fake(self, fail_url=None):
        import sys

        this_file = pathlib.Path(__file__).resolve()

        def caller_file():
            # First frame outside unittest.mock and this test module = the real caller.
            frame = sys._getframe(2)
            while frame is not None:
                path = pathlib.Path(frame.f_code.co_filename)
                if path.name != "mock.py" and path.resolve() != this_file:
                    return path
                frame = frame.f_back
            return pathlib.Path("?")

        def fake_get(url, *args, **kwargs):
            caller = caller_file()
            if caller.parts[-2:] != ("dynasty_core", "sleeper.py"):
                raise AssertionError(f"Sleeper request issued outside dynasty_core: {caller.name} -> {url}")
            if url not in self.ALLOWED:
                raise AssertionError(f"unexpected Sleeper URL {url}")
            resp = mock.Mock(status_code=200)
            resp.json.return_value = self.ALLOWED[url]
            if url == fail_url:
                resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "error", request=mock.Mock(), response=mock.Mock(status_code=500))
            else:
                resp.raise_for_status.return_value = None
            return resp
        return fake_get

    def _fn(self):
        names = ("get_user", "get_rosters", "get_users_in_league", "get_traded_picks")
        return _load_pick_arsenal_from_app({n: getattr(facade, n, None) for n in names})

    def test_success_through_the_real_facade_and_shared_core(self):
        fn = self._fn()
        with _env(), mock.patch.object(core.httpx, "get", side_effect=self._fake()) as http_get:
            result = fn()
        self.assertEqual(result["my_rid"], 1)
        self.assertEqual(len(result["picks"]), 4)
        self.assertEqual(sorted(c.args[0] for c in http_get.call_args_list), sorted(self.ALLOWED))

    def test_non_2xx_traded_picks_raises_at_the_provider_boundary(self):
        fn = self._fn()
        with _env(), mock.patch.object(core.httpx, "get",
                                       side_effect=self._fake(fail_url=f"{BASE}/league/L1/traded_picks")):
            with self.assertRaises(httpx.HTTPStatusError):
                fn()


class FacadeAndSourceBoundaryTest(unittest.TestCase):
    def test_facade_re_exports_shared_get_traded_picks(self):
        self.assertIs(facade.get_traded_picks, core.get_traded_picks)
        self.assertIn("get_traded_picks", facade.__all__)

    def test_no_direct_sleeper_http_in_production_scout_source(self):
        skip = {"tests", "dynasty_core", "__pycache__", ".git"}
        for path in ROOT.rglob("*.py"):
            rel = path.relative_to(ROOT)
            if skip & set(rel.parts):
                continue
            with self.subTest(str(rel)):
                self.assertNotIn("api.sleeper.app", path.read_text(encoding="utf-8"))

    def test_app_and_facade_have_no_httpx_get(self):
        for rel in ("app.py", "tools/sleeper.py"):
            with self.subTest(rel):
                self.assertNotIn("httpx.get", (ROOT / rel).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
