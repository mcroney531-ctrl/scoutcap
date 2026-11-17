"""
D4 (model-facing): the MCP dynasty_value tool description is read by MCP
clients' models, and it called the league "12-team superflex PPR". Scout's
league is half-PPR (config/league.py LEAGUE["scoring"]), and FantasyCalc is
queried with ppr=0.5. Only the description changes, not the tool.
"""
import os
import re
import unittest

os.environ.setdefault("ANTHROPIC_API_KEY", "x")

import mcp_server
from config.league import LEAGUE


class McpLeagueDescriptionTest(unittest.TestCase):
    def test_dynasty_value_description_states_half_ppr(self):
        self.assertEqual(LEAGUE["scoring"], "half-PPR")
        doc = mcp_server.dynasty_value.__doc__ or ""
        self.assertIn("12-team superflex half-PPR settings", doc)
        self.assertIsNone(re.search(r"(?<!half-)\bPPR\b", doc))


if __name__ == "__main__":
    unittest.main()
