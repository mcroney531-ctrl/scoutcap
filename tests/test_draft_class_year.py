"""
D1: one Scout-owned draft class year.

config/league.py owns DRAFT_CLASS_YEAR (2026). It is a deliberate, manual
product switch, never derived from the calendar: the Sleeper rookie board
(years_exp == 0) stays the 2026 class into late 2026, so a date-based roll to
2027 would split Scout across two classes.

Before D1, "2026" was written independently in app.py, the Production and
Situation agents, the Synthesis sentiment note, tools/espn.py defaults and
mcp_server.py. The ESPN draft-roster cache was also a single slot, so the
first season loaded was returned for every later season.

The college-stats clock ("most recent completed college season") is a
separate, deliberately calendar-based concept and stays that way.
"""
import inspect
import os
import pathlib
import re
import unittest
from unittest import mock

os.environ.setdefault("ANTHROPIC_API_KEY", "x")

import config.league as league
import tools.espn as espn

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNTIME_FILES = (
    [ROOT / "app.py", ROOT / "mcp_server.py"]
    + sorted((ROOT / "agents").glob("*.py"))
    + sorted((ROOT / "tools").glob("*.py"))
    + sorted((ROOT / "config").glob("*.py"))
)


class CanonicalYearTest(unittest.TestCase):
    def test_draft_class_year_is_2026_and_an_int(self):
        self.assertEqual(league.DRAFT_CLASS_YEAR, 2026)
        self.assertIsInstance(league.DRAFT_CLASS_YEAR, int)

    def test_no_runtime_file_writes_the_year_independently(self):
        for path in RUNTIME_FILES:
            if path == ROOT / "config" / "league.py":
                continue
            with self.subTest(str(path.relative_to(ROOT))):
                self.assertIsNone(re.search(r"\b2026\b", path.read_text(encoding="utf-8")))

    def test_config_defines_it_once(self):
        src = (ROOT / "config" / "league.py").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"^DRAFT_CLASS_YEAR\s*=", src, re.M)), 1)

    def test_not_derived_from_the_calendar(self):
        src = (ROOT / "config" / "league.py").read_text(encoding="utf-8")
        self.assertNotIn("date.today", src)
        self.assertNotIn("datetime", src)


class ConsumersUseTheCanonicalYearTest(unittest.TestCase):
    """Patch the consumer module's name to a different year: the call must follow."""

    def test_production_agent_draft_lookup(self):
        import agents.production_agent as production
        with mock.patch.object(production, "DRAFT_CLASS_YEAR", 2031), \
             mock.patch.object(production, "search_draft_prospects", return_value=[]) as search:
            production.lookup_draft_prospect_info("Some Rookie")
        search.assert_called_once_with("Some Rookie", season=2031)

    def test_situation_agent_draft_capital(self):
        import agents.situation_agent as situation
        with mock.patch.object(situation, "DRAFT_CLASS_YEAR", 2031), \
             mock.patch.object(situation, "search_draft_prospects", return_value=[]) as search:
            situation.lookup_draft_capital("Some Rookie")
        search.assert_called_once_with("Some Rookie", season=2031)

    def test_mcp_search_prospects(self):
        import mcp_server
        with mock.patch.object(mcp_server, "DRAFT_CLASS_YEAR", 2031), \
             mock.patch.object(mcp_server, "search_draft_prospects", return_value=[]) as search:
            mcp_server.search_prospects("Some Rookie")
        search.assert_called_once_with("Some Rookie", season=2031)

    def test_espn_draft_helper_defaults(self):
        for name in ("_build_draft_roster", "_get_draft_roster", "search_draft_prospects",
                     "get_espn_athlete_id", "get_draft_prospect"):
            with self.subTest(name):
                default = inspect.signature(getattr(espn, name)).parameters["season"].default
                self.assertEqual(default, league.DRAFT_CLASS_YEAR)

    def test_synthesis_sentiment_note_uses_the_configured_year(self):
        import agents.synthesis_agent as synthesis
        with mock.patch.object(synthesis, "DRAFT_CLASS_YEAR", 2031), \
             mock.patch.object(synthesis, "get_trending", return_value=[]), \
             mock.patch.object(synthesis, "get_nfl_players", return_value={}):
            note = synthesis.get_sentiment_signal("Some Rookie")["note"]
        self.assertIn("2031 rookie class", note)


class EspnCacheIsSeasonKeyedTest(unittest.TestCase):
    def setUp(self):
        self._saved = dict(espn._draft_roster_cache)
        espn._draft_roster_cache.clear()

    def tearDown(self):
        espn._draft_roster_cache.clear()
        espn._draft_roster_cache.update(self._saved)

    def test_each_season_is_built_once_and_kept_separate(self):
        with mock.patch.object(espn, "_build_draft_roster", side_effect=lambda s: {"season": s}) as build:
            first = espn._get_draft_roster(2026)
            again = espn._get_draft_roster(2026)
            other = espn._get_draft_roster(2027)
            back = espn._get_draft_roster(2026)
        self.assertEqual([c.args[0] for c in build.call_args_list], [2026, 2027])
        self.assertEqual((first, again, back), ({"season": 2026},) * 3)
        self.assertEqual(other, {"season": 2027})

    def test_search_uses_the_requested_seasons_roster(self):
        rosters = {2026: {"alpha": {"name": "Alpha"}}, 2027: {"beta": {"name": "Beta"}}}
        with mock.patch.object(espn, "_build_draft_roster", side_effect=lambda s: rosters[s]):
            self.assertEqual(espn.search_draft_prospects("alpha", season=2026), [{"name": "Alpha"}])
            self.assertEqual(espn.search_draft_prospects("beta", season=2027), [{"name": "Beta"}])
            self.assertEqual(espn.search_draft_prospects("beta", season=2026), [])


class CollegeSeasonClockStaysSeparateTest(unittest.TestCase):
    def test_college_season_is_calendar_based_and_independent(self):
        import agents.production_agent as production
        src = inspect.getsource(production._latest_completed_college_season)
        self.assertIn("date.today()", src)
        self.assertNotIn("DRAFT_CLASS_YEAR", src)


if __name__ == "__main__":
    unittest.main()
