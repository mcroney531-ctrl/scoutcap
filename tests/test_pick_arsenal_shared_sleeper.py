"""
Stage 2C-4 (post-convergence audit F5): app.py::_load_pick_arsenal must use
the shared Sleeper primitives through the tools.sleeper facade, not its own
httpx calls. The old helper fetched /league/{id}/users and
/league/{id}/traded_picks directly and parsed the body without
raise_for_status(), so a non-2xx response would have been treated as data.

What must NOT change (and is pinned here): the 2026 season policy, the
4-round ownership algorithm, own/acquired classification, from_team naming,
(round, orig_rid) sorting, the returned shape, and the
{"error": "Could not find your roster"} path.

app.py can't be imported directly in a test (it's a Streamlit script), so
the real _load_pick_arsenal is compiled out of app.py's own source and run
with the names it resolves at call time. Scout-only; no live Sleeper calls.
"""
import ast
import os
import pathlib
import unittest
from unittest import mock

import httpx

import dynasty_core.sleeper as core
import tools.sleeper as facade

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_PATH = ROOT / "app.py"
BASE = core.BASE_URL

USER = {"user_id": "u1", "display_name": "Me"}
ROSTERS = [{"roster_id": 1, "owner_id": "u1"}, {"roster_id": 2, "owner_id": "u2"},
           {"roster_id": 3, "owner_id": "u3"}]
USERS = [{"user_id": "u1", "display_name": "Me"}, {"user_id": "u2", "display_name": "Team Two"},
         {"user_id": "u3", "display_name": "Team Three"}]
TRADED = [
    {"season": "2026", "round": 1, "roster_id": 2, "owner_id": 1},  # acquired Team Two's 1st
    {"season": "2026", "round": 2, "roster_id": 1, "owner_id": 3},  # traded away my 2nd
    {"season": "2027", "round": 1, "roster_id": 3, "owner_id": 1},  # other season
]


def _load_pick_arsenal_from_app(namespace: dict):
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_load_pick_arsenal")
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(APP_PATH), "exec"), namespace)
    return namespace["_load_pick_arsenal"]


def _env():
    return mock.patch.dict(os.environ, {"SLEEPER_USERNAME": "me", "SLEEPER_LEAGUE_ID": "L1"})


def _no_direct_http():
    # Any request that doesn't go through a mocked shared primitive fails loudly.
    return mock.patch.object(httpx, "get", side_effect=AssertionError("direct Sleeper HTTP from app.py"))


class ArsenalUsesSharedPrimitivesTest(unittest.TestCase):
    def _run(self, season="2026", **overrides):
        prims = {
            "get_user": mock.Mock(return_value=USER),
            "get_rosters": mock.Mock(return_value=ROSTERS),
            "get_users_in_league": mock.Mock(return_value=USERS),
            "get_traded_picks": mock.Mock(return_value=TRADED),
        }
        prims.update(overrides)
        fn = _load_pick_arsenal_from_app({"os": os, **prims})
        with _env(), _no_direct_http():
            return fn(season), prims

    def test_calls_each_shared_primitive_once_with_expected_args(self):
        _, prims = self._run()
        prims["get_user"].assert_called_once_with("me")
        prims["get_rosters"].assert_called_once_with("L1")
        prims["get_users_in_league"].assert_called_once_with("L1")
        prims["get_traded_picks"].assert_called_once_with("L1")

    def test_2026_ownership_shape_and_sort_unchanged(self):
        result, _ = self._run("2026")
        self.assertEqual(result, {"my_rid": 1, "picks": [
            {"round": 1, "orig_rid": 1, "source": "own", "from_team": "Me"},
            {"round": 1, "orig_rid": 2, "source": "acquired", "from_team": "Team Two"},
            {"round": 3, "orig_rid": 1, "source": "own", "from_team": "Me"},
            {"round": 4, "orig_rid": 1, "source": "own", "from_team": "Me"},
        ]})

    def test_requested_season_filters_traded_picks(self):
        result, _ = self._run("2027")
        self.assertEqual([(p["round"], p["orig_rid"], p["source"]) for p in result["picks"]],
                         [(1, 1, "own"), (1, 3, "acquired"), (2, 1, "own"), (3, 1, "own"), (4, 1, "own")])

    def test_default_season_is_still_2026(self):
        tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_load_pick_arsenal")
        self.assertEqual(ast.literal_eval(fn.args.defaults[0]), "2026")
        self.assertIn('_load_pick_arsenal("2026")', APP_PATH.read_text(encoding="utf-8"))

    def test_missing_roster_returns_same_error_dict(self):
        result, _ = self._run(get_user=mock.Mock(return_value={"user_id": "nobody"}))
        self.assertEqual(result, {"error": "Could not find your roster"})

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
        return _load_pick_arsenal_from_app({"os": os, **{n: getattr(facade, n, None) for n in names}})

    def test_success_through_the_real_facade_and_shared_core(self):
        fn = self._fn()
        with _env(), mock.patch.object(core.httpx, "get", side_effect=self._fake()) as http_get:
            result = fn("2026")
        self.assertEqual(result["my_rid"], 1)
        self.assertEqual(len(result["picks"]), 4)
        self.assertEqual(sorted(c.args[0] for c in http_get.call_args_list), sorted(self.ALLOWED))

    def test_non_2xx_traded_picks_now_raises_at_the_provider_boundary(self):
        fn = self._fn()
        with _env(), mock.patch.object(core.httpx, "get",
                                       side_effect=self._fake(fail_url=f"{BASE}/league/L1/traded_picks")):
            with self.assertRaises(httpx.HTTPStatusError):
                fn("2026")


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
