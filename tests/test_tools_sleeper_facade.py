"""
Stage 2B Batch 6: scoutcap/tools/sleeper.py is a pure facade over
dynasty_core.sleeper. It owns no HTTP; it keeps Scout's public names as
aliases (so no caller changes) plus Scout-specific search_players policy.

Deliberate changes to unused surface, each pinned here so it can't regress:
  - get_leagues re-exports the shared version: season is required (the old
    season="2025" default was stale and had no caller).
  - get_player re-exports the shared cached-map lookup, replacing the old raw
    GET /players/nfl/{id} request.
  - get_traded_picks was removed from the facade in Batch 6 (zero callers
    then). Stage 2C-4 re-exports it because app.py's pick-arsenal helper now
    uses it, replacing that helper's direct HTTP. Same reasoning, new caller
    fact: the facade exposes a shared primitive once Scout has a consumer.

The active-consumer tests route a fake at the network layer
(dynasty_core.sleeper.httpx.get) and run real consumers end to end:
consumer -> facade alias -> shared implementation. No live Sleeper,
FantasyCalc, or Anthropic calls.
"""
import inspect
import os
import unittest
from unittest import mock

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-for-import-only")
os.environ.setdefault("GOOGLE_API_KEY", "test-key-for-import-only")

import dynasty_core.sleeper as core
import tools.sleeper as facade

BASE = core.BASE_URL

CATALOG = {
    "100": {"full_name": "Bijan Robinson", "position": "RB", "team": "ATL",
            "years_exp": 3, "depth_chart_order": 1, "search_rank": 5},
    "101": {"full_name": "Travis Hunter", "position": "WR", "team": "JAX",
            "years_exp": 0, "depth_chart_order": 2, "search_rank": 40},
    "102": {"full_name": "Hunter Henry", "position": "TE", "team": "NE",
            "years_exp": 10, "depth_chart_order": 1, "search_rank": 90},
    "103": {"full_name": "Jalen Hurts", "position": "QB", "team": "PHI",
            "years_exp": 6, "depth_chart_order": 1, "search_rank": 3},
    "104": {"full_name": "Hunter Kicker", "position": "K", "team": "DAL", "years_exp": 4},
    "PHI": {"full_name": None, "position": "DEF", "team": "PHI"},
}


class _FakeSleeper:
    """Routes httpx.get by URL, records every URL, and fails loudly on any
    route the facade should never produce (e.g. the raw single-player one)."""

    def __init__(self):
        self.urls = []

    def __call__(self, url, params=None, timeout=None):
        self.urls.append(url)
        routes = {
            f"{BASE}/user/me": {"user_id": "u1", "username": "me"},
            f"{BASE}/league/L1/rosters": [
                {"owner_id": "u1", "players": ["100", "101", "103", "104"]},
                {"owner_id": "u2", "players": ["102"]},
            ],
            f"{BASE}/league/L1/users": [{"user_id": "u1"}, {"user_id": "u2"}],
            f"{BASE}/players/nfl": CATALOG,
            f"{BASE}/players/nfl/trending/add": [
                {"player_id": "101", "count": 900},
                {"player_id": "104", "count": 500},
                {"player_id": "100", "count": 300},
            ],
        }
        if url not in routes:
            raise AssertionError(f"unexpected Sleeper URL: {url}")
        resp = mock.Mock()
        resp.json.return_value = routes[url]
        resp.raise_for_status.return_value = None
        return resp


class _SharedCacheReset(unittest.TestCase):
    def setUp(self):
        self._orig = (core._players_cache, core._players_cache_time)
        core._players_cache = None
        core._players_cache_time = 0.0
        self.fake = _FakeSleeper()
        patcher = mock.patch.object(core.httpx, "get", side_effect=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        core._players_cache, core._players_cache_time = self._orig


class FacadeAliasIdentityTest(unittest.TestCase):
    def test_active_names_are_shared_implementations(self):
        self.assertIs(facade.get_user, core.get_user)
        self.assertIs(facade.get_rosters, core.get_league_rosters)
        self.assertIs(facade.get_users_in_league, core.get_league_users)
        self.assertIs(facade.get_nfl_players, core.get_all_players)
        self.assertIs(facade.get_trending, core.get_trending)

    def test_unused_names_re_export_shared_contracts(self):
        self.assertIs(facade.get_leagues, core.get_leagues)
        self.assertIs(facade.get_player, core.get_player)


class FacadeOwnsNoNetworkTest(unittest.TestCase):
    def test_source_has_no_http_or_raw_sleeper_urls(self):
        source = inspect.getsource(facade)
        for forbidden in ("import httpx", "httpx.", "api.sleeper.app", "https://", "BASE"):
            self.assertNotIn(forbidden, source)

    def test_module_has_no_httpx_or_base_attribute(self):
        self.assertFalse(hasattr(facade, "httpx"))
        self.assertFalse(hasattr(facade, "BASE"))

    def test_traded_picks_is_the_shared_primitive_now_that_it_has_a_caller(self):
        self.assertIs(facade.get_traded_picks, core.get_traded_picks)


class FacadeContractTest(_SharedCacheReset):
    def test_get_trending_keeps_active_scout_call_shape(self):
        result = facade.get_trending("add", limit=25)
        core.httpx.get.assert_called_once_with(
            f"{BASE}/players/nfl/trending/add",
            params={"lookback_hours": 24, "limit": 25},
            timeout=15,
        )
        self.assertEqual([t["player_id"] for t in result], ["101", "104", "100"])

    def test_get_leagues_requires_explicit_season(self):
        season = inspect.signature(facade.get_leagues).parameters["season"]
        self.assertIs(season.default, inspect.Parameter.empty)
        with self.assertRaises(TypeError):
            facade.get_leagues("u1")

    def test_get_player_uses_cached_map_not_raw_single_player_route(self):
        self.assertIs(facade.get_player("103"), CATALOG["103"])
        self.assertIsNone(facade.get_player("does-not-exist"))
        self.assertEqual(self.fake.urls, [f"{BASE}/players/nfl"])


class SearchPlayersPolicyTest(unittest.TestCase):
    def _search(self, name):
        with mock.patch.object(facade, "get_nfl_players", return_value=CATALOG):
            return facade.search_players(name)

    def test_case_insensitive_substring_match(self):
        names = sorted(p["full_name"] for p in self._search("hUnTeR"))
        self.assertEqual(names, ["Hunter Henry", "Travis Hunter"])

    def test_only_skill_positions_returned(self):
        # "Hunter Kicker" (K) matches the name but is filtered out by position;
        # the DEF entry with full_name=None must not crash the match.
        self.assertNotIn("Hunter Kicker", [p["full_name"] for p in self._search("hunter")])
        self.assertTrue(all(p["position"] in ("QB", "RB", "WR", "TE") for p in self._search("")))

    def test_player_id_attached(self):
        [p] = self._search("jalen hurts")
        self.assertEqual(p["player_id"], "103")
        self.assertEqual(p["team"], "PHI")


class SearchPlayersInheritsSharedCacheTest(_SharedCacheReset):
    def test_repeated_searches_fetch_catalog_once(self):
        facade.search_players("hunter")
        facade.search_players("bijan")
        self.assertEqual(self.fake.urls, [f"{BASE}/players/nfl"])


class ActiveConsumersThroughFacadeTest(_SharedCacheReset):
    def test_synthesis_get_my_roster_needs(self):
        import agents.synthesis_agent as synthesis

        def fake_value(pid):
            return {"dynasty_value": int(pid) * 10, "dynasty_pos_rank": 3}

        with mock.patch.dict(os.environ, {"SLEEPER_USERNAME": "me", "SLEEPER_LEAGUE_ID": "L1"}), \
             mock.patch("tools.fantasycalc.get_player_value", side_effect=fake_value):
            result = synthesis.get_my_roster_needs()

        counts = {pos: v["count"] for pos, v in result["roster_by_position"].items()}
        # My roster: 100 RB, 101 WR, 103 QB, 104 K (K dropped); 102 TE is u2's.
        self.assertEqual(counts, {"QB": 1, "RB": 1, "WR": 1, "TE": 0})
        self.assertEqual(
            sorted(self.fake.urls),
            sorted([f"{BASE}/user/me", f"{BASE}/league/L1/rosters",
                    f"{BASE}/league/L1/users", f"{BASE}/players/nfl"]),
        )

    def test_situation_player_depth_lookup(self):
        import agents.situation_agent as situation
        result = situation.lookup_player_opportunity("travis hunter")
        self.assertEqual(result["player_id"], "101")
        self.assertEqual(result["team"], "JAX")
        self.assertEqual(result["depth_chart_order"], 2)
        self.assertEqual(self.fake.urls, [f"{BASE}/players/nfl"])

    def test_mcp_trending_adds(self):
        import mcp_server
        result = mcp_server.trending_adds(limit=10)
        # K (104) filtered out; order and counts preserved.
        self.assertEqual(
            [(t["name"], t["add_count"]) for t in result["trending_adds"]],
            [("Travis Hunter", 900), ("Bijan Robinson", 300)],
        )
        self.assertEqual(
            self.fake.urls,
            [f"{BASE}/players/nfl/trending/add", f"{BASE}/players/nfl"],
        )


if __name__ == "__main__":
    unittest.main()
