"""
Scout's dependency checker, on fixture pyproject.toml / uv.lock data.

Stage 2C-6.5 introduced exactly one immutable VCS form, reserved for the
shared package. The uv migration keeps that contract and moves it into
pyproject.toml: seven exact ordinary pins, plus a bare `dynasty-core`
dependency whose only allowed source is

  [tool.uv.sources]
  dynasty-core = { git = "https://github.com/mcroney531-ctrl/dynasty-core.git", rev = "<40 lowercase hex>" }

Every form that was rejected in requirements.txt is still rejected in its
pyproject equivalent, plus the new uv-specific escape hatches (path / url /
index / editable sources, extra indexes, overrides, dependency groups). The
real-file contract lives in test_uv_project_contract.py.

The installed-source checks mock importlib.metadata, so they test checker
behavior, not whatever this sandbox happens to have installed.
"""
import json
import unittest
from unittest import mock

import scripts.check_dependency_versions as cdv

SHA = "0123456789abcdef0123456789abcdef01234567"
REPO = "https://github.com/mcroney531-ctrl/dynasty-core"
GIT = f"{REPO}.git"

SEVEN = [
    "google-adk[extensions]==2.9.2",
    "anthropic==1.6.0",
    "httpx==0.28.1",
    "python-dotenv==1.2.3",
    "streamlit==1.64.0",
    "pandas==2.3.3",
    "mcp[cli]==1.28.1",
]


def _data(deps=None, source=None, sources=None, uv=None, extra=None, project=None):
    """Build parsed-pyproject data. `source` replaces the dynasty-core entry."""
    data = {
        "project": {"name": "scoutcap", "requires-python": ">=3.14,<3.15",
                    "dependencies": (SEVEN + ["dynasty-core"]) if deps is None else deps,
                    **(project or {})},
        "tool": {"uv": {"package": False,
                        "sources": ({"dynasty-core": {"git": GIT, "rev": SHA} if source is None else source}
                                    if sources is None else sources),
                        **(uv or {})}},
    }
    data.update(extra or {})
    return data


class ValidProjectTest(unittest.TestCase):
    def test_seven_pins_plus_the_immutable_git_source(self):
        parsed = cdv.parse_project_data(_data())
        self.assertEqual(len(parsed), 8)
        self.assertEqual(parsed["dynasty-core"], {"kind": "git", "value": SHA, "repo": REPO})
        self.assertEqual(sum(s["kind"] == "version" for s in parsed.values()), 7)
        self.assertEqual(parsed["google-adk"], {"kind": "version", "value": "2.9.2", "extras": "[extensions]"})

    def test_text_entry_point_parses_real_toml(self):
        text = (
            '[project]\nname = "scoutcap"\ndependencies = ["httpx==0.28.1", "dynasty-core"]\n'
            '[tool.uv]\npackage = false\n'
            f'[tool.uv.sources]\ndynasty-core = {{ git = "{GIT}", rev = "{SHA}" }}\n'
        )
        self.assertEqual(set(cdv.parse_project_text(text)), {"httpx", "dynasty-core"})

    def test_invalid_toml_is_a_contract_error(self):
        with self.assertRaises(cdv.DependencyContractError):
            cdv.parse_project_text("[project\n")


class ImmutableGitSourceTest(unittest.TestCase):
    REJECTED_SOURCES = {
        "rev main": {"git": GIT, "rev": "main"},
        "rev master": {"git": GIT, "rev": "master"},
        "rev tag": {"git": GIT, "rev": "v0.1.0"},
        "short sha 7": {"git": GIT, "rev": SHA[:7]},
        "short sha 16": {"git": GIT, "rev": SHA[:16]},
        "39 hex": {"git": GIT, "rev": SHA[:-1]},
        "41 hex": {"git": GIT, "rev": SHA + "0"},
        "uppercase sha": {"git": GIT, "rev": SHA.upper()},
        "missing rev": {"git": GIT},
        "branch key": {"git": GIT, "branch": "main"},
        "tag key": {"git": GIT, "tag": "v0.1.0"},
        "rev plus branch": {"git": GIT, "rev": SHA, "branch": "main"},
        "subdirectory": {"git": GIT, "rev": SHA, "subdirectory": "pkg"},
        "different owner": {"git": "https://github.com/someone-else/dynasty-core.git", "rev": SHA},
        "different repository": {"git": "https://github.com/mcroney531-ctrl/other-repo.git", "rev": SHA},
        "missing .git suffix": {"git": REPO, "rev": SHA},
        "git+ssh": {"git": "ssh://git@github.com/mcroney531-ctrl/dynasty-core.git", "rev": SHA},
        "http not https": {"git": "http://github.com/mcroney531-ctrl/dynasty-core.git", "rev": SHA},
        "embedded token": {"git": "https://token@github.com/mcroney531-ctrl/dynasty-core.git", "rev": SHA},
        "user:pass": {"git": "https://u:p@github.com/mcroney531-ctrl/dynasty-core.git", "rev": SHA},
        "archive url": {"url": f"{REPO}/archive/{SHA}.zip"},
        "local path": {"path": "../dynasty-core"},
        "editable path": {"path": "../dynasty-core", "editable": True},
        "index source": {"index": "private"},
        "workspace": {"workspace": True},
        "list of sources": [{"git": GIT, "rev": SHA}],
        "non-string rev": {"git": GIT, "rev": 123},
    }

    def test_every_non_immutable_source_is_rejected(self):
        for label, source in self.REJECTED_SOURCES.items():
            with self.subTest(label), self.assertRaises(cdv.DependencyContractError):
                cdv.parse_project_data(_data(source=source))

    def test_sources_for_any_other_package_are_rejected(self):
        for label, sources in {
            "httpx from the core repo": {"dynasty-core": {"git": GIT, "rev": SHA},
                                         "httpx": {"git": GIT, "rev": SHA}},
            "requests from its own repo": {"dynasty-core": {"git": GIT, "rev": SHA},
                                           "requests": {"git": "https://github.com/psf/requests.git", "rev": SHA}},
            "non-canonical key spelling": {"dynasty_core": {"git": GIT, "rev": SHA}},
        }.items():
            with self.subTest(label), self.assertRaises(cdv.DependencyContractError):
                cdv.parse_project_data(_data(sources=sources))

    def test_dynasty_core_without_its_source_is_rejected(self):
        # An unsourced name would resolve from a package index.
        with self.assertRaises(cdv.DependencyContractError):
            cdv.parse_project_data(_data(sources={}))

    def test_source_without_the_dependency_is_rejected(self):
        with self.assertRaises(cdv.DependencyContractError):
            cdv.parse_project_data(_data(deps=list(SEVEN)))

    REJECTED_DYNASTY_CORE_ENTRIES = {
        "index pin": "dynasty-core==0.1.0",
        "direct reference": f"dynasty-core @ git+{GIT}@{SHA}",
        "extras": "dynasty-core[extra]",
        "marker": "dynasty-core ; python_version >= '3.14'",
        "range": "dynasty-core>=0.1",
        "non-canonical spelling": "dynasty_core",
    }

    def test_dynasty_core_must_be_the_bare_name(self):
        for label, entry in self.REJECTED_DYNASTY_CORE_ENTRIES.items():
            with self.subTest(label), self.assertRaises(cdv.DependencyContractError):
                cdv.parse_project_data(_data(deps=SEVEN + [entry]))


class OrdinaryPinsAreNotWeakenedTest(unittest.TestCase):
    def test_ranges_unpinned_urls_and_markers_are_rejected(self):
        for entry in ("httpx>=0.28", "httpx~=0.28.1", "httpx<1", "httpx", "httpx==0.28.*,<1",
                      "httpx @ https://example.com/httpx.whl", f"httpx @ git+{GIT}@{SHA}",
                      "httpx==0.28.1 ; python_version >= '3.14'", "httpx == 0.28.1", "-e .", 7):
            with self.subTest(entry), self.assertRaises(cdv.DependencyContractError):
                cdv.parse_project_data(_data(deps=SEVEN + ["dynasty-core", entry]))

    def test_invalid_entry_fails_instead_of_being_skipped(self):
        with self.assertRaises(cdv.DependencyContractError) as ctx:
            cdv.parse_project_data(_data(deps=SEVEN + ["dynasty-core", "fastapi>=0.1"]))
        self.assertIn("fastapi>=0.1", str(ctx.exception))

    def test_duplicates_are_rejected_including_normalized_names(self):
        for dup in ("dynasty-core", "python_dotenv==1.2.3", "HTTPX==0.28.1", "Google.ADK==2.9.2"):
            with self.subTest(dup), self.assertRaises(cdv.DependencyContractError):
                cdv.parse_project_data(_data(deps=SEVEN + ["dynasty-core", dup]))

    def test_dependencies_must_be_a_list(self):
        with self.assertRaises(cdv.DependencyContractError):
            cdv.parse_project_data(_data(deps="httpx==0.28.1"))


class UvSettingsCannotWidenTheGraphTest(unittest.TestCase):
    def test_extra_indexes_overrides_and_groups_are_rejected(self):
        cases = {
            "index-url": _data(uv={"index-url": "https://evil.example/simple"}),
            "extra-index-url": _data(uv={"extra-index-url": ["https://evil.example/simple"]}),
            "index table": _data(uv={"index": [{"name": "private", "url": "https://evil.example/simple"}]}),
            "find-links": _data(uv={"find-links": ["https://evil.example/wheels"]}),
            "override-dependencies": _data(uv={"override-dependencies": ["httpx==0.27.0"]}),
            "constraint-dependencies": _data(uv={"constraint-dependencies": ["httpx<0.28"]}),
            "dev-dependencies": _data(uv={"dev-dependencies": ["pytest"]}),
            "package true": _data(uv={"package": True}),
            "dependency-groups": _data(extra={"dependency-groups": {"dev": ["pytest"]}}),
            "optional-dependencies": _data(project={"optional-dependencies": {"x": ["pytest"]}}),
        }
        for label, data in cases.items():
            with self.subTest(label), self.assertRaises(cdv.DependencyContractError):
                cdv.parse_project_data(data)

    def test_package_setting_is_required(self):
        data = _data()
        del data["tool"]["uv"]["package"]
        with self.assertRaises(cdv.DependencyContractError):
            cdv.parse_project_data(data)


def _lock(**changes):
    pypi = {"registry": cdv.PYPI_REGISTRY}
    packages = {
        "google-adk": {"name": "google-adk", "version": "2.9.2", "source": pypi},
        "anthropic": {"name": "anthropic", "version": "1.6.0", "source": pypi},
        "httpx": {"name": "httpx", "version": "0.28.1", "source": pypi},
        "python-dotenv": {"name": "python-dotenv", "version": "1.2.3", "source": pypi},
        "streamlit": {"name": "streamlit", "version": "1.64.0", "source": pypi},
        "pandas": {"name": "pandas", "version": "2.3.3", "source": pypi},
        "mcp": {"name": "mcp", "version": "1.28.1", "source": pypi},
        "dynasty-core": {"name": "dynasty-core", "version": "0.1.0",
                         "source": {"git": f"{GIT}?rev={SHA}#{SHA}"}},
        "certifi": {"name": "certifi", "version": "2026.1.1", "source": pypi},
        "scoutcap": {"name": "scoutcap", "version": "0.0.0", "source": {"virtual": "."}},
    }
    for name, value in changes.items():
        name = name.replace("_", "-")
        if value is None:
            packages.pop(name, None)
        else:
            packages[name] = {"name": name, **value}
    return {"version": 1, "requires-python": "==3.14.*", "package": list(packages.values())}


class LockCheckTest(unittest.TestCase):
    def setUp(self):
        self.specs = cdv.parse_project_data(_data())

    def test_consistent_lock_has_no_problems(self):
        self.assertEqual(cdv.check_lock_data(_lock(), self.specs), [])

    def test_lock_inconsistencies_are_reported(self):
        pypi = {"registry": cdv.PYPI_REGISTRY}
        cases = {
            "ordinary version drift": _lock(httpx={"version": "0.28.2", "source": pypi}),
            "ordinary pin from another index": _lock(httpx={"version": "0.28.1",
                                                            "source": {"registry": "https://evil.example/simple"}}),
            "core at another commit": _lock(dynasty_core={"version": "0.1.0",
                                                          "source": {"git": f"{GIT}?rev={'f' * 40}#{'f' * 40}"}}),
            "core resolved to another commit": _lock(dynasty_core={"version": "0.1.0",
                                                                   "source": {"git": f"{GIT}?rev={SHA}#{'f' * 40}"}}),
            "core from another repo": _lock(dynasty_core={
                "version": "0.1.0", "source": {"git": f"https://github.com/x/dynasty-core.git?rev={SHA}#{SHA}"}}),
            "core from an index": _lock(dynasty_core={"version": "0.1.0", "source": pypi}),
            "transitive from git": _lock(certifi={"version": "1", "source": {"git": "https://github.com/x/y.git#abc"}}),
            "transitive from url": _lock(certifi={"version": "1", "source": {"url": "https://x/y.whl"}}),
            "transitive from path": _lock(certifi={"version": "1", "source": {"path": "../y"}}),
            "transitive editable": _lock(certifi={"version": "1", "source": {"editable": "../y"}}),
            "pinned package missing": _lock(mcp=None),
        }
        for label, lock in cases.items():
            with self.subTest(label):
                self.assertNotEqual(cdv.check_lock_data(lock, self.specs), [])

    def test_duplicate_locked_entries_are_reported(self):
        lock = _lock()
        lock["package"].append({"name": "httpx", "version": "0.27.0", "source": {"registry": cdv.PYPI_REGISTRY}})
        self.assertNotEqual(cdv.check_lock_data(lock, self.specs), [])

    def test_empty_lock_is_reported(self):
        self.assertNotEqual(cdv.check_lock_data({"version": 1}, self.specs), [])


class _FakeDist:
    def __init__(self, direct_url):
        self._direct_url = direct_url

    def read_text(self, name):
        return self._direct_url if name == "direct_url.json" else None


def _metadata(direct_url=None, installed=True):
    md = mock.Mock()
    md.PackageNotFoundError = type("PackageNotFoundError", (Exception,), {})
    if installed:
        md.distribution.return_value = _FakeDist(direct_url)
    else:
        md.distribution.side_effect = md.PackageNotFoundError("dynasty-core")
    return md


def _direct_url(url=GIT, vcs="git", commit=SHA, requested=SHA):
    return json.dumps({"url": url, "vcs_info": {"vcs": vcs, "commit_id": commit, "requested_revision": requested}})


class GitInstalledSourceCheckTest(unittest.TestCase):
    def _check(self, md):
        return cdv.check_git_install("dynasty-core", SHA, REPO, metadata=md)

    def test_matching_repository_and_commit_is_ok(self):
        self.assertEqual(self._check(_metadata(_direct_url()))[0], "OK")

    def test_benign_url_spelling_differences_are_ok(self):
        for url in (REPO, f"{REPO}/", GIT, f"{GIT}/"):
            with self.subTest(url):
                self.assertEqual(self._check(_metadata(_direct_url(url=url)))[0], "OK")

    def test_wrong_commit_is_mismatch(self):
        status, message = self._check(_metadata(_direct_url(commit="f" * 40, requested="main")))
        self.assertEqual(status, "MISMATCH")
        self.assertIn("requested 'main'", message)

    def test_missing_direct_url_is_mismatch(self):
        self.assertEqual(self._check(_metadata(None))[0], "MISMATCH")

    def test_malformed_direct_url_is_mismatch(self):
        for raw in ("{not json", json.dumps({"url": REPO}), json.dumps({"vcs_info": {"vcs": "git"}}), "[]"):
            with self.subTest(raw):
                self.assertEqual(self._check(_metadata(raw))[0], "MISMATCH")

    def test_non_git_vcs_is_mismatch(self):
        self.assertEqual(self._check(_metadata(_direct_url(vcs="hg")))[0], "MISMATCH")

    def test_wrong_repository_is_mismatch_even_with_matching_commit(self):
        for url in ("https://github.com/someone-else/dynasty-core.git",
                    "https://github.com/mcroney531-ctrl/other-repo.git",
                    "https://token@github.com/mcroney531-ctrl/dynasty-core.git"):
            with self.subTest(url):
                self.assertEqual(self._check(_metadata(_direct_url(url=url)))[0], "MISMATCH")

    def test_package_not_installed_is_missing(self):
        self.assertEqual(self._check(_metadata(installed=False))[0], "MISSING")


class MainDispatchTest(unittest.TestCase):
    def test_git_spec_is_checked_by_source_not_version(self):
        specs = cdv.parse_project_data(_data())
        with mock.patch.object(cdv, "parse_project", return_value=specs), \
             mock.patch.object(cdv, "check_lock", return_value=[]), \
             mock.patch.object(cdv, "check_version_install", return_value=("OK", "x")) as by_version, \
             mock.patch.object(cdv, "check_git_install", return_value=("OK", "git")) as by_git, \
             mock.patch("builtins.print"):
            self.assertEqual(cdv.main(), 0)
        by_git.assert_called_once_with("dynasty-core", SHA, REPO)
        self.assertEqual(by_version.call_count, 7)
        self.assertNotIn("dynasty-core", [c.args[0] for c in by_version.call_args_list])

    def test_invalid_project_makes_main_fail(self):
        with mock.patch.object(cdv, "parse_project", side_effect=cdv.DependencyContractError("bad")), \
             mock.patch("builtins.print"):
            self.assertEqual(cdv.main(), 2)

    def test_inconsistent_lock_makes_main_fail_before_install_checks(self):
        specs = cdv.parse_project_data(_data())
        with mock.patch.object(cdv, "parse_project", return_value=specs), \
             mock.patch.object(cdv, "check_lock", return_value=["httpx: drift"]), \
             mock.patch.object(cdv, "check_version_install") as by_version, \
             mock.patch("builtins.print"):
            self.assertEqual(cdv.main(), 2)
        by_version.assert_not_called()


if __name__ == "__main__":
    unittest.main()
