"""
D3: Mock Draft pick-arsenal UI states, driven through Streamlit AppTest.

The draft order and slots come from Sleeper's draft (faked here as the real
league's: linear, 4 x 12, each user drafting from their roster number's slot),
so slot 1 owns 1.01 / 2.01 / 3.01 / 4.01. When Sleeper can't say, the user
must choose an order explicitly; an unsupported order blocks the draft.

Three arsenal states stay distinct:
  not loaded            natural slot picks; the Load button is offered
  load failed           error visible, still not loaded, Load stays available
  loaded (even zero)    exactly the arsenal's picks; zero shows "No picks",
                        Start Draft does not restore natural picks, the draft
                        runs to completion and the haul shows an empty state

Sleeper is faked at the HTTP layer that dynasty_core uses, FantasyCalc is
stubbed and time.sleep is a no-op, so no network or paid call is made.
"""
import os
import pathlib
import unittest
from unittest import mock

os.environ.setdefault("ANTHROPIC_API_KEY", "x")

import httpx
from streamlit.testing.v1 import AppTest

import config.league as league
import dynasty_core.sleeper as core
import tools.fantasycalc as fantasycalc

APP_PATH = str(pathlib.Path(__file__).resolve().parent.parent / "app.py")
# Generous on purpose: the first run in a fresh Python 3.14 environment
# compiles the app's whole import graph (google-adk, litellm, pandas...) and
# was observed to exceed 240s. This bounds startup only; no assertion changes.
APPTEST_TIMEOUT_SECONDS = 900
BASE = core.BASE_URL
YEAR = league.DRAFT_CLASS_YEAR
TEAMS = league.LEAGUE["picks_per_round"]
TOTAL = league.LEAGUE["total_picks"]

PLAYERS = {
    str(1000 + i): {"full_name": f"Rookie {i}", "position": ("QB", "RB", "WR", "TE")[i % 4],
                    "team": "KC", "years_exp": 0, "active": True, "search_rank": 100 + i}
    for i in range(TOTAL + 10)
}
USER = {"user_id": "u1", "display_name": "Me"}
ROSTERS = [{"roster_id": i, "owner_id": f"u{i}"} for i in range(1, TEAMS + 1)]
USERS = [{"user_id": f"u{i}", "display_name": f"Team {i}"} for i in range(1, TEAMS + 1)]
ALL_MY_PICKS_TRADED = [{"season": str(YEAR), "round": r, "roster_id": 1, "owner_id": 2}
                       for r in range(1, league.LEAGUE["rounds"] + 1)]
ACQUIRED_FIRST = [{"season": str(YEAR), "round": 1, "roster_id": 2, "owner_id": 1}]
DRAFT_ORDER = {f"u{i}": i for i in range(1, TEAMS + 1)}


def _draft(type_="linear", reversal=0, status="complete", draft_order=DRAFT_ORDER):
    return {"draft_id": "d1", "season": str(YEAR), "type": type_, "status": status,
            "settings": {"rounds": league.LEAGUE["rounds"], "teams": TEAMS, "reversal_round": reversal},
            "draft_order": draft_order}


LINEAR_DRAFTS = [_draft()]


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://api.sleeper.app/")
            raise httpx.HTTPStatusError("boom", request=request,
                                        response=httpx.Response(self.status_code, request=request))


def _fake_sleeper(traded, rosters=ROSTERS, fail_league=False, drafts=None):
    drafts = LINEAR_DRAFTS if drafts is None else drafts
    def get(url, *a, **k):
        if url == f"{BASE}/players/nfl":
            return _Resp(PLAYERS)
        if url == f"{BASE}/user/me":
            return _Resp(USER)
        if url.startswith(f"{BASE}/league/L1/"):
            if fail_league:
                return _Resp({}, status=503)
            return _Resp({"rosters": rosters, "users": USERS, "drafts": drafts,
                          "traded_picks": traded}[url.rsplit("/", 1)[1]])
        raise AssertionError(f"unexpected request {url}")
    return get


class _MockDraftUiBase(unittest.TestCase):
    def setUp(self):
        core._players_cache = None
        patches = [
            mock.patch.dict(os.environ, {"SLEEPER_USERNAME": "me", "SLEEPER_LEAGUE_ID": "L1"}),
            mock.patch.object(fantasycalc, "get_player_value", return_value=None),
            mock.patch("time.sleep", lambda *_: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _app(self, **sleeper):
        http = mock.patch.object(core.httpx, "get", side_effect=_fake_sleeper(**sleeper))
        http.start()
        self.addCleanup(http.stop)
        at = AppTest.from_file(APP_PATH, default_timeout=APPTEST_TIMEOUT_SECONDS)
        at.session_state["view"] = "mock"
        at.run()
        self.assertFalse(at.exception, at.exception)
        return at

    @staticmethod
    def _button(at, key):
        return next(b for b in at.button if b.key == key)

    @staticmethod
    def _has_button(at, key):
        return any(b.key == key for b in at.button)

    @staticmethod
    def _picks_metric(at):
        return next(m for m in at.metric if m.label == "Your picks").value

    @staticmethod
    def _captions(at):
        return [c.value for c in at.caption]

    def _load(self, at):
        self._button(at, "load_arsenal_btn").click().run()
        self.assertFalse(at.exception, at.exception)


class MockDraftUiTest(_MockDraftUiBase):
    def test_not_loaded_shows_natural_picks(self):
        at = self._app(traded=[])
        self.assertTrue(self._has_button(at, "load_arsenal_btn"))
        self.assertEqual(self._picks_metric(at), "1.01  ·  2.01  ·  3.01  ·  4.01")

    def test_normal_arsenal_loads_labels_and_starts(self):
        at = self._app(traded=ACQUIRED_FIRST)
        self._load(at)
        self.assertEqual(at.session_state["mock_arsenal"]["my_rid"], 1)
        self.assertFalse(self._has_button(at, "load_arsenal_btn"))
        # own 1.01/2.01/3.01/4.01; Team 2's 1st sits at Team 2's real slot, 1.02
        self.assertEqual(self._picks_metric(at), "1.01  ·  1.02  ·  2.01  ·  3.01  ·  4.01")
        self.assertEqual(at.selectbox(key="acq_slot_1_2").value, 2)
        self.assertIn("✓ Sleeper draft order", self._captions(at))
        self._button(at, "start_draft_btn").click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(at.session_state["mock_draft_user_picks_set"], {1, 2, 13, 25, 37})
        self.assertTrue(any("1.01" in m.value for m in at.markdown if "on the clock" in m.value))

    def test_zero_pick_arsenal_stays_zero_through_completion(self):
        at = self._app(traded=ALL_MY_PICKS_TRADED)
        self._load(at)
        self.assertEqual(at.session_state["mock_arsenal"], {"my_rid": 1, "picks": []})
        self.assertTrue(any("hold no picks" in w.value for w in at.warning))
        self.assertEqual(self._picks_metric(at), "No picks")
        self._button(at, "start_draft_btn").click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(at.session_state["mock_draft_user_picks_set"], set())
        self.assertEqual(at.session_state["mock_draft_current_pick"], TOTAL + 1)
        self.assertTrue(any("Draft complete" in s.value for s in at.success))
        self.assertTrue(any("No picks in this draft" in i.value for i in at.info))

    def test_structured_failure_is_visible_not_loaded_and_retryable(self):
        at = self._app(traded=[], rosters=ROSTERS[:TEAMS - 2])
        self._load(at)
        self.assertIsNone(at.session_state["mock_arsenal"])
        self.assertTrue(any(f"{TEAMS - 2} rosters" in e.value for e in at.error))
        self.assertTrue(self._has_button(at, "load_arsenal_btn"))
        # The type is still verified; the 10-roster league can't verify slots.
        self.assertEqual(self._picks_metric(at), "1.01  ·  2.01  ·  3.01  ·  4.01")
        self.assertIn("Assumed — no Sleeper slot available", self._captions(at))

    def test_provider_exception_shows_safe_message_and_retry(self):
        at = self._app(traded=[], fail_league=True)
        self._load(at)
        self.assertIsNone(at.session_state["mock_arsenal"])
        errors = [e.value for e in at.error]
        self.assertEqual(errors, ["Couldn’t load your Sleeper pick assets. Try again."])
        self.assertFalse(at.exception)
        self.assertTrue(self._has_button(at, "load_arsenal_btn"))


class DraftOrderUiTest(_MockDraftUiBase):
    """Order and slot evidence on the setup screen, and the frozen pick set."""

    def test_verified_order_slot_and_replay_caption(self):
        at = self._app(traded=[])
        captions = self._captions(at)
        self.assertIn("Draft order: **Linear** · verified from Sleeper", captions)
        self.assertIn("✓ Sleeper draft order", captions)
        self.assertTrue(any("what-if replay" in c for c in captions))
        self.assertFalse(any(sb.key == "mock_order_assumed" for sb in at.selectbox))
        self.assertFalse(self._button(at, "start_draft_btn").disabled)

    def test_override_is_labelled_and_moves_the_picks_and_board_before_start(self):
        at = self._app(traded=[])
        at.selectbox(key="mock_slot_sel").set_value(6).run()
        self.assertEqual(self._picks_metric(at), "1.06  ·  2.06  ·  3.06  ·  4.06")
        self.assertIn("✎ What-if — Sleeper has slot 1", self._captions(at))
        self._button(at, "start_draft_btn").click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(at.session_state["mock_draft_user_picks_set"], {6, 18, 30, 42})
        self.assertTrue(any("1.06" in m.value for m in at.markdown if "on the clock" in m.value))

    def test_unknown_order_requires_an_explicit_assumption(self):
        at = self._app(traded=[], drafts=[])
        self.assertIsNone(at.selectbox(key="mock_order_assumed").value)
        self.assertEqual(self._picks_metric(at), "Choose a draft order")
        self.assertTrue(self._button(at, "start_draft_btn").disabled)
        self.assertIn("Assumed — no Sleeper slot available", self._captions(at))
        at.selectbox(key="mock_order_assumed").set_value("Snake").run()
        self.assertEqual(self._picks_metric(at), "1.01  ·  2.12  ·  3.01  ·  4.12")
        self.assertFalse(self._button(at, "start_draft_btn").disabled)
        self.assertFalse(any("verified from Sleeper" in c for c in self._captions(at)))

    def test_unsupported_order_blocks_the_draft_without_offering_a_substitute(self):
        at = self._app(traded=[], drafts=[_draft(type_="snake", reversal=3)])
        self.assertTrue(any("reversal" in e.value.lower() for e in at.error))
        self.assertFalse(any(sb.key == "mock_order_assumed" for sb in at.selectbox))
        self.assertEqual(self._picks_metric(at), "Choose a draft order")
        self.assertTrue(self._button(at, "start_draft_btn").disabled)

    def test_verified_type_without_slots_keeps_the_type(self):
        at = self._app(traded=[], drafts=[_draft(status="pre_draft", draft_order=None)])
        captions = self._captions(at)
        self.assertIn("Draft order: **Linear** · verified from Sleeper", captions)
        self.assertIn("Assumed — no Sleeper slot available", captions)
        self.assertFalse(any("what-if replay" in c for c in captions))
        self.assertEqual(self._picks_metric(at), "1.01  ·  2.01  ·  3.01  ·  4.01")

    def test_pick_set_is_frozen_once_the_draft_starts(self):
        at = self._app(traded=[])
        self._button(at, "start_draft_btn").click().run()
        frozen = set(at.session_state["mock_draft_user_picks_set"])
        self.assertEqual(frozen, {1, 13, 25, 37})
        self.assertFalse(any(sb.key in ("mock_slot_sel", "mock_order_assumed") for sb in at.selectbox))
        at.session_state["mock_slot"] = 9
        at.run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(at.session_state["mock_draft_user_picks_set"], frozen)


if __name__ == "__main__":
    unittest.main()
