#!/usr/bin/env python3
"""
Scout's dependency contract: pyproject.toml declares it, uv.lock resolves it
exactly, and the installed environment must match both.

Three layers, all checked by main():

1. pyproject.toml (validated with stdlib tomllib, no extra dependency).
   [project].dependencies may hold only two forms:

     name[optional-extras]==exact-version     ordinary direct dependency
     dynasty-core                             bare name, sourced below

   and [tool.uv.sources] may hold only one entry:

     dynasty-core = { git = "https://github.com/mcroney531-ctrl/dynasty-core.git",
                      rev = "<40 lowercase hex>" }

   Branches, tags, short SHAs, other repositories, other transports,
   embedded credentials, path/url/index/editable sources, sources for any
   other package, extra indexes and dependency overrides are all rejected.
   dynasty-core is never accepted as an index pin or a PEP 508 direct
   reference, and never without its Git source (it isn't published to any
   package index, so an unsourced name could resolve to someone else's
   upload). Anything else is an error, never silently skipped.

2. uv.lock (offline). Each ordinary pin is locked at exactly its version from
   PyPI, dynasty-core is locked from the canonical repository at the pinned
   commit, and every other locked package comes from PyPI: no other Git,
   URL, path or directory source can enter the graph unreviewed. Whether the
   lock is *current* with pyproject.toml is `uv lock --check`, which needs
   uv and runs in the release proof (README "Setup").

3. The installed environment. Ordinary versions must equal the pins. For
   dynasty-core the version proves nothing; the installed package's PEP 610
   direct_url.json must say vcs == "git", commit_id == the pinned SHA and
   url == the canonical repository.

Deliberately NOT part of the offline test suite as a whole run: layer 3
depends on what's installed wherever it runs. Run it after `uv sync --locked`:

  uv run --locked python scripts/check_dependency_versions.py
"""
import importlib.metadata
import json
import pathlib
import re
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PYPROJECT_PATH = ROOT / "pyproject.toml"
LOCK_PATH = ROOT / "uv.lock"

DYNASTY_CORE_DIST = "dynasty-core"
DYNASTY_CORE_REPO_URL = "https://github.com/mcroney531-ctrl/dynasty-core"
DYNASTY_CORE_GIT_URL = DYNASTY_CORE_REPO_URL + ".git"
PYPI_REGISTRY = "https://pypi.org/simple"

_PIN_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)(\[[^\]]+\])?==([A-Za-z0-9_.\-+]+)$")
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
# [tool.uv] may say only these; anything else (indexes, find-links,
# overrides, constraints, dev-dependencies...) could change the graph
# outside the reviewed contract.
_ALLOWED_TOOL_UV_KEYS = {"package", "sources"}
_FORBIDDEN_TOP_LEVEL = ("dependency-groups",)


class DependencyContractError(ValueError):
    """pyproject.toml declares something outside the allowed dependency forms."""


def normalize_name(name: str) -> str:
    """PEP 503 name normalization, for duplicate detection."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _first_name(entry: str) -> str:
    return normalize_name(re.split(r"[\s@\[=<>~!;(]", entry.strip(), maxsplit=1)[0])


def parse_dependency(entry: str) -> tuple[str, dict]:
    """Parse one [project].dependencies entry into (name, spec).

    spec is {"kind": "version", "value": "<version>", "extras": "[...]" or ""}
    or {"kind": "sourced"} for the bare dynasty-core name, which only becomes
    a Git spec once its [tool.uv.sources] entry is validated."""
    if not isinstance(entry, str):
        raise DependencyContractError(f"{entry!r}: dependency entries must be strings")
    if entry == DYNASTY_CORE_DIST:
        return DYNASTY_CORE_DIST, {"kind": "sourced"}
    pin = _PIN_PATTERN.match(entry)
    if pin and normalize_name(pin.group(1)) != DYNASTY_CORE_DIST:
        name, extras, version = pin.groups()
        return name, {"kind": "version", "value": version, "extras": extras or ""}
    if _first_name(entry) == DYNASTY_CORE_DIST:
        raise DependencyContractError(
            f"{entry!r}: list dynasty-core as exactly 'dynasty-core' and pin it in [tool.uv.sources] "
            f"(git = {DYNASTY_CORE_GIT_URL!r}, rev = <40-char lowercase commit sha>)"
        )
    raise DependencyContractError(
        f"{entry!r}: not an allowed dependency form -- expected 'name[extras]==exact-version' "
        "(no ranges, markers, URLs or direct references)"
    )


def parse_dynasty_core_source(sources) -> str:
    """Validate [tool.uv.sources]; return the pinned dynasty-core commit."""
    if not isinstance(sources, dict):
        raise DependencyContractError("[tool.uv.sources] must be a table")
    extra = sorted(k for k in sources if k != DYNASTY_CORE_DIST)
    if extra:
        raise DependencyContractError(f"[tool.uv.sources] may only configure dynasty-core, not {extra}")
    source = sources.get(DYNASTY_CORE_DIST)
    if not isinstance(source, dict):
        raise DependencyContractError(
            "dynasty-core needs exactly one [tool.uv.sources] table entry (no lists of sources)"
        )
    if set(source) != {"git", "rev"}:
        raise DependencyContractError(
            f"dynasty-core source must have exactly 'git' and 'rev' (got {sorted(source)}): "
            "no branch, tag, path, url, index, editable or subdirectory"
        )
    if source["git"] != DYNASTY_CORE_GIT_URL:
        raise DependencyContractError(
            f"dynasty-core git source {source['git']!r} must be exactly {DYNASTY_CORE_GIT_URL!r}"
        )
    if not isinstance(source["rev"], str) or not _SHA_PATTERN.match(source["rev"]):
        raise DependencyContractError(
            f"dynasty-core rev {source['rev']!r} must be a full 40-char lowercase commit sha"
        )
    return source["rev"]


def parse_project_data(data: dict) -> dict[str, dict]:
    """Validate parsed pyproject data. Collects every problem; never skips."""
    errors: list[str] = []
    project = data.get("project") or {}
    tool_uv = (data.get("tool") or {}).get("uv") or {}

    for key in _FORBIDDEN_TOP_LEVEL:
        if key in data:
            errors.append(f"[{key}] is not part of Scout's dependency contract")
    if "optional-dependencies" in project:
        errors.append("[project.optional-dependencies] is not part of Scout's dependency contract")
    unknown_uv = sorted(set(tool_uv) - _ALLOWED_TOOL_UV_KEYS)
    if unknown_uv:
        errors.append(f"[tool.uv] may only set {sorted(_ALLOWED_TOOL_UV_KEYS)}, not {unknown_uv}")
    if tool_uv.get("package") is not False:
        errors.append("[tool.uv] package must be false (Scout is an application, not a package)")

    parsed: dict[str, dict] = {}
    seen: dict[str, str] = {}
    entries = project.get("dependencies")
    if not isinstance(entries, list):
        errors.append("[project].dependencies must be a list")
        entries = []
    for entry in entries:
        try:
            name, spec = parse_dependency(entry)
        except DependencyContractError as exc:
            errors.append(str(exc))
            continue
        key = normalize_name(name)
        if key in seen:
            errors.append(f"{entry!r}: duplicate dependency (already declared as {seen[key]!r})")
            continue
        seen[key] = entry
        parsed[name] = spec

    sources = tool_uv.get("sources", {})
    if DYNASTY_CORE_DIST in parsed:
        try:
            sha = parse_dynasty_core_source(sources)
            parsed[DYNASTY_CORE_DIST] = {"kind": "git", "value": sha, "repo": DYNASTY_CORE_REPO_URL}
        except DependencyContractError as exc:
            errors.append(str(exc))
    elif sources:
        errors.append("[tool.uv.sources] configures a package that isn't a declared dependency")

    if errors:
        raise DependencyContractError("invalid pyproject.toml:\n  " + "\n  ".join(errors))
    return parsed


def parse_project_text(text: str) -> dict[str, dict]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise DependencyContractError(f"pyproject.toml is not valid TOML: {exc}") from exc
    return parse_project_data(data)


def parse_project(path: pathlib.Path = PYPROJECT_PATH) -> dict[str, dict]:
    return parse_project_text(path.read_text(encoding="utf-8"))


def parse_pins(path: pathlib.Path = PYPROJECT_PATH) -> dict[str, str]:
    """{name: exact version} for the ordinary pins. Raises on any invalid entry."""
    return {name: spec["value"] for name, spec in parse_project(path).items() if spec["kind"] == "version"}


def check_lock_data(lock: dict, specs: dict[str, dict]) -> list[str]:
    """Offline checks of a parsed uv.lock against the validated contract.
    Returns a list of problems (empty means the lock is consistent)."""
    problems: list[str] = []
    packages = lock.get("package")
    if not isinstance(packages, list) or not packages:
        return ["uv.lock has no [[package]] entries"]

    locked: dict[str, list[dict]] = {}
    for pkg in packages:
        locked.setdefault(normalize_name(str(pkg.get("name", ""))), []).append(pkg)

    for name, spec in specs.items():
        entries = locked.get(normalize_name(name), [])
        if len(entries) != 1:
            problems.append(f"{name}: expected exactly one locked entry, found {len(entries)}")
            continue
        pkg = entries[0]
        source = pkg.get("source") or {}
        if spec["kind"] == "version":
            if pkg.get("version") != spec["value"]:
                problems.append(f"{name}: pinned {spec['value']}, locked {pkg.get('version')}")
            if source != {"registry": PYPI_REGISTRY}:
                problems.append(f"{name}: locked from {source!r}, expected PyPI")
        else:
            expected = f"{DYNASTY_CORE_GIT_URL}?rev={spec['value']}#{spec['value']}"
            if source != {"git": expected}:
                problems.append(f"{name}: locked from {source!r}, expected git {expected!r}")

    for pkg in packages:
        name = normalize_name(str(pkg.get("name", "")))
        source = pkg.get("source") or {}
        if name == DYNASTY_CORE_DIST:
            continue
        if source == {"registry": PYPI_REGISTRY}:
            continue
        if source == {"virtual": "."}:      # the Scout project itself (package = false)
            continue
        problems.append(f"{name}: locked from non-PyPI source {source!r}")
    return problems


def check_lock(specs: dict[str, dict], path: pathlib.Path = LOCK_PATH) -> list[str]:
    if not path.is_file():
        return [f"{path.name} is missing"]
    try:
        lock = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return [f"{path.name} is not valid TOML: {exc}"]
    return check_lock_data(lock, specs)


def _normalize_repo_url(url: str) -> str:
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[: -len(".git")]
    return url.rstrip("/")


def check_version_install(dist_name: str, pinned: str, metadata=importlib.metadata) -> tuple[str, str]:
    try:
        installed = metadata.version(dist_name)
    except metadata.PackageNotFoundError:
        return "MISSING", f"{dist_name}: pinned {pinned}, not installed"
    if installed == pinned:
        return "OK", f"{dist_name}: {installed}"
    return "MISMATCH", f"{dist_name}: pinned {pinned}, installed {installed}"


def check_git_install(dist_name: str, expected_sha: str, expected_repo: str = DYNASTY_CORE_REPO_URL,
                      metadata=importlib.metadata) -> tuple[str, str]:
    """Verify a Git-pinned install from its PEP 610 direct_url.json.
    The resolved vcs_info.commit_id is authoritative; requested_revision is
    diagnostic only."""
    try:
        dist = metadata.distribution(dist_name)
    except metadata.PackageNotFoundError:
        return "MISSING", f"{dist_name}: pinned commit {expected_sha}, not installed"
    raw = dist.read_text("direct_url.json")
    if raw is None:
        return "MISMATCH", f"{dist_name}: no direct_url.json -- not installed from the pinned Git source"
    try:
        info = json.loads(raw)
        vcs_info = info["vcs_info"]
        vcs, commit, url = vcs_info["vcs"], vcs_info["commit_id"], info["url"]
    except (ValueError, TypeError, KeyError) as exc:
        return "MISMATCH", f"{dist_name}: malformed direct_url.json ({exc.__class__.__name__}: {exc})"
    requested = vcs_info.get("requested_revision")
    if vcs != "git":
        return "MISMATCH", f"{dist_name}: installed from vcs {vcs!r}, expected 'git'"
    if _normalize_repo_url(url) != _normalize_repo_url(expected_repo):
        return "MISMATCH", f"{dist_name}: installed from {url!r}, expected {expected_repo!r}"
    if commit != expected_sha:
        return "MISMATCH", (f"{dist_name}: installed commit {commit}, pinned {expected_sha}"
                            + (f" (requested {requested!r})" if requested else ""))
    return "OK", f"{dist_name}: git {commit}" + (f" (requested {requested!r})" if requested else "")


def main() -> int:
    try:
        specs = parse_project()
    except DependencyContractError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not specs:
        print(f"No dependencies declared in {PYPROJECT_PATH}", file=sys.stderr)
        return 2

    lock_problems = check_lock(specs)
    for problem in lock_problems:
        print(f"[LOCK]      {problem}")
    if lock_problems:
        print(f"\nuv.lock does not match the dependency contract ({len(lock_problems)} problem(s)).")
        return 2

    problems = 0
    for name, spec in sorted(specs.items()):
        if spec["kind"] == "git":
            status, message = check_git_install(name, spec["value"], spec["repo"])
        else:
            status, message = check_version_install(name, spec["value"])
        print(f"{'[' + status + ']':<11} {message}")
        problems += status != "OK"

    print()
    if problems:
        print(f"{problems} of {len(specs)} pinned dependencies do not match what's installed.")
        return 1
    print(f"uv.lock is consistent with pyproject.toml; all {len(specs)} pinned dependencies match what's installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
