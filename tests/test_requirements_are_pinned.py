"""
Stage 2C-5: scoutcap's requirements.txt pins its seven direct runtime
dependencies to the exact versions verified by a clean Python 3.12
install + full suite + Streamlit AppTest. This only checks that the file
itself is a clean, exact-pin contract. Whether the *installed* versions
match belongs to scripts/check_dependency_versions.py, which stays out of
the offline suite because the installed set varies by environment.

Direct pins only, not a transitive lockfile (same discipline as
Ddreportcards' Phase 4B).
"""
import pathlib
import re
import unittest

import scripts.check_dependency_versions as check_versions

REQUIREMENTS_PATH = pathlib.Path(__file__).resolve().parent.parent / "requirements.txt"

EXPECTED_DIRECT_DEPENDENCIES = {
    "google-adk",
    "anthropic",
    "httpx",
    "python-dotenv",
    "streamlit",
    "pandas",
    "mcp",
}


def _requirement_lines() -> list[str]:
    return [
        line.strip() for line in REQUIREMENTS_PATH.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


class RequirementsAreFullyPinnedTest(unittest.TestCase):
    def test_every_non_comment_line_parses_as_an_exact_pin(self):
        pins = check_versions.parse_pins()
        self.assertEqual(
            len(pins), len(_requirement_lines()),
            "every non-comment line in requirements.txt must be an exact ==-pinned dependency",
        )

    def test_exactly_the_seven_direct_dependencies_are_present(self):
        pins = check_versions.parse_pins()
        self.assertEqual({_normalize(n) for n in pins}, EXPECTED_DIRECT_DEPENDENCIES)

    def test_no_duplicate_direct_names(self):
        names = [_normalize(re.split(r"[\[=<>~!@ ]", line, maxsplit=1)[0]) for line in _requirement_lines()]
        self.assertEqual(len(names), len(set(names)))

    def test_extras_are_preserved(self):
        text = REQUIREMENTS_PATH.read_text()
        self.assertIn("google-adk[extensions]==", text)
        self.assertIn("mcp[cli]==", text)

    def test_no_ranges_or_vcs_dependencies(self):
        for line in _requirement_lines():
            with self.subTest(line):
                for forbidden in (">=", "<=", "~=", "!=", "<", ">", " @ ", "git+", "://"):
                    self.assertNotIn(forbidden, line)
                self.assertEqual(line.count("=="), 1)


if __name__ == "__main__":
    unittest.main()
