"""
Stage 2C-5: scoutcap's requirements.txt pins its seven direct runtime
dependencies to the exact versions verified by a clean Python 3.12
install + full suite + Streamlit AppTest. This only checks that the file
itself is a clean, exact-pin contract. Whether the *installed* versions
match belongs to scripts/check_dependency_versions.py, which stays out of
the offline suite because the installed set varies by environment.

Direct pins only, not a transitive lockfile (same discipline as
Ddreportcards' Phase 4B).

Stage 2C-7: the actual file now holds the seven ==-pins plus exactly one
immutable dynasty-core Git pin (the canonical shared package, replacing the
local dynasty_core/ copy). test_dependency_contract.py proves every other
VCS/URL form is rejected. parse_requirements() covers the whole contract;
parse_pins() intentionally returns only the ordinary version pins.
"""
import pathlib
import re
import unittest

import scripts.check_dependency_versions as check_versions

REQUIREMENTS_PATH = pathlib.Path(__file__).resolve().parent.parent / "requirements.txt"

# Canonical dynasty-core commit pinned by this app (Stage 2C-7).
CORE_SHA = "cef3c3d2b7120825110235eb2c30b4f8dd9a0247"

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
    def test_every_non_comment_line_parses_as_an_allowed_form(self):
        specs = check_versions.parse_requirements()
        self.assertEqual(
            len(specs), len(_requirement_lines()),
            "every non-comment line must be an exact ==-pin or the immutable dynasty-core Git pin",
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

    def test_seven_version_pins_plus_one_immutable_dynasty_core_pin(self):
        specs = check_versions.parse_requirements()
        self.assertEqual(len(specs), 8)
        self.assertEqual(sum(spec["kind"] == "version" for spec in specs.values()), 7)
        git = {name: spec for name, spec in specs.items() if spec["kind"] == "git"}
        self.assertEqual(list(git), ["dynasty-core"])
        self.assertEqual(git["dynasty-core"]["repo"], "https://github.com/mcroney531-ctrl/dynasty-core")
        self.assertEqual(git["dynasty-core"]["value"], CORE_SHA)


if __name__ == "__main__":
    unittest.main()
