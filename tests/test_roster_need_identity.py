"""
D4: Scout's second identity reader fails cleanly.

Scout has one logical identity source: SLEEPER_USERNAME and SLEEPER_LEAGUE_ID,
bridged from Streamlit secrets into the environment. The Mock Draft pick
loader (app.py) already validates them. The Synthesis Agent's roster-need
tool did not: with either value missing it called get_user(None), and an
unknown username made it index into None. It now returns the same kind of
structured error the agent can report, without calling Sleeper.
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("ANTHROPIC_API_KEY", "x")

import agents.synthesis_agent as synthesis


class RosterNeedIdentityTest(unittest.TestCase):
    def _run(self, env, user=None):
        calls = {name: mock.Mock(side_effect=AssertionError(f"{name} must not be called"))
                 for name in ("get_user", "get_rosters", "get_users_in_league")}
        if user is not None:
            calls["get_user"] = mock.Mock(return_value=user)
        clean = {k: v for k, v in os.environ.items() if k not in ("SLEEPER_USERNAME", "SLEEPER_LEAGUE_ID")}
        with mock.patch.dict(os.environ, {**clean, **env}, clear=True), \
             mock.patch.multiple(synthesis, **calls):
            return synthesis.get_my_roster_needs(), calls

    def test_missing_identity_is_a_structured_error_without_sleeper_calls(self):
        for env in ({}, {"SLEEPER_USERNAME": "me"}, {"SLEEPER_LEAGUE_ID": "L1"},
                    {"SLEEPER_USERNAME": " ", "SLEEPER_LEAGUE_ID": "L1"}):
            with self.subTest(env=env):
                result, calls = self._run(env)
                self.assertEqual(set(result), {"error"})
                self.assertIn("SLEEPER_USERNAME and SLEEPER_LEAGUE_ID", result["error"])
                for name, call in calls.items():
                    call.assert_not_called()

    def test_unknown_user_is_a_structured_error(self):
        for user in ({}, {"display_name": "x"}):
            with self.subTest(user=user):
                calls_env = {"SLEEPER_USERNAME": "nobody", "SLEEPER_LEAGUE_ID": "L1"}
                with mock.patch.dict(os.environ, calls_env), \
                     mock.patch.object(synthesis, "get_user", return_value=user) as get_user, \
                     mock.patch.object(synthesis, "get_rosters",
                                       side_effect=AssertionError("must not fetch rosters")):
                    result = synthesis.get_my_roster_needs()
                self.assertEqual(set(result), {"error"})
                self.assertIn("SLEEPER_USERNAME", result["error"])
                get_user.assert_called_once_with("nobody")


if __name__ == "__main__":
    unittest.main()
